from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
import os
import uuid
from dotenv import load_dotenv
from openai import OpenAI
from dxf_processor import DXFProcessor
from layout_optimizer import LayoutOptimizer, GridLayoutEngine
from ai_advisor import (get_ai_layout_placements,
                        get_ai_boundary_index, get_ai_explanation,
                        get_ai_capacity_analysis, TITAN_GATEWAY_URL)

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

# Suppress noisy ezdxf internal log messages (ACAD dictionary, header vars, etc.)
import logging as _logging_init
_logging_init.getLogger('ezdxf').setLevel(_logging_init.ERROR)

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'dxf'}
REFERENCE_ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ── Compass: entrance wall is always South ──────────────────────────────────
# Standing at the entrance facing into the store, left = West, right = East,
# and the opposite wall = North. This is the single source of truth for
# every compass-relative calculation (Vastu SW corner, AI prompt wording,
# frontend compass overlay) — there is no independent "north direction"
# setting; it is always derived from the entrance wall.
_OPPOSITE_WALL = {'FRONT': 'BACK', 'BACK': 'FRONT', 'LEFT': 'RIGHT', 'RIGHT': 'LEFT'}
_WEST_OF_ENTRANCE = {'FRONT': 'LEFT', 'BACK': 'RIGHT', 'LEFT': 'BACK', 'RIGHT': 'FRONT'}
_EAST_OF_ENTRANCE = {'FRONT': 'RIGHT', 'BACK': 'LEFT', 'LEFT': 'FRONT', 'RIGHT': 'BACK'}


def compass_from_entrance(entrance_wall):
    """Return {south, north, west, east: <FRONT|BACK|LEFT|RIGHT wall>} for a given entrance wall."""
    entrance_wall = entrance_wall if entrance_wall in _OPPOSITE_WALL else 'FRONT'
    return {
        'south': entrance_wall,
        'north': _OPPOSITE_WALL[entrance_wall],
        'west': _WEST_OF_ENTRANCE[entrance_wall],
        'east': _EAST_OF_ENTRANCE[entrance_wall],
    }


def _detect_entrance_wall(doors, bounds):
    """
    Infer which store wall (FRONT=y_min, BACK=y_max, LEFT=x_min, RIGHT=x_max)
    the real entrance is on, from the door(s) detected in the DXF. Falls back
    to FRONT only when no door was detected at all.
    """
    if not doors:
        return 'FRONT'
    min_x, min_y = bounds['min']
    max_x, max_y = bounds['max']
    door = doors[0]
    dx, dy = door['x'], door['y']
    dist_to_wall = {
        'FRONT': dy - min_y,
        'BACK':  max_y - dy,
        'LEFT':  dx - min_x,
        'RIGHT': max_x - dx,
    }
    return min(dist_to_wall, key=dist_to_wall.get)

# ── existing endpoints (unchanged) ──────────────────────────────────────────

@app.route('/list-models', methods=['GET'])
def list_models():
    from ai_advisor import _get_api_key
    api_key = _get_api_key()
    if not api_key:
        return jsonify({'error': 'TITAN_API_KEY not set in .env'}), 400
    try:
        client = OpenAI(base_url=TITAN_GATEWAY_URL, api_key=api_key, timeout=30.0)
        models = client.models.list()
        return jsonify({'models': [m.id for m in models.data]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if file and allowed_file(file.filename):
        file_id = str(uuid.uuid4())
        filename = secure_filename(f"{file_id}.dxf")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        try:
            processor = DXFProcessor(filepath)
            metadata = processor.get_metadata()
            boundary_candidates = processor.get_boundary_candidates()
            boundary = boundary_candidates[0] if boundary_candidates else processor.detect_store_boundary()
            store_bounds = boundary.get('bounds') if boundary else None
            columns = processor.detect_columns(store_bounds)
            beams = processor.detect_beams(store_bounds)
            doors = processor.detect_doors(store_bounds)
            plumbing = processor.detect_plumbing_points(store_bounds)
        except Exception as e:
            os.remove(filepath)
            return jsonify({'error': f'Invalid or corrupt DXF file: {str(e)}'}), 400
        return jsonify({
            'file_id': file_id,
            'metadata': metadata,
            'boundary': boundary,
            'boundary_candidates': boundary_candidates,
            'columns': columns,
            'beams': beams,
            'doors': doors,
            'plumbing': plumbing,
            'message': 'File uploaded successfully'
        }), 200
    return jsonify({'error': 'Invalid file type'}), 400

@app.route('/upload-reference', methods=['POST'])
def upload_reference_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
    if ext not in REFERENCE_ALLOWED_EXTENSIONS:
        return jsonify({'error': 'Invalid file type. Allowed: png, jpg, jpeg, pdf'}), 400
    file_id = str(uuid.uuid4())
    filename = secure_filename(f"{file_id}.{ext}")
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    return jsonify({
        'reference_file_id': file_id,
        'reference_file_ext': ext,
        'message': 'Reference file uploaded successfully'
    }), 200

@app.route('/structural-elements/<file_id>', methods=['GET'])
def structural_elements(file_id):
    """
    Return detected columns and beams for a previously uploaded DXF.

    Optional query params:
      candidate_index (int, default 0) – which boundary candidate to use
        as the store bounds filter for structural detection.

    Response:
      { columns: [...], beams: [...], store_bounds: {...} }
    """
    input_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}.dxf")
    if not os.path.exists(input_path):
        return jsonify({'error': 'File not found'}), 404
    try:
        candidate_index = int(request.args.get('candidate_index', 0))
        processor = DXFProcessor(input_path)
        boundary_candidates = processor.get_boundary_candidates()
        if boundary_candidates:
            idx = max(0, min(candidate_index, len(boundary_candidates) - 1))
            store_bounds = boundary_candidates[idx].get('bounds')
        else:
            bd = processor.detect_store_boundary()
            store_bounds = bd.get('bounds')
        columns = processor.detect_columns(store_bounds)
        beams = processor.detect_beams(store_bounds)
        doors = processor.detect_doors(store_bounds)
        return jsonify({
            'columns': columns,
            'beams': beams,
            'doors': doors,
            'store_bounds': store_bounds,
            'column_count': len(columns),
            'beam_count': len(beams),
            'door_count': len(doors),
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/debug-beams/<file_id>', methods=['GET'])
def debug_beams(file_id):
    """Debug: show collected BOB texts and beam centers with their matched BOB heights."""
    input_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}.dxf")
    if not os.path.exists(input_path):
        return jsonify({'error': 'File not found'}), 404
    try:
        processor = DXFProcessor(input_path)
        scale = processor._unit_scale()
        bob_texts = processor._collect_bob_texts(scale)
        boundary_candidates = processor.get_boundary_candidates()
        if boundary_candidates:
            store_bounds = boundary_candidates[0].get('bounds')
        else:
            bd = processor.detect_store_boundary()
            store_bounds = bd.get('bounds')

        beams = processor.detect_beams(store_bounds)

        # For each beam compute distance to each bob_text
        beam_debug = []
        for b in beams:
            cx, cy = b['x'], b['y']
            dists = sorted(
                [{'x': round(ex), 'y': round(ey), 'bob': h,
                  'dist_mm': round(((ex-cx)**2+(ey-cy)**2)**0.5)}
                 for ex, ey, h in bob_texts],
                key=lambda d: d['dist_mm']
            )[:5]  # top-5 nearest
            beam_debug.append({
                'cx': cx, 'cy': cy,
                'orientation': b['orientation'],
                'bob_height': b['bob_height'],
                'nearest_texts': dists,
            })

        return jsonify({
            'scale': scale,
            'bob_texts_count': len(bob_texts),
            'bob_texts': [{'x': round(ex), 'y': round(ey), 'bob': h}
                          for ex, ey, h in bob_texts],
            'beams_count': len(beams),
            'beams': beam_debug,
        }), 200
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500

@app.route('/debug-boundary/<file_id>', methods=['GET'])
def debug_boundary(file_id):
    """Return raw boundary candidates with extra detail for debugging."""
    input_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}.dxf")
    if not os.path.exists(input_path):
        return jsonify({'error': 'File not found'}), 404
    try:
        from collections import defaultdict
        processor = DXFProcessor(input_path)
        # ── Raw DXF diagnostics ──────────────────────────────────────────────
        doc = processor.doc
        msp = processor.msp
        # Document units (4=mm, 5=cm, 6=m, 1=inches, 2=feet, 0=unitless)
        dxf_units = doc.header.get('$INSUNITS', 0)
        # Collect ALL entities grouped by layer and type
        from ezdxf import bbox as ezdxf_bbox
        layer_types = defaultdict(lambda: defaultdict(int))
        layer_bbox = defaultdict(lambda: {'xs': [], 'ys': []})

        for entity in msp:
            etype = entity.dxftype()
            layer = entity.dxf.get('layer', '0')
            layer_types[layer][etype] += 1

            # Try to get bounding box for any entity
            try:
                bb = ezdxf_bbox.extents([entity], fast=True)
                if bb:
                    layer_bbox[layer]['xs'].extend([bb.extmin.x, bb.extmax.x])
                    layer_bbox[layer]['ys'].extend([bb.extmin.y, bb.extmax.y])
            except Exception:
                pass

        layer_summary = {}
        for layer in set(list(layer_types.keys()) + list(layer_bbox.keys())):
            xs = layer_bbox[layer]['xs']
            ys = layer_bbox[layer]['ys']
            layer_summary[layer] = {
                'entity_types': dict(layer_types[layer]),
                'span_w': round(max(xs)-min(xs), 4) if xs else None,
                'span_h': round(max(ys)-min(ys), 4) if ys else None,
                'x_range': [round(min(xs),4), round(max(xs),4)] if xs else None,
                'y_range': [round(min(ys),4), round(max(ys),4)] if ys else None,
            }

        # ── Inspect INSERT blocks ─────────────────────────────────────────────
        block_summary = []
        for entity in msp:
            if entity.dxftype() != 'INSERT':
                continue
            try:
                block_name = entity.dxf.name
                block_def = doc.blocks.get(block_name)
                if block_def is None:
                    continue
                type_counts = defaultdict(int)
                blk_xs, blk_ys = [], []
                for e in block_def:
                    etype = e.dxftype()
                    if etype in ('ATTDEF', 'ATTRIB', 'SEQEND'):
                        continue
                    type_counts[etype] += 1
                    try:
                        bb2 = ezdxf_bbox.extents([e], fast=True)
                        if bb2:
                            blk_xs.extend([bb2.extmin.x, bb2.extmax.x])
                            blk_ys.extend([bb2.extmin.y, bb2.extmax.y])
                    except Exception:
                        pass
                block_summary.append({
                    'block_name': block_name,
                    'insert_layer': entity.dxf.get('layer', '0'),
                    'entity_types': dict(type_counts),
                    'block_span_w': round(max(blk_xs)-min(blk_xs), 4) if blk_xs else None,
                    'block_span_h': round(max(blk_ys)-min(blk_ys), 4) if blk_ys else None,
                })
            except Exception as be:
                block_summary.append({'block_name': '?', 'error': str(be)})

        wall_result = processor._polygonize_walls()
        candidates = processor.get_boundary_candidates()

        return jsonify({
            'dxf_units_code': dxf_units,
            'dxf_units_name': {0:'unitless',1:'inches',2:'feet',4:'mm',5:'cm',6:'m'}.get(dxf_units, 'unknown'),
            'layer_stats': layer_summary,
            'insert_blocks': block_summary,
            'polygonize_walls': wall_result,
            'all_candidates': candidates,
        }), 200
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500

@app.route('/debug-inserts/<file_id>', methods=['GET'])
def debug_inserts(file_id):
    """Return every INSERT entity's bbox to diagnose missing column detection."""
    input_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}.dxf")
    if not os.path.exists(input_path):
        return jsonify({'error': 'File not found'}), 404
    try:
        from ezdxf import bbox as ezdxf_bbox
        processor = DXFProcessor(input_path)
        scale = processor._unit_scale()
        results = []
        for entity in processor.msp:
            if entity.dxftype() != 'INSERT':
                continue
            layer = entity.dxf.get('layer', '0')
            block_name = entity.dxf.get('name', '')
            ins = entity.dxf.insert
            bb_fast = ezdxf_bbox.extents([entity], fast=True)
            bb_slow = ezdxf_bbox.extents([entity], fast=False)
            def fmt(bb):
                if not bb:
                    return None
                return {
                    'x1': round(bb.extmin.x * scale), 'y1': round(bb.extmin.y * scale),
                    'x2': round(bb.extmax.x * scale), 'y2': round(bb.extmax.y * scale),
                    'w': round((bb.extmax.x - bb.extmin.x) * scale),
                    'h': round((bb.extmax.y - bb.extmin.y) * scale),
                }
            results.append({
                'block_name': block_name, 'layer': layer,
                'insert_pt': [round(ins.x * scale), round(ins.y * scale)],
                'bbox_fast': fmt(bb_fast), 'bbox_slow': fmt(bb_slow),
            })
        return jsonify({'scale': scale, 'unit_code': processor.doc.header.get('$INSUNITS', 0),
                        'insert_count': len(results), 'inserts': results})
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500

