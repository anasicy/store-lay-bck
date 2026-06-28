import os
from typing import Optional
import ezdxf
from ezdxf import bbox as ezdxf_bbox

class DXFProcessor:
    def __init__(self, filepath):
        self.filepath = filepath
        self.doc = ezdxf.readfile(filepath)  # type: ignore[reportPrivateImportUsage]
        self.msp = self.doc.modelspace()
    
    def get_metadata(self):
        """Extract basic DXF file information"""
        entities = list(self.msp)
        
        layers = set()
        entity_types = {}
        
        for entity in entities:
            layers.add(entity.dxf.get('layer', '0'))
            entity_type = entity.dxftype()
            entity_types[entity_type] = entity_types.get(entity_type, 0) + 1
        
        return {
            'total_entities': len(entities),
            'layers': list(layers),
            'entity_types': entity_types
        }
    
    def extract_entities(self):
        """Extract all entities with their properties"""
        entities_data = []
        
        for entity in self.msp:
            entity_info = {
                'type': entity.dxftype(),
                'layer': entity.dxf.layer,
                'color': entity.dxf.get('color', 256),
            }

            # Get bounding box
            try:
                bb = ezdxf_bbox.extents([entity], fast=True)
                if bb:
                    entity_info['bbox'] = {
                        'min': (bb.extmin.x, bb.extmin.y),
                        'max': (bb.extmax.x, bb.extmax.y)
                    }
                else:
                    entity_info['bbox'] = None
            except Exception:
                entity_info['bbox'] = None
            
            # Extract coordinates based on type
            if entity.dxftype() == 'LINE':
                entity_info['start'] = (entity.dxf.start.x, entity.dxf.start.y)
                entity_info['end'] = (entity.dxf.end.x, entity.dxf.end.y)
            
            elif entity.dxftype() == 'CIRCLE':
                entity_info['center'] = (entity.dxf.center.x, entity.dxf.center.y)
                entity_info['radius'] = entity.dxf.radius
            
            elif entity.dxftype() in ['LWPOLYLINE', 'POLYLINE']:
                entity_info['points'] = [(p[0], p[1]) for p in entity.get_points()]  # type: ignore[reportAttributeAccessIssue]
            
            entities_data.append({
                'entity': entity,
                'data': entity_info
            })
        
        return entities_data
    
    # DXF unit code → mm conversion factor
    _UNIT_TO_MM = {1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0}

    # Known wall layer names (case-insensitive match)
    _WALL_LAYERS = ('ceiling', 'wall', 'walls', 'store', 'boundary',
                    'outline', 'perimeter', 'lease', 'leasehold')

    # Known column layer name keywords
    _COLUMN_LAYERS = ('column', 'col', 'columns', 'pillar', 'post',
                      'structural', 'struct', 'support', 'pier')

    # Known beam layer name keywords
    _BEAM_LAYERS = ('beam', 'beams', 'girder', 'joist', 'rafter',
                    'structural', 'struct', 'framing', 'lintel')

    def _unit_scale(self):
        """Return mm-per-unit factor based on DXF $INSUNITS header."""
        code = self.doc.header.get('$INSUNITS', 0)
        return self._UNIT_TO_MM.get(code, 1.0)

    def _iter_all_entities(self):
        """Yield all entities, expanding INSERT blocks into modelspace coords."""
        for entity in self.msp:
            if entity.dxftype() == 'INSERT':
                try:
                    for ve in entity.virtual_entities():  # type: ignore[reportAttributeAccessIssue]
                        yield ve
                except Exception:
                    pass
            else:
                yield entity

    def _polygonize_walls(self):
        """
        Primary boundary detection via wall geometry.

        Expands INSERT blocks into modelspace coordinates so that wall geometry
        stored inside blocks is also considered. Converts DXF units to mm.
        Tries closed LWPOLYLINE first (most accurate), then LINE concave hull.
        """
        try:
            from shapely.geometry import MultiPoint
        except ImportError:
            return []

        scale = self._unit_scale()  # convert DXF units → mm

        # ── Collect closed LWPOLYLINE candidates from expanded entities ────────
        lwpoly_candidates = []
        line_pts = []

        for entity in self._iter_all_entities():
            etype = entity.dxftype()

            if etype in ('LWPOLYLINE', 'POLYLINE'):
                try:
                    is_closed = (getattr(entity, 'closed', False) or
                                 bool(entity.dxf.get('flags', 0) & 1))
                    pts = [(p[0] * scale, p[1] * scale)
                           for p in entity.get_points()]  # type: ignore[reportAttributeAccessIssue]
                    if len(pts) >= 3:
                        if not is_closed:
                            dx = pts[-1][0] - pts[0][0]
                            dy = pts[-1][1] - pts[0][1]
                            is_closed = (dx*dx + dy*dy) < (200*200)
                        if is_closed:
                            xs = [p[0] for p in pts]
                            ys = [p[1] for p in pts]
                            w = max(xs) - min(xs)
                            h = max(ys) - min(ys)
                            if w >= 500 and h >= 500:
                                n = len(pts)
                                area = abs(sum(
                                    pts[i][0]*pts[(i+1)%n][1] -
                                    pts[(i+1)%n][0]*pts[i][1]
                                    for i in range(n)
                                )) / 2.0
                                lwpoly_candidates.append({
                                    'pts': pts, 'area': area,
                                    'w': w, 'h': h,
                                    'xs': xs, 'ys': ys,
                                })
                except Exception:
                    pass

            elif etype == 'LINE':
                try:
                    s = (entity.dxf.start.x * scale, entity.dxf.start.y * scale)
                    e = (entity.dxf.end.x * scale, entity.dxf.end.y * scale)
                    length = ((e[0]-s[0])**2 + (e[1]-s[1])**2)**0.5
                    if 50 <= length <= 30000:
                        line_pts.extend([s, e])
                except Exception:
                    pass

        # ── Pick best LWPOLYLINE: largest that is not a container of others ────
        if lwpoly_candidates:
            lwpoly_candidates.sort(key=lambda c: c['area'], reverse=True)

            def _contains(outer, inner):
                return (outer['xs'][0] <= min(inner['xs']) and
                        max(outer['xs']) >= max(inner['xs']) and
                        outer['ys'][0] <= min(inner['ys']) and
                        max(outer['ys']) >= max(inner['ys']))

            # Mark containers (sheet borders that wrap everything else)
            for i, c in enumerate(lwpoly_candidates):
                c['_container'] = any(
                    _contains(c, lwpoly_candidates[j])
                    for j in range(len(lwpoly_candidates)) if j != i
                )

            # Best = largest non-container; fall back to largest overall
            non_containers = [c for c in lwpoly_candidates if not c['_container']]
            best = non_containers[0] if non_containers else lwpoly_candidates[0]

            xs_o, ys_o = best['xs'], best['ys']
            return [{
                'width_mm': round(best['w']),
                'height_mm': round(best['h']),
                'layer': 'walls(lwpoly)',
                'polygon': best['pts'][:40],
                'bounds': {'min': [min(xs_o), min(ys_o)],
                           'max': [max(xs_o), max(ys_o)]},
                'area': best['area'],
                '_title': False, '_container': False,
            }]

        # ── Fallback: concave hull of LINE endpoints ───────────────────────────
        if len(line_pts) >= 3:
            mp = MultiPoint(line_pts)
            try:
                from shapely import concave_hull
                hull = concave_hull(mp, ratio=0.2)
            except Exception:
                hull = mp.convex_hull
            if hasattr(hull, 'exterior'):
                coords = list(hull.exterior.coords)  # type: ignore[reportAttributeAccessIssue]
                xs_o = [p[0] for p in coords]
                ys_o = [p[1] for p in coords]
                w = max(xs_o) - min(xs_o)
                h = max(ys_o) - min(ys_o)
                if w >= 500 and h >= 500:
                    return [{
                        'width_mm': round(w), 'height_mm': round(h),
                        'layer': 'walls(auto-hull)',
                        'polygon': coords[:40],
                        'bounds': {'min': [min(xs_o), min(ys_o)],
                                   'max': [max(xs_o), max(ys_o)]},
                        'area': hull.area,
                        '_title': False, '_container': False,
                    }]

        return []

    def _reconstruct_polygon_from_lines(self, lines, tolerance=10.0):
        """Trace a closed polygon from a list of (start, end) LINE segments."""
        from collections import defaultdict

        def snap(pt):
            return (round(pt[0] / tolerance) * tolerance,
                    round(pt[1] / tolerance) * tolerance)

        adj = defaultdict(list)
        for i, (start, end) in enumerate(lines):
            s, e = snap(start), snap(end)
            if s == e:
                continue
            adj[s].append((e, i))
            adj[e].append((s, i))

        # Start from a node with exactly 2 connections (clean corner)
        start_nodes = [n for n in adj if len(adj[n]) == 2]
        if not start_nodes:
            start_nodes = list(adj.keys())
        if not start_nodes:
            return []

        start_node = start_nodes[0]
        path = [start_node]
        used_edges = set()
        current = start_node

        for _ in range(len(lines) + 2):
            nexts = [(n, idx) for n, idx in adj[current] if idx not in used_edges]
            if not nexts:
                break
            next_node, edge_idx = nexts[0]
            used_edges.add(edge_idx)
            if next_node == start_node:
                return path  # closed polygon found
            if next_node in path:
                break
            path.append(next_node)
            current = next_node

        return []

    def _line_based_candidates(self):
        """Find boundary candidates by grouping LINE entities by layer.

        Tries polygon reconstruction first; falls back to percentile bounding box.
        """
        from collections import defaultdict

        layer_lines = defaultdict(list)
        for entity in self.msp:
            if entity.dxftype() != 'LINE':
                continue
            try:
                layer = entity.dxf.get('layer', '0')
                start = (entity.dxf.start.x, entity.dxf.start.y)
                end = (entity.dxf.end.x, entity.dxf.end.y)
                if abs(start[0] - end[0]) < 1 and abs(start[1] - end[1]) < 1:
                    continue  # zero-length line
                layer_lines[layer].append((start, end))
            except Exception:
                continue

        # Prioritize layers whose names suggest store boundaries
        PRIORITY = ['lease', 'wall', 'boundary', 'outline', 'store', 'perimeter',
                    'leasehold', 'unit']

        def priority(name):
            low = name.lower()
            for i, kw in enumerate(PRIORITY):
                if kw in low:
                    return i
            return len(PRIORITY)

        sorted_layers = sorted(layer_lines.keys(), key=priority)

        candidates = []
        seen_areas = []

        for layer in sorted_layers:
            lines = layer_lines[layer]
            if len(lines) < 3:
                continue

            polygon = self._reconstruct_polygon_from_lines(lines)

            if polygon and len(polygon) >= 4:
                xs = [p[0] for p in polygon]
                ys = [p[1] for p in polygon]
                x_min, x_max = min(xs), max(xs)
                y_min, y_max = min(ys), max(ys)
            else:
                # Percentile bounding box (5th–95th) to exclude stray lines
                all_pts = [p for seg in lines for p in seg]
                xs_s = sorted(p[0] for p in all_pts)
                ys_s = sorted(p[1] for p in all_pts)
                n = len(xs_s)
                lo, hi = max(0, n // 20), min(n - 1, n - n // 20 - 1)
                x_min, x_max = xs_s[lo], xs_s[hi]
                y_min, y_max = ys_s[lo], ys_s[hi]
                polygon = [(x_min, y_min), (x_max, y_min),
                           (x_max, y_max), (x_min, y_max)]

            w = x_max - x_min
            h = y_max - y_min
            if w < 500 or h < 500:
                continue
            if w > 150000 or h > 150000:
                continue

            area = w * h
            # Skip near-duplicate areas
            if any(abs(area - a) / max(a, 1) < 0.05 for a in seen_areas):
                continue
            seen_areas.append(area)

            candidates.append({
                'width_mm': round(w), 'height_mm': round(h),
                'layer': layer,
                'polygon': polygon,
                'bounds': {'min': [x_min, y_min], 'max': [x_max, y_max]},
                'area': area,
            })

        candidates.sort(key=lambda c: c['area'], reverse=True)
        return candidates[:5]

    def get_boundary_candidates(self):
        """
        Return all viable closed polygon candidates, best candidates first.

        Detection pipeline (in priority order):
          1. Wall-polygonize  – shapely polygonize on LINE entities only.
                                Sheet borders (always LWPOLYLINE) are invisible here.
          2. Closed polylines – LWPOLYLINE / POLYLINE, ranked with title-block and
                                container polygons pushed to the end.
          3. LINE-based       – per-layer polygon reconstruction / bbox fallback.

        Each entry: {width_mm, height_mm, layer, polygon (≤40 pts), bounds}.
        """
        _TITLE_KWS = ('border', 'frame', 'title', 'sheet', 'margin', 'limit',
                      'viewport', 'defpoint')

        def _is_title_layer(name):
            low = name.lower().strip()
            if low in ('0', 'defpoints'):
                return True
            return any(kw in low for kw in _TITLE_KWS)

        # ── Source 1: wall polygonize (best — ignores LWPOLYLINE sheet borders) ─
        raw = self._polygonize_walls()

        # ── Source 2: closed LWPOLYLINE / POLYLINE ───────────────────────────
        poly_raw = []
        for entity in self.msp:
            if entity.dxftype() not in ('LWPOLYLINE', 'POLYLINE'):
                continue
            try:
                layer = entity.dxf.get('layer', '0')
                # Always skip layer "0" (drawing sheet border) — never the store
                if layer == '0':
                    continue
                is_closed = getattr(entity, 'closed', False) or bool(entity.dxf.get('flags', 0) & 1)
                if not is_closed:
                    # Also treat as closed if last point ≈ first point
                    pts_check = [(p[0], p[1]) for p in entity.get_points()]  # type: ignore[reportAttributeAccessIssue]
                    if len(pts_check) >= 3:
                        dx = pts_check[-1][0] - pts_check[0][0]
                        dy = pts_check[-1][1] - pts_check[0][1]
                        is_closed = (dx * dx + dy * dy) < (100 * 100)
                if not is_closed:
                    continue
                pts = [(p[0], p[1]) for p in entity.get_points()]  # type: ignore[reportAttributeAccessIssue]
                if len(pts) < 3:
                    continue
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                w = max(xs) - min(xs)
                h = max(ys) - min(ys)
                if w < 500 or h < 500:
                    continue
                n = len(pts)
                area = abs(sum(
                    pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1]
                    for i in range(n)
                )) / 2.0
                poly_raw.append({
                    'area': area, 'width_mm': round(w), 'height_mm': round(h),
                    'layer': layer, 'polygon': pts,
                    'bounds': {'min': [min(xs), min(ys)], 'max': [max(xs), max(ys)]},
                    '_title': _is_title_layer(layer),
                    '_container': False,
                })
            except Exception:
                continue

        poly_raw.sort(key=lambda c: c['area'], reverse=True)

        # Containment: polygon that fully contains another = sheet border → push last
        def _bbox_contains(outer, inner):
            return (outer['bounds']['min'][0] <= inner['bounds']['min'][0] and
                    outer['bounds']['min'][1] <= inner['bounds']['min'][1] and
                    outer['bounds']['max'][0] >= inner['bounds']['max'][0] and
                    outer['bounds']['max'][1] >= inner['bounds']['max'][1])

        for i in range(len(poly_raw)):
            for j in range(len(poly_raw)):
                if i != j and _bbox_contains(poly_raw[i], poly_raw[j]):
                    poly_raw[i]['_container'] = True
                    break

        # Sort closed-polyline candidates: good first, bad last
        def _rank(c):
            return (int(c['_container']) + int(c['_title']), -c['area'])
        poly_raw.sort(key=_rank)

        # Merge into raw, deduplicating by area
        existing_areas = [c['area'] for c in raw]
        for c in poly_raw:
            if not any(abs(c['area'] - a) / max(a, 1) < 0.05 for a in existing_areas):
                raw.append(c)
                existing_areas.append(c['area'])

        # ── Source 3: LINE-based per-layer reconstruction ────────────────────
        line_cands = self._line_based_candidates()
        for lc in line_cands:
            if not any(abs(lc['area'] - a) / max(a, 1) < 0.05 for a in existing_areas):
                lc['_title'] = _is_title_layer(lc.get('layer', '0'))
                lc['_container'] = False
                raw.append(lc)
                existing_areas.append(lc['area'])

        result = []
        for c in raw[:8]:
            poly = c['polygon']
            if len(poly) > 40:
                step = len(poly) / 40
                poly = [poly[int(i * step)] for i in range(40)]
            result.append({
                'width_mm': c['width_mm'],
                'height_mm': c['height_mm'],
                'layer': c['layer'],
                'polygon': poly,
                'bounds': c['bounds'],
            })
        return result

    def detect_store_boundary(self, candidate_index=0):
        """
        Detect the store wall boundary from the DXF.
        Returns {'polygon': [(x,y), ...], 'bounds': {'min': [x,y], 'max': [x,y]}}.
        candidate_index: which candidate to use (0 = largest by area).
        Falls back to bounding box of all entities if no closed polyline is found.
        """
        candidates = self.get_boundary_candidates()

        if candidates:
            idx = max(0, min(candidate_index, len(candidates) - 1))
            c = candidates[idx]
            return {'polygon': c['polygon'], 'bounds': c['bounds']}

        # Fallback: bounding box of all entities
        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')
        for entity in self.msp:
            try:
                bb = ezdxf_bbox.extents([entity], fast=True)
                if bb:
                    min_x = min(min_x, bb.extmin.x)
                    min_y = min(min_y, bb.extmin.y)
                    max_x = max(max_x, bb.extmax.x)
                    max_y = max(max_y, bb.extmax.y)
            except Exception:
                continue

        if min_x == float('inf'):
            return {'polygon': None, 'bounds': {'min': [0, 0], 'max': [10000, 8000]}}

        polygon = [
            (min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)
        ]
        return {'polygon': polygon, 'bounds': {'min': [min_x, min_y], 'max': [max_x, max_y]}}

    def detect_columns(self, store_bounds=None):
        """
        Detect structural columns in the DXF.

        Detection sources (in order):
          1. INSERT block references — column symbols stored as blocks.
             Matched by layer name OR block name containing column keywords.
             Also catches any INSERT whose bounding box is small and squarish.
          2. Closed LWPOLYLINE / POLYLINE — small solid rectangles.
             Named-layer columns: aspect ≤ 5 (100–2000 mm).
             Geometry-only columns: aspect ≤ 2 (truly square, 100–800 mm)
             to avoid picking up room partitions.
          3. CIRCLE entities — round columns.

        Returns list of dicts:
          {x, y, width, height, layer, bounds, shape ('rectangle'|'circle')}
        Coordinates are in mm (scaled from DXF units).
        """
        from ezdxf import bbox as ezdxf_bbox

        scale = self._unit_scale()
        MIN_SIZE = 50        # mm — minimum column dimension
        MAX_SIZE = 2000      # mm — maximum column dimension (named-layer)
        MAX_SIZE_GEO = 2000  # mm — same as named-layer; boundary excluded by size elsewhere
        MAX_ASPECT_NAMED = 5   # aspect cap for explicitly named column layers
        MAX_ASPECT_GEO = 3     # aspect cap for geometry-only (column squares can be 1:2.5ish)

        sb = store_bounds
        # Columns are often embedded in walls, so their centres sit on or just
        # outside the boundary polyline.  Allow 1500 mm margin around the store.
        _COL_MARGIN = 1500

        def _in_store(cx, cy):
            if not sb:
                return True
            return (sb['min'][0] - _COL_MARGIN <= cx <= sb['max'][0] + _COL_MARGIN and
                    sb['min'][1] - _COL_MARGIN <= cy <= sb['max'][1] + _COL_MARGIN)

        candidates = []

        # ── Source 1: INSERT block references ────────────────────────────────
        for entity in self.msp:
            if entity.dxftype() != 'INSERT':
                continue
            try:
                layer = entity.dxf.get('layer', '0')
                block_name = entity.dxf.get('name', '').lower()
                layer_low = layer.lower()
                is_col_layer = any(kw in layer_low for kw in self._COLUMN_LAYERS)
                is_col_block = any(kw in block_name
                                   for kw in ('col', 'column', 'pillar', 'post',
                                              'pier', 'support'))
                bb = ezdxf_bbox.extents([entity], fast=False)
                if not bb:
                    continue
                x1 = bb.extmin.x * scale
                y1 = bb.extmin.y * scale
                x2 = bb.extmax.x * scale
                y2 = bb.extmax.y * scale
                w = x2 - x1
                h = y2 - y1
                if w <= 0 or h <= 0:
                    continue
                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2
                aspect = max(w, h) / max(min(w, h), 1)
                # Named layer/block: relaxed size & aspect
                if (is_col_layer or is_col_block):
                    if MIN_SIZE <= w <= MAX_SIZE and MIN_SIZE <= h <= MAX_SIZE and aspect <= MAX_ASPECT_NAMED:
                        if _in_store(cx, cy):
                            candidates.append({
                                'x': round(cx), 'y': round(cy),
                                'width': round(w), 'height': round(h),
                                'layer': layer,
                                'bounds': {'min': [x1, y1], 'max': [x2, y2]},
                                'shape': 'rectangle',
                            })
                else:
                    # Geometry only: must be small and truly square
                    if (MIN_SIZE <= w <= MAX_SIZE_GEO and
                            MIN_SIZE <= h <= MAX_SIZE_GEO and
                            aspect <= MAX_ASPECT_GEO):
                        if _in_store(cx, cy):
                            candidates.append({
                                'x': round(cx), 'y': round(cy),
                                'width': round(w), 'height': round(h),
                                'layer': layer,
                                'bounds': {'min': [x1, y1], 'max': [x2, y2]},
                                'shape': 'rectangle',
                            })
            except Exception:
                continue

        # ── Source 2: Closed LWPOLYLINE / POLYLINE ───────────────────────────
        for entity in self._iter_all_entities():
            if entity.dxftype() not in ('LWPOLYLINE', 'POLYLINE'):
                continue
            try:
                layer = entity.dxf.get('layer', '0')
                is_closed = (getattr(entity, 'closed', False) or
                             bool(entity.dxf.get('flags', 0) & 1))
                pts = [(p[0] * scale, p[1] * scale)
                       for p in entity.get_points()]  # type: ignore[reportAttributeAccessIssue]
                if len(pts) < 3:
                    continue
                if not is_closed:
                    dx = pts[-1][0] - pts[0][0]
                    dy = pts[-1][1] - pts[0][1]
                    is_closed = (dx * dx + dy * dy) < (50 * 50)
                if not is_closed:
                    continue
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                w = max(xs) - min(xs)
                h = max(ys) - min(ys)
                if w <= 0 or h <= 0:
                    continue
                cx = (min(xs) + max(xs)) / 2
                cy = (min(ys) + max(ys)) / 2
                layer_low = layer.lower()
                is_col_layer = any(kw in layer_low for kw in self._COLUMN_LAYERS)
                aspect = max(w, h) / max(min(w, h), 1)
                if is_col_layer:
                    ok = (MIN_SIZE <= w <= MAX_SIZE and
                          MIN_SIZE <= h <= MAX_SIZE and
                          aspect <= MAX_ASPECT_NAMED)
                else:
                    # Geometry only — must be truly small and square
                    ok = (MIN_SIZE <= w <= MAX_SIZE_GEO and
                          MIN_SIZE <= h <= MAX_SIZE_GEO and
                          aspect <= MAX_ASPECT_GEO)
                if ok and _in_store(cx, cy):
                    candidates.append({
                        'x': round(cx), 'y': round(cy),
                        'width': round(w), 'height': round(h),
                        'layer': layer,
                        'bounds': {'min': [min(xs), min(ys)],
                                   'max': [max(xs), max(ys)]},
                        'shape': 'rectangle',
                    })
            except Exception:
                continue

        # ── Source 3: CIRCLE entities (round columns) ─────────────────────────
        for entity in self._iter_all_entities():
            if entity.dxftype() != 'CIRCLE':
                continue
            try:
                layer = entity.dxf.get('layer', '0')
                cx = entity.dxf.center.x * scale
                cy = entity.dxf.center.y * scale
                r = entity.dxf.radius * scale
                diameter = r * 2
                layer_low = layer.lower()
                is_col_layer = any(kw in layer_low for kw in self._COLUMN_LAYERS)
                max_d = MAX_SIZE if is_col_layer else MAX_SIZE_GEO
                # Small symbol circles (e.g. water inlet/outlet markers,
                # ~30-200mm) satisfy the same broad size range as a real
                # round column when no layer name is available to tell them
                # apart. Require a larger minimum for geometry-only matches
                # so plumbing markers aren't misdetected as columns.
                min_d = MIN_SIZE if is_col_layer else 250
                if (min_d <= diameter <= max_d) and _in_store(cx, cy):
                    candidates.append({
                        'x': round(cx), 'y': round(cy),
                        'width': round(diameter), 'height': round(diameter),
                        'radius': round(r),
                        'layer': layer,
                        'bounds': {'min': [cx - r, cy - r],
                                   'max': [cx + r, cy + r]},
                        'shape': 'circle',
                    })
            except Exception:
                continue

        # Remove near-duplicates (centres within 50 mm)
        unique = []
        for c in candidates:
            if not any(abs(c['x'] - u['x']) < 50 and abs(c['y'] - u['y']) < 50
                       for u in unique):
                unique.append(c)
        return unique

    def detect_plumbing_points(self, store_bounds=None):
        """
        Detect water inlet/outlet markers for wet rooms (Toilet, Fitting Lab).

        These are drawn as small CIRCLE entities in close pairs (one inlet +
        one outlet) — much smaller than structural columns. A single small
        circle is treated as noise/unrelated and ignored; only circles found
        in a close pair/cluster count as a real plumbing point, reported as
        the cluster's centroid.

        Returns list of dicts: {x, y, radius, layer} in mm.
        """
        scale = self._unit_scale()
        MIN_R, MAX_R = 30, 200    # mm — small symbol circles only, not columns
        PAIR_DIST = 600           # mm — max centre-to-centre gap to count as a pair

        sb = store_bounds

        def _in_store(cx, cy):
            if not sb:
                return True
            return (sb['min'][0] <= cx <= sb['max'][0] and
                    sb['min'][1] <= cy <= sb['max'][1])

        small_circles = []
        for entity in self._iter_all_entities():
            if entity.dxftype() != 'CIRCLE':
                continue
            try:
                layer = entity.dxf.get('layer', '0')
                cx = entity.dxf.center.x * scale
                cy = entity.dxf.center.y * scale
                r = entity.dxf.radius * scale
                if not (MIN_R <= r <= MAX_R):
                    continue
                if not _in_store(cx, cy):
                    continue
                small_circles.append({'x': cx, 'y': cy, 'radius': r, 'layer': layer})
            except Exception:
                continue

        def _dist(a, b):
            return ((a['x'] - b['x']) ** 2 + (a['y'] - b['y']) ** 2) ** 0.5

        n = len(small_circles)
        visited = [False] * n
        points = []
        for i in range(n):
            if visited[i]:
                continue
            cluster = [i]
            visited[i] = True
            changed = True
            while changed:
                changed = False
                for j in range(n):
                    if visited[j]:
                        continue
                    if any(_dist(small_circles[j], small_circles[k]) <= PAIR_DIST
                           for k in cluster):
                        cluster.append(j)
                        visited[j] = True
                        changed = True
            if len(cluster) >= 2:
                xs = [small_circles[k]['x'] for k in cluster]
                ys = [small_circles[k]['y'] for k in cluster]
                avg_r = sum(small_circles[k]['radius'] for k in cluster) / len(cluster)
                points.append({
                    'x': round(sum(xs) / len(xs)),
                    'y': round(sum(ys) / len(ys)),
                    'radius': round(avg_r),
                    'layer': small_circles[cluster[0]]['layer'],
                })
        return points

    # ── BOB (Bottom-of-Beam) height helpers ──────────────────────────────────

    @staticmethod
    def _parse_bob_from_layer(layer_name):
        """
        Extract a BOB elevation (mm) encoded in a layer name.

        Recognises patterns like:
          BEAM-3500   BEAM_3500   BEAM@3200   BOB-2800
          BEAM-H3000  LINTEL-2400  BEAM-3.5M  GIRDER_3.5m
        Returns an integer (mm) in range 500–10 000, or None.
        """
        import re
        name = layer_name.upper()
        m = re.search(r'[-_@=]H?(\d+(?:\.\d+)?)\s*(MM?|M)?\b', name)
        if m:
            val  = float(m.group(1))
            unit = (m.group(2) or '').replace(' ', '')
            if unit == 'MM' or (unit == '' and val >= 500):
                if 500 <= val <= 10000:
                    return round(val)
            elif unit == 'M' or (unit == '' and val < 100):
                val_mm = val * 1000
                if 500 <= val_mm <= 10000:
                    return round(val_mm)
        return None

    @staticmethod
    def _parse_bob_from_text(text):
        """
        Extract a BOB elevation (mm) from a TEXT / MTEXT string.

        Handles:
          metric  — 3500  3500mm  3.5m  BOB=3500  BOT:3200  H=2800
          imperial— BOB:14'10"  14'10"  14'-10"  14 ft 10 in
        Returns an integer (mm) in range 500–15 000, or None.
        """
        import re
        raw = (text or '').strip()
        # Strip DXF rich-text formatting codes like {\C256;...}
        raw = re.sub(r'\{[^}]*\}', lambda m: re.sub(r'\\[A-Za-z][^;]*;', '', m.group(0)).strip('{}'), raw)
        raw = re.sub(r'\\[A-Za-z][^;]*;', '', raw).strip()
        upper = raw.upper()

        # ── Imperial with explicit BOB/BOT label: BOB:14'10"  BOT 14'-10" ──────
        # Require the BOB/BOT keyword so bare ceiling heights like +5'6" are ignored.
        m_imp = re.search(
            r'(?:BOB|BOT(?:TOM)?)\s*[=:\s]\s*(\d+)\'\s*-?\s*(\d+(?:\.\d+)?)\s*"',
            upper
        )
        if m_imp:
            feet   = int(m_imp.group(1))
            inches = float(m_imp.group(2))
            val_mm = feet * 304.8 + inches * 25.4
            if 2000 <= val_mm <= 15000:
                return round(val_mm)

        # ── Metric with explicit label: BOB=3500  BOT:3200  H=2800  3500mm ────
        m_met = re.search(
            r'(?:BOB|BOT(?:TOM)?|HEIGHT|H|EL(?:EV)?)'
            r'\s*[=:]\s*(\d+(?:\.\d+)?)\s*(MM?|M)?\b',
            upper
        )
        if m_met:
            val  = float(m_met.group(1))
            unit = (m_met.group(2) or '').strip()
            if unit in ('MM', '') and val >= 2000:
                if 2000 <= val <= 15000:
                    return round(val)
            elif unit == 'M' or (unit == '' and val < 100):
                val_mm = val * 1000
                if 2000 <= val_mm <= 15000:
                    return round(val_mm)
        return None

    @staticmethod
    def _read_mtext_raw(entity):
        """Return raw text string from a TEXT or MTEXT entity."""
        try:
            if entity.dxftype() == 'TEXT':
                return entity.dxf.text
            # MTEXT — try multiple ezdxf API variants
            try:
                return entity.text          # ezdxf ≥ 0.18
            except AttributeError:
                pass
            try:
                return entity.dxf.text
            except AttributeError:
                pass
        except Exception:
            pass
        return ''

    def _collect_bob_texts(self, scale):
        """
        Return list of (x_mm, y_mm, bob_mm) for every TEXT/MTEXT in the
        drawing that carries a BOB height.

        Strategy:
        1. Search modelspace + expanded INSERT blocks (standard path).
        2. If nothing found, search EVERY block definition for ones that
           contain BOB MTEXT alongside beam LINE entities.  When found,
           look for a corresponding modelspace-referenced block with the
           same LINE count and compute the coordinate transform to bring
           the annotation positions into modelspace coordinates.
        """
        results = []
        sources = list(self.msp)
        # Also expand INSERT blocks
        for e in self.msp:
            if e.dxftype() == 'INSERT':
                try:
                    sources.extend(e.virtual_entities())  # type: ignore[reportAttributeAccessIssue]
                except Exception:
                    pass
        for entity in sources:
            if entity.dxftype() not in ('TEXT', 'MTEXT'):
                continue
            try:
                pos = entity.dxf.insert
                ex, ey = pos.x * scale, pos.y * scale
                raw = self._read_mtext_raw(entity)
                h = self._parse_bob_from_text(raw)
                if h is not None:
                    results.append((ex, ey, h))
            except Exception:
                continue

        if not results:
            results = self._collect_bob_from_annotated_blocks(scale)

        return results

    def _collect_bob_from_annotated_blocks(self, scale):
        """
        Scan ALL block definitions for ones that have BOB MTEXT annotations
        AND beam LINE entities.  These are "annotated" versions of blocks that
        may be referenced from modelspace without the annotations.

        For each annotated block, find the corresponding modelspace INSERT
        (matched by LINE count), compute the coordinate offset, and transform
        the annotation positions into modelspace coordinates.
        """
        results = []

        # Build map of modelspace INSERT blocks: name → INSERT entity
        msp_inserts = {}
        for e in self.msp:
            if e.dxftype() == 'INSERT':
                msp_inserts[e.dxf.name] = e

        # Pre-compute centroid of beam LINEs for each modelspace block
        def _beam_line_centroid(block_def):
            pts = []
            for e in block_def:
                if e.dxftype() != 'LINE':
                    continue
                layer = e.dxf.get('layer', '0')
                if any(kw in layer.lower() for kw in self._BEAM_LAYERS):
                    pts.append((e.dxf.start.x, e.dxf.start.y))
                    pts.append((e.dxf.end.x, e.dxf.end.y))
            if not pts:
                return None, 0
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            return (cx, cy), len(pts) // 2

        ms_block_centroids = {}  # block_name → (centroid, line_count)
        for name, ins in msp_inserts.items():
            blk = self.doc.blocks.get(name)
            if blk:
                c, n = _beam_line_centroid(blk)
                if c:
                    ms_block_centroids[name] = (c, n, ins)

        for block in self.doc.blocks:
            if block.name.startswith('*'):
                continue  # skip paper spaces / anonymous blocks

            # Collect BOB MTEXT from this block
            bob_texts_in_block = []
            for e in block:
                if e.dxftype() not in ('TEXT', 'MTEXT'):
                    continue
                try:
                    pos = e.dxf.insert
                    raw = self._read_mtext_raw(e)
                    h = self._parse_bob_from_text(raw)
                    if h is not None:
                        bob_texts_in_block.append((pos.x, pos.y, h))
                except Exception:
                    continue

            if not bob_texts_in_block:
                continue

            # Compute centroid + count of beam LINEs in this annotated block
            ann_centroid, ann_line_count = _beam_line_centroid(block)
            if ann_centroid is None or ann_line_count == 0:
                continue

            # Find a modelspace block with the same LINE count
            for ms_name, (ms_centroid, ms_count, ms_insert) in ms_block_centroids.items():
                if ms_count != ann_line_count:
                    continue

                # Offset: annotated block → corresponding modelspace block
                block_offset_x = (ms_centroid[0] - ann_centroid[0]) * scale
                block_offset_y = (ms_centroid[1] - ann_centroid[1]) * scale

                # Add modelspace INSERT position
                try:
                    ipos = ms_insert.dxf.insert
                    insert_x = ipos.x * scale
                    insert_y = ipos.y * scale
                except Exception:
                    insert_x, insert_y = 0.0, 0.0

                total_dx = block_offset_x + insert_x
                total_dy = block_offset_y + insert_y

                for (bx, by, h) in bob_texts_in_block:
                    ms_x = bx * scale + total_dx
                    ms_y = by * scale + total_dy
                    results.append((ms_x, ms_y, h))

        return results

    def _find_nearby_bob_text(self, cx, cy, bob_texts, search_radius_mm=10000):
        """
        From a pre-collected list of (x, y, bob_mm) tuples, return the
        BOB height of the nearest annotation.

        First tries within search_radius_mm (annotations placed on the plan).
        If nothing found (annotations are in a separate legend area, which is
        common in architectural drawings), falls back to the globally nearest
        BOB-labelled text in the entire drawing.
        """
        if not bob_texts:
            return None
        best_height = None
        best_dist   = search_radius_mm
        for ex, ey, h in bob_texts:
            dist = ((ex - cx) ** 2 + (ey - cy) ** 2) ** 0.5
            if dist < best_dist:
                best_height = h
                best_dist   = dist
        if best_height is not None:
            return best_height
        # Fallback: globally nearest (no radius limit)
        best_height, best_dist = None, float('inf')
        for ex, ey, h in bob_texts:
            dist = ((ex - cx) ** 2 + (ey - cy) ** 2) ** 0.5
            if dist < best_dist:
                best_height = h
                best_dist   = dist
        return best_height

    # ── Beam detection ────────────────────────────────────────────────────────

    def detect_beams(self, store_bounds=None):
        """
        Detect structural beams in the DXF.

        Detection sources (named beam layers ONLY):
          1. Closed LWPOLYLINE / POLYLINE on beam layers.
          2. Pairs of parallel LINE entities on beam layers that form beam
             outlines (the most common CAD representation — two lines define
             the beam's two faces, their separation = beam depth).

        BOB (Bottom-of-Beam) height extracted from (in priority order):
          1. Entity Z elevation (dxf.elevation / dxf.start.z).
          2. Numeric value encoded in the layer name (e.g. BEAM-3500).
          3. Nearest TEXT / MTEXT annotation within 8 m that contains a height.

        Returns list of dicts:
          {x, y, width, height, orientation ('horizontal'|'vertical'),
           layer, bob_height (mm or null), bounds}
        Coordinates are in mm.
        """
        scale = self._unit_scale()

        # Size thresholds (mm)
        MAX_SHORT   = 1500    # max beam depth (short side)
        MIN_LONG    = 300     # min beam span (long side)
        MAX_LONG    = 60000   # max beam span
        MIN_ASPECT  = 3       # long/short must be ≥ 3 to be a beam
        # Pair-matching thresholds
        MAX_SEPARATION = 1500 # max gap between two parallel lines (beam depth)
        MIN_SEPARATION = 50   # min gap (avoid co-linear noise)
        MIN_OVERLAP    = 300  # min shared run length for a valid pair

        sb = store_bounds

        def _in_store(cx, cy):
            if not sb:
                return True
            margin = 2000  # allow beams slightly outside boundary
            return (sb['min'][0] - margin <= cx <= sb['max'][0] + margin and
                    sb['min'][1] - margin <= cy <= sb['max'][1] + margin)

        # Pre-collect all BOB text annotations (once, for performance)
        bob_texts = self._collect_bob_texts(scale)

        def _bob_for_beam(cx, cy, layer, z_val):
            bob = None
            # 1. Z elevation from entity geometry
            if z_val and z_val > 0:
                candidate = round(z_val * scale)
                if 500 <= candidate <= 15000:
                    bob = candidate
            # 2. Layer name encoding
            if bob is None:
                bob = self._parse_bob_from_layer(layer)
            # 3. Nearest annotation
            if bob is None:
                bob = self._find_nearby_bob_text(cx, cy, bob_texts)
            return bob

        def _emit(cx, cy, w, h, layer, z_val=None):
            if not _in_store(cx, cy):
                return None
            long_s  = max(w, h)
            short_s = min(w, h)
            if not (short_s <= MAX_SHORT and MIN_LONG <= long_s <= MAX_LONG
                    and long_s / max(short_s, 1) >= MIN_ASPECT):
                return None
            bob = _bob_for_beam(cx, cy, layer, z_val)
            min_x = cx - w / 2
            min_y = cy - h / 2
            return {
                'x': round(cx), 'y': round(cy),
                'width': round(w), 'height': round(h),
                'orientation': 'horizontal' if w >= h else 'vertical',
                'layer': layer,
                'bob_height': bob,
                'bounds': {'min': [min_x, min_y],
                           'max': [min_x + w, min_y + h]},
            }

        candidates = []

        # ── Source 1: Closed LWPOLYLINE / POLYLINE on beam layers ─────────────
        for entity in self._iter_all_entities():
            if entity.dxftype() not in ('LWPOLYLINE', 'POLYLINE'):
                continue
            try:
                layer = entity.dxf.get('layer', '0')
                if not any(kw in layer.lower() for kw in self._BEAM_LAYERS):
                    continue
                is_closed = (getattr(entity, 'closed', False) or
                             bool(entity.dxf.get('flags', 0) & 1))
                pts = [(p[0] * scale, p[1] * scale)
                       for p in entity.get_points()]  # type: ignore[reportAttributeAccessIssue]
                if len(pts) < 3:
                    continue
                if not is_closed:
                    ddx = pts[-1][0] - pts[0][0]
                    ddy = pts[-1][1] - pts[0][1]
                    is_closed = (ddx * ddx + ddy * ddy) < (50 * 50)
                if not is_closed:
                    continue
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                w  = max(xs) - min(xs)
                h  = max(ys) - min(ys)
                cx = (min(xs) + max(xs)) / 2
                cy = (min(ys) + max(ys)) / 2
                elev = entity.dxf.get('elevation', 0) or 0
                b = _emit(cx, cy, w, h, layer, elev)
                if b:
                    candidates.append(b)
            except Exception:
                continue

        # ── Source 2: Parallel LINE pairs on beam layers ───────────────────────
        # Use _iter_all_entities so beam lines inside INSERT blocks are included.
        # Lines are deduplicated by position (±1 mm) to handle files where the
        # same lines appear both directly in modelspace and inside a block.
        layer_lines = {}   # layer_name → list of (x1,y1,x2,y2,z)
        seen_lines = set() # (rounded coords) for dedup across msp + blocks
        for entity in self._iter_all_entities():
            if entity.dxftype() != 'LINE':
                continue
            try:
                layer = entity.dxf.get('layer', '0')
                if not any(kw in layer.lower() for kw in self._BEAM_LAYERS):
                    continue
                s   = entity.dxf.start
                end = entity.dxf.end
                x1, y1 = s.x * scale, s.y * scale
                x2, y2 = end.x * scale, end.y * scale
                z = (s.z + end.z) / 2 * scale
                # Dedup: round to 1 mm, normalise direction
                key = (round(min(x1,x2)), round(min(y1,y2)),
                       round(max(x1,x2)), round(max(y1,y2)))
                if key in seen_lines:
                    continue
                seen_lines.add(key)
                layer_lines.setdefault(layer, []).append((x1, y1, x2, y2, z))
            except Exception:
                continue

        def _cluster_lines(lines_1d, pos_tol=5):
            """
            Group a list of (pos, lo, hi, z) lines into clusters where all
            lines share the same pos within pos_tol mm.
            Returns list of (avg_pos, [(lo,hi,z), ...]).
            """
            if not lines_1d:
                return []
            lines_1d = sorted(lines_1d, key=lambda l: l[0])
            clusters = []
            cur_pos, cur_segs = lines_1d[0][0], []
            for pos, lo, hi, z in lines_1d:
                if abs(pos - cur_pos) <= pos_tol:
                    cur_segs.append((lo, hi, z))
                else:
                    clusters.append((cur_pos, cur_segs))
                    cur_pos, cur_segs = pos, [(lo, hi, z)]
            clusters.append((cur_pos, cur_segs))
            return clusters

        def _pair_clusters(clusters, axis_lo, axis_hi,
                           min_sep, max_sep, min_overlap):
            """
            For each pair of clusters whose pos values are within [min_sep,
            max_sep], yield individual beam segments: for every segment in
            cluster A, intersect with every segment in cluster B.
            One cluster face (e.g. a full-span line) can produce multiple beams
            against a segmented opposite face.
            """
            paired_cluster_pairs = set()
            for i, (pa, segs_a) in enumerate(clusters):
                for j, (pb, segs_b) in enumerate(clusters):
                    if j <= i:
                        continue
                    sep = abs(pb - pa)
                    if sep < min_sep or sep > max_sep:
                        continue
                    key = (i, j)
                    if key in paired_cluster_pairs:
                        continue
                    paired_cluster_pairs.add(key)
                    # Intersect every seg in A with every seg in B
                    for (lo_a, hi_a, za) in segs_a:
                        for (lo_b, hi_b, zb) in segs_b:
                            ovl_lo = max(lo_a, lo_b)
                            ovl_hi = min(hi_a, hi_b)
                            if ovl_hi - ovl_lo >= min_overlap:
                                yield (pa, pb, ovl_lo, ovl_hi,
                                       (za + zb) / 2)

        for layer, lines in layer_lines.items():
            # Separate into horizontal and vertical lines
            h_lines_raw = []  # (y, x_min, x_max, z)
            v_lines_raw = []  # (x, y_min, y_max, z)
            for (x1, y1, x2, y2, z) in lines:
                ddx = abs(x2 - x1)
                ddy = abs(y2 - y1)
                length = (ddx ** 2 + ddy ** 2) ** 0.5
                if length < 100:
                    continue
                if ddy < ddx * 0.15:   # horizontal
                    avg_y = (y1 + y2) / 2
                    h_lines_raw.append((avg_y, min(x1, x2), max(x1, x2), z))
                elif ddx < ddy * 0.15: # vertical
                    avg_x = (x1 + x2) / 2
                    v_lines_raw.append((avg_x, min(y1, y2), max(y1, y2), z))

            # Cluster lines at same y/x, then pair clusters
            h_clusters = _cluster_lines(h_lines_raw)
            for (ya, yb, xlo, xhi, zavg) in _pair_clusters(
                    h_clusters, axis_lo=0, axis_hi=0,
                    min_sep=MIN_SEPARATION, max_sep=MAX_SEPARATION,
                    min_overlap=MIN_OVERLAP):
                bw = xhi - xlo
                bh = abs(yb - ya)
                bcx = (xlo + xhi) / 2
                bcy = (ya + yb) / 2
                b = _emit(bcx, bcy, bw, bh, layer, zavg)
                if b:
                    candidates.append(b)

            v_clusters = _cluster_lines(v_lines_raw)
            for (xa, xb, ylo, yhi, zavg) in _pair_clusters(
                    v_clusters, axis_lo=0, axis_hi=0,
                    min_sep=MIN_SEPARATION, max_sep=MAX_SEPARATION,
                    min_overlap=MIN_OVERLAP):
                bw = abs(xb - xa)
                bh = yhi - ylo
                bcx = (xa + xb) / 2
                bcy = (ylo + yhi) / 2
                b = _emit(bcx, bcy, bw, bh, layer, zavg)
                if b:
                    candidates.append(b)

        # Remove near-duplicates (centres within 200 mm, similar size)
        unique = []
        for c in candidates:
            if not any(abs(c['x'] - u['x']) < 200 and
                       abs(c['y'] - u['y']) < 200 and
                       abs(c['width'] - u['width']) < 200 and
                       abs(c['height'] - u['height']) < 200
                       for u in unique):
                unique.append(c)
        return unique

    def detect_doors(self, store_bounds=None):
        """
        Detect door openings in the DXF.

        Doors are identified by:
          1. ARC entities — door swing arcs (radius 200–2000 mm).
             Layer name containing door keywords gets relaxed radius range.
          2. INSERT block references whose block name contains door keywords.

        Returns list of dicts:
          {x, y, radius, start_angle, end_angle, layer, bounds, type}
        Coordinates and radius are in mm.
        """
        from ezdxf import bbox as ezdxf_bbox
        import math

        scale = self._unit_scale()
        _DOOR_LAYERS = ('door', 'doors', 'opening', 'entry', 'exit',
                        'entrance', 'gate', 'swing')

        MIN_R_NAMED = 200    # mm
        MAX_R_NAMED = 2500   # mm
        MIN_R_GEO   = 500    # mm — geometry-only: typical door swing
        MAX_R_GEO   = 1500   # mm

        sb = store_bounds

        def _in_store(cx, cy):
            if not sb:
                return True
            return (sb['min'][0] <= cx <= sb['max'][0] and
                    sb['min'][1] <= cy <= sb['max'][1])

        candidates = []

        # ── ARC entities ─────────────────────────────────────────────────────
        for entity in self._iter_all_entities():
            if entity.dxftype() != 'ARC':
                continue
            try:
                layer = entity.dxf.get('layer', '0')
                cx = entity.dxf.center.x * scale
                cy = entity.dxf.center.y * scale
                r = entity.dxf.radius * scale
                start_a = entity.dxf.start_angle
                end_a = entity.dxf.end_angle
                layer_low = layer.lower()
                is_door_layer = any(kw in layer_low for kw in _DOOR_LAYERS)
                min_r = MIN_R_NAMED if is_door_layer else MIN_R_GEO
                max_r = MAX_R_NAMED if is_door_layer else MAX_R_GEO
                if min_r <= r <= max_r and _in_store(cx, cy):
                    candidates.append({
                        'x': round(cx), 'y': round(cy),
                        'radius': round(r),
                        'start_angle': round(start_a, 1),
                        'end_angle': round(end_a, 1),
                        'layer': layer,
                        'bounds': {'min': [cx - r, cy - r],
                                   'max': [cx + r, cy + r]},
                        'type': 'swing',
                    })
            except Exception:
                continue

        # ── INSERT blocks with door-related names ─────────────────────────────
        for entity in self.msp:
            if entity.dxftype() != 'INSERT':
                continue
            try:
                block_name = entity.dxf.get('name', '').lower()
                layer = entity.dxf.get('layer', '0')
                if not any(kw in block_name for kw in _DOOR_LAYERS):
                    continue
                bb = ezdxf_bbox.extents([entity], fast=True)
                if not bb:
                    continue
                x1 = bb.extmin.x * scale
                y1 = bb.extmin.y * scale
                x2 = bb.extmax.x * scale
                y2 = bb.extmax.y * scale
                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2
                r = max(x2 - x1, y2 - y1) / 2
                if _in_store(cx, cy):
                    candidates.append({
                        'x': round(cx), 'y': round(cy),
                        'radius': round(r),
                        'start_angle': 0,
                        'end_angle': 90,
                        'layer': layer,
                        'bounds': {'min': [x1, y1], 'max': [x2, y2]},
                        'type': 'block',
                    })
            except Exception:
                continue

        # ── LWPOLYLINE with bulge (door swing symbols stored as polylines) ───────
        import math as _math
        for entity in self.msp:
            if entity.dxftype() != 'LWPOLYLINE':
                continue
            try:
                if entity.closed:  # type: ignore[reportAttributeAccessIssue]
                    continue
                pts = list(entity.get_points('xyb'))  # x, y, bulge  # type: ignore[reportAttributeAccessIssue]
                if len(pts) < 2:
                    continue
                layer = entity.dxf.get('layer', '0')
                # Find segments with significant bulge (the arc part of the door)
                for i in range(len(pts) - 1):
                    px1, py1, b1 = pts[i][0] * scale, pts[i][1] * scale, pts[i][2]
                    px2, py2, _  = pts[i+1][0] * scale, pts[i+1][1] * scale, 0
                    if abs(b1) < 0.05:
                        continue  # straight segment, skip
                    chord = _math.hypot(px2 - px1, py2 - px1)
                    chord = _math.hypot(px2 - px1, py2 - py1)
                    if chord < 1:
                        continue
                    # Arc radius from LWPOLYLINE bulge formula
                    r = chord * (1 + b1 * b1) / (4 * abs(b1))
                    if not (400 <= r <= 2000):
                        continue
                    # Arc center
                    dx, dy = px2 - px1, py2 - py1
                    s = (1 - b1 * b1) / (4 * b1)
                    cx = (px1 + px2) / 2 - s * dy
                    cy = (py1 + py2) / 2 + s * dx
                    # Angles from center to p1 and p2
                    a1 = _math.degrees(_math.atan2(py1 - cy, px1 - cx))
                    a2 = _math.degrees(_math.atan2(py2 - cy, px2 - cx))
                    if not _in_store(cx, cy):
                        continue
                    candidates.append({
                        'x': round(cx), 'y': round(cy),
                        'radius': round(r),
                        'start_angle': round(a1, 1),
                        'end_angle': round(a2, 1),
                        'bulge_sign': 1 if b1 > 0 else -1,
                        'layer': layer,
                        'bounds': {'min': [cx - r, cy - r],
                                   'max': [cx + r, cy + r]},
                        'type': 'swing',
                    })
            except Exception:
                continue

        # Deduplicate (centres within 150 mm)
        unique = []
        for d in candidates:
            if not any(abs(d['x'] - u['x']) < 150 and abs(d['y'] - u['y']) < 150
                       for u in unique):
                unique.append(d)
        return unique

    # ── Fixture DXF catalogue ─────────────────────────────────────────────────
    # Maps a lowercase keyword (matched against fixture name) → filename inside
    # the backend/fixtures/ folder.  First match wins.
    # ── Fixture DXF catalogue ─────────────────────────────────────────────────
    # Maps a lowercase keyword (matched against fixture name) → filename inside
    # the backend/fixtures/ folder.  First match wins.
    # All filenames are verified against the actual files in backend/fixtures/.
    _FIXTURE_DXF_CATALOGUE = [
        # (keyword_in_fixture_name,                         dxf_filename)

        # ── Island / floor units ──────────────────────────────────────────────
        ('double side island',           'double side island unit.dxf'),
        ('single side island',           'single side island unit.dxf'),

        # ── Flatbed / floor-mount sunglass display ────────────────────────────
        # Floor-mount sunglass unit (not a wall fixture)
        ('sunglass unit - floor mount - 1.22w lh', 'sunglass floormount lhs.dxf'),
        ('sunglass unit - floor mount - 1.22w rh', 'sunglass floormount lhs.dxf'),
        ('sunglass floormount',          'sunglass floormount lhs.dxf'),
        ('flatbed sunglass display 1.50','sunglasses wallmount rhs and lhs.dxf'),
        ('flatbed sunglass display 1.20','sunglasses wallmount rhs and lhs.dxf'),
        ('flatbed',                      'sunglasses wallmount rhs and lhs.dxf'),

        # ── Smart display ─────────────────────────────────────────────────────
        ('smart display',                'sunglasses wallmount lhs.dxf'),

        # ── IB Frame wall units ───────────────────────────────────────────────
        ('ib frame unit 2.25',           'ib frames unit 2.25.dxf'),
        ('ib frame unit 1.29',           'ib frames unit 1.29.dxf'),
        ('ib frame',                     'ib frames unit 2.25.dxf'),

        # ── Luxury wall units ─────────────────────────────────────────────────
        ('luxury unit open',             'luxury  unit open top 0.82.dxf'),
        ('luxury unit glass',            'luxury unit glass top 0.82.dxf'),
        ('luxury',                       'luxury  unit open top 0.82.dxf'),

        # ── Lens unit ─────────────────────────────────────────────────────────
        ('lens unit',                    'ib frames unit 1.29.dxf'),

        # ── HB-YA frame wall units ────────────────────────────────────────────
        ('hb-ya frame unit 2.25',        'ib frames unit 2.25.dxf'),
        ('hb-ya frame unit 1.29',        'ib frames unit 1.29.dxf'),
        ('hb-ya',                        'ib frames unit 2.25.dxf'),

        # ── HB-M&W frame wall units ───────────────────────────────────────────
        ('hb-m&w frame unit 2.25',       'ib frames unit 2.25.dxf'),
        ('hb-m&w frame unit 1.29',       'ib frames unit 1.29.dxf'),
        ('hb-m',                         'ib frames unit 2.25.dxf'),

        # ── Affordable Fastrack eyewear wall units ────────────────────────────
        ('affordable fastrack eyewear unit 2.25', 'affodable fastrack eyewear unit 2.25.dxf'),
        ('affordable fastrack eyewear unit 1.29', 'afforadable fastrack eyewaer unit 1.29.dxf'),
        ('affordable fastrack',          'affodable fastrack eyewear unit 2.25.dxf'),

        # ── Affordable Men & Women wall units ─────────────────────────────────
        ('affordable men and women unit 2.25', 'affordable men and women unit 2.25.dxf'),
        ('affordable men and women unit 1.29', 'affordable men and women unit 1.29.dxf'),
        ('affordable men',               'affordable men and women unit 2.25.dxf'),
        ('affordable',                   'affordable men and women unit 2.25.dxf'),

        # ── Kids unit ─────────────────────────────────────────────────────────
        ('prem kids',                    'kids unit.dxf'),
        ('kids',                         'kids unit.dxf'),

        # ── Sunglass wall-mount units ─────────────────────────────────────────
        # Specific named variants first (most specific → least specific)
        ('sunglass unit - wall mount - 1.22w lh',  'sunglasses wallmount lhs.dxf'),
        ('sunglass unit - wall mount - 1.22w rh',  'sunglasses wall mount rhs.dxf'),
        ('sunglass angular unit - wall mount lh',  'sunglass angular unit lhs.dxf'),
        ('sunglass angular unit - wall mount rh',  'sunglasses angular rhs.dxf'),
        ('sunglasses angular lhs and rhs',         'sunglasses angular lhs and rhs wall mount.dxf'),
        ('sunglass angular',                       'sunglasses angular lhs and rhs wall mount.dxf'),
        ('sunglasses wallmount rhs and lhs',       'sunglasses wallmount rhs and lhs.dxf'),
        ('sunglasses wallmount lhs',               'sunglasses wallmount lhs.dxf'),
        ('sunglasses wallmount rhs',               'sunglasses wall mount rhs.dxf'),
        ('sunglasses wall mount rhs',              'sunglasses wall mount rhs.dxf'),
        ('sunglasses wall mount lhs',              'sunglasses wallmount lhs.dxf'),
        # Generic sunglass fallback
        ('sunglass',                               'sunglasses wallmount lhs.dxf'),

        # ── Transaction / center tables ───────────────────────────────────────
        ('transaction table',            'transanction table.dxf'),
        ('center table',                 'center table.dxf'),
        ('table top mirror',             'center table.dxf'),

        # ── Cash counters ─────────────────────────────────────────────────────
        ('cash counter l shaped lhs',    'cash counter l shaped lhs.dxf'),
        ('cash counter l shaped rhs',    'cash counter l shaped rhs.dxf'),
        ('cash counter l shaped',        'cash counter l shaped lhs.dxf'),
        ('cash counter 1.20',            'cash counter 1,20w.dxf'),
        ('cash counter 1.80',            'cash counter 1.80w.dxf'),
        ('cash counter',                 'cash counter 1.80w.dxf'),

        # ── BOH rooms ──────────────────────────────────────────────────────────
        ('electrical room',              'Electrical Room.dxf'),
        ('fitting lab',                  'Fitting Lab(Semi Edger Machine).dxf'),
        ('clinic tran table',            'Clinic Tran Table (1.25W).dxf'),
        ('small clinic table',           'Small Clinic Table (0.45W).dxf'),
    ]

    @staticmethod
    def _fixtures_dir():
        """Return absolute path to the backend/fixtures/ directory."""
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')

    def _find_fixture_dxf(self, fixture_name: str, store_area_sqft: Optional[float] = None):
        """
        Return the full path to the best-matching fixture DXF file, or None.
        Matching is case-insensitive, first-match-wins against _FIXTURE_DXF_CATALOGUE.

        Pantry and Toilet have multiple DXF files by store-size bracket, so they
        are resolved against store_area_sqft before falling back to the
        keyword catalogue (which has no entry for them).
        """
        name_low = fixture_name.lower()
        fdir = self._fixtures_dir()
        area = store_area_sqft if store_area_sqft is not None else 700  # mid-bracket default

        if 'pantry' in name_low:
            if area > 850:
                filename = 'Pantry(Stores above 850 Sqft area).dxf'
            elif area < 500:
                filename = 'Pantry(Stores below 500 Sqft area.dxf'
            else:
                filename = 'Pantry(Stores between 500 to 850Sqft area.dxf'
            path = os.path.join(fdir, filename)
            if os.path.exists(path):
                return path

        if 'toilet' in name_low or 'wash room' in name_low:
            filename = ('Toilet(Stores above 850Sqft).dxf' if area > 850
                        else 'Toilet (Store area 500-850 Sqft).dxf')
            path = os.path.join(fdir, filename)
            if os.path.exists(path):
                return path

        for keyword, filename in self._FIXTURE_DXF_CATALOGUE:
            if keyword in name_low:
                path = os.path.join(fdir, filename)
                if os.path.exists(path):
                    return path
        return None

    @staticmethod
    def _define_fixture_block(out_doc, block_name: str, fixture_dxf_path: str,
                               target_w: float, target_d: float):
        """
        Load fixture_dxf_path, expand all nested INSERT blocks via
        virtual_entities(), normalise the resulting geometry to (0,0),
        scale it to fit target_w × target_d, and define it as a named
        block in out_doc.

        Fixture DXF files store geometry inside nested block references
        (INSERT entities), so iterating modelspace directly yields only
        the INSERT wrapper — we must call virtual_entities() to get the
        actual LINE / LWPOLYLINE / ARC / CIRCLE geometry.

        Returns True on success, False on any error.
        """
        try:
            fix_doc = ezdxf.readfile(fixture_dxf_path)  # type: ignore[reportPrivateImportUsage]
            fix_msp = fix_doc.modelspace()

            # ── Collect all virtual (expanded) entities ───────────────────
            # virtual_entities() recursively expands INSERT blocks into
            # their constituent geometry in modelspace coordinates.
            all_virtual = []
            for entity in fix_msp:
                if entity.dxftype() == 'INSERT':
                    try:
                        all_virtual.extend(entity.virtual_entities())  # type: ignore[reportAttributeAccessIssue]
                    except Exception:
                        pass
                else:
                    all_virtual.append(entity)

            if not all_virtual:
                return False

            # ── Compute 2-D bounding box from virtual entities ────────────
            xs, ys = [], []
            for ve in all_virtual:
                vtype = ve.dxftype()
                try:
                    if vtype == 'LINE':
                        xs += [ve.dxf.start.x, ve.dxf.end.x]
                        ys += [ve.dxf.start.y, ve.dxf.end.y]
                    elif vtype in ('LWPOLYLINE', 'POLYLINE'):
                        for p in ve.get_points():  # type: ignore[reportAttributeAccessIssue]
                            xs.append(p[0]); ys.append(p[1])
                    elif vtype in ('ARC', 'CIRCLE'):
                        r = ve.dxf.radius
                        xs += [ve.dxf.center.x - r, ve.dxf.center.x + r]
                        ys += [ve.dxf.center.y - r, ve.dxf.center.y + r]
                except Exception:
                    pass

            if not xs or not ys:
                return False

            fx_min_x, fx_max_x = min(xs), max(xs)
            fx_min_y, fx_max_y = min(ys), max(ys)
            fx_w = fx_max_x - fx_min_x
            fx_d = fx_max_y - fx_min_y
            if fx_w <= 0 or fx_d <= 0:
                return False

            # Scale factors to fit the fixture into target_w × target_d
            sx = target_w / fx_w
            sy = target_d / fx_d

            # ── Define block in output document ───────────────────────────
            if block_name in out_doc.blocks:
                return True  # already defined (same fixture used twice)
            blk = out_doc.blocks.new(name=block_name)

            # ── Copy virtual entities into the block ──────────────────────
            # Translate to (0,0) origin and scale to target size.
            # All coordinates are flattened to 2-D (Z ignored).
            for ve in all_virtual:
                vtype = ve.dxftype()
                try:
                    if vtype == 'LINE':
                        s = ve.dxf.start
                        e = ve.dxf.end
                        blk.add_line(
                            ((s.x - fx_min_x) * sx, (s.y - fx_min_y) * sy),
                            ((e.x - fx_min_x) * sx, (e.y - fx_min_y) * sy),
                            dxfattribs={'layer': 'AI_FIXTURES'},
                        )
                    elif vtype in ('LWPOLYLINE', 'POLYLINE'):
                        pts = [
                            ((p[0] - fx_min_x) * sx, (p[1] - fx_min_y) * sy)
                            for p in ve.get_points()  # type: ignore[reportAttributeAccessIssue]
                        ]
                        if len(pts) >= 2:
                            is_closed = (getattr(ve, 'closed', False) or
                                         bool(ve.dxf.get('flags', 0) & 1))
                            blk.add_lwpolyline(
                                pts, close=is_closed,
                                dxfattribs={'layer': 'AI_FIXTURES'},
                            )
                    elif vtype == 'ARC':
                        cx = (ve.dxf.center.x - fx_min_x) * sx
                        cy = (ve.dxf.center.y - fx_min_y) * sy
                        r  = ve.dxf.radius * ((sx + sy) / 2)
                        blk.add_arc(
                            (cx, cy), r,
                            ve.dxf.start_angle, ve.dxf.end_angle,
                            dxfattribs={'layer': 'AI_FIXTURES'},
                        )
                    elif vtype == 'CIRCLE':
                        cx = (ve.dxf.center.x - fx_min_x) * sx
                        cy = (ve.dxf.center.y - fx_min_y) * sy
                        r  = ve.dxf.radius * ((sx + sy) / 2)
                        blk.add_circle(
                            (cx, cy), r,
                            dxfattribs={'layer': 'AI_FIXTURES'},
                        )
                    elif vtype == 'SPLINE':
                        pts_s = [
                            ((p[0] - fx_min_x) * sx, (p[1] - fx_min_y) * sy)
                            for p in ve.control_points
                        ]
                        if len(pts_s) >= 2:
                            blk.add_lwpolyline(
                                pts_s,
                                dxfattribs={'layer': 'AI_FIXTURES'},
                            )
                    # HATCH, TEXT, MTEXT, POINT etc. intentionally skipped
                except Exception:
                    continue

            return True
        except Exception:
            return False

    def create_ai_layout_dxf(self, placements, store_bounds, output_path,
                              coord_mode='center', store_polygon=None, doors=None):
        """
        Create a clean DXF with the store outline drawn at (0,0) + placed fixtures.

        Each fixture is rendered using its actual DXF shape from backend/fixtures/.
        If no matching fixture DXF is found, a labelled rectangle is drawn instead.

        All output coordinates are normalised to origin (0,0) so the result is
        independent of where the original DXF geometry was positioned.

        coord_mode:
          'center'      – placement x/y are centre coordinates (legacy AI output)
          'bottom_left' – placement x/y are bottom-left corner (GridLayoutEngine output)

        store_polygon: optional list of (x,y) tuples for the real store outline.
                       If supplied it is normalised and drawn.  Otherwise a simple
                       rectangle is drawn from the bounds.
        """
        # ── fresh document — no original content copied ───────────────────────
        new_doc = ezdxf.new('R2010')  # type: ignore[reportPrivateImportUsage]
        new_msp = new_doc.modelspace()

        # Layers
        new_doc.layers.new('STORE_OUTLINE', dxfattribs={'color': 1, 'lineweight': 70})
        new_doc.layers.new('AI_FIXTURES',   dxfattribs={'color': 5, 'lineweight': 50})
        new_doc.layers.new('AI_LABELS',     dxfattribs={'color': 3})
        new_doc.layers.new('AI_DIMS',       dxfattribs={'color': 6})  # magenta
        new_doc.layers.new('DOORS',         dxfattribs={'color': 3, 'lineweight': 50})  # green, matches 2D preview

        # ── store dimensions (all output normalised to 0,0) ───────────────────
        raw_min_x = store_bounds['min'][0]
        raw_min_y = store_bounds['min'][1]
        store_w = store_bounds['max'][0] - raw_min_x
        store_d = store_bounds['max'][1] - raw_min_y

        # Actual polygon area (Shoelace) when available, else bounding box —
        # used to pick the right Pantry/Toilet DXF size-bracket variant.
        if store_polygon and len(store_polygon) >= 3:
            n = len(store_polygon)
            _area_mm2 = abs(sum(
                store_polygon[i][0] * store_polygon[(i + 1) % n][1] -
                store_polygon[(i + 1) % n][0] * store_polygon[i][1]
                for i in range(n)
            )) / 2.0
        else:
            _area_mm2 = store_w * store_d
        store_area_sqft = (_area_mm2 / 1_000_000) * 10.7639

        # ── draw store outline ────────────────────────────────────────────────
        if store_polygon and len(store_polygon) >= 3:
            pts_norm = [(pt[0] - raw_min_x, pt[1] - raw_min_y)
                        for pt in store_polygon]
            new_msp.add_lwpolyline(pts_norm, close=True,
                                   dxfattribs={'layer': 'STORE_OUTLINE'})
        else:
            new_msp.add_lwpolyline(
                [(0, 0), (store_w, 0), (store_w, store_d), (0, store_d)],
                close=True, dxfattribs={'layer': 'STORE_OUTLINE'}
            )

        # ── entrance doors — standard "door open" symbol: one straight leaf
        # line (hinge → open position) + the swing arc (open position →
        # closed position along the wall). NOT a closed pie/wedge — a real
        # door has no line drawn back from the closed position to the hinge.
        if doors:
            import math
            for door in doors:
                try:
                    dx = door['x'] - raw_min_x
                    dy = door['y'] - raw_min_y
                    r = door.get('radius', 900)
                    if r < 300:
                        continue  # degenerate/noise candidate — not a real door swing
                    sa = door.get('start_angle', 0) % 360
                    ea = door.get('end_angle', 90) % 360
                    # A real door swing is a quarter-ish arc. Malformed angle
                    # data (e.g. from a misread bulge) can produce a near-zero
                    # or near-full-circle span, which renders as a degenerate
                    # bowtie/cross instead of a clean swing — fall back to a
                    # standard 90 degree quarter swing in that case.
                    span = (ea - sa) % 360
                    if span < 15 or span > 270:
                        ea = (sa + 90) % 360
                    start_rad = math.radians(sa)
                    sx = dx + r * math.cos(start_rad)
                    sy = dy + r * math.sin(start_rad)
                    # Door leaf: hinge to open position.
                    new_msp.add_line((dx, dy), (sx, sy), dxfattribs={'layer': 'DOORS'})
                    # Swing arc: open position back to the closed position
                    # along the wall — no line closing it back to the hinge.
                    new_msp.add_arc(center=(dx, dy), radius=r, start_angle=sa,
                                    end_angle=ea, dxfattribs={'layer': 'DOORS'})
                except Exception:
                    pass

        # ── polygon-aware safety net ────────────────────────────────────────
        # The bounding-box clamp below only keeps fixtures inside the
        # rectangular store_w x store_d frame. For non-rectangular stores
        # (L-shape / notches) that rectangle is bigger than the real polygon,
        # so a fixture can pass the box clamp while still landing in a
        # cut-out area outside the actual wall. Catch that here as a final
        # check before drawing.
        _store_shapely = None
        if store_polygon and len(store_polygon) >= 3:
            try:
                from shapely.geometry import Polygon as _SPoly
                _pts = [(pt[0] - raw_min_x, pt[1] - raw_min_y) for pt in store_polygon]
                _sp = _SPoly(_pts)
                if not _sp.is_valid:
                    _sp = _sp.buffer(0)
                # No inward inset: it can erase a narrow wall notch/step
                # entirely, making the cut-out area register as "inside".
                _store_shapely = _sp
            except Exception:
                _store_shapely = None

        # ── fixtures ─────────────────────────────────────────────────────────
        # Track block names already defined (fixture DXF → block name)
        _block_cache: dict = {}   # fixture_dxf_path → block_name (or None=fallback)
        _block_counter = [0]

        for p in placements:
            x = p.get('x_mm', p.get('x', 0))
            y = p.get('y_mm', p.get('y', 0))
            w0 = p.get('w_mm', p.get('l', 1000))
            d0 = p.get('d_mm', p.get('d', 500))
            rot = p.get('rotation_deg', p.get('rotation', 0))
            fixture_name = p.get('fixture', 'FIXTURE')

            # Apply 90° rotation swap for effective footprint
            w = d0 if rot in [90, 270] else w0
            d = w0 if rot in [90, 270] else d0

            if coord_mode == 'center':
                x_abs = x - w / 2.0
                y_abs = y - d / 2.0
            else:  # bottom_left
                x_abs = x
                y_abs = y

            # Clamp to store bounds
            x_abs = max(0.0, min(x_abs, store_w - w))
            y_abs = max(0.0, min(y_abs, store_d - d))

            # ── Polygon safety net: nudge toward the polygon centroid if the
            # box clamp above left this fixture sitting in a notch/cut-out
            # that's outside the real (non-rectangular) store outline ──────
            if _store_shapely is not None:
                try:
                    from shapely.geometry import box as _SBox
                    fbox = _SBox(x_abs, y_abs, x_abs + w, y_abs + d)
                    inter = _store_shapely.intersection(fbox)
                    if fbox.area > 0 and inter.area < fbox.area * 0.98:
                        fixed = False
                        cx, cy = _store_shapely.centroid.x, _store_shapely.centroid.y
                        for frac in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
                            nx = max(0.0, min(x_abs + (cx - (x_abs + w / 2)) * frac, store_w - w))
                            ny = max(0.0, min(y_abs + (cy - (y_abs + d / 2)) * frac, store_d - d))
                            fbox2 = _SBox(nx, ny, nx + w, ny + d)
                            inter2 = _store_shapely.intersection(fbox2)
                            if inter2.area >= fbox2.area * 0.98:
                                x_abs, y_abs = nx, ny
                                fixed = True
                                break
                        # Centroid-nudge can still fail for an irregular
                        # polygon (e.g. the target direction is itself
                        # blocked by another notch). Fall back to an
                        # exhaustive grid search over the whole store so a
                        # fixture is NEVER rendered outside the real wall —
                        # this is the last line of defense before drawing.
                        if not fixed:
                            step = 200
                            gy = 0.0
                            while gy + d <= store_d and not fixed:
                                gx = 0.0
                                while gx + w <= store_w:
                                    fbox3 = _SBox(gx, gy, gx + w, gy + d)
                                    inter3 = _store_shapely.intersection(fbox3)
                                    if inter3.area >= fbox3.area * 0.98:
                                        x_abs, y_abs = gx, gy
                                        fixed = True
                                        break
                                    gx += step
                                gy += step
                except Exception:
                    pass

            # ── Try to use real fixture DXF shape ────────────────────────────
            fix_path = self._find_fixture_dxf(fixture_name, store_area_sqft=store_area_sqft)
            used_shape = False

            if fix_path is not None:
                # Block geometry is defined using the fixture's NATURAL
                # (unrotated) dimensions w0×d0, so the artwork keeps its
                # correct proportions/orientation. Rotation is then applied
                # as a real INSERT rotation rather than by stretching the
                # drawing into the swapped w×d footprint.
                cache_key = (fix_path, round(w0), round(d0))
                if cache_key not in _block_cache:
                    _block_counter[0] += 1
                    bname = f'FIX_{_block_counter[0]:04d}'
                    ok = self._define_fixture_block(new_doc, bname, fix_path, w0, d0)
                    _block_cache[cache_key] = bname if ok else None

                bname = _block_cache[cache_key]
                if bname is not None:
                    # Insertion point is offset so the rotated block's
                    # bounding box still lands exactly on
                    # [x_abs, x_abs+w] x [y_abs, y_abs+d].
                    rot_norm = rot % 360
                    if rot_norm == 90:
                        ins = (x_abs + d0, y_abs)
                    elif rot_norm == 180:
                        ins = (x_abs + w0, y_abs + d0)
                    elif rot_norm == 270:
                        ins = (x_abs, y_abs + w0)
                    else:
                        rot_norm = 0
                        ins = (x_abs, y_abs)
                    new_msp.add_blockref(
                        bname,
                        insert=ins,
                        dxfattribs={'layer': 'AI_FIXTURES', 'rotation': rot_norm},
                    )
                    used_shape = True

            # ── Fallback: draw a labelled rectangle ───────────────────────────
            if not used_shape:
                new_msp.add_lwpolyline(
                    [(x_abs, y_abs), (x_abs + w, y_abs),
                     (x_abs + w, y_abs + d), (x_abs, y_abs + d)],
                    close=True,
                    dxfattribs={'layer': 'AI_FIXTURES'}
                )

            # ── Label (always drawn) ──────────────────────────────────────────
            label_height = max(50, min(w, d) * 0.08)
            new_msp.add_text(
                fixture_name,
                dxfattribs={
                    'layer': 'AI_LABELS',
                    'height': label_height,
                    'insert': (x_abs + w * 0.05, y_abs + d / 2),
                }
            )

        # ── dimension lines (at 0,0 origin) ──────────────────────────────────
        dim_offset = max(300, store_w * 0.04)

        # Width dimension (below store)
        y_dim = -dim_offset
        new_msp.add_line((0, y_dim), (store_w, y_dim),
                         dxfattribs={'layer': 'AI_DIMS'})
        new_msp.add_line((0, y_dim - 100), (0, y_dim + 100),
                         dxfattribs={'layer': 'AI_DIMS'})
        new_msp.add_line((store_w, y_dim - 100), (store_w, y_dim + 100),
                         dxfattribs={'layer': 'AI_DIMS'})
        new_msp.add_text(
            f"{store_w / 1000:.2f} m",
            dxfattribs={
                'layer': 'AI_DIMS',
                'height': max(100, store_w * 0.012),
                'insert': (store_w / 2, y_dim - 250),
                'halign': 1,
                'align_point': (store_w / 2, y_dim - 250),
            }
        )

        # Depth dimension (left of store)
        x_dim = -dim_offset
        new_msp.add_line((x_dim, 0), (x_dim, store_d),
                         dxfattribs={'layer': 'AI_DIMS'})
        new_msp.add_line((x_dim - 100, 0), (x_dim + 100, 0),
                         dxfattribs={'layer': 'AI_DIMS'})
        new_msp.add_line((x_dim - 100, store_d), (x_dim + 100, store_d),
                         dxfattribs={'layer': 'AI_DIMS'})
        new_msp.add_text(
            f"{store_d / 1000:.2f} m",
            dxfattribs={
                'layer': 'AI_DIMS',
                'height': max(100, store_d * 0.012),
                'insert': (x_dim - 250, store_d / 2),
                'rotation': 90,
            }
        )

        new_doc.saveas(output_path)

    def create_optimized_dxf(self, optimized_entities, output_path):
        """Create new DXF file with optimized layout"""
        import ezdxf.xref as xref

        new_doc = ezdxf.new('R2010')  # type: ignore[reportPrivateImportUsage]

        # Copy all entities, blocks, and resources from source doc
        xref.load_modelspace(self.doc, new_doc)

        new_doc.saveas(output_path)
    
    def generate_preview(self, entities):
        """Generate preview data for frontend"""
        preview = {
            'entities': [],
            'bounds': {'min': [float('inf'), float('inf')], 'max': [float('-inf'), float('-inf')]}
        }
        
        for entity_data in entities:
            data = entity_data['data']
            
            if data.get('bbox'):
                bbox = data['bbox']
                preview['bounds']['min'][0] = min(preview['bounds']['min'][0], bbox['min'][0])
                preview['bounds']['min'][1] = min(preview['bounds']['min'][1], bbox['min'][1])
                preview['bounds']['max'][0] = max(preview['bounds']['max'][0], bbox['max'][0])
                preview['bounds']['max'][1] = max(preview['bounds']['max'][1], bbox['max'][1])
            
            preview['entities'].append({
                'type': data['type'],
                'layer': data['layer'],
                'bbox': data.get('bbox')
            })
        
        return preview