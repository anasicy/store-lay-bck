import os
import json
from openai import OpenAI

TITAN_GATEWAY_URL = "https://ai.titan.in/gateway"
AI_MODEL = os.environ.get("TITAN_MODEL", "azure/gpt-5-mini")

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')


def _get_api_key() -> str:
    """
    Read TITAN_API_KEY fresh from the .env file on every call so that
    rotating a short-lived JWT token (Azure AD, ~1 h expiry) takes effect
    immediately without restarting the Flask server.
    """
    # Re-parse the .env file directly — do NOT use load_dotenv() here because
    # that only updates os.environ once and won't overwrite an already-set key.
    try:
        with open(_ENV_PATH, 'r', encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if line.startswith('TITAN_API_KEY='):
                    key = line[len('TITAN_API_KEY='):].strip().strip('"').strip("'")
                    if key:
                        return key
    except OSError:
        pass
    # Fallback to environment variable (set before server start)
    return os.environ.get("TITAN_API_KEY", "")


def _simplify_polygon(polygon, max_points=20):
    """Reduce polygon to at most max_points vertices by uniform sampling."""
    if len(polygon) <= max_points:
        return polygon
    step = len(polygon) / max_points
    return [polygon[int(i * step)] for i in range(max_points)]


def get_ai_boundary_index(candidates, reference_image_path):
    """Use GPT-4o vision to identify which boundary candidate is the store interior.

    candidates: list of dicts with width_mm, height_mm, layer, polygon, bounds.
    reference_image_path: path to uploaded image/PDF.
    Returns: int index into candidates list.
    """
    api_key = _get_api_key()
    if not api_key:
        raise ValueError("TITAN_API_KEY not set in .env")

    client = OpenAI(base_url=TITAN_GATEWAY_URL, api_key=api_key, timeout=60.0)

    desc_lines = []
    for i, c in enumerate(candidates):
        desc_lines.append(
            f"Candidate {i}: {c['width_mm']}mm × {c['height_mm']}mm, layer='{c['layer']}'"
        )
    candidates_desc = "\n".join(desc_lines)

    prompt = f"""You are analyzing a store floor plan image to identify the main retail store interior boundary.

I extracted {len(candidates)} closed polygon candidates from a DXF architectural drawing:
{candidates_desc}

Rules for choosing the correct candidate:
- The store interior boundary is the polygon that encloses the RETAIL SALES FLOOR where customers shop.
- Ignore drawing sheet / title block borders (they are usually the largest rectangle with no architectural meaning).
- Ignore site/plot boundaries (outdoor perimeter, much larger than the store).
- Ignore small internal rooms (too small to be the main store).
- The correct candidate is typically a medium-sized polygon that fits the visible store walls in the image.

Looking at the floor plan image, return ONLY this JSON (no extra text):
{{"boundary_index": <integer 0-{len(candidates)-1}>, "confidence": "high|medium|low", "reason": "<one sentence>"}}"""

    user_content: list[dict] = [{"type": "text", "text": prompt}]

    ext = os.path.splitext(reference_image_path)[1].lower()
    if ext in {'.png', '.jpg', '.jpeg'}:
        import base64
        mime = 'image/png' if ext == '.png' else 'image/jpeg'
        with open(reference_image_path, 'rb') as f:
            encoded = base64.b64encode(f.read()).decode('utf-8')
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{encoded}"}
        })
    else:
        user_content.append({
            "type": "text",
            "text": "Reference file is a PDF. Use candidate dimensions and layer names to make your best guess."
        })

    response = client.chat.completions.create(
        model=AI_MODEL,
        messages=[{"role": "user", "content": user_content}],  # type: ignore[arg-type]
        max_tokens=256
    )

    # ── Token usage logging ───────────────────────────────────────────────────
    if hasattr(response, 'usage') and response.usage:
        import logging as _tlog
        _tlog.getLogger('layout').info(
            f"[TOKEN USAGE] get_ai_boundary_index  "
            f"prompt={response.usage.prompt_tokens}  "
            f"completion={response.usage.completion_tokens}  "
            f"total={response.usage.total_tokens}"
        )
        print(f"[TOKEN USAGE] boundary_index  prompt={response.usage.prompt_tokens}  "
              f"completion={response.usage.completion_tokens}  "
              f"total={response.usage.total_tokens}")

    text = (response.choices[0].message.content or "").strip()
    start = text.find('{')
    end = text.rfind('}') + 1
    if start == -1 or end == 0:
        raise ValueError(f"AI did not return JSON for boundary detection. Response: {text[:300]!r}")
    result = json.loads(text[start:end])
    idx = int(result.get("boundary_index", 0))
    return max(0, min(idx, len(candidates) - 1))


def get_ai_explanation(placements: list, requirements: dict,
                       store_w: float, store_d: float) -> str:
    """Generate a plain-text AI explanation for the chosen layout."""
    api_key = _get_api_key()
    if not api_key:
        return "AI explanation unavailable (no API key)."

    client = OpenAI(base_url=TITAN_GATEWAY_URL, api_key=api_key, timeout=30.0)

    zone_counts: dict = {}
    for p in placements:
        z = p.get('zone', 'DISPLAY')
        zone_counts[z] = zone_counts.get(z, 0) + 1
    zone_summary = ', '.join(
        f"{cnt} {z.lower().replace('_', ' ')}" for z, cnt in zone_counts.items()
    )

    branch    = requirements.get('branch_name') or 'Titan Eyewear'
    tier      = requirements.get('store_tier', 'STANDARD').replace('_', ' ').title()
    entrance  = requirements.get('entrance_wall', 'FRONT')
    walkway   = requirements.get('walkway_width', 1500)
    clinics   = requirements.get('clinic_count', 2)
    clinic_t  = requirements.get('clinic_type', 'PHOROPTER')
    north     = requirements.get('north_direction', 'FRONT')
    ceiling   = requirements.get('ceiling_height', 3000)

    prompt = f"""You are a Titan Eyewear store layout consultant.

Store: {branch} ({tier})
Size: {store_w / 1000:.1f} m × {store_d / 1000:.1f} m
Entrance: {entrance} wall | North direction: {north} wall
Walkway: {walkway / 1000:.1f} m | Ceiling: {ceiling} mm
Clinics: {clinics}× {clinic_t} | {len(placements)} fixtures placed
Zones used: {zone_summary}

Mandatory constraints applied:
- Cash counter placed in South-West corner (Vastu), facing North or East
- Clinics placed in mid-rear zone, not in entrance sightline
- 900 mm minimum clearance between floor and wall fixtures
- Retail zone at frontage (closest to glazing), Clinic zone mid-rear, BOH at rear

Write 4–5 sentences explaining why this layout works well for a Titan Eyewear Premium store.
Be specific about: entrance zone attraction (BAY_BIG door, BAY_SMALL TV), retail-first zoning,
clinic privacy, cash counter Vastu placement, walkway flow, and customer experience.
Professional tone, no bullet points, no JSON."""

    try:
        resp = client.chat.completions.create(
            model=AI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
        )
        if hasattr(resp, 'usage') and resp.usage:
            print(f"[TOKEN USAGE] get_ai_explanation  "
                  f"prompt={resp.usage.prompt_tokens}  "
                  f"completion={resp.usage.completion_tokens}  "
                  f"total={resp.usage.total_tokens}")
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        return (f"Layout generated successfully with {len(placements)} fixtures placed across "
                f"{len(zone_counts)} zones. Cash counter positioned in South-West corner (Vastu). "
                f"Clinics placed in mid-rear zone away from entrance sightline.")