@app.route('/detect-boundary', methods=['POST'])
def detect_boundary():
    data = request.json
    file_id = data.get('file_id')
    reference_file_id = data.get('reference_file_id')
    reference_file_ext = data.get('reference_file_ext')
    if not file_id:
        return jsonify({'error': 'No file_id provided'}), 400
    if not reference_file_id or not reference_file_ext:
        return jsonify({'error': 'No reference file provided'}), 400
    input_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}.dxf")
    if not os.path.exists(input_path):
        return jsonify({'error': 'DXF file not found'}), 404
    ext = reference_file_ext.lower().lstrip('.')
    if ext not in REFERENCE_ALLOWED_EXTENSIONS:
        return jsonify({'error': 'Invalid reference file type'}), 400
    reference_file_path = os.path.join(app.config['UPLOAD_FOLDER'],
                                       f"{reference_file_id}.{ext}")
    if not os.path.exists(reference_file_path):
        return jsonify({'error': 'Reference file not found'}), 404
    try:
        processor = DXFProcessor(input_path)
        candidates = processor.get_boundary_candidates()
        if not candidates:
            return jsonify({'error': 'No boundary candidates found in DXF'}), 400
        idx = get_ai_boundary_index(candidates, reference_file_path)
        return jsonify({
            'boundary_index': idx,
            'boundary': candidates[idx],
            'total_candidates': len(candidates)
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/analyze', methods=['POST'])
def analyze_layout():
    data = request.json
    file_id = data.get('file_id')
    constraints = data.get('constraints', {})
    if not file_id:
        return jsonify({'error': 'No file_id provided'}), 400
    input_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}.dxf")
    output_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}_optimized.dxf")
    if not os.path.exists(input_path):
        return jsonify({'error': 'File not found'}), 404
    try:
        processor = DXFProcessor(input_path)
        entities = processor.extract_entities()
        optimizer = LayoutOptimizer(entities, constraints)
        optimized_entities = optimizer.optimize()
        processor.create_optimized_dxf(optimized_entities, output_path)
        preview_data = processor.generate_preview(optimized_entities)
        return jsonify({'file_id': file_id, 'preview': preview_data,
                        'message': 'Layout optimized successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── updated main layout endpoint ─────────────────────────────────────────────

@app.route('/ai-layout-dxf', methods=['POST'])
def ai_layout_dxf():
    """
    Generate layout variants using AI-driven placement (GPT-5) as primary source.
    Falls back to GridLayoutEngine if AI fails or returns invalid placements.
    Body: { file_id, requirements, selected_fixtures, constraints, boundary_index,
            reference_file_id?, reference_file_ext? }
    Returns: { variants: [...], ai_explanation, store_boundary, placement_source }
    """
    data = request.json
    file_id = data.get('file_id')
    requirements = data.get('requirements', {})
    selected_fixtures = data.get('selected_fixtures', [])
    constraints = data.get('constraints', {})
    boundary_index = int(data.get('boundary_index', 0))
    reference_file_id = data.get('reference_file_id')
    reference_file_ext = data.get('reference_file_ext')

    if not file_id:
        return jsonify({'error': 'No file_id provided'}), 400
    if not selected_fixtures:
        return jsonify({'error': 'No fixtures selected'}), 400

    input_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}.dxf")
    if not os.path.exists(input_path):
        return jsonify({'error': 'File not found'}), 404

    reference_file_path = None
    if reference_file_id and reference_file_ext:
        ext = reference_file_ext.lower().lstrip('.')
        candidate = os.path.join(app.config['UPLOAD_FOLDER'],
        f"{reference_file_id}.{ext}")
        if os.path.exists(candidate):
            reference_file_path = candidate

    try:
        processor = DXFProcessor(input_path)
        store_boundary = processor.detect_store_boundary(candidate_index=boundary_index)

        # Detect structural obstacles
        store_bounds = store_boundary.get('bounds')
        try:
            layout_doors = processor.detect_doors(store_bounds)
        except Exception:
            layout_doors = []
        try:
            layout_columns = processor.detect_columns(store_bounds)
        except Exception:
            layout_columns = []
        try:
            layout_plumbing = processor.detect_plumbing_points(store_bounds)
        except Exception:
            layout_plumbing = []

        bounds = store_boundary['bounds']
        store_w = bounds['max'][0] - bounds['min'][0]
        store_d = bounds['max'][1] - bounds['min'][1]

        # ── Entrance wall: ALWAYS derived from the actual detected door,
        # never from a manual setting. The entrance wall is treated as
        # South; standing at it facing into the store, left = West,
        # right = East (see _detect_entrance_wall / compass mapping below).
        requirements['entrance_wall'] = _detect_entrance_wall(layout_doors, bounds)

        # ── Detailed terminal logging ──────────────────────────────────────
        import logging as _log
        _log.basicConfig(level=_log.INFO, format='%(asctime)s [LAYOUT] %(message)s',
                         datefmt='%H:%M:%S')
        _logger = _log.getLogger('layout')

        _logger.info("=" * 70)
        _logger.info(f"LAYOUT REQUEST  file_id={file_id}")
        _logger.info(f"Store size: {store_w/1000:.2f} m × {store_d/1000:.2f} m  "
                     f"({store_w:.0f} × {store_d:.0f} mm)")
        _logger.info(f"Doors detected: {len(layout_doors)}  |  "
                     f"Columns detected: {len(layout_columns)}")

        # Log selected fixtures
        _logger.info(f"Selected fixtures ({len(selected_fixtures)} total):")
        _fix_counts = {}
        for f in selected_fixtures:
            _fix_counts[f['name']] = _fix_counts.get(f['name'], 0) + 1
        for fname, cnt in _fix_counts.items():
            _logger.info(f"  [{cnt}x] {fname}")

        # Log BOH rooms requested. Clinic rooms are tracked separately from
        # BOH here for clarity — they're combined into one _boh_requested
        # list below only because the AI placement filter needs both in a
        # single allowed-names set.
        _boh_only = []
        if requirements.get('has_fitting_lab', True):   _boh_only.append('FITTING LAB 1370x1830')
        if requirements.get('has_toilet', True):         _boh_only.append('TOILET / WASH ROOM')
        if requirements.get('has_pantry', True):         _boh_only.append('PANTRY')
        if requirements.get('has_fr_room', True):        _boh_only.append('FR ROOM (FRANCHISEE)')
        if requirements.get('has_storage', True):        _boh_only.append('STORAGE ROOM')
        if requirements.get('has_electrical', True):     _boh_only.append('ELECTRICAL ROOM')
        _clinic_count = int(requirements.get('clinic_count', 2))
        _clinic_type  = requirements.get('clinic_type', 'PHOROPTER')
        _clinic_types = requirements.get('clinic_types') or [_clinic_type] * _clinic_count
        _clinic_only = [
            f"{'PHOROPTER' if (_clinic_types[i] if i < len(_clinic_types) else _clinic_type) == 'PHOROPTER' else 'NORMAL'} CLINIC ROOM {i+1}"
            for i in range(_clinic_count)
        ]
        _boh_requested = _boh_only + _clinic_only

        _logger.info(f"BOH rooms requested ({len(_boh_only)} room instances "
                     f"from {sum(1 for k in ('has_fitting_lab','has_toilet','has_pantry','has_fr_room','has_storage','has_electrical') if requirements.get(k, True))} categories checked):")
        for rname in _boh_only:
            _logger.info(f"  - {rname}")
        _logger.info(f"Clinic rooms requested ({len(_clinic_only)} total):")
        for rname in _clinic_only:
            _logger.info(f"  - {rname}")
        _logger.info("-" * 70)

        # ── PRIMARY: AI-driven placement ──────────────────────────────────
        ai_placements = None
        ai_layout_style = None
        ai_summary = None
        placement_source = 'grid_engine'
        ai_error = None
        ai_traceback = None
        ai_removed_count = 0
        skipped_fixtures = []   # fixtures that could not be placed (overlap / no space)

        try:
            ai_placements, ai_layout_style, ai_summary = get_ai_layout_placements(
                store_boundary,
                selected_fixtures,
                constraints,
                requirements=requirements,
                reference_file_path=reference_file_path,
                doors=layout_doors,
                columns=layout_columns,
                plumbing=layout_plumbing,
            )
            if ai_placements and len(ai_placements) > 0:
                # Drop any placement the AI hallucinated that wasn't actually
                # requested (e.g. an unselected cash counter or fixture type).
                _allowed_names = {f['name'].lower() for f in selected_fixtures}
                _allowed_names |= {n.lower() for n in _boh_requested}
                _before_hallucination_filter = len(ai_placements)
                ai_placements = [
                    p for p in ai_placements
                    if p.get('fixture', '').lower() in _allowed_names
                ]
                if len(ai_placements) < _before_hallucination_filter:
                    _logger.info(
                        f"[ai-layout] Dropped {_before_hallucination_filter - len(ai_placements)} "
                        f"hallucinated placement(s) not in the requested fixture/room list."
                    )
                placement_source = 'ai'
            else:
                ai_error = "AI returned empty placements list — falling back to grid engine."
        except Exception as e:
            import traceback as _tb
            ai_error = str(e)
            ai_traceback = _tb.format_exc()
            ai_placements = None

        # ── FALLBACK: GridLayoutEngine if AI failed ───────────────────────
        # AI is the only layout we show the user; the grid engine only
        # steps in silently if the AI call failed entirely, and even then
        # we surface just its single best-scoring variant.
        if not ai_placements:
            engine = GridLayoutEngine(
                store_boundary, requirements, selected_fixtures,
                doors=layout_doors, columns=layout_columns,
            )
            _best = engine.generate_all_variants()[0]
            _best['source'] = 'grid_engine'
            grid_variants = [_best]
        else:
            # Wrap AI placements into the same 3-variant structure
            # Score the AI placements using GridLayoutEngine scorer
            engine = GridLayoutEngine(
                store_boundary, requirements, selected_fixtures,
                doors=layout_doors, columns=layout_columns,
            )

            # ── Post-process: remove any AI placement that falls outside
            #    the actual store polygon (handles L-shapes, notches, etc.)
            #    AI placements are in normalized (0,0)-origin space.
            #    The store polygon from DXF is in raw DXF coords — normalize it.
            _store_poly_filter = None
            _raw_polygon = store_boundary.get('polygon')
            _bmin = store_boundary['bounds']['min']
            if _raw_polygon and len(_raw_polygon) >= 3:
                try:
                    from shapely.geometry import Polygon as _SPoly
                    _norm_pts = [
                        (pt[0] - _bmin[0], pt[1] - _bmin[1])
                        for pt in _raw_polygon
                    ]
                    _sp = _SPoly(_norm_pts)
                    if not _sp.is_valid:
                        _sp = _sp.buffer(0)
                    # Shrink by 50 mm so fixtures touching the wall edge are OK
                    _store_poly_filter = _sp.buffer(-50)
                except Exception:
                    _store_poly_filter = None

            def _ai_in_store(p):
                rot = p.get('rotation', 0) in (90, 270)
                fw = p['d'] if rot else p['l']
                fd = p['l'] if rot else p['d']
                # Basic bounding-box check (always applied)
                if p['x'] < -50 or p['y'] < -50:
                    return False
                if p['x'] + fw > store_w + 50:
                    return False
                if p['y'] + fd > store_d + 50:
                    return False
                # Shapely polygon containment (for L-shapes, notches, etc.)
                if _store_poly_filter is not None:
                    try:
                        from shapely.geometry import box as _SBox
                        fix_box = _SBox(p['x'], p['y'], p['x'] + fw, p['y'] + fd)
                        # Accept if at least 85% of fixture area is inside polygon
                        intersection = _store_poly_filter.intersection(fix_box)
                        if intersection.area < fix_box.area * 0.98:
                            return False
                    except Exception:
                        return False  # real polygon data but check failed — reject
                return True

            before = len(ai_placements)
            ai_placements = [p for p in ai_placements if _ai_in_store(p)]
            after = len(ai_placements)
            ai_removed_count = before - after
            if ai_removed_count > 0:
                import logging
                logging.warning(
                    f"[ai-layout] Removed {ai_removed_count} out-of-bounds AI placements "
                    f"(store {store_w:.0f}×{store_d:.0f} mm, polygon shape)"
                )

            if not ai_placements:
                # All AI placements were invalid — fall back to grid engine
                _best = engine.generate_all_variants()[0]
                _best['source'] = 'grid_engine'
                grid_variants = [_best]
                placement_source = 'grid_engine'
            else:
                # ── Per-fixture fallback: fill in anything the AI missed ──────
                # Build a count of how many times each fixture name appears in
                # the AI output (after filtering).
                import collections as _col

                ai_name_counts = _col.Counter(p['fixture'] for p in ai_placements)

                # 1. Missing user-selected fixtures
                #    Walk selected_fixtures in order; for each one check whether
                #    the AI placed it (by exact name match, case-insensitive).
                #    We track how many of each name we still need.
                needed_counts = _col.Counter(
                    f['name'] for f in selected_fixtures
                )
                # Subtract what the AI already placed
                for name, cnt in ai_name_counts.items():
                    # match case-insensitively
                    for sel_name in list(needed_counts.keys()):
                        if sel_name.lower() == name.lower():
                            needed_counts[sel_name] = max(
                                0, needed_counts[sel_name] - cnt
                            )

                missing_fixtures = []
                for f in selected_fixtures:
                    n = f['name']
                    if needed_counts.get(n, 0) > 0:
                        missing_fixtures.append(f)
                        needed_counts[n] -= 1

                # 2. Missing clinic rooms
                #    Build the same per-clinic-type list the AI prompt used.
                clinic_type   = requirements.get('clinic_type', 'PHOROPTER')
                clinic_count  = int(requirements.get('clinic_count', 2))
                clinic_types  = requirements.get('clinic_types') or [clinic_type] * clinic_count
                clinic_h = 2800
                for i in range(clinic_count):
                    ct = clinic_types[i] if i < len(clinic_types) else clinic_type
                    clinic_l = 3050 if ct == 'PHOROPTER' else 2745
                    clinic_d = 2440 if ct == 'PHOROPTER' else 2135
                    cname = (
                        f"PHOROPTER CLINIC ROOM {i+1}"
                        if ct == 'PHOROPTER'
                        else f"NORMAL CLINIC ROOM {i+1}"
                    )
                    already = sum(
                        1 for p in ai_placements
                        if p['fixture'].lower() == cname.lower()
                    )
                    if already == 0:
                        missing_fixtures.append({
                            'name': cname,
                            'l': clinic_l, 'd': clinic_d, 'h': clinic_h,
                        })

                # 3. Missing BOH rooms
                boh_room_defs = []
                if requirements.get('has_fitting_lab', True):
                    boh_room_defs.append(('FITTING LAB 1370x1830', 1370, 1830, 2800))
                if requirements.get('has_toilet', True):
                    boh_room_defs.append(('TOILET / WASH ROOM', 1500, 1800, 2800))
                if requirements.get('has_pantry', True):
                    boh_room_defs.append(('PANTRY', 1800, 1500, 2800))
                if requirements.get('has_fr_room', True):
                    boh_room_defs.append(('FR ROOM (FRANCHISEE)', 2400, 2000, 2800))
                if requirements.get('has_storage', True):
                    boh_room_defs.append(('STORAGE ROOM', 2000, 1800, 2800))
                if requirements.get('has_electrical', True):
                    boh_room_defs.append(('ELECTRICAL ROOM', 1200, 1000, 2800))

                for rname, rl, rd, rh in boh_room_defs:
                    already = sum(
                        1 for p in ai_placements
                        if p['fixture'].lower() == rname.lower()
                    )
                    if already == 0:
                        missing_fixtures.append({
                            'name': rname, 'l': rl, 'd': rd, 'h': rh,
                        })

                # 4. Place all missing fixtures using the engine's exhaustive
                #    grid-scan fallback, appending into the AI placement list.
                if missing_fixtures:
                    import logging as _log
                    _log.info(
                        f"[ai-layout] AI missed {len(missing_fixtures)} fixture(s); "
                        f"filling with grid fallback: "
                        f"{[f['name'] for f in missing_fixtures]}"
                    )
                    # _place_anywhere(fixes, placements) scans the whole store
                    # for each fixture in `fixes` and appends to `placements`.
                    engine._place_anywhere(missing_fixtures, ai_placements)
                    placement_source = 'ai+grid_fallback'

                # ── Hard-constraint enforcement pass ─────────────────────────
                # The AI often ignores positional rules even when told in the
                # prompt.  We enforce them deterministically here by relocating
                # any non-compliant placement to the correct position.

                # --- 1. Cash counter → South-West corner (Vastu) -------------
                sw_x, sw_y = engine._sw_corner()
                W, D = engine.store_w, engine.store_d
                _margin = 400

                def _is_cash(p):
                    return p.get('zone') == 'CASH' or 'cash counter' in p['fixture'].lower()

                cash_placements = [p for p in ai_placements if _is_cash(p)]
                non_cash = [p for p in ai_placements if not _is_cash(p)]

                for cp in cash_placements:
                    w, d = cp['l'], cp['d']
                    # Four corner candidates sorted by distance to SW corner
                    _candidates = [
                        (_margin,         _margin),
                        (_margin,         D - d - _margin),
                        (W - w - _margin, _margin),
                        (W - w - _margin, D - d - _margin),
                    ]
                    _candidates.sort(
                        key=lambda c: (c[0] - sw_x) ** 2 + (c[1] - sw_y) ** 2
                    )
                    for cx, cy in _candidates:
                        cx = max(_margin, min(cx, int(W) - w - _margin))
                        cy = max(_margin, min(cy, int(D) - d - _margin))
                        if (engine._in_store(cx, cy, w, d)
                                and not engine._hits_obstacle(cx, cy, w, d)
                                and not engine._overlaps(non_cash, cx, cy, w, d, gap=600)):
                            cp['x'] = cx
                            cp['y'] = cy
                            break

                def _others(p):
                    return [o for o in ai_placements if o is not p]

                def _fits(p, x, y, fw, fd):
                    return (engine._in_store(x, y, fw, fd)
                            and not engine._hits_obstacle(x, y, fw, fd)
                            and not engine._overlaps(_others(p), x, y, fw, fd, gap=150))

                def _find_slot_in_zone(p, fw, fd, zx1, zx2, zy1, zy2, gap, start_x, start_y):
                    """Row-pack search for a non-overlapping slot inside a zone."""
                    cy = start_y
                    while cy + fd <= zy2 - gap:
                        cx = start_x if cy == start_y else zx1 + gap
                        while cx + fw <= zx2 - gap:
                            if _fits(p, cx, cy, fw, fd):
                                return (int(cx), int(cy))
                            cx += gap
                        cy += gap
                    return None

                # Wall-mounted display fixture name keywords — used both to
                # exclude them as "real" obstacles while clustering BOH rooms
                # (the AI often dumps them mid-store/near-entrance before
                # pass #4 below snaps them to their actual wall, so they
                # shouldn't be allowed to block BOH packing) and by pass #4
                # itself to enforce wall rotation.
                _WALL_FIX_TYPES = {
                    'ib frame', 'lux unit', 'luxury unit', 'hb-ya', 'hb-m',
                    'affordable', 'fastrack', 'kids', 'sunglass', 'lens unit',
                    'smart display', 'contact lens',
                }

                # --- 2. Clinics → CLINIC zone (mid-rear) ---------------------
                _zones = engine._zones()
                clinic_zone = _zones.get('CLINIC', _zones.get('SERVICE'))
                if clinic_zone:
                    czx1, czx2, czy1, czy2 = clinic_zone
                    _gap = 600
                    _cx_cursor = czx1 + _gap
                    _cy_cursor = czy1 + _gap
                    for p in ai_placements:
                        _is_clinic = (p.get('zone') == 'CLINIC'
                                      or 'clinic room' in p['fixture'].lower())
                        if not _is_clinic:
                            continue
                        rot = p.get('rotation', 0) in (90, 270)
                        fw = p['d'] if rot else p['l']
                        fd = p['l'] if rot else p['d']
                        # Check if already inside clinic zone AND not colliding
                        already_ok = (
                            czx1 <= p['x'] and p['x'] + fw <= czx2 and
                            czy1 <= p['y'] and p['y'] + fd <= czy2
                            and _fits(p, p['x'], p['y'], fw, fd)
                        )
                        if not already_ok:
                            slot = _find_slot_in_zone(
                                p, fw, fd, czx1, czx2, czy1, czy2, _gap,
                                _cx_cursor, _cy_cursor,
                            )
                            if slot:
                                p['x'], p['y'] = slot
                                _cx_cursor = slot[0] + fw + _gap
                                _cy_cursor = slot[1]
                            # else: leave original AI position — later passes
                            # (overlap-removal / recovery) will handle it.

                # --- 3. BOH rooms → BOH zone (rear), packed as one cluster ---
                boh_zone = _zones.get('BOH')
                _BOH_NAMES = {
                    'fitting lab', 'toilet', 'wash room', 'pantry',
                    'fr room', 'franchisee', 'storage room',
                    'electrical room',
                }

                # The AI frequently dumps wall-mounted display fixtures (which
                # pass #4 below hasn't relocated to their wall yet) at y-values
                # that fall inside the BOH zone. If those are treated as real
                # obstacles here, they can block later BOH rooms (in iteration
                # order) from finding a slot, leaving them stuck near the
                # entrance — exactly the "BOH rooms scattered" symptom. Ignore
                # them as obstacles for this pass; pass #4 will move them to
                # an actual wall afterwards, avoiding the now-placed BOH rooms.
                def _boh_others(p):
                    return [o for o in ai_placements if o is not p
                            and not any(k in o['fixture'].lower() for k in _WALL_FIX_TYPES)]

                def _boh_fits(p, x, y, fw, fd):
                    return (engine._in_store(x, y, fw, fd)
                            and not engine._hits_obstacle(x, y, fw, fd)
                            and not engine._overlaps(_boh_others(p), x, y, fw, fd, gap=150))

                def _find_boh_slot(p, fw, fd, zx1, zx2, zy1, zy2, gap, start_x, start_y):
                    cy = start_y
                    while cy + fd <= zy2 - gap:
                        cx = start_x if cy == start_y else zx1 + gap
                        while cx + fw <= zx2 - gap:
                            if _boh_fits(p, cx, cy, fw, fd):
                                return (int(cx), int(cy))
                            cx += gap
                        cy += gap
                    return None

                if boh_zone:
                    bzx1, bzx2, bzy1, bzy2 = boh_zone
                    _bgap = 300

                    _boh_items = [p for p in ai_placements
                                  if any(k in p['fixture'].lower() for k in _BOH_NAMES)]

                    # --- 3a. Water-dependent rooms (Toilet, Fitting Lab) MUST
                    # sit next to a detected plumbing point. Anchor them here,
                    # before the general shelf-pack below, so they land near
                    # actual water inlet/outlet markers instead of wherever
                    # the pack cursor happens to be.
                    _WATER_ROOM_NAMES = {'toilet', 'wash room', 'fitting lab'}
                    _norm_plumbing = [
                        {'x': pt['x'] - _bmin[0], 'y': pt['y'] - _bmin[1]}
                        for pt in (layout_plumbing or [])
                    ]
                    def _find_closest_boh_slot(p, fw, fd, target_x, target_y):
                        """Scan the WHOLE BOH zone and return the valid slot
                        closest to (target_x, target_y) — unlike
                        _find_boh_slot, this isn't direction-biased, so it
                        can't miss a free slot that's behind/left of the
                        plumbing point."""
                        best, best_d2 = None, None
                        cy = bzy1 + _bgap
                        while cy + fd <= bzy2 - _bgap:
                            cx = bzx1 + _bgap
                            while cx + fw <= bzx2 - _bgap:
                                if _boh_fits(p, cx, cy, fw, fd):
                                    d2 = (cx - target_x) ** 2 + (cy - target_y) ** 2
                                    if best_d2 is None or d2 < best_d2:
                                        best_d2, best = d2, (int(cx), int(cy))
                                cx += _bgap
                            cy += _bgap
                        return best

                    if _norm_plumbing:
                        _water_items = [p for p in _boh_items
                                        if any(k in p['fixture'].lower() for k in _WATER_ROOM_NAMES)]
                        for p in _water_items:
                            rot = p.get('rotation', 0) in (90, 270)
                            fw = p['d'] if rot else p['l']
                            fd = p['l'] if rot else p['d']
                            best_slot, best_dist = None, None
                            for pt in _norm_plumbing:
                                slot = _find_closest_boh_slot(p, fw, fd, pt['x'], pt['y'])
                                if slot:
                                    d2 = (slot[0] - pt['x']) ** 2 + (slot[1] - pt['y']) ** 2
                                    if best_dist is None or d2 < best_dist:
                                        best_dist, best_slot = d2, slot
                            if best_slot:
                                p['x'], p['y'] = best_slot
                                # Only now is it safe to exclude from the
                                # general pack below — it already has a
                                # good, water-adjacent position.
                                _boh_items.remove(p)
                            # else: no valid slot near any water point —
                            # leave it in _boh_items so the general shelf-pack
                            # still gives it a position somewhere in the BOH
                            # zone, instead of stranding it at its original
                            # (likely near-entrance) AI position.

                    # Biggest rooms first — packs more reliably than AI's
                    # arbitrary placement order.
                    _boh_items.sort(key=lambda p: max(p['l'], p['d']), reverse=True)

                    cursor_x = bzx1 + _bgap
                    cursor_y = bzy1 + _bgap
                    row_h = 0
                    for p in _boh_items:
                        rot = p.get('rotation', 0) in (90, 270)
                        fw = p['d'] if rot else p['l']
                        fd = p['l'] if rot else p['d']
                        if cursor_x + fw > bzx2 - _bgap:
                            cursor_x = bzx1 + _bgap
                            cursor_y += row_h + _bgap
                            row_h = 0
                        slot = _find_boh_slot(
                            p, fw, fd, bzx1, bzx2, bzy1, bzy2, _bgap,
                            cursor_x, cursor_y,
                        )
                        if slot:
                            p['x'], p['y'] = slot
                            cursor_x = slot[0] + fw + _bgap
                            row_h = max(row_h, fd)
                        # else: leave original AI position — later recovery /
                        # skip-reason logging handles genuinely unplaceable items.

                # --- 4. Wall fixture rotation enforcement -------------------
                # The AI frequently places wall fixtures with rotation=0
                # (long side horizontal) even against left/right walls.
                # Enforce: fixtures near left/right walls MUST use rotation=90
                # so their long side runs vertically along the wall.
                # Matched by fixture NAME only — never trust the AI's
                # self-reported zone field, it's frequently wrong.
                _WALL_THRESHOLD = W * 0.25  # within 25% of store width = near a wall

                # _in_store() (used by _fits) rejects anything below margin=100,
                # so every wall-anchor coordinate here MUST use that same
                # margin — a 50mm anchor makes _fits() always return False.
                _WALL_MARGIN = 100

                def _slide_along_wall(p, fw, fd, fixed_x, target_y, step=150):
                    """Search up/down from target_y for a free slot at fixed_x."""
                    if _fits(p, fixed_x, target_y, fw, fd):
                        return target_y
                    offset = step
                    while offset <= D:
                        for cand_y in (target_y - offset, target_y + offset):
                            cand_y = max(_WALL_MARGIN, min(cand_y, int(D - fd - _WALL_MARGIN)))
                            if _fits(p, fixed_x, cand_y, fw, fd):
                                return cand_y
                        offset += step
                    return None

                for p in ai_placements:
                    pname_low = p['fixture'].lower()
                    if not any(k in pname_low for k in _WALL_FIX_TYPES):
                        continue
                    # Only fix rotation=0 placements that are near left or right wall
                    if p.get('rotation', 0) != 0:
                        continue
                    px, pl, pd = p['x'], p['l'], p['d']
                    # Near left wall: x is small
                    near_left  = px <= _WALL_THRESHOLD
                    # Near right wall: x + l is near store width
                    near_right = (px + pl) >= W - _WALL_THRESHOLD
                    if near_left or near_right:
                        # Switch to rotation=90: long side (l) runs along Y axis
                        # effective_w = d (depth), effective_d = l (length)
                        new_x = _WALL_MARGIN if near_left else int(W - pd - _WALL_MARGIN)
                        target_y = max(_WALL_MARGIN, min(p['y'], int(D - pl - _WALL_MARGIN)))
                        new_y = _slide_along_wall(p, pd, pl, new_x, target_y)
                        if new_y is not None:
                            p['rotation'] = 90
                            p['x'] = new_x
                            p['y'] = new_y
                        # else: leave original placement untouched

                # --- 4b. Wall-snap pass: force wall fixtures to actual walls --
                # If a wall fixture is NOT near any wall (floating in center),
                # snap it to the nearest wall based on its x position.
                _WALL_SNAP_MARGIN = _WALL_MARGIN   # must match _in_store()'s margin=100

                def _slide_along_wall_h(p, fw, fd, fixed_y, target_x, step=150):
                    """Search left/right from target_x for a free slot at fixed_y."""
                    if _fits(p, target_x, fixed_y, fw, fd):
                        return target_x
                    offset = step
                    while offset <= W:
                        for cand_x in (target_x - offset, target_x + offset):
                            cand_x = max(_WALL_MARGIN, min(cand_x, int(W - fw - _WALL_MARGIN)))
                            if _fits(p, cand_x, fixed_y, fw, fd):
                                return cand_x
                        offset += step
                    return None

                for p in ai_placements:
                    pname_low = p['fixture'].lower()
                    if not any(k in pname_low for k in _WALL_FIX_TYPES):
                        continue
                    rot = p.get('rotation', 0) in (90, 270)
                    fw = p['d'] if rot else p['l']
                    fd = p['l'] if rot else p['d']
                    px, py = p['x'], p['y']
                    # Check if fixture is NOT against any wall
                    on_left   = px <= 200
                    on_right  = px + fw >= W - 200
                    on_bottom = py <= 200
                    on_top    = py + fd >= D - 200
                    if not (on_left or on_right or on_bottom or on_top):
                        # Floating — snap to nearest wall
                        dist_left   = px
                        dist_right  = W - (px + fw)
                        dist_bottom = py
                        dist_top    = D - (py + fd)
                        min_dist = min(dist_left, dist_right, dist_bottom, dist_top)
                        if min_dist == dist_left:
                            # Snap to left wall with rotation=90
                            new_y = _slide_along_wall(p, p['d'], p['l'], _WALL_SNAP_MARGIN,
                                                       max(_WALL_SNAP_MARGIN, min(py, int(D - p['l'] - _WALL_SNAP_MARGIN))))
                            if new_y is not None:
                                p['rotation'] = 90
                                p['x'] = _WALL_SNAP_MARGIN
                                p['y'] = new_y
                        elif min_dist == dist_right:
                            # Snap to right wall with rotation=90
                            snap_x = int(W - p['d'] - _WALL_SNAP_MARGIN)
                            new_y = _slide_along_wall(p, p['d'], p['l'], snap_x,
                                                       max(_WALL_SNAP_MARGIN, min(py, int(D - p['l'] - _WALL_SNAP_MARGIN))))
                            if new_y is not None:
                                p['rotation'] = 90
                                p['x'] = snap_x
                                p['y'] = new_y
                        elif min_dist == dist_bottom:
                            # Snap to bottom wall (entrance) with rotation=0
                            new_x = _slide_along_wall_h(p, p['l'], p['d'], _WALL_SNAP_MARGIN,
                                                         max(_WALL_SNAP_MARGIN, min(px, int(W - p['l'] - _WALL_SNAP_MARGIN))))
                            if new_x is not None:
                                p['rotation'] = 0
                                p['y'] = _WALL_SNAP_MARGIN
                                p['x'] = new_x
                        else:
                            # Snap to top wall with rotation=0
                            snap_y = int(D - p['d'] - _WALL_SNAP_MARGIN)
                            new_x = _slide_along_wall_h(p, p['l'], p['d'], snap_y,
                                                         max(_WALL_SNAP_MARGIN, min(px, int(W - p['l'] - _WALL_SNAP_MARGIN))))
                            if new_x is not None:
                                p['rotation'] = 0
                                p['y'] = snap_y
                                p['x'] = new_x

                # --- 4c. Keep left/right-wall fixtures out of the CLINIC/BOH
                # band. Passes #4/#4b only fix X (snap to wall) and rotation —
                # they never constrain Y, so a wall fixture can end up
                # sitting deep inside the CLINIC or BOH zone, "behind" the
                # retail floor. Slide it back within the RETAIL zone's
                # Y-range, along the same wall, if it has drifted north.
                _retail_zone = _zones.get('RETAIL')
                if _retail_zone and requirements['entrance_wall'] in ('FRONT', 'BACK'):
                    _ry1, _ry2 = _retail_zone[2], _retail_zone[3]
                    for p in ai_placements:
                        pname_low = p['fixture'].lower()
                        if not any(k in pname_low for k in _WALL_FIX_TYPES):
                            continue
                        if p.get('rotation', 0) not in (90, 270):
                            continue  # only left/right-wall (vertical) fixtures run along Y
                        fw, fd = p['d'], p['l']
                        px, py = p['x'], p['y']
                        on_left  = px <= 200
                        on_right = px + fw >= W - 200
                        if not (on_left or on_right):
                            continue
                        if py >= _ry1 and py + fd <= _ry2:
                            continue  # already within the retail band
                        target_y = max(_ry1, min(py, int(_ry2 - fd)))
                        new_y = _slide_along_wall(p, fw, fd, px, target_y)
                        if new_y is not None:
                            p['y'] = new_y
                        # else: leave as-is — better a fixture slightly out of
                        # band than one silently dropped.

                # --- 5. Door & column clearance enforcement ------------------
                # The AI ignores door clearance zones entirely.  Build the
                # same obstacle rectangles that GridLayoutEngine uses and
                # remove any AI placement that blocks a door or column.
                _bmin = store_boundary['bounds']['min']
                _DOOR_CLEARANCE = 1500
                _COL_MARGIN = 300
                _obstacle_zones = []

                for door in layout_doors:
                    r = door.get('radius', 900)
                    dx = door['x'] - _bmin[0]
                    dy = door['y'] - _bmin[1]
                    _obstacle_zones.append((
                        dx - r - _DOOR_CLEARANCE,
                        dy - r - _DOOR_CLEARANCE,
                        dx + r + _DOOR_CLEARANCE,
                        dy + r + _DOOR_CLEARANCE,
                        f"door at ({round(dx)}, {round(dy)})",
                    ))

                for col in layout_columns:
                    cx = col['x'] - _bmin[0]
                    cy = col['y'] - _bmin[1]
                    hw = col.get('width', 400) / 2
                    hd = col.get('height', 400) / 2
                    _obstacle_zones.append((
                        cx - hw - _COL_MARGIN,
                        cy - hd - _COL_MARGIN,
                        cx + hw + _COL_MARGIN,
                        cy + hd + _COL_MARGIN,
                        f"column at ({round(cx)}, {round(cy)})",
                    ))

                def _hits_obstacle_zone(px, py, pw, pd_):
                    for ox1, oy1, ox2, oy2, olabel in _obstacle_zones:
                        if not (px + pw <= ox1 or ox2 <= px or
                                py + pd_ <= oy1 or oy2 <= py):
                            return olabel
                    return None

                if _obstacle_zones:
                    _cleared = []
                    for p in ai_placements:
                        pw, pd_ = (p['d'], p['l']) if p.get('rotation', 0) in (90, 270) else (p['l'], p['d'])
                        hit = _hits_obstacle_zone(p['x'], p['y'], pw, pd_)
                        if hit:
                            skipped_fixtures.append({
                                'fixture': p['fixture'],
                                'zone': p.get('zone', ''),
                                'size_mm': f"{p['l']}×{p['d']} mm",
                                'reason': f"Blocks {hit} — 1500 mm clearance required in front of doors",
                            })
                        else:
                            _cleared.append(p)
                    ai_placements = _cleared

                # --- 6. Overlap-removal pass ---------------------------------
                # Walk placements in priority order (BOH/CLINIC first, then
                # retail fixtures).  Keep a placement only if it does NOT
                # overlap any already-accepted placement.  Removed items are
                # collected in skipped_fixtures with a human-readable reason.
                _PRIORITY_ORDER = ['BOH', 'FITTING_LAB', 'CLINIC', 'CASH',
                                   'RETAIL_FRONT', 'RETAIL_MID', 'RETAIL_PREMIUM',
                                   'SUNGLASSES', 'KIDS', 'SMART']

                def _fix_eff(p):
                    rot = p.get('rotation', 0) in (90, 270)
                    return (p['d'] if rot else p['l'],
                            p['l'] if rot else p['d'])

                def _overlaps_any(accepted, px, py, pw, pd_, gap=50):
                    for a in accepted:
                        aw, ad_ = _fix_eff(a)
                        if not (px + pw + gap <= a['x'] or
                                a['x'] + aw + gap <= px or
                                py + pd_ + gap <= a['y'] or
                                a['y'] + ad_ + gap <= py):
                            return a
                    return None

                # Sort: priority zones first, then by fixture area descending
                def _sort_key(p):
                    z = p.get('zone', 'RETAIL_MID')
                    pri = _PRIORITY_ORDER.index(z) if z in _PRIORITY_ORDER else len(_PRIORITY_ORDER)
                    return (pri, -(p['l'] * p['d']))

                sorted_placements = sorted(ai_placements, key=_sort_key)
                accepted = []
                skipped_fixtures = []

                for p in sorted_placements:
                    pw, pd_ = _fix_eff(p)
                    conflict = _overlaps_any(accepted, p['x'], p['y'], pw, pd_)
                    if conflict is None:
                        accepted.append(p)
                    else:
                        skipped_fixtures.append({
                            'fixture': p['fixture'],
                            'zone': p.get('zone', ''),
                            'size_mm': f"{p['l']}×{p['d']} mm",
                            'reason': (
                                f"Overlaps with '{conflict['fixture']}' — "
                                f"not enough space in the {p.get('zone','').replace('_',' ').title()} zone"
                            ),
                        })

                ai_placements = accepted

                # --- 7. Missing-fixture recovery pass -----------------------
                # After all filtering passes, some fixtures that were in the
                # original request may still be absent (AI never placed them,
                # or they were removed by door/overlap passes).
                # Re-attempt placement for every missing item using the grid
                # engine's exhaustive _place_anywhere scan.
                _placed_names_set = {p['fixture'].lower() for p in ai_placements}

                # Build the full list of items that should have been placed
                _all_requested = list(selected_fixtures)
                # Add BOH/clinic rooms — per-clinic type, not the single legacy field
                _clinic_count2 = int(requirements.get('clinic_count', 2))
                _clinic_types2 = requirements.get('clinic_types') or \
                    [requirements.get('clinic_type', 'PHOROPTER')] * _clinic_count2
                for i in range(_clinic_count2):
                    _ctype = (_clinic_types2[i] if i < len(_clinic_types2)
                              else requirements.get('clinic_type', 'PHOROPTER'))
                    _ctype = 'PHOROPTER' if _ctype == 'PHOROPTER' else 'NORMAL'
                    _cl2 = 3050 if _ctype == 'PHOROPTER' else 2745
                    _cd2 = 2440 if _ctype == 'PHOROPTER' else 2135
                    _all_requested.append({'name': f'{_ctype} CLINIC ROOM {i+1}', 'l': _cl2, 'd': _cd2, 'h': 2800})
                _boh_defs2 = []
                if requirements.get('has_fitting_lab', True):   _boh_defs2.append(('FITTING LAB 1370x1830', 1370, 1830))
                if requirements.get('has_toilet', True):         _boh_defs2.append(('TOILET / WASH ROOM', 1500, 1800))
                if requirements.get('has_pantry', True):         _boh_defs2.append(('PANTRY', 1800, 1500))
                if requirements.get('has_fr_room', True):        _boh_defs2.append(('FR ROOM (FRANCHISEE)', 2400, 2000))
                if requirements.get('has_storage', True):        _boh_defs2.append(('STORAGE ROOM', 2000, 1800))
                if requirements.get('has_electrical', True):     _boh_defs2.append(('ELECTRICAL ROOM', 1200, 1000))
                for rname, rl, rd in _boh_defs2:
                    _all_requested.append({'name': rname, 'l': rl, 'd': rd, 'h': 2800})

                _still_missing = []
                for req_f in _all_requested:
                    if req_f['name'].lower() not in _placed_names_set:
                        _still_missing.append(req_f)

                if _still_missing:
                    import logging as _log2
                    _log2.getLogger('layout').info(
                        f"[recovery] Re-attempting {len(_still_missing)} missing fixture(s) "
                        f"with grid fallback: {[f['name'] for f in _still_missing]}"
                    )
                    _before_recovery_names = {p['fixture'].lower() for p in ai_placements}
                    engine._place_anywhere(_still_missing, ai_placements)

                    # Items added by this late recovery pass skipped the
                    # earlier zone-enforcement pass entirely (it already ran).
                    # Re-apply BOH/clinic zone correction to just the newly
                    # added items so they don't land outside their zone.
                    _newly_added = [
                        p for p in ai_placements
                        if p['fixture'].lower() not in _before_recovery_names
                    ]
                    for p in _newly_added:
                        pname_low = p['fixture'].lower()
                        rot = p.get('rotation', 0) in (90, 270)
                        fw = p['d'] if rot else p['l']
                        fd = p['l'] if rot else p['d']

                        if 'clinic room' in pname_low and clinic_zone:
                            czx1, czx2, czy1, czy2 = clinic_zone
                            already_ok = (czx1 <= p['x'] and p['x'] + fw <= czx2 and
                                          czy1 <= p['y'] and p['y'] + fd <= czy2
                                          and _fits(p, p['x'], p['y'], fw, fd))
                            if not already_ok:
                                slot = _find_slot_in_zone(p, fw, fd, czx1, czx2, czy1, czy2,
                                                           600, czx1 + 600, czy1 + 600)
                                if slot:
                                    p['x'], p['y'] = slot
                        elif any(k in pname_low for k in _BOH_NAMES) and boh_zone:
                            bzx1, bzx2, bzy1, bzy2 = boh_zone
                            already_ok = (bzx1 <= p['x'] and p['x'] + fw <= bzx2 and
                                          bzy1 <= p['y'] and p['y'] + fd <= bzy2
                                          and _fits(p, p['x'], p['y'], fw, fd))
                            if not already_ok:
                                slot = _find_slot_in_zone(p, fw, fd, bzx1, bzx2, bzy1, bzy2,
                                                           300, bzx1 + 300, bzy1 + 300)
                                if slot:
                                    p['x'], p['y'] = slot

                    # Update placed names set
                    _placed_names_set = {p['fixture'].lower() for p in ai_placements}
                    placement_source = placement_source + '+recovery' if 'recovery' not in placement_source else placement_source

                    # Drop stale skip entries for anything this recovery pass
                    # successfully re-placed — a fixture can't be both
                    # "placed" and "could not be placed" at the same time.
                    skipped_fixtures = [
                        s for s in skipped_fixtures
                        if s['fixture'].lower() not in _placed_names_set
                    ]

                    # Anything still missing after every fallback attempt is
                    # genuinely out of space — record it instead of letting
                    # it vanish from the output with no explanation.
                    for req_f in _still_missing:
                        if req_f['name'].lower() not in _placed_names_set:
                            skipped_fixtures.append({
                                'fixture': req_f['name'],
                                'zone': '',
                                'size_mm': f"{req_f['l']}×{req_f['d']} mm",
                                'reason': 'No free space found anywhere in the store after all placement attempts',
                            })

        if ai_placements:
            ai_score = engine._score(ai_placements)

            # Only the AI-generated layout is shown to the user — no grid
            # alternates. The grid engine remains available purely as the
            # silent fallback above when the AI fails outright.
            grid_variants = [
                {
                    'name': ai_layout_style or 'AI Layout',
                    'description': (
                        ai_summary or
                        'AI-generated layout with precise fixture and room placement. '
                        'Cash counter in South-West corner (Vastu). '
                        'Clinics in mid-rear zone. BOH at rear.'
                    ),
                    'style': 'AI_LAYOUT',
                    'placements': ai_placements,
                    'score': ai_score,
                    'source': 'ai',
                },
            ]

        variants = grid_variants

        # Save DXF for each variant
        for i, v in enumerate(variants):
            out_path = os.path.join(app.config['UPLOAD_FOLDER'],
                                    f"{file_id}_layout_{i}.dxf")
            processor.create_ai_layout_dxf(
                v['placements'], store_boundary['bounds'], out_path,
                coord_mode='bottom_left',
                store_polygon=store_boundary.get('polygon'),
                doors=layout_doors,
            )
            v['dxf_index'] = i

        # ── AI explanation for best variant ───────────────────────────────
        best_placements = variants[0]['placements']
        ai_explanation = get_ai_explanation(best_placements, requirements,
                                            store_w, store_d)

        # ai_layout_concept removed — was a redundant second AI call adding
        # 30-60 s latency with no visible output in the UI.
        ai_layout_concept = None

        # ── Placement summary logging ──────────────────────────────────────
        best_v = variants[0] if variants else None
        placed = best_v['placements'] if best_v else []
        placed_names = [p['fixture'] for p in placed]

        _logger.info("=" * 70)
        _logger.info(f"PLACEMENT SUMMARY  (best variant: {best_v['name'] if best_v else 'N/A'})")
        _logger.info(f"Source: {placement_source}")
        _logger.info(f"Placed: {len(placed)} fixtures")
        _placed_counts = {}
        for n in placed_names:
            _placed_counts[n] = _placed_counts.get(n, 0) + 1
        for fname, cnt in _placed_counts.items():
            _logger.info(f"  [PLACED {cnt}x] {fname}")

        if skipped_fixtures:
            _logger.info(f"Skipped: {len(skipped_fixtures)} fixtures")
            for s in skipped_fixtures:
                _logger.info(f"  [SKIPPED] {s['fixture']} ({s['size_mm']}) — {s['reason']}")
        else:
            _logger.info("Skipped: 0 fixtures — all placed successfully")

        # Check which requested fixtures are missing from placed list
        _all_requested_names = [f['name'] for f in selected_fixtures] + _boh_requested
        _placed_set = set(placed_names)
        _missing = [n for n in _all_requested_names if n not in _placed_set]
        if _missing:
            _logger.info(f"Missing from output ({len(_missing)} items not in any placed list):")
            for m in _missing:
                _logger.info(f"  [MISSING] {m}")
        _logger.info("=" * 70)

        response_data = {
            'file_id': file_id,
            'variants': variants,
            'ai_explanation': ai_explanation,
            'ai_layout_concept': ai_layout_concept,
            'placement_source': placement_source,
            'skipped_fixtures': skipped_fixtures,
            'store_boundary': {
                'polygon': store_boundary.get('polygon'),
                'bounds': store_boundary['bounds'],
            },
            'entrance_wall': requirements['entrance_wall'],
            'compass': compass_from_entrance(requirements['entrance_wall']),
        }
        if ai_error:
            response_data['ai_placement_error'] = ai_error
        if ai_traceback:
            response_data['ai_placement_traceback'] = ai_traceback
        if ai_removed_count > 0:
            response_data['ai_fixtures_removed'] = ai_removed_count

        return jsonify(response_data), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/render-edited-layout', methods=['POST'])
def render_edited_layout():
    """
    Regenerate DXF from user-edited placements (after drag/move).
    Body: { file_id, placements, store_boundary }
    Returns: { download_path }
    """
    data = request.json
    file_id = data.get('file_id')
    placements = data.get('placements', [])
    store_boundary = data.get('store_boundary', {})

    if not file_id or not placements:
        return jsonify({'error': 'file_id and placements required'}), 400

    input_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}.dxf")
    if not os.path.exists(input_path):
        return jsonify({'error': 'DXF file not found'}), 404

    out_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}_edited.dxf")
    try:
        processor = DXFProcessor(input_path)
        bounds = store_boundary.get('bounds', {'min': [0, 0], 'max': [10000, 8000]})
        edited_doors = processor.detect_doors(bounds)
        processor.create_ai_layout_dxf(placements, bounds, out_path,
                                       coord_mode='bottom_left',
                                       store_polygon=store_boundary.get('polygon'),
                                       doors=edited_doors)
        return jsonify({'message': 'Edited layout saved', 'file_id': file_id}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/capacity-analysis/<file_id>', methods=['GET'])
def capacity_analysis(file_id):
    """
    After DXF upload, ask AI to recommend how many fixtures and BOH rooms
    can realistically fit in this store.
    Returns: { store_w_m, store_d_m, store_area_m2, recommendations, summary }
    """
    input_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}.dxf")
    if not os.path.exists(input_path):
        return jsonify({'error': 'File not found'}), 404

    candidate_index = int(request.args.get('candidate_index', 0))
    try:
        processor = DXFProcessor(input_path)
        store_boundary = processor.detect_store_boundary(candidate_index=candidate_index)
        result = get_ai_capacity_analysis(store_boundary)
        return jsonify(result), 200
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


