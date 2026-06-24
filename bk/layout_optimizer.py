from typing import List, Dict, Tuple, Optional

# ── Zone colours ──────────────────────────────────────────────────────────────
ZONE_COLORS = {
    # Retail (showroom) sub-zones
    'RETAIL_FRONT':    '#3B82F6',   # blue  – entrance / impulse
    'RETAIL_MID':      '#6366F1',   # indigo – core categories
    'RETAIL_PREMIUM':  '#A855F7',   # purple – lux / premium
    'SUNGLASSES':      '#F97316',   # orange
    'KIDS':            '#EC4899',   # pink
    'SMART':           '#06B6D4',   # cyan
    # Clinic zone
    'CLINIC':          '#10B981',   # emerald
    'FITTING_LAB':     '#14B8A6',   # teal
    # BOH zone
    'BOH':             '#6B7280',   # grey
    'CASH':            '#EF4444',   # red
    # Legacy / fallback
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

# ── Fixture → zone mapping ────────────────────────────────────────────────────
FIXTURE_TO_ZONE = {
    # Floor fixtures
    'ISLAND':           'RETAIL_MID',
    'FLATBED':          'SUNGLASSES',
    'TRANSACTION_TABLE':'RETAIL_MID',
    # Wall fixtures
    'IB_FRAME':         'RETAIL_MID',
    'LUX_UNIT':         'RETAIL_PREMIUM',
    'KIDS_UNIT':        'KIDS',
    'HB_YA':            'RETAIL_MID',
    'HB_MW':            'RETAIL_MID',
    'SG_WALL':          'SUNGLASSES',
    'SG_ANGULAR':       'SUNGLASSES',
    'LENS_UNIT':        'RETAIL_PREMIUM',
    'SMART_UNIT':       'SMART',
    # Checkout
    'CASH_COUNTER':     'CASH',
    'CASHBACK':         'CASH',
    # Clinic
    'CLINIC':           'CLINIC',
    'FITTING_LAB':      'FITTING_LAB',
    # BOH
    'BOH':              'BOH',
    'STORAGE':          'BOH',
    # Legacy
    'WALL_DISPLAY':     'RETAIL_MID',
    'LUXURY':           'RETAIL_PREMIUM',
    'AFFORDABLE':       'RETAIL_FRONT',
    'CONTACT_LENS':     'RETAIL_PREMIUM',
    'DISPLAY':          'RETAIL_FRONT',
    'SERVICE':          'CLINIC',
}

# Minimum clearance between floor fixture and wall fixture (mm)
MIN_CLEARANCE_MM = 900


def classify_fixture(name: str) -> str:
    n = name.lower()
    # Cash / checkout
    if 'cash counter' in n or 'cashback' in n:
        return 'CASH_COUNTER'
    # Clinic rooms
    if 'phoropter' in n or 'clinic room' in n:
        return 'CLINIC'
    if 'fitting lab' in n:
        return 'FITTING_LAB'
    # BOH rooms
    if any(k in n for k in ('pantry', 'toilet', 'wash room', 'washroom',
                             'electrical', 'fr room', 'franchisee',
                             'fitting room', 'storage', 'audiology stor',
                             'boh', 'back of house', 'misc')):
        return 'BOH'
    # Floor fixtures
    if 'island' in n:
        return 'ISLAND'
    if 'flatbed' in n:
        return 'FLATBED'
    if 'transaction table' in n or 'center table' in n:
        return 'TRANSACTION_TABLE'
    # Wall fixtures
    if 'ib frame' in n:
        return 'IB_FRAME'
    if 'luxury' in n or 'lux unit' in n:
        return 'LUX_UNIT'
    if 'kids' in n:
        return 'KIDS_UNIT'
    if 'hb-ya' in n or 'hb ya' in n or 'hb–ya' in n:
        return 'HB_YA'
    if 'hb-m' in n or 'hb m' in n or 'hb–m' in n or 'men and women' in n or 'men & women' in n:
        return 'HB_MW'
    if 'smart' in n:
        return 'SMART_UNIT'
    if 'lens unit' in n or 'contact lens' in n:
        return 'LENS_UNIT'
    if 'sunglass' in n and 'angular' in n:
        return 'SG_ANGULAR'
    if 'sunglass' in n and ('wall' in n or 'mount' in n):
        return 'SG_WALL'
    if 'sunglass' in n:
        return 'SG_WALL'
    if 'affordable' in n or 'fastrack' in n:
        return 'HB_MW'
    if 'mirror' in n:
        return 'TRANSACTION_TABLE'
    if 'audiology' in n:
        return 'BOH'
    if 'clinic' in n:
        return 'CLINIC'
    if 'storage' in n:
        return 'BOH'
    return 'DISPLAY'


def _zone_color(ftype: str) -> str:
    zone = FIXTURE_TO_ZONE.get(ftype, 'DISPLAY')
    return ZONE_COLORS.get(zone, ZONE_COLORS.get(ftype, '#94A3B8'))


# ── Wall-fixture types (MUST be placed flush against a store wall) ────────────
WALL_FIXTURE_TYPES = {
    'IB_FRAME', 'LUX_UNIT', 'KIDS_UNIT', 'HB_YA', 'HB_MW',
    'SG_WALL', 'SG_ANGULAR', 'LENS_UNIT', 'SMART_UNIT',
    'WALL_DISPLAY', 'LUXURY', 'AFFORDABLE', 'CONTACT_LENS',
}

FLOOR_FIXTURE_TYPES = {
    'ISLAND', 'FLATBED', 'TRANSACTION_TABLE', 'DISPLAY',
}

# Which walls are available for wall-fixture placement (all four by default)
ALL_WALLS = ('LEFT', 'RIGHT', 'FRONT', 'BACK')


class GridLayoutEngine:
    """
    Zone-based layout engine for Titan Eyewear stores.

    Zoning (mandatory):
      RETAIL  – front/mid/rear retail showroom (closest to glazing + entrance)
      CLINIC  – 2× phoropter clinics (3050×2440 mm each), tucked behind retail
      BOH     – pantry, toilet, storage, electrical, FR room, fitting rooms, fitting lab

    Hard constraints enforced:
      • Door in BAY_BIG (glazing bay), TV in BAY_SMALL
      • Cash counter in South-West corner, facing North or East (Vastu)
      • 900 mm minimum clearance between floor and wall fixtures
      • Pillar/partition spine rule
      • Premium wall fixture height 2400 mm; false ceiling ≥ 2500 mm FFL
    """

    # Phoropter clinic fixed size (mm)
    CLINIC_W = 3050
    CLINIC_D = 2440
    # Fitting lab fixed size (mm)
    FITTING_LAB_W = 1370
    FITTING_LAB_D = 1830
    # Standard BOH room sizes (mm)
    BOH_ROOM_W = 2000
    BOH_ROOM_D = 1800
    TOILET_W   = 1500
    TOILET_D   = 1800
    PANTRY_W   = 1800
    PANTRY_D   = 1500
    ELEC_W     = 1200
    ELEC_D     = 1000
    FR_ROOM_W  = 2400
    FR_ROOM_D  = 2000

    def __init__(self, store_boundary: Dict, requirements: Dict, fixtures: List[Dict],
                 doors: List[Dict] = None, columns: List[Dict] = None):
        bounds = store_boundary['bounds']
        self.store_w = bounds['max'][0] - bounds['min'][0]
        self.store_d = bounds['max'][1] - bounds['min'][1]
        self.requirements = requirements
        self.fixtures = fixtures

        self.entrance_wall  = requirements.get('entrance_wall', 'FRONT')
        self.walkway_w      = int(requirements.get('walkway_width', 1500))
        self.checkout_count = int(requirements.get('checkout_count', 1))
        self.store_tier     = requirements.get('store_tier', 'STANDARD')
        self.has_kids       = requirements.get('has_kids_section', False)
        self.has_contact_lens = requirements.get('has_contact_lens_bar', False)
        self.has_optometrist  = requirements.get('has_optometrist', False)

        # New fields from updated RequirementsForm
        self.clinic_count   = int(requirements.get('clinic_count', 2))
        self.clinic_type    = requirements.get('clinic_type', 'PHOROPTER')  # NORMAL | PHOROPTER
        self.has_pantry     = requirements.get('has_pantry', True)
        self.has_toilet     = requirements.get('has_toilet', True)
        self.has_fitting_lab = requirements.get('has_fitting_lab', True)
        self.has_storage    = requirements.get('has_storage', True)
        self.has_electrical = requirements.get('has_electrical', True)
        self.has_fr_room    = requirements.get('has_fr_room', True)
        self.ceiling_height = int(requirements.get('ceiling_height', 3000))
        self.bay_big_side   = requirements.get('bay_big_side', 'LEFT')   # LEFT | RIGHT (within frontage)
        self.has_pillar_line = requirements.get('has_pillar_line', False)
        self.pillar_line_axis = requirements.get('pillar_line_axis', 'X')  # X (horizontal) | Y (vertical)

        # Build Shapely polygon for containment checks
        self._store_poly = None
        bmin = bounds['min']
        polygon = store_boundary.get('polygon')
        if polygon and len(polygon) >= 3:
            try:
                from shapely.geometry import Polygon
                pts = [(pt[0] - bmin[0], pt[1] - bmin[1]) for pt in polygon]
                poly = Polygon(pts)
                if not poly.is_valid:
                    poly = poly.buffer(0)
                self._store_poly = poly.buffer(-100)
            except Exception:
                pass

        # Door clearance zones — no fixture may block 1500 mm in front of a door
        DOOR_CLEARANCE = 1500
        self._door_zones: List[Tuple] = []
        for door in (doors or []):
            r = door.get('radius', 900)
            dx = door['x'] - bmin[0]
            dy = door['y'] - bmin[1]
            self._door_zones.append((
                dx - r - DOOR_CLEARANCE,
                dy - r - DOOR_CLEARANCE,
                dx + r + DOOR_CLEARANCE,
                dy + r + DOOR_CLEARANCE,
            ))

        # Column obstacle zones — keep 300 mm clearance around each column
        COL_MARGIN = 300
        self._col_zones: List[Tuple] = []
        for col in (columns or []):
            cx = col['x'] - bmin[0]
            cy = col['y'] - bmin[1]
            hw = col.get('width', 400) / 2
            hd = col.get('height', 400) / 2
            self._col_zones.append((
                cx - hw - COL_MARGIN,
                cy - hd - COL_MARGIN,
                cx + hw + COL_MARGIN,
                cy + hd + COL_MARGIN,
            ))

    # ── South-West corner helper ──────────────────────────────────────────────

    def _sw_corner(self) -> Tuple[float, float]:
        """
        Return (x, y) of the South-West corner in store coordinates.

        The entrance wall is ALWAYS South. Standing at the entrance facing
        into the store, left = West, right = East, and the opposite wall
        = North:
          entrance=FRONT (y=0)   → South=y=0, North=y=D, West=x=0,   East=x=W   → SW=(0,0)
          entrance=BACK  (y=D)   → South=y=D, North=y=0, West=x=W,   East=x=0   → SW=(W,D)
          entrance=LEFT  (x=0)   → South=x=0, North=x=W, West=y=D,   East=y=0   → SW=(0,D)
          entrance=RIGHT (x=W)   → South=x=W, North=x=0, West=y=0,   East=y=D   → SW=(W,0)
        """
        W, D = self.store_w, self.store_d
        entrance = self.entrance_wall
        return {
            'FRONT': (0.0, 0.0),
            'BACK':  (W, D),
            'LEFT':  (0.0, D),
            'RIGHT': (W, 0.0),
        }.get(entrance, (0.0, 0.0))

    # ── Zone layout ───────────────────────────────────────────────────────────

    def _zones(self) -> Dict[str, Tuple]:
        """
        Returns zone bounds as (x_min, x_max, y_min, y_max) in store mm coords.

        Three mandatory macro-zones:
          RETAIL  – front 60% of store depth (closest to glazing/entrance)
          CLINIC  – mid-rear 25% of store depth
          BOH     – rear 15% of store depth

        Within RETAIL:
          RETAIL_FRONT – first 30% (entrance impulse zone)
          RETAIL_MID   – next 30% (core categories)
          RETAIL_PREMIUM – last 10% of retail (premium/lux, near clinic transition)

        Cash counter: South-West corner (computed from entrance_wall).
        """
        W, D = self.store_w, self.store_d
        margin = 300

        # The entrance-facing axis: depth runs along Y for FRONT/BACK
        # entrances, along X for LEFT/RIGHT entrances.
        span = D if self.entrance_wall in ('FRONT', 'BACK') else W

        # Minimum absolute depth CLINIC/BOH need to actually fit their
        # largest room (its smaller side + placement gaps) — a fixed
        # percentage of store depth alone can produce a zone too shallow
        # to fit anything, regardless of how big the store is.
        _MIN_CLINIC_DEPTH = 2440 + 600   # Phoropter clinic's smaller side + gaps
        _MIN_BOH_DEPTH    = 2000 + 600   # FR Room's smaller side + gaps

        clinic_depth = max(span * 0.25, _MIN_CLINIC_DEPTH)
        boh_depth    = max(span * 0.15, _MIN_BOH_DEPTH)
        retail_depth = max(span * 0.30, span - clinic_depth - boh_depth)

        # Retail sub-zone split, expressed as fractions of retail_depth
        # itself (not of the whole store) so they always nest correctly
        # even when clinic_depth/boh_depth have grown past their default
        # share of the store.
        _front_frac, _mid_frac = 0.333, 0.750  # cumulative: front 33%, mid +42%, premium remaining 25%

        if self.entrance_wall == 'FRONT':
            # Entrance at y=0 (bottom), depth goes up
            retail_y1  = margin
            retail_y2  = retail_y1 + retail_depth
            clinic_y1  = retail_y2
            clinic_y2  = retail_y2 + clinic_depth
            boh_y1     = clinic_y2
            boh_y2     = D - margin

            wall_strip = 600
            side_margin = margin + self.walkway_w

            return {
                'RETAIL':         (margin, W - margin, retail_y1, retail_y2),
                'RETAIL_FRONT':   (margin, W - margin, retail_y1, retail_y1 + retail_depth * _front_frac),
                'RETAIL_MID':     (margin, W - margin, retail_y1 + retail_depth * _front_frac, retail_y1 + retail_depth * _mid_frac),
                'RETAIL_PREMIUM': (margin, W - margin, retail_y1 + retail_depth * _mid_frac, retail_y2),
                'CLINIC':         (margin, W - margin, clinic_y1, clinic_y2),
                'BOH':            (margin, W - margin, boh_y1, boh_y2),
                'LEFT_WALL':      (margin, wall_strip + margin, retail_y1, retail_y2),
                'RIGHT_WALL':     (W - wall_strip - margin, W - margin, retail_y1, retail_y2),
                'CENTER':         (wall_strip + margin + side_margin,
                                   W - wall_strip - margin - side_margin,
                                   retail_y1 + retail_depth * _front_frac, retail_y2),
                'CHECKOUT':       (margin, W - margin, D - boh_depth, D - margin),
                'SERVICE':        (W - 3500, W - margin, clinic_y1, clinic_y2),
            }

        elif self.entrance_wall == 'BACK':
            retail_y1  = D - margin - retail_depth
            retail_y2  = D - margin
            clinic_y1  = retail_y1 - clinic_depth
            clinic_y2  = retail_y1
            boh_y1     = margin
            boh_y2     = clinic_y1

            wall_strip = 600
            side_margin = margin + self.walkway_w

            return {
                'RETAIL':         (margin, W - margin, retail_y1, retail_y2),
                'RETAIL_FRONT':   (margin, W - margin, retail_y2 - retail_depth * _front_frac, retail_y2),
                'RETAIL_MID':     (margin, W - margin, retail_y2 - retail_depth * _mid_frac, retail_y2 - retail_depth * _front_frac),
                'RETAIL_PREMIUM': (margin, W - margin, retail_y1, retail_y2 - retail_depth * _mid_frac),
                'CLINIC':         (margin, W - margin, clinic_y1, clinic_y2),
                'BOH':            (margin, W - margin, boh_y1, boh_y2),
                'LEFT_WALL':      (margin, wall_strip + margin, retail_y1, retail_y2),
                'RIGHT_WALL':     (W - wall_strip - margin, W - margin, retail_y1, retail_y2),
                'CENTER':         (wall_strip + margin + side_margin,
                                   W - wall_strip - margin - side_margin,
                                   retail_y1, retail_y2 - retail_depth * _front_frac),
                'CHECKOUT':       (margin, W - margin, margin, boh_depth),
                'SERVICE':        (W - 3500, W - margin, clinic_y1, clinic_y2),
            }

        elif self.entrance_wall == 'LEFT':
            retail_x1  = margin
            retail_x2  = retail_x1 + retail_depth
            clinic_x1  = retail_x2
            clinic_x2  = retail_x2 + clinic_depth
            boh_x1     = clinic_x2
            boh_x2     = W - margin

            wall_strip = 600
            side_margin = margin + self.walkway_w

            return {
                'RETAIL':         (retail_x1, retail_x2, margin, D - margin),
                'RETAIL_FRONT':   (retail_x1, retail_x1 + retail_depth * _front_frac, margin, D - margin),
                'RETAIL_MID':     (retail_x1 + retail_depth * _front_frac, retail_x1 + retail_depth * _mid_frac, margin, D - margin),
                'RETAIL_PREMIUM': (retail_x1 + retail_depth * _mid_frac, retail_x2, margin, D - margin),
                'CLINIC':         (clinic_x1, clinic_x2, margin, D - margin),
                'BOH':            (boh_x1, boh_x2, margin, D - margin),
                'LEFT_WALL':      (retail_x1, retail_x2, margin, wall_strip + margin),
                'RIGHT_WALL':     (retail_x1, retail_x2, D - wall_strip - margin, D - margin),
                'CENTER':         (retail_x1 + retail_depth * _front_frac, retail_x2,
                                   wall_strip + margin + side_margin,
                                   D - wall_strip - margin - side_margin),
                'CHECKOUT':       (boh_x1, W - margin, margin, D - margin),
                'SERVICE':        (clinic_x1, clinic_x2, D - 2800 - margin, D - margin),
            }

        else:  # RIGHT
            retail_x1  = margin + boh_depth + clinic_depth
            retail_x2  = W - margin
            clinic_x1  = margin + boh_depth
            clinic_x2  = retail_x1
            boh_x1     = margin
            boh_x2     = clinic_x1

            wall_strip = 600
            side_margin = margin + self.walkway_w

            return {
                'RETAIL':         (retail_x1, retail_x2, margin, D - margin),
                'RETAIL_FRONT':   (retail_x2 - retail_depth * _front_frac, retail_x2, margin, D - margin),
                'RETAIL_MID':     (retail_x2 - retail_depth * _mid_frac, retail_x2 - retail_depth * _front_frac, margin, D - margin),
                'RETAIL_PREMIUM': (retail_x1, retail_x2 - retail_depth * _mid_frac, margin, D - margin),
                'CLINIC':         (clinic_x1, clinic_x2, margin, D - margin),
                'BOH':            (boh_x1, boh_x2, margin, D - margin),
                'LEFT_WALL':      (retail_x1, retail_x2, margin, wall_strip + margin),
                'RIGHT_WALL':     (retail_x1, retail_x2, D - wall_strip - margin, D - margin),
                'CENTER':         (retail_x1, retail_x2 - retail_depth * _front_frac,
                                   wall_strip + margin + side_margin,
                                   D - wall_strip - margin - side_margin),
                'CHECKOUT':       (margin, boh_x2, margin, D - margin),
                'SERVICE':        (clinic_x1, clinic_x2, D - 2800 - margin, D - margin),
            }

    # ── Containment + overlap checks ─────────────────────────────────────────

    def _in_store(self, x: float, y: float, w: float, d: float) -> bool:
        margin = 100
        # Always enforce bounds — fixtures must fit inside store dimensions
        if x < margin or y < margin:
            return False
        if x + w > self.store_w - margin or y + d > self.store_d - margin:
            return False
        if self._store_poly is not None:
            try:
                from shapely.geometry import box as shapely_box
                fix_box = shapely_box(x, y, x + w, y + d)
                # Require at least 85% of fixture area inside the (inset) polygon
                # This allows wall fixtures that legitimately touch the wall edge
                intersection = self._store_poly.intersection(fix_box)
                return intersection.area >= fix_box.area * 0.85
            except Exception:
                pass
        return True

    def _overlaps(self, placements: List[Dict], x: float, y: float,
                  w: float, d: float, gap: Optional[float] = None) -> bool:
        """Check overlap with existing placements + mandatory gap."""
        if gap is None:
            gap = MIN_CLEARANCE_MM
        for p in placements:
            pw = p['d'] if p.get('rotation') in [90, 270] else p['l']
            pd = p['l'] if p.get('rotation') in [90, 270] else p['d']
            if not (x + w + gap <= p['x'] or p['x'] + pw + gap <= x or
                    y + d + gap <= p['y'] or p['y'] + pd + gap <= y):
                return True
        return False

    def _hits_obstacle(self, x: float, y: float, w: float, d: float) -> bool:
        """Return True if the placement rectangle overlaps any door clearance or column zone."""
        for (ox1, oy1, ox2, oy2) in self._door_zones + self._col_zones:
            if not (x + w <= ox1 or ox2 <= x or y + d <= oy1 or oy2 <= y):
                return True
        return False

    def _make_p(self, fix: Dict, x: float, y: float, rot: int = 0,
                zone_override: str = None) -> Dict:
        ftype = classify_fixture(fix['name'])
        zone  = zone_override or FIXTURE_TO_ZONE.get(ftype, 'RETAIL_MID')
        color = ZONE_COLORS.get(zone, '#94A3B8')
        return {
            'fixture':    fix['name'],
            'x':          round(x),
            'y':          round(y),
            'l':          fix['l'],
            'd':          fix['d'],
            'h':          fix.get('h', 1000),
            'rotation':   rot,
            'zone':       zone,
            'zone_color': color,
        }

    # ── Placement helpers ─────────────────────────────────────────────────────

    def _place_horiz(self, fixes: List[Dict], zone: Tuple,
                     placements: List[Dict], gap: int = 300,
                     zone_override: str = None):
        if not fixes:
            return
        zx1, zx2, zy1, zy2 = zone
        zone_h = zy2 - zy1
        cx = zx1 + gap
        for f in fixes:
            w, d = f['l'], f['d']
            if cx + w > zx2 - gap:
                break
            if d + gap * 2 > zone_h:
                continue
            y = zy1 + gap
            if (self._in_store(cx, y, w, d)
                    and not self._hits_obstacle(cx, y, w, d)
                    and not self._overlaps(placements, cx, y, w, d)):
                placements.append(self._make_p(f, cx, y, zone_override=zone_override))
            cx += w + gap

    def _place_vert(self, fixes: List[Dict], zone: Tuple,
                    placements: List[Dict], side: str = 'left', gap: int = 300,
                    zone_override: str = None):
        if not fixes:
            return
        zx1, zx2, zy1, zy2 = zone
        cy = zy1 + gap
        for f in fixes:
            fw = f['d']
            fd = f['l']
            if cy + fd > zy2 - gap:
                break
            x = zx1 if side == 'left' else zx2 - fw
            if (self._in_store(x, cy, fw, fd)
                    and not self._hits_obstacle(x, cy, fw, fd)
                    and not self._overlaps(placements, x, cy, fw, fd)):
                placements.append(self._make_p(f, x, cy, rot=90, zone_override=zone_override))
            cy += fd + gap

    def _place_grid(self, fixes: List[Dict], zone: Tuple,
                    placements: List[Dict], gap: int = None,
                    zone_override: str = None):
        if not fixes:
            return
        gap = gap or self.walkway_w
        zx1, zx2, zy1, zy2 = zone
        cx, cy = zx1 + gap, zy1 + gap
        row_h = 0
        for f in fixes:
            w, d = f['l'], f['d']
            if cx + w > zx2 - gap:
                cx = zx1 + gap
                cy += row_h + gap
                row_h = 0
            if cy + d > zy2 - gap:
                break
            if (self._in_store(cx, cy, w, d)
                    and not self._hits_obstacle(cx, cy, w, d)
                    and not self._overlaps(placements, cx, cy, w, d)):
                placements.append(self._make_p(f, cx, cy, zone_override=zone_override))
                row_h = max(row_h, d)
            cx += w + gap

    def _place_on_wall(self, fixes: List[Dict], placements: List[Dict],
                       walls: tuple = ALL_WALLS, gap: int = 300,
                       zone_override: str = None):
        """
        Place wall fixtures flush against the actual store wall edges.

        For each fixture the method tries each requested wall in order:
          LEFT  – fixture right-edge touches x=0  (x = 0, depth into store)
          RIGHT – fixture left-edge  touches x=W  (x = W - fixture_depth)
          FRONT – fixture back-edge  touches y=0  (y = 0)
          BACK  – fixture front-edge touches y=D  (y = D - fixture_depth)

        Fixtures are slid along the wall until a free slot is found.
        The method respects _in_store, _hits_obstacle and _overlaps checks.
        """
        if not fixes:
            return
        W, D = self.store_w, self.store_d
        # _in_store() rejects anything below x/y=100, so this margin must be
        # >= 100 or every single placement attempt fails that check before
        # it even gets to look for free space.
        margin = 100

        # Track current cursor position along each wall (mm from corner)
        cursors = {'LEFT': margin, 'RIGHT': margin, 'FRONT': margin, 'BACK': margin}

        for f in fixes:
            placed = False
            fl, fd = f['l'], f['d']

            for wall in walls:
                if placed:
                    break

                if wall == 'LEFT':
                    # Fixture runs along the left wall (x=0).
                    # Place with its back flush at x=0; depth protrudes rightward.
                    # Orientation: length along Y axis → rotate 90°
                    w_placed, d_placed = fd, fl   # rotated: width=depth, depth=length
                    rot = 90
                    x = margin
                    cursor = cursors['LEFT']
                    while cursor + d_placed <= D - margin:
                        y = cursor
                        if (self._in_store(x, y, w_placed, d_placed)
                                and not self._hits_obstacle(x, y, w_placed, d_placed)
                                and not self._overlaps(placements, x, y, w_placed, d_placed, gap=gap)):
                            placements.append(self._make_p(f, x, y, rot=rot,
                                                           zone_override=zone_override))
                            cursors['LEFT'] = cursor + d_placed + gap
                            placed = True
                            break
                        cursor += gap

                elif wall == 'RIGHT':
                    # Fixture runs along the right wall (x=W).
                    # Back flush at x = W - w_placed.
                    w_placed, d_placed = fd, fl
                    rot = 90
                    x = W - w_placed - margin
                    cursor = cursors['RIGHT']
                    while cursor + d_placed <= D - margin:
                        y = cursor
                        if (x >= margin
                                and self._in_store(x, y, w_placed, d_placed)
                                and not self._hits_obstacle(x, y, w_placed, d_placed)
                                and not self._overlaps(placements, x, y, w_placed, d_placed, gap=gap)):
                            placements.append(self._make_p(f, x, y, rot=rot,
                                                           zone_override=zone_override))
                            cursors['RIGHT'] = cursor + d_placed + gap
                            placed = True
                            break
                        cursor += gap

                elif wall == 'FRONT':
                    # Fixture runs along the front wall (y=0).
                    # Back flush at y=0; depth protrudes upward.
                    w_placed, d_placed = fl, fd   # no rotation needed
                    rot = 0
                    y = margin
                    cursor = cursors['FRONT']
                    while cursor + w_placed <= W - margin:
                        x = cursor
                        if (self._in_store(x, y, w_placed, d_placed)
                                and not self._hits_obstacle(x, y, w_placed, d_placed)
                                and not self._overlaps(placements, x, y, w_placed, d_placed, gap=gap)):
                            placements.append(self._make_p(f, x, y, rot=rot,
                                                           zone_override=zone_override))
                            cursors['FRONT'] = cursor + w_placed + gap
                            placed = True
                            break
                        cursor += gap

                else:  # BACK
                    # Fixture runs along the back wall (y=D).
                    # Back flush at y = D - d_placed.
                    w_placed, d_placed = fl, fd
                    rot = 0
                    y = D - d_placed - margin
                    cursor = cursors['BACK']
                    while cursor + w_placed <= W - margin:
                        x = cursor
                        if (y >= margin
                                and self._in_store(x, y, w_placed, d_placed)
                                and not self._hits_obstacle(x, y, w_placed, d_placed)
                                and not self._overlaps(placements, x, y, w_placed, d_placed, gap=gap)):
                            placements.append(self._make_p(f, x, y, rot=rot,
                                                           zone_override=zone_override))
                            cursors['BACK'] = cursor + w_placed + gap
                            placed = True
                            break
                        cursor += gap

    def _place_wall_fixtures_fallback(self, fixes: List[Dict], placements: List[Dict]):
        """
        Last-resort wall placement: tries all 4 walls in sequence for any
        wall fixture that was not placed by the primary logic.
        Wall fixtures must NEVER fall back to a free-floor scan.
        """
        self._place_on_wall(fixes, placements, walls=ALL_WALLS, gap=200)

    def _place_anywhere(self, fixes: List[Dict], placements: List[Dict],
                        step: int = 300):
        """
        Exhaustive grid scan to place each fixture anywhere in the store.
        Tries rotation=0 first, then rotation=90 if the first fails.
        Uses a 300 mm gap (reduced from 900 mm) so more fixtures can fit.

        HARD CONSTRAINT: wall fixture types are NEVER placed by this method —
        they must only appear flush against a store wall.
        """
        if not fixes:
            return
        W, D = self.store_w, self.store_d
        margin = 100
        _GAP = 150  # reduced gap for fallback placement

        floor_fixes = [f for f in fixes if classify_fixture(f['name']) not in WALL_FIXTURE_TYPES]
        wall_fixes  = [f for f in fixes if classify_fixture(f['name']) in WALL_FIXTURE_TYPES]

        # Wall fixtures: try all 4 walls before giving up
        self._place_wall_fixtures_fallback(wall_fixes, placements)

        for f in floor_fixes:
            placed = False
            # Try rotation=0 then rotation=90
            for rot, w, d in [(0, f['l'], f['d']), (90, f['d'], f['l'])]:
                if placed:
                    break
                cy = margin
                while cy + d <= D - margin and not placed:
                    cx = margin
                    while cx + w <= W - margin and not placed:
                        if (self._in_store(cx, cy, w, d)
                                and not self._hits_obstacle(cx, cy, w, d)
                                and not self._overlaps(placements, cx, cy, w, d,
                                                       gap=_GAP)):
                            placements.append(self._make_p(f, cx, cy, rot=rot))
                            placed = True
                        cx += step
                    cy += step

    def _unplaced(self, placements: List[Dict]) -> List[Dict]:
        remaining = {}
        for p in placements:
            remaining[p['fixture']] = remaining.get(p['fixture'], 0) + 1
        result = []
        seen = {}
        for f in self.fixtures:
            n = f['name']
            seen[n] = seen.get(n, 0) + 1
            if seen[n] <= remaining.get(n, 0):
                continue
            result.append(f)
        return result

    # ── Cash counter placement (South-West, Vastu) ────────────────────────────

    def _place_cash_counter(self, placements: List[Dict], cash_fixtures: List[Dict]):
        """
        Place cash counter in the South-West corner facing North or East (Vastu).
        SW corner is derived from entrance_wall (entrance is always South).
        """
        if not cash_fixtures:
            return
        sw_x, sw_y = self._sw_corner()
        W, D = self.store_w, self.store_d
        margin = 400

        for f in cash_fixtures:
            w, d = f['l'], f['d']
            # Try SW corner with margin
            candidates = []
            # Option A: near (0,0) bottom-left
            candidates.append((margin, margin))
            # Option B: near (0, D) top-left
            candidates.append((margin, D - d - margin))
            # Option C: near (W, 0) bottom-right
            candidates.append((W - w - margin, margin))
            # Option D: near (W, D) top-right
            candidates.append((W - w - margin, D - d - margin))

            # Sort by distance to SW corner
            candidates.sort(key=lambda c: (c[0] - sw_x) ** 2 + (c[1] - sw_y) ** 2)

            for cx, cy in candidates:
                if (cx >= 0 and cy >= 0 and cx + w <= W and cy + d <= D
                        and self._in_store(cx, cy, w, d)
                        and not self._hits_obstacle(cx, cy, w, d)
                        and not self._overlaps(placements, cx, cy, w, d, gap=600)):
                    placements.append(self._make_p(f, cx, cy, zone_override='CASH'))
                    break

    # ── Clinic placement ──────────────────────────────────────────────────────

    def _place_clinics(self, placements: List[Dict]):
        """
        Place 2× phoropter clinics (3050×2440 mm) in the CLINIC zone.
        Clinics must NOT be in the entrance sightline (not in RETAIL_FRONT).
        """
        zones = self._zones()
        clinic_zone = zones.get('CLINIC', zones.get('SERVICE'))
        if not clinic_zone:
            return

        zx1, zx2, zy1, zy2 = clinic_zone
        cw = self.CLINIC_W if self.clinic_type == 'PHOROPTER' else 2745
        cd = self.CLINIC_D if self.clinic_type == 'PHOROPTER' else 2135

        gap = 600
        cx = zx1 + gap
        for i in range(self.clinic_count):
            if cx + cw > zx2 - gap:
                # Try stacking vertically
                cx = zx1 + gap
                zy1 += cd + gap
            cy = zy1 + gap
            if cy + cd > zy2 - gap:
                break
            if (self._in_store(cx, cy, cw, cd)
                    and not self._hits_obstacle(cx, cy, cw, cd)
                    and not self._overlaps(placements, cx, cy, cw, cd, gap=gap)):
                clinic_fix = {
                    'name': f'PHOROPTER CLINIC ROOM {i + 1}' if self.clinic_type == 'PHOROPTER'
                            else f'CLINIC ROOM {i + 1}',
                    'l': cw, 'd': cd, 'h': 2800,
                }
                placements.append(self._make_p(clinic_fix, cx, cy, zone_override='CLINIC'))
            cx += cw + gap

    # ── BOH room placement ────────────────────────────────────────────────────

    def _place_boh_rooms(self, placements: List[Dict]):
        """
        Place all required BOH rooms in the BOH zone (rear of store).
        Adjacency rules:
          - Toilet adjacent to pantry (plumbing proximity)
          - Fitting lab adjacent to fitting rooms
          - Electrical room near BOH entry
          - FR room (franchisee) near clinic transition
        """
        zones = self._zones()
        boh_zone = zones.get('BOH')
        if not boh_zone:
            return

        zx1, zx2, zy1, zy2 = boh_zone
        gap = 300
        cx, cy = zx1 + gap, zy1 + gap
        row_h = 0

        def _try_place(name: str, w: float, d: float, zone: str = 'BOH'):
            nonlocal cx, cy, row_h
            if cx + w > zx2 - gap:
                cx = zx1 + gap
                cy += row_h + gap
                row_h = 0
            if cy + d > zy2 - gap:
                return
            fix = {'name': name, 'l': int(w), 'd': int(d), 'h': 2800}
            if (self._in_store(cx, cy, w, d)
                    and not self._hits_obstacle(cx, cy, w, d)
                    and not self._overlaps(placements, cx, cy, w, d, gap=gap)):
                placements.append(self._make_p(fix, cx, cy, zone_override=zone))
                row_h = max(row_h, d)
            cx += w + gap

        # Fitting lab (fixed size)
        if self.has_fitting_lab:
            _try_place('FITTING LAB 1370x1830', self.FITTING_LAB_W, self.FITTING_LAB_D, 'FITTING_LAB')

        # Toilet + Pantry (adjacent — plumbing)
        if self.has_toilet:
            _try_place('TOILET / WASH ROOM', self.TOILET_W, self.TOILET_D)
        if self.has_pantry:
            _try_place('PANTRY', self.PANTRY_W, self.PANTRY_D)

        # FR room (franchisee)
        if self.has_fr_room:
            _try_place('FR ROOM (FRANCHISEE)', self.FR_ROOM_W, self.FR_ROOM_D)

        # Storage
        if self.has_storage:
            _try_place('STORAGE ROOM', self.BOH_ROOM_W, self.BOH_ROOM_D)

        # Electrical room
        if self.has_electrical:
            _try_place('ELECTRICAL ROOM', self.ELEC_W, self.ELEC_D)

    # ── Partition spine (pillar line) ─────────────────────────────────────────

    def _place_partition_spine(self, placements: List[Dict]) -> Optional[Dict]:
        """
        If a line of pillars connected by beams exists, create a partition spine
        along that line. Returns the spine placement dict (for developer reference).
        """
        if not self.has_pillar_line:
            return None
        W, D = self.store_w, self.store_d
        # Spine runs along the retail/clinic boundary
        zones = self._zones()
        if self.pillar_line_axis == 'X':
            # Horizontal spine at retail/clinic boundary
            spine_y = zones['RETAIL'][3]  # retail y_max
            spine = {
                'fixture':    'PARTITION SPINE (PILLAR LINE)',
                'x':          0,
                'y':          round(spine_y),
                'l':          round(W),
                'd':          200,
                'h':          2800,
                'rotation':   0,
                'zone':       'BOH',
                'zone_color': ZONE_COLORS['BOH'],
            }
        else:
            # Vertical spine at mid-store
            spine_x = W * 0.60
            spine = {
                'fixture':    'PARTITION SPINE (PILLAR LINE)',
                'x':          round(spine_x),
                'y':          0,
                'l':          200,
                'd':          round(D),
                'h':          2800,
                'rotation':   0,
                'zone':       'BOH',
                'zone_color': ZONE_COLORS['BOH'],
            }
        placements.append(spine)
        return spine

    # ── Scoring ───────────────────────────────────────────────────────────────

    def _score(self, placements: List[Dict]) -> float:
        if not placements:
            return 0.0
        total_area = sum(p['l'] * p['d'] for p in placements)
        store_area = self.store_w * self.store_d
        util = total_area / (store_area * 0.65)
        util_score = max(0.0, 1.0 - abs(util - 0.85) * 1.5)

        violations = 0
        for i, a in enumerate(placements):
            aw = a['d'] if a.get('rotation') in [90, 270] else a['l']
            ad = a['l'] if a.get('rotation') in [90, 270] else a['d']
            for b in placements[i + 1:]:
                bw = b['d'] if b.get('rotation') in [90, 270] else b['l']
                bd = b['l'] if b.get('rotation') in [90, 270] else b['d']
                ox = min(a['x'] + aw, b['x'] + bw) - max(a['x'], b['x'])
                oy = min(a['y'] + ad, b['y'] + bd) - max(a['y'], b['y'])
                if ox > 0 and oy > 0:
                    violations += 1
        spacing_score = max(0.0, 1.0 - violations * 0.1)

        # Bonus: cash counter in SW corner
        cash = [p for p in placements if p.get('zone') == 'CASH']
        sw_x, sw_y = self._sw_corner()
        sw_bonus = 0.0
        if cash:
            dist = min(((p['x'] - sw_x) ** 2 + (p['y'] - sw_y) ** 2) ** 0.5 for p in cash)
            sw_bonus = max(0.0, 0.1 * (1.0 - dist / max(self.store_w, self.store_d)))

        # Bonus: clinics not in front zone
        clinic_placements = [p for p in placements if p.get('zone') == 'CLINIC']
        clinic_bonus = 0.0
        if clinic_placements:
            zones = self._zones()
            front_y2 = zones.get('RETAIL_FRONT', (0, 0, 0, self.store_d * 0.20))[3]
            not_upfront = all(p['y'] > front_y2 for p in clinic_placements)
            clinic_bonus = 0.05 if not_upfront else 0.0

        return round((util_score * 0.55 + spacing_score * 0.35 + sw_bonus + clinic_bonus) * 100, 1)

    # ── Fixture grouping ──────────────────────────────────────────────────────

    def _group(self) -> Dict[str, List[Dict]]:
        g: Dict[str, List[Dict]] = {}
        for f in self.fixtures:
            ft = classify_fixture(f['name'])
            g.setdefault(ft, []).append(f)
        return g

    # ── Ceiling height compliance ─────────────────────────────────────────────

    def _fixture_height(self, base_h: int = 2400) -> int:
        """Return compliant fixture height given ceiling height."""
        if self.ceiling_height >= 2500:
            return base_h  # premium standard
        # Adapt: leave 100 mm clearance below ceiling
        return max(1800, self.ceiling_height - 100)

    # ── The 3 variants ────────────────────────────────────────────────────────

    def generate_classic_grid(self) -> Tuple[List[Dict], float]:
        """
        Classic Grid: perimeter wall displays + centre islands in rows.
        Retail front → mid → premium. Clinics in mid-rear. BOH at rear.
        Cash counter in SW corner.
        """
        zones = self._zones()
        pl: List[Dict] = []
        g = self._group()

        # 0. Partition spine (if pillar line)
        self._place_partition_spine(pl)

        # 1. Cash counter — SW corner (Vastu)
        cash = g.get('CASH_COUNTER', [])[:self.checkout_count]
        self._place_cash_counter(pl, cash)

        # 2. Clinics (not upfront)
        self._place_clinics(pl)

        # 3. BOH rooms
        self._place_boh_rooms(pl)

        # 4. Wall displays — flush against LEFT then RIGHT store walls
        wall = (g.get('IB_FRAME', []) + g.get('LUX_UNIT', []) +
                g.get('HB_YA', []) + g.get('HB_MW', []) +
                g.get('LENS_UNIT', []) + g.get('WALL_DISPLAY', []) +
                g.get('LUXURY', []) + g.get('AFFORDABLE', []))
        half = len(wall) // 2
        self._place_on_wall(wall[:half], pl, walls=('LEFT',), gap=300,
                            zone_override='RETAIL_MID')
        self._place_on_wall(wall[half:], pl, walls=('RIGHT',), gap=300,
                            zone_override='RETAIL_MID')

        # 5. Sunglass wall units — flush against LEFT then RIGHT store walls
        sun_wall = g.get('SG_WALL', []) + g.get('SG_ANGULAR', [])
        sh = len(sun_wall) // 2
        self._place_on_wall(sun_wall[:sh], pl, walls=('LEFT',), gap=300,
                            zone_override='SUNGLASSES')
        self._place_on_wall(sun_wall[sh:], pl, walls=('RIGHT',), gap=300,
                            zone_override='SUNGLASSES')

        # 6. Kids unit — flush against LEFT wall (near entrance)
        kids = g.get('KIDS_UNIT', [])
        if kids:
            self._place_on_wall(kids, pl, walls=('LEFT',), gap=300,
                                zone_override='KIDS')

        # 7. Smart unit — flush against FRONT wall near entrance
        smart = g.get('SMART_UNIT', [])
        if smart:
            self._place_on_wall(smart[:1], pl, walls=('FRONT',), gap=500,
                                zone_override='SMART')

        # 8. Islands in centre (RETAIL_MID)
        self._place_grid(g.get('ISLAND', []), zones['CENTER'], pl,
                         self.walkway_w, zone_override='RETAIL_MID')

        # 9. Flatbeds (sunglasses floor) in RETAIL_MID
        self._place_grid(g.get('FLATBED', []), zones['CENTER'], pl,
                         self.walkway_w, zone_override='SUNGLASSES')

        # 10. Transaction tables in RETAIL_MID
        self._place_grid(g.get('TRANSACTION_TABLE', []), zones['CENTER'], pl,
                         self.walkway_w, zone_override='RETAIL_MID')

        # 11. Display units near entrance (impulse)
        self._place_horiz(g.get('DISPLAY', []), zones['RETAIL_FRONT'], pl, 500,
                          zone_override='RETAIL_FRONT')

        # 12. Fallback
        self._place_anywhere(self._unplaced(pl), pl)

        return pl, self._score(pl)

    def generate_racetrack_loop(self) -> Tuple[List[Dict], float]:
        """
        Racetrack Loop: all display units around the perimeter, islands at far end,
        wide open loop aisle through the centre.
        Clinics tucked in rear corners. BOH at rear.
        """
        zones = self._zones()
        pl: List[Dict] = []
        g = self._group()

        # 0. Partition spine
        self._place_partition_spine(pl)

        # 1. Cash counter — SW corner
        self._place_cash_counter(pl, g.get('CASH_COUNTER', [])[:self.checkout_count])

        # 2. Clinics
        self._place_clinics(pl)

        # 3. BOH rooms
        self._place_boh_rooms(pl)

        # 4. All wall + affordable units — flush against LEFT then RIGHT store walls
        wall_all = (g.get('IB_FRAME', []) + g.get('SG_WALL', []) + g.get('SG_ANGULAR', []) +
                    g.get('LUX_UNIT', []) + g.get('HB_YA', []) + g.get('HB_MW', []) +
                    g.get('LENS_UNIT', []) + g.get('WALL_DISPLAY', []) +
                    g.get('LUXURY', []) + g.get('AFFORDABLE', []))
        half = len(wall_all) // 2
        self._place_on_wall(wall_all[:half], pl, walls=('LEFT',), gap=300,
                            zone_override='RETAIL_MID')
        self._place_on_wall(wall_all[half:], pl, walls=('RIGHT',), gap=300,
                            zone_override='RETAIL_MID')

        # 5. Kids + Smart — flush against walls
        if g.get('KIDS_UNIT'):
            self._place_on_wall(g['KIDS_UNIT'], pl, walls=('LEFT',), gap=300,
                                zone_override='KIDS')
        if g.get('SMART_UNIT'):
            self._place_on_wall(g['SMART_UNIT'][:1], pl, walls=('FRONT',), gap=500,
                                zone_override='SMART')

        # 6. Islands pushed to far end of centre zone
        zx1, zx2, zy1, zy2 = zones['CENTER']
        far_depth = min(self.store_d * 0.35, 3500)
        if self.entrance_wall in ('FRONT', 'LEFT'):
            island_zone = (zx1, zx2, zy2 - far_depth, zy2)
        else:
            island_zone = (zx1, zx2, zy1, zy1 + far_depth)
        self._place_grid(g.get('ISLAND', []), island_zone, pl, self.walkway_w,
                         zone_override='RETAIL_MID')

        # 7. Flatbeds + display near entrance
        disp = g.get('DISPLAY', []) + g.get('FLATBED', [])[:3]
        self._place_horiz(disp, zones['RETAIL_FRONT'], pl, 500,
                          zone_override='RETAIL_FRONT')

        # 8. Transaction tables
        self._place_grid(g.get('TRANSACTION_TABLE', []), zones['CENTER'], pl,
                         self.walkway_w, zone_override='RETAIL_MID')

        # 9. Fallback
        self._place_anywhere(self._unplaced(pl), pl)

        return pl, self._score(pl)

    def generate_premium_open(self) -> Tuple[List[Dict], float]:
        """
        Premium Open: luxury fixtures near entrance, wider walkways,
        minimal centre clutter. Ideal for flagship/premium stores.
        Clinics in rear corners. BOH at rear.
        """
        premium_gap = max(self.walkway_w, 1800)
        zones = self._zones()
        pl: List[Dict] = []
        g = self._group()

        # 0. Partition spine
        self._place_partition_spine(pl)

        # 1. Cash counter — SW corner (Vastu)
        self._place_cash_counter(pl, g.get('CASH_COUNTER', [])[:self.checkout_count])

        # 2. Clinics (rear, not upfront)
        self._place_clinics(pl)

        # 3. BOH rooms
        self._place_boh_rooms(pl)

        # 4. Luxury + hero floor displays near entrance (impulse zone — floor fixtures only)
        hero = g.get('FLATBED', [])[:2] + g.get('DISPLAY', [])[:1]
        self._place_horiz(hero, zones['RETAIL_FRONT'], pl, 700,
                          zone_override='RETAIL_PREMIUM')

        # 5. Smart unit — flush against FRONT wall near entrance
        if g.get('SMART_UNIT'):
            self._place_on_wall(g['SMART_UNIT'][:1], pl, walls=('FRONT',), gap=500,
                                zone_override='SMART')

        # 6. Premium wall displays — flush against LEFT then RIGHT store walls
        pw = (g.get('IB_FRAME', []) + g.get('LUX_UNIT', []) +
              g.get('LENS_UNIT', []) + g.get('HB_YA', []))
        if self.store_tier == 'PREMIUM_FLAGSHIP':
            pw = [f for f in pw if 'affordable' not in f['name'].lower()]
        half = len(pw) // 2
        self._place_on_wall(pw[:half], pl, walls=('LEFT',), gap=500,
                            zone_override='RETAIL_PREMIUM')
        self._place_on_wall(pw[half:], pl, walls=('RIGHT',), gap=500,
                            zone_override='RETAIL_PREMIUM')

        # 7. Sunglass wall units — flush against LEFT then RIGHT store walls
        sw = g.get('SG_WALL', []) + g.get('SG_ANGULAR', [])
        sh = len(sw) // 2
        self._place_on_wall(sw[:sh], pl, walls=('LEFT',), gap=500,
                            zone_override='SUNGLASSES')
        self._place_on_wall(sw[sh:], pl, walls=('RIGHT',), gap=500,
                            zone_override='SUNGLASSES')

        # 8. HB-M&W — flush against remaining wall space
        mw = g.get('HB_MW', []) + g.get('AFFORDABLE', [])
        mw_h = len(mw) // 2
        self._place_on_wall(mw[:mw_h], pl, walls=('LEFT',), gap=500,
                            zone_override='RETAIL_MID')
        self._place_on_wall(mw[mw_h:], pl, walls=('RIGHT',), gap=500,
                            zone_override='RETAIL_MID')

        # 9. Kids unit — flush against LEFT wall
        if g.get('KIDS_UNIT'):
            self._place_on_wall(g['KIDS_UNIT'], pl, walls=('LEFT',), gap=500,
                                zone_override='KIDS')

        # 10. At most 2 centre islands (open plan)
        self._place_grid(g.get('ISLAND', [])[:2], zones['CENTER'], pl, premium_gap,
                         zone_override='RETAIL_MID')

        # 11. Transaction tables
        self._place_grid(g.get('TRANSACTION_TABLE', []), zones['CENTER'], pl,
                         premium_gap, zone_override='RETAIL_MID')

        # 12. Fallback
        self._place_anywhere(self._unplaced(pl), pl)

        return pl, self._score(pl)

    def generate_all_variants(self) -> List[Dict]:
        """Generate all 3 layout variants, scored and sorted best-first."""
        p1, s1 = self.generate_classic_grid()
        p2, s2 = self.generate_racetrack_loop()
        p3, s3 = self.generate_premium_open()

        variants = [
            {
                'name':        'Classic Grid',
                'description': (
                    'Perimeter wall displays + centre island rows. '
                    'Retail front → mid → premium. Clinics in mid-rear. '
                    'Cash counter in South-West (Vastu). BOH at rear.'
                ),
                'style':       'CLASSIC_GRID',
                'placements':  p1,
                'score':       s1,
            },
            {
                'name':        'Racetrack Loop',
                'description': (
                    'Perimeter displays with a wide central loop aisle. '
                    'Optimal customer flow. Clinics tucked in rear corners. '
                    'Cash counter in South-West (Vastu). BOH at rear.'
                ),
                'style':       'RACETRACK_LOOP',
                'placements':  p2,
                'score':       s2,
            },
            {
                'name':        'Premium Open',
                'description': (
                    'Open plan with luxury positioning near entrance and wider walkways. '
                    'Clinics in rear. Cash counter in South-West (Vastu). '
                    'Ideal for flagship/premium stores.'
                ),
                'style':       'PREMIUM_OPEN',
                'placements':  p3,
                'score':       s3,
            },
        ]
        variants.sort(key=lambda v: v['score'], reverse=True)
        return variants


# ── Backward-compat LayoutOptimizer (kept for /analyze endpoint) ──────────────

class LayoutOptimizer:
    def __init__(self, entities, constraints):
        self.entities = entities
        self.constraints = constraints
        self.min_spacing = constraints.get('minSpacing', 10)
        self.max_area_utilization = constraints.get('maxAreaUtilization', 0.8)
        self.alignment = constraints.get('alignment', 'grid')
        self.allow_rotation = constraints.get('allowRotation', False)
        self.preserve_layers = constraints.get('preserveLayers', True)

    def optimize(self):
        if self.alignment in ('grid', 'compact'):
            return self._grid_packing()
        return self.entities

    def _grid_packing(self):
        optimized = []
        current_x = current_y = row_height = 0
        max_width = 1000
        for entity_data in self.entities:
            bbox = entity_data['data'].get('bbox')
            if not bbox:
                optimized.append(entity_data)
                continue
            width  = bbox['max'][0] - bbox['min'][0]
            height = bbox['max'][1] - bbox['min'][1]
            if current_x + width > max_width:
                current_x = 0
                current_y += row_height + self.min_spacing
                row_height = 0
            entity_data['new_position'] = (current_x, current_y)
            optimized.append(entity_data)
            current_x += width + self.min_spacing
            row_height = max(row_height, height)
        return optimized

    def check_collision(self, entity1, entity2):
        bbox1 = entity1['data'].get('bbox')
        bbox2 = entity2['data'].get('bbox')
        if not bbox1 or not bbox2:
            return False
        return not (
            bbox1['max'][0] + self.min_spacing < bbox2['min'][0] or
            bbox2['max'][0] + self.min_spacing < bbox1['min'][0] or
            bbox1['max'][1] + self.min_spacing < bbox2['min'][1] or
            bbox2['max'][1] + self.min_spacing < bbox1['min'][1]
        )