# ── Full fixture library (all Titan catalog items) ────────────────────────────
FIXTURE_LIBRARY_JSON = """[
  {"code":"ISLAND_DS_2545","name":"DOUBLE SIDE ISLAND UNIT 2.54W","L_mm":2545,"D_mm":1058,"H_mm":1104,"zone":"RETAIL_MID","type":"floor"},
  {"code":"ISLAND_SS_2545","name":"SINGLE SIDE ISLAND UNIT 2.54W","L_mm":2545,"D_mm":574,"H_mm":1104,"zone":"RETAIL_MID","type":"floor"},
  {"code":"FLATBED_1200","name":"FLATBED SUNGLASS DISPLAY 1.20W","L_mm":1200,"D_mm":600,"H_mm":900,"zone":"SUNGLASSES","type":"floor"},
  {"code":"FLATBED_1500","name":"FLATBED SUNGLASS DISPLAY 1.50W","L_mm":1500,"D_mm":600,"H_mm":900,"zone":"SUNGLASSES","type":"floor"},
  {"code":"SMART_1840","name":"SMART DISPLAY UNIT 1.84W","L_mm":1840,"D_mm":605,"H_mm":1295,"zone":"SMART","type":"wall"},
  {"code":"IB_2225","name":"IB FRAME UNIT 2.25W","L_mm":2225,"D_mm":400,"H_mm":2400,"zone":"RETAIL_MID","type":"wall"},
  {"code":"IB_1290","name":"IB FRAME UNIT 1.29W","L_mm":1290,"D_mm":400,"H_mm":2400,"zone":"RETAIL_MID","type":"wall"},
  {"code":"LUX_OPEN_820","name":"LUXURY UNIT OPEN TOP 0.82W","L_mm":820,"D_mm":435,"H_mm":2400,"zone":"RETAIL_PREMIUM","type":"wall"},
  {"code":"LUX_GLASS_820","name":"LUXURY UNIT GLASS TOP 0.82W","L_mm":820,"D_mm":435,"H_mm":2400,"zone":"RETAIL_PREMIUM","type":"wall"},
  {"code":"LENS_600","name":"LENS UNIT 0.60W","L_mm":600,"D_mm":400,"H_mm":2400,"zone":"RETAIL_PREMIUM","type":"wall"},
  {"code":"HB_YA_2225","name":"HB-YA FRAME UNIT 2.25W","L_mm":2225,"D_mm":400,"H_mm":2400,"zone":"RETAIL_MID","type":"wall"},
  {"code":"HB_YA_1290","name":"HB-YA FRAME UNIT 1.29W","L_mm":1290,"D_mm":400,"H_mm":2400,"zone":"RETAIL_MID","type":"wall"},
  {"code":"HB_MW_2225","name":"HB-M&W FRAME UNIT 2.25W","L_mm":2225,"D_mm":400,"H_mm":2400,"zone":"RETAIL_MID","type":"wall"},
  {"code":"HB_MW_1290","name":"HB-M&W FRAME UNIT 1.29W","L_mm":1290,"D_mm":400,"H_mm":2400,"zone":"RETAIL_MID","type":"wall"},
  {"code":"AFF_FAST_2225","name":"AFFORDABLE FASTRACK EYEWEAR UNIT 2.25W","L_mm":2225,"D_mm":400,"H_mm":2400,"zone":"RETAIL_FRONT","type":"wall"},
  {"code":"AFF_FAST_1290","name":"AFFORDABLE FASTRACK EYEWEAR UNIT 1.29W","L_mm":1290,"D_mm":400,"H_mm":2400,"zone":"RETAIL_FRONT","type":"wall"},
  {"code":"AFF_MW_2225","name":"AFFORDABLE MEN AND WOMEN UNIT 2.25W","L_mm":2225,"D_mm":400,"H_mm":2400,"zone":"RETAIL_MID","type":"wall"},
  {"code":"AFF_MW_1290","name":"AFFORDABLE MEN AND WOMEN UNIT 1.29W","L_mm":1290,"D_mm":400,"H_mm":2400,"zone":"RETAIL_MID","type":"wall"},
  {"code":"KIDS_1000","name":"PREM KIDS DISPLAY UNIT LGP 1.00W","L_mm":1000,"D_mm":400,"H_mm":2400,"zone":"KIDS","type":"wall"},
  {"code":"SG_WALL_LH_1228","name":"SUNGLASS UNIT - WALL MOUNT - 1.22W LH","L_mm":1228,"D_mm":450,"H_mm":2400,"zone":"SUNGLASSES","type":"wall"},
  {"code":"SG_WALL_RH_1228","name":"SUNGLASS UNIT - WALL MOUNT - 1.22W RH","L_mm":1228,"D_mm":450,"H_mm":2400,"zone":"SUNGLASSES","type":"wall"},
  {"code":"SG_FLOOR_LH_1228","name":"SUNGLASS UNIT - FLOOR MOUNT - 1.22W LH","L_mm":1228,"D_mm":450,"H_mm":2400,"zone":"SUNGLASSES","type":"floor"},
  {"code":"SG_FLOOR_RH_1228","name":"SUNGLASS UNIT - FLOOR MOUNT - 1.22W RH","L_mm":1228,"D_mm":450,"H_mm":2400,"zone":"SUNGLASSES","type":"floor"},
  {"code":"SG_ANG_LH_1324","name":"SUNGLASS ANGULAR UNIT - WALL MOUNT LH","L_mm":1324,"D_mm":681,"H_mm":2400,"zone":"SUNGLASSES","type":"wall"},
  {"code":"SG_ANG_RH_1324","name":"SUNGLASS ANGULAR UNIT - WALL MOUNT RH","L_mm":1324,"D_mm":681,"H_mm":2400,"zone":"SUNGLASSES","type":"wall"},
  {"code":"TBL_TRN_D750","name":"TRANSACTION TABLE 0.75 DIA-CORIAN","L_mm":750,"D_mm":750,"H_mm":770,"zone":"RETAIL_MID","type":"floor","shape":"circle"},
  {"code":"TBL_CTR_600","name":"CENTER TABLE 0.6D","L_mm":600,"D_mm":600,"H_mm":450,"zone":"RETAIL_MID","type":"floor"},
  {"code":"CASH_L_2300","name":"CASH COUNTER L SHAPED 2.30W","L_mm":2300,"D_mm":1000,"H_mm":1100,"zone":"CASH","type":"floor"},
  {"code":"CASH_1200","name":"CASH COUNTER 1.20W","L_mm":1200,"D_mm":600,"H_mm":1100,"zone":"CASH","type":"floor"},
  {"code":"CASH_1800","name":"CASH COUNTER 1.80W","L_mm":1800,"D_mm":600,"H_mm":1100,"zone":"CASH","type":"floor"},
  {"code":"CASH_L_LH_1350","name":"CASH COUNTER L SHAPED 1.3W LH","L_mm":1350,"D_mm":1500,"H_mm":1100,"zone":"CASH","type":"floor"},
  {"code":"CASH_L_RH_1350","name":"CASH COUNTER L SHAPED 1.3W RH","L_mm":1350,"D_mm":1500,"H_mm":1100,"zone":"CASH","type":"floor"},
  {"code":"CASHBACK_2290","name":"CASHBACK-WHITE-2.29W","L_mm":2290,"D_mm":400,"H_mm":526,"zone":"CASH","type":"wall"},
  {"code":"CASHBACK_1800","name":"CASHBACK-WHITE-1.8W","L_mm":1800,"D_mm":400,"H_mm":526,"zone":"CASH","type":"wall"},
  {"code":"MIRROR_200","name":"TABLE TOP MIRROR-MS","L_mm":200,"D_mm":200,"H_mm":400,"zone":"RETAIL_MID","type":"floor"},
  {"code":"CLN_TBL_1250","name":"CLINIC TRAN TABLE WOOD TOP-1.25W","L_mm":1250,"D_mm":350,"H_mm":740,"zone":"CLINIC","type":"floor"},
  {"code":"CLN_TBL_450","name":"SMALL CLINIC TABLE 0.45W","L_mm":450,"D_mm":350,"H_mm":740,"zone":"CLINIC","type":"floor"},
  {"code":"PHOROPTER_CLINIC","name":"PHOROPTER CLINIC ROOM","L_mm":3050,"D_mm":2440,"H_mm":2800,"zone":"CLINIC","type":"room"},
  {"code":"NORMAL_CLINIC","name":"NORMAL CLINIC ROOM","L_mm":2745,"D_mm":2135,"H_mm":2800,"zone":"CLINIC","type":"room"},
  {"code":"FITTING_LAB","name":"FITTING LAB 1370x1830","L_mm":1370,"D_mm":1830,"H_mm":2800,"zone":"FITTING_LAB","type":"room"},
  {"code":"TOILET","name":"TOILET / WASH ROOM","L_mm":1500,"D_mm":1800,"H_mm":2800,"zone":"BOH","type":"room"},
  {"code":"PANTRY","name":"PANTRY","L_mm":1800,"D_mm":1500,"H_mm":2800,"zone":"BOH","type":"room"},
  {"code":"STORAGE","name":"STORAGE ROOM","L_mm":2000,"D_mm":1800,"H_mm":2800,"zone":"BOH","type":"room"},
  {"code":"ELEC_ROOM","name":"ELECTRICAL ROOM","L_mm":1200,"D_mm":1000,"H_mm":2800,"zone":"BOH","type":"room"},
  {"code":"FR_ROOM","name":"FR ROOM (FRANCHISEE)","L_mm":2400,"D_mm":2000,"H_mm":2800,"zone":"BOH","type":"room"},
  {"code":"FITTING_ROOM","name":"FITTING ROOM","L_mm":1200,"D_mm":1200,"H_mm":2800,"zone":"BOH","type":"room"},
  {"code":"PSTOR_2W_911","name":"PREM STORAGE TWO WAY - 0.91W","L_mm":911,"D_mm":700,"H_mm":700,"zone":"BOH","type":"floor"},
  {"code":"PSTOR_1W_911","name":"PREM STORAGE ONE WAY - 0.91W","L_mm":911,"D_mm":700,"H_mm":700,"zone":"BOH","type":"floor"}
]"""