@app.route('/generate-pdf', methods=['POST'])
def generate_pdf():
    """
    Generate a PDF of the layout with dimensions.
    Body: { file_id, placements, store_boundary, requirements, variant_name }
    """
    data = request.json
    file_id = data.get('file_id')
    placements = data.get('placements', [])
    store_boundary = data.get('store_boundary', {})
    requirements = data.get('requirements', {})
    variant_name = data.get('variant_name', 'Store Layout')

    if not file_id or not placements:
        return jsonify({'error': 'file_id and placements required'}), 400

    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}_layout.pdf")

    try:
        _generate_layout_pdf(placements, store_boundary, requirements,
                              variant_name, pdf_path)
        return send_file(pdf_path, as_attachment=True,
                         download_name='titan_store_layout.pdf',
                         mimetype='application/pdf')
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _generate_layout_pdf(placements, store_boundary, requirements,
                          variant_name, pdf_path):
    """Draw store layout as a PDF using reportlab."""
    from reportlab.lib.pagesizes import A3, landscape
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib import colors

    page_w, page_h = landscape(A3)  # ~1190 × 842 points

    c = rl_canvas.Canvas(pdf_path, pagesize=(page_w, page_h))

    bounds = store_boundary.get('bounds', {'min': [0, 0], 'max': [10000, 8000]})
    store_w = bounds['max'][0] - bounds['min'][0]
    store_d = bounds['max'][1] - bounds['min'][1]

    # Drawing area
    margin = 60
    legend_h = 120
    draw_w = page_w - margin * 2
    draw_h = page_h - margin * 2 - 80 - legend_h  # title + legend

    scale = min(draw_w / store_w, draw_h / store_d)
    origin_x = margin + (draw_w - store_w * scale) / 2
    origin_y = margin + legend_h + (draw_h - store_d * scale) / 2

    def tx(x):
        return origin_x + x * scale

    def ty(y):
        return origin_y + y * scale

    # ── title block ──────────────────────────────────────────────────────────
    branch = requirements.get('branch_name') or 'Titan Eyewear'
    c.setFont('Helvetica-Bold', 18)
    c.setFillColor(colors.HexColor('#1e3a5f'))
    c.drawString(margin, page_h - 45, f"Titan Eyewear — {branch}")
    c.setFont('Helvetica', 11)
    c.setFillColor(colors.HexColor('#555555'))
    c.drawString(margin, page_h - 62,
                 f"Layout: {variant_name}  |  "
                 f"Store: {store_w / 1000:.1f} m × {store_d / 1000:.1f} m  |  "
                 f"Entrance: {requirements.get('entrance_wall', 'FRONT')}  |  "
                 f"Tier: {requirements.get('store_tier', 'STANDARD')}")

    # ── store boundary ───────────────────────────────────────────────────────
    polygon = store_boundary.get('polygon')
    c.setStrokeColor(colors.HexColor('#334155'))
    c.setFillColor(colors.HexColor('#f8faff'))
    c.setLineWidth(2)
    if polygon and len(polygon) >= 3:
        path = c.beginPath()
        path.moveTo(tx(polygon[0][0] - bounds['min'][0]),
                    ty(polygon[0][1] - bounds['min'][1]))
        for pt in polygon[1:]:
            path.lineTo(tx(pt[0] - bounds['min'][0]),
                        ty(pt[1] - bounds['min'][1]))
        path.close()
        c.drawPath(path, fill=1, stroke=1)
    else:
        c.rect(tx(0), ty(0), store_w * scale, store_d * scale, fill=1, stroke=1)

    # ── fixtures ─────────────────────────────────────────────────────────────
    for p in placements:
        rot = p.get('rotation', 0) in [90, 270]
        fw = float(p.get('d') or 0) if rot else float(p.get('l') or 0)
        fd = float(p.get('l') or 0) if rot else float(p.get('d') or 0)
        px, py = float(p.get('x') or 0), float(p.get('y') or 0)
        if fw <= 0 or fd <= 0:
            continue  # malformed placement — skip rather than crash the whole PDF

        zone_color = p.get('zone_color') or '#94A3B8'
        try:
            c.setFillColor(colors.HexColor(zone_color))
        except Exception:
            c.setFillColor(colors.HexColor('#94A3B8'))
        c.setFillAlpha(0.75)
        c.setStrokeColor(colors.HexColor('#1e3a5f'))
        c.setStrokeAlpha(1)
        c.setLineWidth(0.8)
        c.rect(tx(px), ty(py), fw * scale, fd * scale, fill=1, stroke=1)

        # label
        name_short = p.get('fixture', p.get('name', 'FIXTURE'))[:22]
        fs = max(4, min(fw, fd) * scale * 0.08)
        if fs > 4 and fw * scale > 20 and fd * scale > 10:
            c.setFillColor(colors.HexColor('#1e3a5f'))
            c.setFillAlpha(1)
            c.setFont('Helvetica', fs)
            cx_ = tx(px + fw / 2)
            cy_ = ty(py + fd / 2) - fs / 2
            c.drawCentredString(cx_, cy_, name_short)

    # ── dimension lines ───────────────────────────────────────────────────────
    dim_offset = 30
    c.setStrokeColor(colors.HexColor('#667eea'))
    c.setStrokeAlpha(1)
    c.setLineWidth(1)
    # Width dimension (bottom)
    y_dim = ty(0) - dim_offset
    c.line(tx(0), y_dim, tx(store_w), y_dim)
    c.line(tx(0), y_dim - 5, tx(0), y_dim + 5)
    c.line(tx(store_w), y_dim - 5, tx(store_w), y_dim + 5)
    c.setFont('Helvetica', 9)
    c.setFillColor(colors.HexColor('#667eea'))
    c.drawCentredString((tx(0) + tx(store_w)) / 2, y_dim - 14,
                        f"{store_w / 1000:.2f} m")
    # Depth dimension (left)
    x_dim = tx(0) - dim_offset
    c.line(x_dim, ty(0), x_dim, ty(store_d))
    c.line(x_dim - 5, ty(0), x_dim + 5, ty(0))
    c.line(x_dim - 5, ty(store_d), x_dim + 5, ty(store_d))
    c.saveState()
    c.translate(x_dim - 14, (ty(0) + ty(store_d)) / 2)
    c.rotate(90)
    c.drawCentredString(0, 0, f"{store_d / 1000:.2f} m")
    c.restoreState()

    # ── zone legend ───────────────────────────────────────────────────────────
    zones_in_use = {}
    for p in placements:
        z = p.get('zone', 'DISPLAY')
        zones_in_use[z] = p.get('zone_color', '#94A3B8')
    leg_x = margin
    leg_y = margin + legend_h - 30
    c.setFont('Helvetica-Bold', 10)
    c.setFillColor(colors.HexColor('#333333'))
    c.drawString(leg_x, leg_y, 'Zone Legend:')
    leg_x += 90
    for zone, color in zones_in_use.items():
        c.setFillColor(colors.HexColor(color))
        c.rect(leg_x, leg_y - 2, 12, 12, fill=1, stroke=0)
        c.setFillColor(colors.HexColor('#333333'))
        c.setFont('Helvetica', 9)
        label = zone.replace('_', ' ').title()
        c.drawString(leg_x + 16, leg_y, label)
        leg_x += len(label) * 6 + 30
        if leg_x > page_w - margin - 60:
            leg_x = margin + 90
            leg_y -= 18

    c.save()


# ── debug AI placement endpoint ──────────────────────────────────────────────

@app.route('/debug-ai-placement/<file_id>', methods=['POST'])
def debug_ai_placement(file_id):
    """
    Test AI placement call in isolation and return raw result + any errors.
    Body: { requirements, selected_fixtures, constraints, boundary_index }
    Returns: { placement_source, placements, ai_error, ai_traceback, fixture_count }
    """
    data = request.json or {}
    requirements = data.get('requirements', {})
    selected_fixtures = data.get('selected_fixtures', [])
    constraints = data.get('constraints', {})
    boundary_index = int(data.get('boundary_index', 0))

    input_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}.dxf")
    if not os.path.exists(input_path):
        return jsonify({'error': 'DXF file not found'}), 404

    try:
        processor = DXFProcessor(input_path)
        store_boundary = processor.detect_store_boundary(candidate_index=boundary_index)

        ai_placements = None
        ai_layout_style = None
        ai_summary = None
        ai_error = None
        ai_traceback_str = None

        try:
            ai_placements, ai_layout_style, ai_summary = get_ai_layout_placements(
                store_boundary,
                selected_fixtures,
                constraints,
                requirements=requirements,
            )
        except Exception as e:
            import traceback as _tb
            ai_error = str(e)
            ai_traceback_str = _tb.format_exc()

        return jsonify({
            'placement_source': 'ai' if ai_placements else 'failed',
            'fixture_count': len(ai_placements) if ai_placements else 0,
            'layout_style': ai_layout_style,
            'summary': ai_summary,
            'placements': ai_placements or [],
            'ai_error': ai_error,
            'ai_traceback': ai_traceback_str,
            'store_bounds': store_boundary.get('bounds'),
        }), 200
    except Exception as e:
        import traceback as _tb
        return jsonify({'error': str(e), 'traceback': _tb.format_exc()}), 500