# Zone colour map (used to enrich AI placements with colours)
ZONE_COLORS = {
    'RETAIL_FRONT':    '#3B82F6',
    'RETAIL_MID':      '#6366F1',
    'RETAIL_PREMIUM':  '#A855F7',
    'SUNGLASSES':      '#F97316',
    'KIDS':            '#EC4899',
    'SMART':           '#06B6D4',
    'CLINIC':          '#10B981',
    'FITTING_LAB':     '#14B8A6',
    'BOH':             '#6B7280',
    'CASH':            '#EF4444',
    'ENTRANCE':        '#FCD34D',
    'PERIMETER':       '#3B82F6',
    'ISLAND':          '#8B5CF6',
    'CHECKOUT':        '#EF4444',
    'SERVICE':         '#10B981',
    'DISPLAY':         '#F59E0B',
    'CONTACT_LENS':    '#06B6D4',
    'LUXURY':          '#A855F7',
    'STORAGE':         '#6B7280',
    'AFFORDABLE':      '#60A5FA',
}


def _enrich_placement(p: dict) -> dict:
    """Add zone_color to a placement dict if missing."""
    zone = p.get('zone', 'RETAIL_MID')
    if 'zone_color' not in p:
        p['zone_color'] = ZONE_COLORS.get(zone, '#94A3B8')
    return p


def get_ai_layout_placements(store_boundary, selected_fixtures, constraints,
                              requirements=None, reference_file_path=None):
    """
    Call GPT-40 via Titan AI Gateway to get EXACT x,y placement coordinates
    for every fixture and room.

    Returns a list of placement dicts compatible with GridLayoutEngine output:
      [{ fixture, x, y, l, d, h, rotation, zone, zone_color }, ...]

    store_boundary: dict with 'polygon' (list of (x,y) in DXF mm) and 'bounds'.
    Coordinates passed to the AI are normalized so the store bottom-left = (0, 0).
    requirements: dict with all store requirements.
    reference_file_path: optional path to reference image/pdf.
    """
    api_key = _get_api_key()
    if not api_key:
        raise ValueError("TITAN_API_KEY not set in .env")

    client = OpenAI(base_url=TITAN_GATEWAY_URL, api_key=api_key, timeout=180.0)

    if requirements is None:
        requirements = {}

    bounds = store_boundary['bounds']
    origin_x = bounds['min'][0]
    origin_y = bounds['min'][1]
    store_w = bounds['max'][0] - origin_x
    store_d = bounds['max'][1] - origin_y

    # Normalize polygon to origin (0,0)
    raw_polygon = store_boundary.get('polygon') or [
        (0, 0), (store_w, 0), (store_w, store_d), (0, store_d)
    ]
    norm_polygon = [(round(p[0] - origin_x, 1), round(p[1] - origin_y, 1))
                    for p in raw_polygon]
    norm_polygon = _simplify_polygon(norm_polygon)

    is_rectangular = len(norm_polygon) == 4

    # Build a human-readable description of the polygon shape for the AI
    def _describe_polygon_shape(poly, sw, sd):
        """Return a plain-English description of the store shape + forbidden zones."""
        if len(poly) == 4:
            return f"rectangular {sw:.0f} mm × {sd:.0f} mm"
        # Compute bounding box of polygon
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        # Find corners of bounding box that are NOT in the polygon
        # (these are the "cut-out" regions the AI must avoid)
        try:
            from shapely.geometry import Polygon as _SP, Point as _SPt
            sp = _SP(poly)
            if not sp.is_valid:
                sp = sp.buffer(0)
            corners = [
                (min_x, min_y, "bottom-left"),
                (max_x, min_y, "bottom-right"),
                (min_x, max_y, "top-left"),
                (max_x, max_y, "top-right"),
            ]
            missing = [name for cx, cy, name in corners
                       if not sp.contains(_SPt(cx + (max_x-min_x)*0.05,
                                               cy + (max_y-min_y)*0.05))]
            if missing:
                return (
                    f"NON-RECTANGULAR (L-shaped or irregular) {sw:.0f} mm × {sd:.0f} mm. "
                    f"The following corner(s) of the bounding box are OUTSIDE the store polygon "
                    f"and must NOT contain any fixtures: {', '.join(missing)} corner(s). "
                    f"Always check each fixture's (x,y) is inside the polygon vertices listed below."
                )
        except Exception:
            pass
        return f"irregular polygon {sw:.0f} mm × {sd:.0f} mm — place fixtures only within the polygon vertices"

    shape_desc = _describe_polygon_shape(norm_polygon, store_w, store_d)

    # Requirements extraction
    branch_name       = requirements.get('branch_name', 'Titan Eyewear')
    store_tier        = requirements.get('store_tier', 'PREMIUM')
    entrance_wall     = requirements.get('entrance_wall', 'FRONT')
    north_dir         = requirements.get('north_direction', 'FRONT')
    walkway_w         = requirements.get('walkway_width', 1500)
    checkout_count    = requirements.get('checkout_count', 1)
    clinic_count      = requirements.get('clinic_count', 2)
    clinic_type       = requirements.get('clinic_type', 'PHOROPTER')
    ceiling_h         = requirements.get('ceiling_height', 3000)
    bay_big_side      = requirements.get('bay_big_side', 'LEFT')
    has_pillar_line   = requirements.get('has_pillar_line', False)
    pillar_axis       = requirements.get('pillar_line_axis', 'X')
    has_pantry        = requirements.get('has_pantry', True)
    has_toilet        = requirements.get('has_toilet', True)
    has_fitting_lab   = requirements.get('has_fitting_lab', True)
    has_storage       = requirements.get('has_storage', True)
    has_electrical    = requirements.get('has_electrical', True)
    has_fr_room       = requirements.get('has_fr_room', True)
    has_fitting_rooms = requirements.get('has_fitting_rooms', True)

    min_spacing    = constraints.get('minSpacing', 900)
    allow_rotation = constraints.get('allowRotation', False)

    has_cash_counter = any('cash counter' in f['name'].lower() for f in selected_fixtures)

    fixture_list_json = json.dumps([
        {"name": f['name'], "l_mm": f['l'], "d_mm": f['d'], "h_mm": f.get('h', 1000)}
        for f in selected_fixtures
    ], indent=2)

    # BOH inclusions
    boh_rooms = []
    if has_fitting_lab:   boh_rooms.append({"name": "FITTING LAB 1370x1830",       "l_mm": 1370, "d_mm": 1830, "zone": "FITTING_LAB"})
    if has_toilet:        boh_rooms.append({"name": "TOILET / WASH ROOM",           "l_mm": 1500, "d_mm": 1800, "zone": "BOH"})
    if has_pantry:        boh_rooms.append({"name": "PANTRY",                        "l_mm": 1800, "d_mm": 1500, "zone": "BOH"})
    if has_fitting_rooms: boh_rooms.append({"name": "FITTING ROOM 1",               "l_mm": 1200, "d_mm": 1200, "zone": "BOH"})
    if has_fitting_rooms: boh_rooms.append({"name": "FITTING ROOM 2",               "l_mm": 1200, "d_mm": 1200, "zone": "BOH"})
    if has_fr_room:       boh_rooms.append({"name": "FR ROOM (FRANCHISEE)",          "l_mm": 2400, "d_mm": 2000, "zone": "BOH"})
    if has_storage:       boh_rooms.append({"name": "STORAGE ROOM",                  "l_mm": 2000, "d_mm": 1800, "zone": "BOH"})
    if has_electrical:    boh_rooms.append({"name": "ELECTRICAL ROOM",               "l_mm": 1200, "d_mm": 1000, "zone": "BOH"})

    clinic_size_str = "3050 × 2440 mm" if clinic_type == 'PHOROPTER' else "2745 × 2135 mm"
    clinic_l = 3050 if clinic_type == 'PHOROPTER' else 2745
    clinic_d = 2440 if clinic_type == 'PHOROPTER' else 2135

    clinic_rooms = [
        {"name": f"{'PHOROPTER' if clinic_type == 'PHOROPTER' else 'NORMAL'} CLINIC ROOM {i+1}",
         "l_mm": clinic_l, "d_mm": clinic_d, "zone": "CLINIC"}
        for i in range(clinic_count)
    ]

    all_rooms_json = json.dumps(clinic_rooms + boh_rooms, indent=2)

    ceiling_note = (
        f"Ceiling: {ceiling_h} mm — {'≥2500 mm OK, premium fixtures at 2400 mm' if ceiling_h >= 2500 else f'BELOW 2500 mm — adapt fixture heights to max {ceiling_h - 100} mm'}"
    )
    pillar_note = (
        f"Pillar line along {pillar_axis}-axis — apply partition spine rule."
        if has_pillar_line else "No pillar line."
    )

    # Derive SW corner description for Vastu
    sw_map = {
        'FRONT': 'bottom-left corner (x≈0, y≈0)',
        'BACK':  'top-right corner (x≈store_w, y≈store_d)',
        'LEFT':  'bottom-right corner (x≈store_w, y≈0)',
        'RIGHT': 'top-left corner (x≈0, y≈store_d)',
    }
    sw_desc = sw_map.get(north_dir, 'bottom-left corner (x≈0, y≈0)')

    # Entrance wall → which edge y=0 / y=store_d / x=0 / x=store_w
    entrance_edge_map = {
        'FRONT': f'y=0 edge (bottom), store depth goes from y=0 to y={store_d:.0f}',
        'BACK':  f'y={store_d:.0f} edge (top)',
        'LEFT':  f'x=0 edge (left)',
        'RIGHT': f'x={store_w:.0f} edge (right)',
    }
    entrance_edge = entrance_edge_map.get(entrance_wall, f'y=0 edge (bottom)')

    # Compute explicit zone y-ranges for the prompt
    _retail_front_y2 = round(store_d * 0.20)
    _retail_mid_y2   = round(store_d * 0.50)
    _retail_prem_y2  = round(store_d * 0.60)
    _clinic_y2       = round(store_d * 0.80)
    _boh_y1          = round(store_d * 0.80)
    _right_wall_x    = round(store_w - 600)

    prompt = f"""You are a Titan Eyewear store layout AI. Output EXACT mm coordinates for every fixture.

═══════════════════════════════════════════════════════════════
STORE GEOMETRY  (bottom-left = 0,0)
═══════════════════════════════════════════════════════════════
Store: {branch_name} | Tier: {store_tier}
Width: {store_w:.0f} mm  |  Depth: {store_d:.0f} mm
Shape: {shape_desc}
Polygon vertices (mm): {json.dumps(norm_polygon)}
Entrance wall: {entrance_wall} → {entrance_edge}
North direction: {north_dir} wall faces North
{ceiling_note}
{pillar_note}
BAY_BIG: {bay_big_side} side | BAY_SMALL: {'RIGHT' if bay_big_side == 'LEFT' else 'LEFT'} side
Minimum walkway: {walkway_w} mm | Min gap between fixtures: {min_spacing} mm

═══════════════════════════════════════════════════════════════
MANDATORY ZONE LAYOUT  (entrance at y=0, rear at y={store_d:.0f})
═══════════════════════════════════════════════════════════════
ZONE              Y range (mm)          X range (mm)
─────────────────────────────────────────────────────────────
RETAIL_FRONT      y=50  → y={_retail_front_y2}     x=50 → x={store_w-50:.0f}
RETAIL_MID        y={_retail_front_y2} → y={_retail_mid_y2}   x=50 → x={store_w-50:.0f}
RETAIL_PREMIUM    y={_retail_mid_y2} → y={_retail_prem_y2}   x=50 → x={store_w-50:.0f}
CLINIC            y={_retail_prem_y2} → y={_clinic_y2}   x=50 → x={store_w-50:.0f}
BOH               y={_boh_y1} → y={store_d-50:.0f}   x=50 → x={store_w-50:.0f}
LEFT_WALL strip   (retail zone)         x=50 → x=650
RIGHT_WALL strip  (retail zone)         x={_right_wall_x} → x={store_w-50:.0f}
CENTER aisle      (retail zone)         x=650+{walkway_w} → x={_right_wall_x-walkway_w}

WALL PLACEMENT PATTERN (follow exactly):
- Left wall fixtures:  x=50, rotation=90, stacked vertically (y increases)
- Right wall fixtures: x={_right_wall_x}, rotation=90, stacked vertically (y increases)
- Bottom wall fixtures (entrance): y=50, rotation=0, placed horizontally (x increases)
- Top wall fixtures (rear): y={store_d-650:.0f}, rotation=0, placed horizontally (x increases)
- Floor fixtures (islands, tables): placed in CENTER zone with {walkway_w} mm aisle clearance

BOH PLACEMENT (rear-left corner preferred):
- Start BOH rooms at x=50, y={_boh_y1}, pack left-to-right then wrap to next row
- Fitting Lab, Toilet, Pantry, Storage, Electrical, FR Room, Fitting Rooms
- All BOH rooms: rotation=0

CLINIC PLACEMENT (mid-rear, side by side):
- Start clinics at x=50, y={_retail_prem_y2+300}, place side by side (x increases)
- Each clinic: rotation=0
{"" if not has_cash_counter else f'''
CASH COUNTER (South-West corner = {sw_desc}):
- Place at x=50, y=50 (or nearest valid position to SW corner)
- rotation=0'''}

═══════════════════════════════════════════════════════════════
FIXTURES TO PLACE (user-selected)
═══════════════════════════════════════════════════════════════
{fixture_list_json}

═══════════════════════════════════════════════════════════════
ROOMS TO PLACE (clinics + BOH — MANDATORY)
═══════════════════════════════════════════════════════════════
{all_rooms_json}

═══════════════════════════════════════════════════════════════
HARD CONSTRAINTS (never violate)
═══════════════════════════════════════════════════════════════
{"1. Cash counter MUST be in the South-West corner = " + sw_desc + " (Vastu)." if has_cash_counter else ""}
2. Clinics MUST be in CLINIC zone (y={_retail_prem_y2}–{_clinic_y2}), NOT near entrance.
3. BOH rooms MUST be in BOH zone (y={_boh_y1}–{store_d-50:.0f}).
4. Retail fixtures MUST be in RETAIL zones (y=50–{_retail_prem_y2}).
5. NO two fixtures may overlap. Minimum {min_spacing} mm gap between all fixtures.
6. All fixtures MUST fit inside the store polygon. 0 ≤ x ≤ {store_w:.0f}, 0 ≤ y ≤ {store_d:.0f}.
7. Wall fixtures MUST be placed against walls (left, right, bottom, or top wall strip).
8. Floor fixtures (ISLAND, FLATBED, TABLE) go in CENTER zone only.
9. Fitting Lab FIXED size: 1370 × 1830 mm.
10. Clinic sizes: Phoropter = {clinic_size_str}.
11. ONLY place fixtures/rooms that appear in the "FIXTURES TO PLACE" or "ROOMS TO PLACE" lists below. Do NOT invent, add, or substitute any fixture that is not explicitly listed there — not even commonly-expected items like a cash counter.

═══════════════════════════════════════════════════════════════
OUTPUT FORMAT — STRICT JSON ONLY
═══════════════════════════════════════════════════════════════
Return ONLY a valid JSON object. No markdown, no explanation, no code fences.

{{
  "placements": [
    {{
      "fixture": "<fixture name>",
      "x": <number — bottom-left x in mm, integer>,
      "y": <number — bottom-left y in mm, integer>,
      "l": <length in mm — same as l_mm from input>,
      "d": <depth in mm — same as d_mm from input>,
      "h": <height in mm>,
      "rotation": <0 or 90>,
      "zone": "<one of: RETAIL_FRONT|RETAIL_MID|RETAIL_PREMIUM|SUNGLASSES|KIDS|SMART|CLINIC|FITTING_LAB|BOH|CASH>"
    }},
    ...
  ],
  "layout_style": "<Classic Grid|Racetrack Loop|Premium Open>",
  "summary": "<one paragraph describing the layout>"
}}

IMPORTANT RULES FOR COORDINATES:
- x and y are the BOTTOM-LEFT corner of the fixture rectangle.
- After rotation=90, the effective width becomes d_mm and effective depth becomes l_mm.
  Always compute BEFORE writing each coordinate:
    effective_w = d_mm if rotation==90 else l_mm
    effective_d = l_mm if rotation==90 else d_mm
  Then verify:
    x + effective_w MUST be <= {store_w:.0f}   (never exceed right wall)
    y + effective_d MUST be <= {store_d:.0f}   (never exceed top wall)
    x MUST be >= 0   (never go left of left wall)
    y MUST be >= 0   (never go below bottom wall)

WALL FIXTURE ROTATION RULES (CRITICAL — always follow):
- Wall fixtures on the LEFT wall  → rotation = 90
    The long side (l_mm) runs along the Y axis (up the wall).
    effective_w = d_mm (shallow depth, pointing right into store)
    effective_d = l_mm (long span, running up the wall)
    x = 50  (flush against left wall)
    y = any valid position so that y + l_mm <= {store_d:.0f}
    EXAMPLE: IB FRAME UNIT 2.25W (l=2225, d=400), rotation=90:
      effective_w=400, effective_d=2225 → x=50, y=<start position>
- Wall fixtures on the RIGHT wall → rotation = 90
    effective_w = d_mm, effective_d = l_mm
    x = {store_w:.0f} - d_mm - 50  (flush against right wall)
    EXAMPLE: IB FRAME UNIT 2.25W (l=2225, d=400), rotation=90:
      effective_w=400 → x = {store_w:.0f} - 400 - 50 = {max(0, store_w - 450):.0f}
- Wall fixtures on the BOTTOM wall (entrance) → rotation = 0
    x = any valid position, y = 50
- Wall fixtures on the TOP wall (rear) → rotation = 0
    x = any valid position, y = {store_d:.0f} - d_mm - 50
- NEVER place a wall fixture with rotation=0 against a left or right wall.
  rotation=0 means the long side runs horizontally (along X axis) — only valid for
  bottom/top wall placement.

- Place wall fixtures flush against walls with a 50 mm margin:
  * Left wall fixtures (rotation=90):   x = 50
  * Right wall fixtures (rotation=90):  x = {store_w:.0f} - d_mm - 50
  * Bottom wall fixtures (rotation=0):  y = 50
  * Top wall fixtures (rotation=0):     y = {store_d:.0f} - d_mm - 50
- Place ALL fixtures from the fixture list AND all rooms from the rooms list.
- Do NOT omit any fixture or room.
- Ensure NO two placements overlap (check all pairs).
- CRITICAL: Every x,y coordinate MUST satisfy:
    0 <= x AND x + effective_w <= {store_w:.0f}
    0 <= y AND y + effective_d <= {store_d:.0f}
  Any placement outside these bounds is INVALID.
"""

    user_content: list[dict] = [{"type": "text", "text": prompt}]

    if reference_file_path and os.path.exists(reference_file_path):
        ext = os.path.splitext(reference_file_path)[1].lower()
        if ext in {'.png', '.jpg', '.jpeg'}:
            import base64
            mime = 'image/png' if ext == '.png' else 'image/jpeg'
            with open(reference_file_path, 'rb') as f:
                encoded = base64.b64encode(f.read()).decode('utf-8')
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{encoded}"}
            })
        elif ext == '.pdf':
            user_content.append({
                "type": "text",
                "text": (f"Reference PDF uploaded. Use it as contextual guidance for zoning and fixture intent.")
            })

    response = client.chat.completions.create(
        model=AI_MODEL,
        messages=[{"role": "user", "content": user_content}],  # type: ignore[arg-type]
        max_tokens=16384,
    )

    # ── Token usage logging ───────────────────────────────────────────────────
    if hasattr(response, 'usage') and response.usage:
        print(f"[TOKEN USAGE] get_ai_layout_placements  "
              f"prompt={response.usage.prompt_tokens}  "
              f"completion={response.usage.completion_tokens}  "
              f"total={response.usage.total_tokens}")

    choice = response.choices[0]
    text = (choice.message.content or "").strip()

    if not text:
        raise ValueError(
            f"AI returned empty response (finish_reason={choice.finish_reason!r})."
        )

    # Parse JSON
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON from text
        start = text.find('{')
        end = text.rfind('}') + 1
        if start == -1 or end == 0:
            raise ValueError(f"AI did not return valid JSON. Response: {text[:500]!r}")
        result = json.loads(text[start:end])

    placements = result.get('placements', [])
    if not placements:
        raise ValueError("AI returned empty placements list.")

    # Build a Shapely polygon from the normalized store boundary for containment checks
    _shapely_store_poly = None
    _raw_polygon = store_boundary.get('polygon')
    if _raw_polygon and len(_raw_polygon) >= 3:
        try:
            from shapely.geometry import Polygon as _SPoly
            _norm_pts = [(pt[0] - origin_x, pt[1] - origin_y) for pt in _raw_polygon]
            _sp = _SPoly(_norm_pts)
            if not _sp.is_valid:
                _sp = _sp.buffer(0)
            # Use a small inset so fixtures touching the wall edge are accepted
            _shapely_store_poly = _sp.buffer(-50)
        except Exception:
            _shapely_store_poly = None

    # Validate, clamp, and enrich each placement
    # The AI works in normalized space: 0 ≤ x ≤ store_w, 0 ≤ y ≤ store_d
    MARGIN = 50  # mm — minimum inset from wall
    validated = []
    for p in placements:
        # Ensure required fields exist
        if not all(k in p for k in ('fixture', 'x', 'y', 'l', 'd')):
            continue
        x   = int(round(float(p['x'])))
        y   = int(round(float(p['y'])))
        l   = int(round(float(p['l'])))
        d   = int(round(float(p['d'])))
        h   = int(round(float(p.get('h', 1000))))
        rot = int(p.get('rotation', 0))

        # Effective footprint after rotation
        eff_w = d if rot in (90, 270) else l
        eff_d = l if rot in (90, 270) else d

        # ── Hard clamp: keep fixture entirely inside store bounding box ────
        x = max(MARGIN, min(x, int(store_w) - eff_w - MARGIN))
        y = max(MARGIN, min(y, int(store_d) - eff_d - MARGIN))

        # Skip degenerate fixtures (size larger than store)
        if eff_w <= 0 or eff_d <= 0:
            continue
        if eff_w > store_w or eff_d > store_d:
            continue

        # ── Shapely polygon check: reject fixtures outside L-shape/notch ──
        if _shapely_store_poly is not None:
            try:
                from shapely.geometry import box as _SBox
                fix_box = _SBox(x, y, x + eff_w, y + eff_d)
                intersection = _shapely_store_poly.intersection(fix_box)
                # Require at least 85% of fixture area inside the polygon
                if fix_box.area > 0 and intersection.area < fix_box.area * 0.85:
                    continue  # skip this placement — mostly outside polygon
            except Exception:
                pass  # if Shapely fails, keep the placement

        p['x'] = x
        p['y'] = y
        p['l'] = l
        p['d'] = d
        p['h'] = h
        p['rotation'] = rot
        p['zone'] = p.get('zone', 'RETAIL_MID')
        p = _enrich_placement(p)
        validated.append(p)

    layout_style = result.get('layout_style', 'AI Layout')
    summary = result.get('summary', '')

    return validated, layout_style, summary