# ── download endpoints ────────────────────────────────────────────────────────

@app.route('/download-ai-layout/<file_id>', methods=['GET'])
def download_ai_layout(file_id):
    """Download a generated DXF. ?variant=0|1|2 or ?edited=1"""
    edited = request.args.get('edited', '0') == '1'
    if edited:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}_edited.dxf")
        dl_name = 'titan_layout_edited.dxf'
    else:
        variant = int(request.args.get('variant', 0))
        filepath = os.path.join(app.config['UPLOAD_FOLDER'],
                                f"{file_id}_layout_{variant}.dxf")
        dl_name = f'titan_layout_v{variant + 1}.dxf'
        # fallback for old single-file path
        if not os.path.exists(filepath):
            filepath = os.path.join(app.config['UPLOAD_FOLDER'],
                                    f"{file_id}_ai_layout.dxf")
            dl_name = 'ai_layout.dxf'

    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404
    return send_file(filepath, as_attachment=True, download_name=dl_name,
                     mimetype='application/octet-stream')


@app.route('/download/<file_id>', methods=['GET'])
def download_file(file_id):
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{file_id}_optimized.dxf")
    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404
    return send_file(filepath, as_attachment=True, download_name='optimized_layout.dxf')


if __name__ == '__main__':
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    app.run(debug=True, port=5000)