# ── Legacy function kept for backward compatibility ───────────────────────────

def get_ai_layout_positions(store_boundary, selected_fixtures, constraints,
                             requirements=None, reference_file_path=None):
    """Legacy wrapper — returns structured text concept (used for ai_layout_concept field)."""
    api_key = _get_api_key()
    if not api_key:
        raise ValueError("TITAN_API_KEY not set in .env")

    client = OpenAI(base_url=TITAN_GATEWAY_URL, api_key=api_key, timeout=120.0)

    if requirements is None:
        requirements = {}

    bounds = store_boundary['bounds']
    origin_x = bounds['min'][0]
    origin_y = bounds['min'][1]
    store_w = bounds['max'][0] - origin_x
    store_d = bounds['max'][1] - origin_y

    norm_polygon = [(round(p[0] - origin_x, 1), round(p[1] - origin_y, 1))
                    for p in (store_boundary.get('polygon') or
                              [(0,0),(store_w,0),(store_w,store_d),(0,store_d)])]
    norm_polygon = _simplify_polygon(norm_polygon)

    branch_name    = requirements.get('branch_name', 'Titan Eyewear')
    store_tier     = requirements.get('store_tier', 'PREMIUM')
    entrance_wall  = requirements.get('entrance_wall', 'FRONT')
    north_dir      = requirements.get('north_direction', 'FRONT')
    walkway_w      = requirements.get('walkway_width', 1500)
    checkout_count = requirements.get('checkout_count', 1)
    clinic_count   = requirements.get('clinic_count', 2)
    clinic_type    = requirements.get('clinic_type', 'PHOROPTER')
    ceiling_h      = requirements.get('ceiling_height', 3000)
    bay_big_side   = requirements.get('bay_big_side', 'LEFT')

    fixture_list = "\n".join(
        f"- {f['name']}: {f['l']}mm wide x {f['d']}mm deep x {f.get('h', 1000)}mm high"
        for f in selected_fixtures
    )

    prompt = f"""You are a Titan Eyewear store layout AI consultant.
Store: {branch_name} ({store_tier}) | {store_w/1000:.1f}m × {store_d/1000:.1f}m
Entrance: {entrance_wall} | North: {north_dir} | Walkway: {walkway_w}mm | Ceiling: {ceiling_h}mm
Clinics: {clinic_count}× {clinic_type} | Checkouts: {checkout_count}
BAY_BIG: {bay_big_side} side

Fixtures:
{fixture_list}

Write a 4-section layout concept (Zoning, Fixture Placement, Clinics/BOH, Cash Counter).
Professional tone. No JSON."""

    try:
        resp = client.chat.completions.create(
            model=AI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
        )
        text = (resp.choices[0].message.content or "").strip()
        return {"layout_concept": text, "structured_output": True}
    except Exception as e:
        return {"layout_concept": f"Layout concept unavailable: {e}", "structured_output": False}


def get_ai_capacity_analysis(store_boundary: dict) -> dict:
    """
    After a DXF is uploaded, ask the AI to analyse the store dimensions and
    recommend how many of each fixture type and BOH room can realistically fit.

    Returns a dict:
    {
      "store_w_m": float,
      "store_d_m": float,
      "store_area_m2": float,
      "recommendations": [
        {"category": str, "item": str, "recommended_qty": int, "reason": str},
        ...
      ],
      "summary": str,
      "raw": str   # full AI text for debugging
    }
    """
    api_key = _get_api_key()
    if not api_key:
        raise ValueError("TITAN_API_KEY not set in .env")

    client = OpenAI(base_url=TITAN_GATEWAY_URL, api_key=api_key, timeout=60.0)

    bounds = store_boundary['bounds']
    origin_x = bounds['min'][0]
    origin_y = bounds['min'][1]
    store_w = bounds['max'][0] - origin_x
    store_d = bounds['max'][1] - origin_y

    # Compute actual polygon area using Shoelace formula (not bounding box)
    # This gives the true floor area for L-shaped / irregular stores.
    polygon = store_boundary.get('polygon')
    if polygon and len(polygon) >= 3:
        n = len(polygon)
        shoelace = abs(sum(
            polygon[i][0] * polygon[(i + 1) % n][1] -
            polygon[(i + 1) % n][0] * polygon[i][1]
            for i in range(n)
        )) / 2.0
        store_area_mm2 = shoelace
    else:
        store_area_mm2 = store_w * store_d

    store_area_m2  = store_area_mm2 / 1_000_000          # m²
    store_area_sqft = store_area_m2 * 10.7639             # sq ft
    store_area = store_area_m2  # keep variable name for backward compat

    polygon = store_boundary.get('polygon') or [
        (0, 0), (store_w, 0), (store_w, store_d), (0, store_d)
    ]
    norm_polygon = [(round(p[0] - origin_x, 1), round(p[1] - origin_y, 1))
                    for p in polygon]
    norm_polygon = _simplify_polygon(norm_polygon, max_points=16)

    prompt = f"""You are a Titan Eyewear store layout consultant.
A store floor plan has been uploaded with the following dimensions:

Store width:  {store_w/1000:.2f} m  ({store_w:.0f} mm)
Store depth:  {store_d/1000:.2f} m  ({store_d:.0f} mm)
Store area:   {store_area_m2:.1f} m²  ({store_area_sqft:.0f} sq ft)  [actual polygon area, not bounding box]
Shape polygon (mm, normalised to 0,0): {json.dumps(norm_polygon)}

Based on these dimensions, recommend the MAXIMUM number of each item that can
realistically fit while maintaining:
- 900 mm minimum walkway clearance between fixtures
- BOH rooms packed in the rear 20% of the store
- 2 clinic rooms in the mid-rear 20% of the store
- Wall fixtures along all 4 walls
- Floor fixtures (islands, tables) in the centre aisle

Return ONLY valid JSON — no markdown, no explanation:
{{
  "recommendations": [
    {{"category": "Wall Fixtures", "item": "IB FRAME UNIT 2.25W (2225×400 mm)", "recommended_qty": <int>, "reason": "<one sentence>"}},
    {{"category": "Wall Fixtures", "item": "IB FRAME UNIT 1.29W (1290×400 mm)", "recommended_qty": <int>, "reason": "<one sentence>"}},
    {{"category": "Wall Fixtures", "item": "LUXURY UNIT 0.82W (820×400 mm)", "recommended_qty": <int>, "reason": "<one sentence>"}},
    {{"category": "Wall Fixtures", "item": "AFFORDABLE FASTRACK 2.25W (2225×400 mm)", "recommended_qty": <int>, "reason": "<one sentence>"}},
    {{"category": "Wall Fixtures", "item": "AFFORDABLE FASTRACK 1.29W (1290×400 mm)", "recommended_qty": <int>, "reason": "<one sentence>"}},
    {{"category": "Wall Fixtures", "item": "AFFORDABLE M&W 2.25W (2225×400 mm)", "recommended_qty": <int>, "reason": "<one sentence>"}},
    {{"category": "Wall Fixtures", "item": "SUNGLASS WALL MOUNT 1.22W (1228×450 mm)", "recommended_qty": <int>, "reason": "<one sentence>"}},
    {{"category": "Wall Fixtures", "item": "SUNGLASS ANGULAR WALL 1.32W (1324×681 mm)", "recommended_qty": <int>, "reason": "<one sentence>"}},
    {{"category": "Wall Fixtures", "item": "KIDS UNIT 1.00W (1000×400 mm)", "recommended_qty": <int>, "reason": "<one sentence>"}},
    {{"category": "Floor Fixtures", "item": "DOUBLE SIDE ISLAND 2.54W (2545×1074 mm)", "recommended_qty": <int>, "reason": "<one sentence>"}},
    {{"category": "Floor Fixtures", "item": "SINGLE SIDE ISLAND 2.54W (2545×574 mm)", "recommended_qty": <int>, "reason": "<one sentence>"}},
    {{"category": "Floor Fixtures", "item": "FLATBED SUNGLASS 1.50W (1500×600 mm)", "recommended_qty": <int>, "reason": "<one sentence>"}},
    {{"category": "Floor Fixtures", "item": "TRANSACTION TABLE 0.75D (828×828 mm)", "recommended_qty": <int>, "reason": "<one sentence>"}},
    {{"category": "Cash Counter", "item": "CASH COUNTER 1.80W (1800×600 mm)", "recommended_qty": 1, "reason": "One cash counter per store in SW corner"}},
    {{"category": "Clinics", "item": "PHOROPTER CLINIC ROOM (3050×2440 mm)", "recommended_qty": <int>, "reason": "<one sentence>"}},
    {{"category": "BOH Rooms", "item": "FITTING LAB (1370×1830 mm)", "recommended_qty": <int>, "reason": "<one sentence>"}},
    {{"category": "BOH Rooms", "item": "TOILET / WASH ROOM (1500×1800 mm)", "recommended_qty": <int>, "reason": "<one sentence>"}},
    {{"category": "BOH Rooms", "item": "PANTRY (1800×1500 mm)", "recommended_qty": <int>, "reason": "<one sentence>"}},
    {{"category": "BOH Rooms", "item": "STORAGE ROOM (2000×1800 mm)", "recommended_qty": <int>, "reason": "<one sentence>"}},
    {{"category": "BOH Rooms", "item": "ELECTRICAL ROOM (1200×1000 mm)", "recommended_qty": <int>, "reason": "<one sentence>"}},
    {{"category": "BOH Rooms", "item": "FR ROOM FRANCHISEE (2400×2000 mm)", "recommended_qty": <int>, "reason": "<one sentence>"}},
    {{"category": "BOH Rooms", "item": "FITTING ROOM (1200×1200 mm)", "recommended_qty": <int>, "reason": "<one sentence>"}}
  ],
  "summary": "<2-3 sentences summarising the store capacity and key constraints>"
}}"""

    try:
        resp = client.chat.completions.create(
            model=AI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
        )
        if hasattr(resp, 'usage') and resp.usage:
            print(f"[TOKEN USAGE] get_ai_capacity_analysis  "
                  f"prompt={resp.usage.prompt_tokens}  "
                  f"completion={resp.usage.completion_tokens}  "
                  f"total={resp.usage.total_tokens}")
        text = (resp.choices[0].message.content or "").strip()

        # Parse JSON
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            start = text.find('{')
            end = text.rfind('}') + 1
            if start != -1 and end > 0:
                result = json.loads(text[start:end])
            else:
                raise ValueError(f"AI did not return valid JSON: {text[:300]!r}")

        return {
            "store_w_m": round(store_w / 1000, 2),
            "store_d_m": round(store_d / 1000, 2),
            "store_area_m2": round(store_area_m2, 1),
            "store_area_sqft": round(store_area_sqft, 0),
            "recommendations": result.get("recommendations", []),
            "summary": result.get("summary", ""),
            "raw": text,
        }
    except Exception as e:
        return {
            "store_w_m": round(store_w / 1000, 2),
            "store_d_m": round(store_d / 1000, 2),
            "store_area_m2": round(store_area_m2, 1),
            "store_area_sqft": round(store_area_sqft, 0),
            "recommendations": [],
            "summary": f"Capacity analysis unavailable: {e}",
            "raw": str(e),
        }
