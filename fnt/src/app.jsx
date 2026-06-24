import { useState, useRef, useCallback } from 'react';
import './app.css';
import FileUpload from './components/FileUpload';
import ConstraintSelector from './components/ConstraintSelector';
import ReferenceImageUpload from './components/ReferenceImageUpload';
import RequirementsForm from './components/RequirementsForm';
import Layout3DView from './components/Layout3DView';

// ── Fixture library (matches ConstraintSelector catalog) ─────────────────────
const FIXTURES = [
  // Islands — from DXF: double side island unit.dxf, single side island unit.dxf
  { name: 'DOUBLE SIDE ISLAND UNIT 2.54W',          l: 2545, d: 1074, h: 1104 },
  { name: 'SINGLE SIDE ISLAND UNIT 2.54W',           l: 2545, d: 581,  h: 1104 },
  // IB Frames — from DXF: ib frames unit 2.25.dxf, ib frames unit 1.29.dxf
  { name: 'IB FRAME UNIT 2.25W',                     l: 2225, d: 400,  h: 2250 },
  { name: 'IB FRAME UNIT 1.29W',                     l: 1292, d: 400,  h: 2250 },
  // Lux — from DXF: luxury unit open top 0.82.dxf, luxury unit glass top 0.82.dxf
  { name: 'LUXURY UNIT OPEN TOP 0.82W',              l: 820,  d: 400,  h: 2275 },
  { name: 'LUXURY UNIT GLASS TOP 0.82W',             l: 820,  d: 400,  h: 2275 },
  // End Portal — no DXF file, keep existing
  { name: 'END PORTAL WOOD-MIRROR',                  l: 120,  d: 95,   h: 1000 },
  // Affordable — from DXF: affodable fastrack eyewear unit 2.25.dxf, afforadable fastrack eyewaer unit 1.29.dxf
  { name: 'AFFORDABLE FASTRACK EYEWEAR UNIT 2.25W',  l: 2225, d: 400,  h: 2250 },
  { name: 'AFFORDABLE FASTRACK EYEWEAR UNIT 1.29W',  l: 1290, d: 400,  h: 2250 },
  // Affordable M&W — from DXF: affordable men and women unit 2.25.dxf, affordable men and women unit 1.29.dxf
  { name: 'AFFORDABLE MEN AND WOMEN UNIT 2.25W',     l: 2223, d: 400,  h: 2250 },
  { name: 'AFFORDABLE MEN AND WOMEN UNIT 1.29W',     l: 1290, d: 400,  h: 2250 },
  // Kids — from DXF: kids unit.dxf
  { name: 'PREM KIDS DISPLAY UNIT LGP 1.00W',        l: 1000, d: 400,  h: 2250 },
  // Contact Lens — no DXF file, keep existing
  { name: 'CONTACT LENS UNIT LAMINATE-0.6W',         l: 600,  d: 400,  h: 2250 },
  // SG Floor Mount — from DXF: sunglass floormount lhs.dxf
  { name: 'SUNGLASS UNIT - FLOOR MOUNT - 1.22W LH',  l: 1236, d: 450,  h: 2250 },
  { name: 'SUNGLASS UNIT - FLOOR MOUNT - 1.22W RH',  l: 1236, d: 450,  h: 2250 },
  // SG Wall — from DXF: sunglasses wallmount lhs.dxf, sunglasses wall mount rhs.dxf
  { name: 'SUNGLASS UNIT - WALL MOUNT - 1.22W LH',   l: 1236, d: 450,  h: 2250 },
  { name: 'SUNGLASS UNIT - WALL MOUNT - 1.22W RH',   l: 1236, d: 450,  h: 2250 },
  // SG Angular Wall — from DXF: sunglass angular unit lhs.dxf, sunglasses angular rhs.dxf
  { name: 'SUNGLASS ANGULAR UNIT -WALL MOUNT LH',    l: 1386, d: 600,  h: 2250 },
  { name: 'SUNGLASS ANGULAR UNIT -WALL MOUNT RH',    l: 1386, d: 600,  h: 2250 },
  // Transaction / center tables — from DXF: transanction table.dxf, center table.dxf
  { name: 'TRANSACTION TABLE 0.75 DIA-CORIAN',       l: 828,  d: 828,  h: 770  },
  { name: 'CENTER TABLE 0.6D',                       l: 730,  d: 730,  h: 450  },
  // Cash counters — from DXF: cash counter l shaped lhs.dxf / rhs.dxf
  { name: 'CASH COUNTER L SHAPED 2.30W',             l: 2300, d: 1000, h: 1100 },
  { name: 'CASH COUNTER 1.20W',                      l: 1200, d: 600,  h: 1100 },
  { name: 'CASH COUNTER 1.80W',                      l: 1800, d: 600,  h: 1100 },
  { name: 'CASH COUNTER L SHAPED 1.3W LH',           l: 1300, d: 1350, h: 1100 },
  { name: 'CASH COUNTER L SHAPED 1.3W RH',           l: 1300, d: 1350, h: 1100 },
  // Clinic tables — no DXF file, keep existing
  { name: 'CLINIC TRAN TABLE WOOD TOP-1.25W',        l: 1250, d: 350,  h: 740  },
  { name: 'SMALL CLINIC TABLE 0.45W',                l: 450,  d: 350,  h: 740  },
];

// ── Zone colour map (matches backend ZONE_COLORS) ─────────────────────────────
const ZONE_LABEL_MAP = {
  RETAIL_FRONT:   'Retail — Front',
  RETAIL_MID:     'Retail — Mid',
  RETAIL_PREMIUM: 'Retail — Premium',
  SUNGLASSES:     'Sunglasses',
  KIDS:           'Kids',
  SMART:          'Smart',
  CLINIC:         'Clinic',
  FITTING_LAB:    'Fitting Lab',
  BOH:            'BOH',
  CASH:           'Cash Counter',
  // legacy
  ENTRANCE:       'Entrance',
  PERIMETER:      'Perimeter',
  ISLAND:         'Island',
  CHECKOUT:       'Checkout',
  SERVICE:        'Service',
  DISPLAY:        'Display',
  CONTACT_LENS:   'Contact Lens',
  LUXURY:         'Luxury',
  STORAGE:        'Storage',
  AFFORDABLE:     'Affordable',
};

// ── sub-components ────────────────────────────────────────────────────────────

function BoundaryPreview({ boundary, columns = [], beams = [], doors = [] }) {
  if (!boundary?.polygon?.length) return null;
  const pts = boundary.polygon;
  const xs = pts.map(p => p[0]);
  const ys = pts.map(p => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const w = maxX - minX, h = maxY - minY;
  if (w === 0 || h === 0) return null;
  const SW = 500, SH = 240, pad = 20;
  const scale = Math.min((SW - pad * 2) / w, (SH - pad * 2) / h);
  const tx = x => pad + (x - minX) * scale;
  const ty = y => SH - pad - (y - minY) * scale;
  const points = pts.map(p => `${tx(p[0])},${ty(p[1])}`).join(' ');

  // Compute actual polygon area using Shoelace formula (mm²)
  const n = pts.length;
  const areaMm2 = Math.abs(pts.reduce((sum, p, i) => {
    const next = pts[(i + 1) % n];
    return sum + p[0] * next[1] - next[0] * p[1];
  }, 0)) / 2;
  const areaM2 = areaMm2 / 1_000_000;
  const areaSqft = Math.round(areaM2 * 10.7639);

  return (
    <div className="boundary-preview">
      <div className="boundary-preview-header">
        <span>Store boundary detected</span>
        <span className="boundary-dims">
          {Math.round(w).toLocaleString()} mm × {Math.round(h).toLocaleString()} mm
          &nbsp;·&nbsp; {areaM2.toFixed(1)} m²
          <span title="Gross area from DXF boundary polygon (outer wall face). Net interior area per area statement will be slightly less.">
            &nbsp;≈ {areaSqft.toLocaleString()} sq ft gross
          </span>
        </span>
      </div>
      {(columns.length > 0 || beams.length > 0 || doors.length > 0) && (
        <div className="structural-legend">
          {columns.length > 0 && <span className="legend-col">▪ {columns.length} column{columns.length !== 1 ? 's' : ''}</span>}
          {beams.length > 0 && (() => {
            const lowBeams = beams.filter(b => b.bob_height != null && b.bob_height < 2743).length;
            return (
              <span className="legend-beam">
                ▬ {beams.length} beam{beams.length !== 1 ? 's' : ''}
                {lowBeams > 0
                  ? <span className="legend-bob legend-bob-low"> · {lowBeams} below 9ft clearance</span>
                  : beams.some(b => b.bob_height != null)
                    ? <span className="legend-bob"> · all ≥9ft clearance</span>
                    : null}
              </span>
            );
          })()}
          {doors.length > 0 && <span className="legend-door">⌒ {doors.length} door{doors.length !== 1 ? 's' : ''}</span>}
        </div>
      )}
      <svg width="100%" viewBox={`0 0 ${SW} ${SH}`} className="boundary-svg">
        <polygon points={points} fill="#eef2ff" stroke="#667eea" strokeWidth="2" />
        {beams.map((b, i) => {
          const bx  = tx(b.bounds.min[0]);
          const by  = ty(b.bounds.max[1]);
          const bw  = Math.max(2, (b.bounds.max[0] - b.bounds.min[0]) * scale);
          const bh  = Math.max(2, (b.bounds.max[1] - b.bounds.min[1]) * scale);
          const bcx = bx + bw / 2;
          const bcy = by + bh / 2;
          const MIN_FIXTURE_BOB = 2743;
          const hasHeight = b.bob_height != null;
          const clearOk   = hasHeight && b.bob_height >= MIN_FIXTURE_BOB;
          const fill   = !hasHeight ? '#92400e' : clearOk ? '#166534' : '#991b1b';
          const stroke = !hasHeight ? '#78350f' : clearOk ? '#14532d' : '#7f1d1d';
          const ftIn = hasHeight ? (() => {
            const totalIn = Math.round(b.bob_height / 25.4);
            return `${Math.floor(totalIn / 12)}'${totalIn % 12}"`;
          })() : null;
          const title = hasHeight
            ? `BOB: ${ftIn} (${b.bob_height} mm) — ${clearOk ? 'OK for fixtures' : 'TOO LOW — no fixtures'}`
            : 'Beam (height unknown)';
          return (
            <g key={`beam-${i}`}>
              <rect x={bx} y={by} width={bw} height={bh}
                fill={fill} fillOpacity="0.8" stroke={stroke} strokeWidth="1">
                <title>{title}</title>
              </rect>
              {hasHeight && bw > 32 && (
                <text x={bcx} y={bcy} textAnchor="middle" dominantBaseline="middle"
                  fontSize="7" fill="#fff" fontWeight="bold" pointerEvents="none">
                  {ftIn}
                </text>
              )}
            </g>
          );
        })}
        {columns.map((c, i) => {
          if (c.shape === 'circle') {
            return (
              <circle key={`col-${i}`}
                cx={tx(c.x)} cy={ty(c.y)}
                r={Math.max(2, c.radius * scale)}
                fill="#6b7280" fillOpacity="0.8" stroke="#374151" strokeWidth="1" />
            );
          }
          const cx2 = tx(c.bounds.min[0]);
          const cy2 = ty(c.bounds.max[1]);
          const cw = Math.max(3, (c.bounds.max[0] - c.bounds.min[0]) * scale);
          const ch = Math.max(3, (c.bounds.max[1] - c.bounds.min[1]) * scale);
          return (
            <rect key={`col-${i}`} x={cx2} y={cy2} width={cw} height={ch}
              fill="#6b7280" fillOpacity="0.85" stroke="#374151" strokeWidth="1" />
          );
        })}
        {doors.map((d, i) => {
          const dcx = tx(d.x);
          const dcy = ty(d.y);
          const dr = Math.max(4, d.radius * scale);
          const startRad = (-d.start_angle * Math.PI) / 180;
          const endRad   = (-d.end_angle   * Math.PI) / 180;
          const x1 = dcx + dr * Math.cos(startRad);
          const y1 = dcy + dr * Math.sin(startRad);
          const x2 = dcx + dr * Math.cos(endRad);
          const y2 = dcy + dr * Math.sin(endRad);
          const bSign = d.bulge_sign ?? 1;
          const sweepFlag = bSign < 0 ? 1 : 0;
          let span = bSign > 0
            ? (d.end_angle - d.start_angle + 360) % 360
            : (d.start_angle - d.end_angle + 360) % 360;
          const largeArc = span > 180 ? 1 : 0;
          const pathD = `M ${dcx} ${dcy} L ${x1} ${y1} A ${dr} ${dr} 0 ${largeArc} ${sweepFlag} ${x2} ${y2} Z`;
          return (
            <path key={`door-${i}`} d={pathD}
              fill="#10b981" fillOpacity="0.25"
              stroke="#059669" strokeWidth="1.5" />
          );
        })}
      </svg>
    </div>
  );
}

function BoundaryPicker({ candidates, selectedIndex, onSelect, aiDetectedIndex, isDetecting }) {
  if (!candidates?.length) return null;
  return (
    <div className="boundary-picker">
      <div className="boundary-picker-label">
        {isDetecting
          ? <><span>AI is identifying store boundary…</span><span className="boundary-detecting-spinner" /></>
          : <span>Store boundary candidates — pick the correct outline:</span>}
        {!isDetecting && aiDetectedIndex !== null && (
          <span className="boundary-ai-badge">AI selected</span>
        )}
      </div>
      <div className="boundary-picker-list">
        {candidates.map((c, i) => (
          <button key={i}
            className={`boundary-picker-item${i === selectedIndex ? ' selected' : ''}`}
            onClick={() => onSelect(i, c)}
          >
            <span className="boundary-picker-dims">
              {c.width_mm.toLocaleString()} × {c.height_mm.toLocaleString()} mm
            </span>
            {i === aiDetectedIndex && <span className="boundary-picker-ai">AI</span>}
            {i === selectedIndex && <span className="boundary-picker-check">✓ Active</span>}
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Fixture icon decoration for 2D plan ──────────────────────────────────────
function FixtureDecoration({ name, x, y, w, h }) {
  if (w < 12 || h < 8) return null;
  const pad = 0.18;
  const ix = x + w * pad, iy = y + h * pad;
  const iw = w * (1 - 2 * pad), ih = h * (1 - 2 * pad);
  const cx = x + w / 2, cy = y + h / 2;
  const sw = Math.max(0.6, Math.min(1.4, w * 0.025));
  const s = { stroke: 'rgba(255,255,255,0.75)', strokeWidth: sw, fill: 'none' };

  const n = name.toUpperCase();

  if (n.includes('ISLAND')) {
    // Three horizontal shelf lines
    return [1, 2, 3].map(i => (
      <line key={i} x1={ix} y1={iy + ih * i / 4} x2={ix + iw} y2={iy + ih * i / 4} {...s} />
    ));
  }

  if (n.includes('TRANSACTION TABLE') || n.includes('CENTER TABLE')) {
    const r = Math.min(iw, ih) / 2 * 0.9;
    return <circle cx={cx} cy={cy} r={r} {...s} />;
  }

  if (n.includes('CASH COUNTER') && n.includes('L SHAPED')) {
    const a = 0.45;
    return (
      <path
        d={`M ${ix} ${iy} L ${ix+iw} ${iy} L ${ix+iw} ${iy+ih*a} L ${ix+iw*a} ${iy+ih*a} L ${ix+iw*a} ${iy+ih} L ${ix} ${iy+ih} Z`}
        {...s}
      />
    );
  }

  if (n.includes('CASH COUNTER')) {
    return <>
      <rect x={ix} y={iy} width={iw} height={ih * 0.55} {...s} />
      <line x1={ix} y1={iy + ih * 0.55} x2={ix + iw} y2={iy + ih * 0.55} {...s} />
    </>;
  }

  if (n.includes('SUNGLASS ANGULAR')) {
    return <>
      <line x1={ix} y1={iy + ih} x2={cx} y2={iy} {...s} />
      <line x1={cx} y1={iy} x2={ix + iw} y2={iy + ih} {...s} />
    </>;
  }

  if (n.includes('SUNGLASS')) {
    // Sunglasses: two ovals + bridge
    const ow = iw * 0.36, oh = Math.min(ih * 0.55, ow * 0.65);
    return <>
      <ellipse cx={cx - iw * 0.22} cy={cy} rx={ow / 2} ry={oh / 2} {...s} />
      <ellipse cx={cx + iw * 0.22} cy={cy} rx={ow / 2} ry={oh / 2} {...s} />
      <line x1={cx - iw * 0.22 + ow / 2} y1={cy} x2={cx + iw * 0.22 - ow / 2} y2={cy} {...s} />
    </>;
  }

  if (n.includes('LUXURY')) {
    return <>
      <rect x={ix} y={iy} width={iw} height={ih} {...s} />
      <path d={`M ${ix} ${cy} Q ${cx} ${iy} ${ix + iw} ${cy}`} {...s} />
    </>;
  }

  if (n.includes('END PORTAL')) {
    return (
      <path d={`M ${ix} ${iy+ih} L ${ix} ${iy+ih*0.35} Q ${cx} ${iy} ${ix+iw} ${iy+ih*0.35} L ${ix+iw} ${iy+ih}`} {...s} />
    );
  }

  if (n.includes('CLINIC')) {
    // Medical cross
    const arm = 0.28;
    return <>
      <line x1={cx} y1={iy} x2={cx} y2={iy + ih} {...s} />
      <line x1={ix + iw * arm} y1={cy} x2={ix + iw * (1 - arm)} y2={cy} {...s} />
    </>;
  }

  // Wall display racks (IB FRAME, AFFORDABLE, KIDS, CONTACT LENS, etc.)
  if (n.includes('IB FRAME') || n.includes('AFFORDABLE') || n.includes('KIDS') ||
      n.includes('CONTACT LENS') || n.includes('PREM KIDS')) {
    const cols = Math.max(2, Math.min(6, Math.floor(iw / 12)));
    return Array.from({ length: cols }, (_, i) => (
      <line
        key={i}
        x1={ix + iw * (i + 1) / (cols + 1)} y1={iy}
        x2={ix + iw * (i + 1) / (cols + 1)} y2={iy + ih}
        {...s}
      />
    ));
  }

  return null;
}

// ── Interactive 2D layout with drag-to-edit ────────────────────────────────────
function Layout2DEdit({ placements, setPlacements, storeBoundary, editMode,
                        columns = [], beams = [], doors = [] }) {
  const svgRef = useRef(null);
  const dragging = useRef(null);
  const [selectedIdx, setSelectedIdx] = useState(null);
  // Unique ID per mount to avoid clipPath ID collisions across re-renders
  const clipId = useRef(`sbc-${Math.random().toString(36).slice(2)}`).current;

  const SVG_W = 760, SVG_H = 500;
  const pad = 36;

  if (!placements?.length || !storeBoundary) return null;

  const bounds = storeBoundary.bounds;
  const minX = bounds.min[0], minY = bounds.min[1];
  const maxX = bounds.max[0], maxY = bounds.max[1];
  const storeW = maxX - minX, storeH = maxY - minY;
  if (storeW === 0 || storeH === 0) return null;

  const scale = Math.min((SVG_W - pad * 2) / storeW, (SVG_H - pad * 2) / storeH);
  const tx = x => pad + (x - minX) * scale;
  const ty = y => SVG_H - pad - (y - minY) * scale;

  const polygon = storeBoundary.polygon;
  const boundaryPoints = polygon?.length
    ? polygon.map(p => `${tx(p[0])},${ty(p[1])}`).join(' ')
    : null;

  // Build zone area bounding boxes from fixture positions
  const zoneAreas = (() => {
    const map = {};
    placements.forEach(p => {
      const rot = p.rotation === 90 || p.rotation === 270;
      const fw = rot ? p.d : p.l;
      const fd = rot ? p.l : p.d;
      const key = p.zone || 'UNKNOWN';
      if (!map[key]) map[key] = { color: p.zone_color || '#94a3b8', minFX: Infinity, minFY: Infinity, maxFX: -Infinity, maxFY: -Infinity };
      map[key].minFX = Math.min(map[key].minFX, p.x);
      map[key].minFY = Math.min(map[key].minFY, p.y);
      map[key].maxFX = Math.max(map[key].maxFX, p.x + fw);
      map[key].maxFY = Math.max(map[key].maxFY, p.y + fd);
    });
    return map;
  })();

  const onMouseDown = (e, idx) => {
    if (!editMode) return;
    e.preventDefault();
    const svgRect = svgRef.current.getBoundingClientRect();
    dragging.current = {
      idx,
      startSvgX: e.clientX - svgRect.left,
      startSvgY: e.clientY - svgRect.top,
      origX: placements[idx].x,
      origY: placements[idx].y,
      moved: false,
    };
  };

  const onDoubleClick = (e, idx) => {
    if (!editMode) return;
    e.preventDefault();
    e.stopPropagation();
    setPlacements(prev => prev.map((item, i) =>
      i === idx ? { ...item, rotation: ((item.rotation || 0) + 90) % 360 } : item
    ));
  };

  const onMouseMove = useCallback(e => {
    if (!dragging.current || !editMode) return;
    const svgRect = svgRef.current.getBoundingClientRect();
    const curSvgX = e.clientX - svgRect.left;
    const curSvgY = e.clientY - svgRect.top;
    const dx = curSvgX - dragging.current.startSvgX;
    const dy = curSvgY - dragging.current.startSvgY;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) dragging.current.moved = true;
    if (!dragging.current.moved) return;
    const dxMm = dx / scale;
    const dyMm = -(dy) / scale;
    const p = placements[dragging.current.idx];
    const fw = p.rotation === 90 || p.rotation === 270 ? p.d : p.l;
    const fd = p.rotation === 90 || p.rotation === 270 ? p.l : p.d;
    const newX = Math.max(0, Math.min(storeW - fw, Math.round(dragging.current.origX + dxMm)));
    const newY = Math.max(0, Math.min(storeH - fd, Math.round(dragging.current.origY + dyMm)));
    setSelectedIdx(dragging.current.idx);
    setPlacements(prev => prev.map((item, i) =>
      i === dragging.current.idx ? { ...item, x: newX, y: newY } : item
    ));
  }, [editMode, placements, scale, storeW, storeH, setPlacements]);

  const onMouseUp = (e, idx) => {
    if (dragging.current && !dragging.current.moved && idx !== undefined) {
      setSelectedIdx(prev => prev === idx ? null : idx);
    }
    dragging.current = null;
  };

  return (
    <svg
      ref={svgRef}
      width="100%" viewBox={`0 0 ${SVG_W} ${SVG_H}`}
      className={`layout-preview-svg${editMode ? ' layout-svg-edit' : ''}`}
      onMouseMove={onMouseMove}
      onMouseUp={e => onMouseUp(e, undefined)}
      onMouseLeave={e => onMouseUp(e, undefined)}
      style={{ userSelect: 'none' }}
      onClick={() => { if (!dragging.current) setSelectedIdx(null); }}
    >
      <defs>
        <clipPath id={clipId}>
          {boundaryPoints
            ? <polygon points={boundaryPoints} />
            : <rect x={tx(minX)} y={ty(maxY)} width={storeW * scale} height={storeH * scale} />
          }
        </clipPath>
      </defs>

      {/* Store boundary */}
      {boundaryPoints
        ? <polygon points={boundaryPoints} fill="#f8faff" stroke="#334155" strokeWidth="2.5" />
        : <rect x={tx(minX)} y={ty(maxY)} width={storeW * scale} height={storeH * scale}
            fill="#f8faff" stroke="#334155" strokeWidth="2.5" />
      }

      {/* Columns */}
      {columns.map((col, i) => {
        if (col.shape === 'circle') {
          return (
            <g key={`col-${i}`}>
              <circle cx={tx(col.x)} cy={ty(col.y)}
                r={Math.max(3, col.radius * scale)}
                fill="#6b7280" fillOpacity="0.85" stroke="#374151" strokeWidth="1.5" />
              <title>Column (circle) — ⌀{col.width} mm · Layer: {col.layer}</title>
            </g>
          );
        }
        const cSvgX = tx(col.bounds.min[0]);
        const cSvgY = ty(col.bounds.max[1]);
        const cSvgW = Math.max(4, (col.bounds.max[0] - col.bounds.min[0]) * scale);
        const cSvgH = Math.max(4, (col.bounds.max[1] - col.bounds.min[1]) * scale);
        return (
          <g key={`col-${i}`}>
            <rect x={cSvgX} y={cSvgY} width={cSvgW} height={cSvgH}
              fill="#6b7280" fillOpacity="0.85" stroke="#374151" strokeWidth="1.5" />
            <title>Column — {col.width}×{col.height} mm · Layer: {col.layer}</title>
          </g>
        );
      })}

      {/* Beams */}
      {beams.map((b, i) => {
        const bSvgX = tx(b.bounds.min[0]);
        const bSvgY = ty(b.bounds.max[1]);
        const bSvgW = Math.max(2, (b.bounds.max[0] - b.bounds.min[0]) * scale);
        const bSvgH = Math.max(2, (b.bounds.max[1] - b.bounds.min[1]) * scale);
        const MIN_FIXTURE_BOB = 2743;
        const hasHeight = b.bob_height != null;
        const clearOk = hasHeight && b.bob_height >= MIN_FIXTURE_BOB;
        const strokeColor = !hasHeight ? '#92400e' : clearOk ? '#16a34a' : '#dc2626';
        const ftIn = hasHeight ? (() => {
          const totalIn = Math.round(b.bob_height / 25.4);
          return `${Math.floor(totalIn / 12)}'${totalIn % 12}"`;
        })() : null;
        const title = hasHeight
          ? `Beam BOB: ${ftIn} (${b.bob_height} mm) — ${clearOk ? 'OK for fixtures' : 'TOO LOW'}`
          : 'Beam (height unknown)';
        return (
          <g key={`beam-${i}`}>
            <rect x={bSvgX} y={bSvgY} width={bSvgW} height={bSvgH}
              fill="none" stroke={strokeColor} strokeWidth="1"
              strokeDasharray="4 2" opacity="0.85" />
            <title>{title}</title>
          </g>
        );
      })}

      {/* Doors */}
      {doors.map((d, i) => {
        const dcx = tx(d.x);
        const dcy = ty(d.y);
        const dr = Math.max(4, d.radius * scale);
        const startRad = (-d.start_angle * Math.PI) / 180;
        const endRad   = (-d.end_angle   * Math.PI) / 180;
        const x1 = dcx + dr * Math.cos(startRad);
        const y1 = dcy + dr * Math.sin(startRad);
        const x2 = dcx + dr * Math.cos(endRad);
        const y2 = dcy + dr * Math.sin(endRad);
        const bSign = d.bulge_sign ?? 1;
        const sweepFlag = bSign < 0 ? 1 : 0;
        let span = bSign > 0
          ? (d.end_angle - d.start_angle + 360) % 360
          : (d.start_angle - d.end_angle + 360) % 360;
        const largeArc = span > 180 ? 1 : 0;
        const pathD = `M ${dcx} ${dcy} L ${x1} ${y1} A ${dr} ${dr} 0 ${largeArc} ${sweepFlag} ${x2} ${y2} Z`;
        return (
          <g key={`door-${i}`}>
            <path d={pathD} fill="#10b981" fillOpacity="0.2"
              stroke="#059669" strokeWidth="1.5" />
            <title>Door — r={d.radius} mm · Layer: {d.layer}</title>
          </g>
        );
      })}

      {/* Zone background shading — clipped to store polygon */}
      <g clipPath={`url(#${clipId})`}>
        {Object.entries(zoneAreas).map(([zone, za]) => {
          const zx = tx(minX + za.minFX) - 6;
          const zy = ty(minY + za.maxFY) - 6;
          const zw = (za.maxFX - za.minFX) * scale + 12;
          const zh = (za.maxFY - za.minFY) * scale + 12;
          if (zw < 4 || zh < 4) return null;
          return (
            <rect key={zone} x={zx} y={zy} width={zw} height={zh}
              fill={za.color + '15'} stroke={za.color + '55'} strokeWidth="0.75"
              strokeDasharray="5 3" rx="3" />
          );
        })}
      </g>

      {/* Fixtures — clipped to store boundary so nothing can render outside */}
      <g clipPath={`url(#${clipId})`}>
      {placements.map((p, i) => {
        const rot = p.rotation === 90 || p.rotation === 270;
        const fw = rot ? p.d : p.l;
        const fd = rot ? p.l : p.d;
        const svgX = tx(minX + p.x);
        const svgY = ty(minY + p.y + fd);
        const svgW = fw * scale;
        const svgH = fd * scale;
        const cx = tx(minX + p.x + fw / 2);
        const cy = ty(minY + p.y + fd / 2);
        const fontSize = Math.max(5, Math.min(svgW, svgH) * 0.11);
        const FIXTURE_ABBREVS = {
          'DOUBLE SIDE ISLAND UNIT': 'DBL ISLAND',
          'SINGLE SIDE ISLAND UNIT': 'SGL ISLAND',
          'IB FRAME UNIT': 'IB FRAME',
          'LUXURY UNIT OPEN TOP': 'LUX OPEN',
          'LUXURY UNIT GLASS TOP': 'LUX GLASS',
          'AFFORDABLE FASTRACK EYEWEAR UNIT': 'AFT EYEWEAR',
          'AFFORDABLE MEN AND WOMEN UNIT': 'AFW M&W',
          'PREM KIDS DISPLAY UNIT LGP': 'KIDS',
          'SUNGLASS UNIT - FLOOR MOUNT': 'SG FLOOR',
          'SUNGLASS UNIT - WALL MOUNT': 'SG WALL',
          'SUNGLASS ANGULAR UNIT -WALL MOUNT': 'SG ANGULAR',
          'TRANSACTION TABLE': 'TXN TABLE',
          'CENTER TABLE': 'CTR TABLE',
          'CASH COUNTER L SHAPED': 'CASH L',
          'CASH COUNTER': 'CASH',
          'CLINIC TRAN TABLE': 'CLINIC TBL',
          'CONTACT LENS UNIT': 'CONTACT LENS',
          'END PORTAL WOOD-MIRROR': 'END PORTAL',
        };
        const shortName = (() => {
          const upper = p.fixture.toUpperCase();
          for (const [key, abbrev] of Object.entries(FIXTURE_ABBREVS)) {
            if (upper.startsWith(key)) return abbrev;
          }
          return p.fixture.length > 16 ? p.fixture.slice(0, 14) + '…' : p.fixture;
        })();
        const color = p.zone_color || '#3B82F6';
        const isSelected = editMode && selectedIdx === i;

        return (
          <g key={i}
            style={{ cursor: editMode ? 'grab' : 'default' }}
            onMouseDown={e => { e.stopPropagation(); onMouseDown(e, i); }}
            onMouseUp={e => { e.stopPropagation(); onMouseUp(e, i); }}
            onDoubleClick={e => onDoubleClick(e, i)}
          >
            <clipPath id={`fix-clip-${i}`}>
              <rect x={svgX} y={svgY} width={svgW} height={svgH} />
            </clipPath>
            <rect x={svgX} y={svgY} width={svgW} height={svgH}
              fill={color + 'd0'} stroke={isSelected ? '#f59e0b' : color}
              strokeWidth={isSelected ? 2.5 : 1.5} rx="1" />
            {isSelected && (
              <rect x={svgX - 2} y={svgY - 2} width={svgW + 4} height={svgH + 4}
                fill="none" stroke="#f59e0b" strokeWidth="1.5" strokeDasharray="4 2" rx="2" />
            )}
            <g clipPath={`url(#fix-clip-${i})`}>
              <FixtureDecoration name={p.fixture} x={svgX} y={svgY} w={svgW} h={svgH} />
            </g>
            {svgW > 14 && svgH > 10 && (
              <text x={cx} y={cy} textAnchor="middle" dominantBaseline="middle"
                fontSize={Math.max(5, Math.min(9, Math.min(svgW, svgH) * 0.14))}
                fill="rgba(255,255,255,0.95)" fontFamily="sans-serif" fontWeight="600"
                style={{ pointerEvents: 'none' }}
                clipPath={`url(#fix-clip-${i})`}>
                {shortName}
              </text>
            )}
            {/* Rotate button for selected fixture */}
            {isSelected && (
              <g
                style={{ cursor: 'pointer' }}
                onClick={e => { e.stopPropagation(); onDoubleClick(e, i); }}
                transform={`translate(${svgX + svgW - 14}, ${svgY + 1})`}
              >
                <circle r="8" fill="#f59e0b" stroke="white" strokeWidth="1.5" />
                <text textAnchor="middle" dominantBaseline="middle" fontSize="9"
                  fill="white" fontWeight="bold">↻</text>
              </g>
            )}
          </g>
        );
      })}
      </g>

      {/* Dimension labels */}
      <text x={SVG_W / 2} y={SVG_H - 4} textAnchor="middle" fontSize="10" fill="#667eea">
        {(storeW / 1000).toFixed(2)} m wide
      </text>
      <text x={8} y={SVG_H / 2} textAnchor="middle" fontSize="10" fill="#667eea"
        transform={`rotate(-90, 8, ${SVG_H / 2})`}>
        {(storeH / 1000).toFixed(2)} m deep
      </text>
    </svg>
  );
}

// ── Zone legend ───────────────────────────────────────────────────────────────
function ZoneLegend({ placements, columns = [], beams = [], doors = [] }) {
  if (!placements?.length) return null;
  const seen = {};
  placements.forEach(p => { seen[p.zone] = p.zone_color || '#94A3B8'; });
  return (
    <div className="zone-legend">
      {Object.entries(seen).map(([zone, color]) => (
        <span key={zone} className="zone-legend-item">
          <span className="zone-dot" style={{ background: color }} />
          {ZONE_LABEL_MAP[zone] || zone.replace(/_/g, ' ')}
        </span>
      ))}
      {columns.length > 0 && (
        <span className="zone-legend-item">
          <span className="zone-dot" style={{ background: '#6b7280' }} />
          Column ({columns.length})
        </span>
      )}
      {beams.length > 0 && (
        <span className="zone-legend-item">
          <span className="zone-dot" style={{ background: '#16a34a', borderRadius: '2px' }} />
          Beam ({beams.length})
        </span>
      )}
      {doors.length > 0 && (
        <span className="zone-legend-item">
          <span className="zone-dot" style={{ background: '#10b981' }} />
          Door ({doors.length})
        </span>
      )}
    </div>
  );
}

// ── Compass overlay ────────────────────────────────────────────────────────────
// The entrance wall is always South. In the 2D/3D layout views, world Y=min
// (FRONT wall) renders at screen-bottom and Y=max (BACK) at screen-top;
// X=min (LEFT) renders at screen-left and X=max (RIGHT) at screen-right.
const WALL_TO_SCREEN_POS = { FRONT: 'bottom', BACK: 'top', LEFT: 'left', RIGHT: 'right' };

function Compass({ compass }) {
  if (!compass) return null;
  const posOf = dir => WALL_TO_SCREEN_POS[compass[dir]] || dir;
  const dirAtPos = {};
  dirAtPos[posOf('north')] = 'N';
  dirAtPos[posOf('south')] = 'S';
  dirAtPos[posOf('west')]  = 'W';
  dirAtPos[posOf('east')]  = 'E';
  return (
    <div className="compass-widget" title="Entrance is always South">
      <div className="compass-circle">
        {['top', 'bottom', 'left', 'right'].map(pos => (
          <span
            key={pos}
            className={`compass-label compass-pos-${pos}${dirAtPos[pos] === 'N' ? ' compass-is-north' : ''}`}
          >
            {dirAtPos[pos]}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── Variant tab bar ───────────────────────────────────────────────────────────
function VariantTabs({ variants, activeIdx, onSelect }) {
  if (!variants?.length) return null;
  return (
    <div className="variant-tabs">
      {variants.map((v, i) => (
        <button
          key={i}
          className={`variant-tab${i === activeIdx ? ' variant-tab-active' : ''}`}
          onClick={() => onSelect(i)}
          type="button"
        >
          <span className="variant-tab-name">{v.name}</span>
          <span className="variant-tab-score">Score {v.score}</span>
          {v.source === 'ai'
            ? <span className="variant-tab-ai-badge">AI</span>
            : <span className="variant-tab-algo-badge">Algorithm</span>}
          {i === 0 && <span className="variant-tab-best">Best</span>}
        </button>
      ))}
    </div>
  );
}

// ── AI Layout Concept panel ───────────────────────────────────────────────────
function LayoutConceptPanel({ data }) {
  if (!data) return null;

  // Object with layout_concept text (from get_ai_layout_positions)
  if (data && typeof data === 'object' && data.layout_concept) {
    return (
      <div className="ai-concept-panel">
        <div className="ai-concept-header">
          <span className="ai-badge">AI</span>
          <span className="ai-concept-title">Layout Concept</span>
        </div>
        <pre className="ai-concept-text">{data.layout_concept}</pre>
      </div>
    );
  }

  // Plain string explanation
  if (typeof data === 'string') {
    return (
      <div className="ai-explanation">
        <span className="ai-badge">AI</span>
        <p>{data}</p>
      </div>
    );
  }

  return null;
}

// ── Main App ──────────────────────────────────────────────────────────────────
function App() {
  // Upload step
  const [fileId, setFileId]                     = useState(null);
  const [metadata, setMetadata]                 = useState(null);
  const [boundary, setBoundary]                 = useState(null);
  const [boundaryCandidates, setBoundaryCandidates] = useState([]);
  const [boundaryIndex, setBoundaryIndex]       = useState(0);
  const [columns, setColumns]                   = useState([]);
  const [beams, setBeams]                       = useState([]);
  const [doors, setDoors]                       = useState([]);
  const [referenceFileId, setReferenceFileId]   = useState(null);
  const [referenceFileExt, setReferenceFileExt] = useState(null);
  const [isDetectingBoundary, setIsDetectingBoundary] = useState(false);
  const [aiDetectedIndex, setAiDetectedIndex]   = useState(null);

  // Requirements step
  const [requirements, setRequirements] = useState(null);

  // Fixture selection
  const [constraints, setConstraints] = useState({
    minSpacing: 900, maxAreaUtilization: 0.8,
    alignment: 'grid', allowRotation: false,
    preserveLayers: true, selectedFixtures: [],
    fixtureQuantities: {},
  });

  // Generation + results
  const [isGenerating, setIsGenerating]   = useState(false);
  const [statusMessage, setStatusMessage] = useState('');
  const [layoutVariants, setLayoutVariants] = useState([]);
  const [activeVariant, setActiveVariant] = useState(0);
  const [storeBoundary, setStoreBoundary] = useState(null);
  const [compass, setCompass] = useState(null);
  const [aiExplanation, setAiExplanation] = useState('');
  const [aiLayoutConcept, setAiLayoutConcept] = useState(null);
  const [skippedFixtures, setSkippedFixtures] = useState([]);

  // Capacity analysis (after upload)
  const [capacityAnalysis, setCapacityAnalysis] = useState(null);
  const [isAnalysing, setIsAnalysing] = useState(false);

  // Editable placements (current variant)
  const [placements, setPlacements] = useState([]);

  // View mode
  const [viewMode, setViewMode] = useState('2d');
  const [editMode, setEditMode] = useState(false);

  // ── Boundary detection ──────────────────────────────────────────────────────
  const runAiBoundaryDetect = async (fId, refId, refExt, candidates) => {
    if (!fId || !refId || !refExt || !candidates?.length) return;
    setIsDetectingBoundary(true);
    try {
      const res = await fetch('http://localhost:5000/detect-boundary', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_id: fId, reference_file_id: refId, reference_file_ext: refExt }),
      });
      if (res.ok) {
        const data = await res.json();
        setAiDetectedIndex(data.boundary_index);
        setBoundaryIndex(data.boundary_index);
        setBoundary(candidates[data.boundary_index]);
      }
    } catch (_) { /* silent */ }
    finally { setIsDetectingBoundary(false); }
  };

  const handleFileUpload = (uploadData) => {
    const fid = uploadData.file_id;
    setFileId(fid);
    setMetadata(uploadData.metadata);
    const cands = uploadData.boundary_candidates || [];
    setBoundaryCandidates(cands);
    setBoundaryIndex(0);
    setAiDetectedIndex(null);
    setBoundary(cands[0] || uploadData.boundary || null);
    setColumns(uploadData.columns || []);
    setBeams(uploadData.beams || []);
    setDoors(uploadData.doors || []);
    setStatusMessage('');
    setLayoutVariants([]);
    setPlacements([]);
    setAiLayoutConcept(null);
    setCapacityAnalysis(null);
    if (referenceFileId && referenceFileExt && cands.length > 1) {
      runAiBoundaryDetect(fid, referenceFileId, referenceFileExt, cands);
    }
    // Trigger AI capacity analysis in background
    setIsAnalysing(true);
    fetch(`http://localhost:5000/capacity-analysis/${fid}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setCapacityAnalysis(data); })
      .catch(() => {})
      .finally(() => setIsAnalysing(false));
  };

  const handleReferenceUpload = (data) => {
    setReferenceFileId(data.reference_file_id);
    setReferenceFileExt(data.reference_file_ext);
    if (fileId && boundaryCandidates.length > 1) {
      runAiBoundaryDetect(fileId, data.reference_file_id, data.reference_file_ext, boundaryCandidates);
    }
  };

  // ── Switch variant ──────────────────────────────────────────────────────────
  const switchVariant = (idx) => {
    setActiveVariant(idx);
    setPlacements([...(layoutVariants[idx]?.placements || [])]);
    setEditMode(false);
  };

  // ── Generate layouts ────────────────────────────────────────────────────────
  const handleGenerateLayout = async () => {
    if (!fileId || !constraints.selectedFixtures?.length || !requirements) return;
    setIsGenerating(true);
    setLayoutVariants([]);
    setPlacements([]);
    setAiLayoutConcept(null);
    setSkippedFixtures([]);
    setStatusMessage('Generating AI layout…');
    setEditMode(false);

    const selectedWithDims = constraints.selectedFixtures.flatMap(name => {
      const fixture = FIXTURES.find(f => f.name === name);
      if (!fixture) return [];
      const qty = (constraints.fixtureQuantities || {})[name] || 1;
      return Array(qty).fill(fixture);
    });

    try {
      const controller = new AbortController();
      const tid = setTimeout(() => controller.abort(), 240000);

      const res = await fetch('http://localhost:5000/ai-layout-dxf', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file_id: fileId,
          requirements,
          constraints,
          selected_fixtures: selectedWithDims,
          boundary_index: boundaryIndex,
          reference_file_id: referenceFileId,
          reference_file_ext: referenceFileExt,
        }),
        signal: controller.signal,
      });
      clearTimeout(tid);

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `Server error ${res.status}`);
      }

      const data = await res.json();
      if (data.ai_placement_error) {
        console.warn('[AI placement error]', data.ai_placement_error);
        if (data.ai_placement_traceback) console.warn(data.ai_placement_traceback);
      }
      if (data.ai_fixtures_removed) {
        console.warn(`[AI layout] ${data.ai_fixtures_removed} fixture(s) were outside the store boundary and removed.`);
      }
      setLayoutVariants(data.variants || []);
      setStoreBoundary(data.store_boundary);
      setCompass(data.compass || null);
      if (data.entrance_wall) {
        setRequirements(r => r ? { ...r, entrance_wall: data.entrance_wall } : r);
      }
      setAiExplanation(data.ai_explanation || '');
      setAiLayoutConcept(data.ai_layout_concept || null);
      setSkippedFixtures(data.skipped_fixtures || []);
      setActiveVariant(0);
      setPlacements([...(data.variants?.[0]?.placements || [])]);
      const count = data.variants?.[0]?.placements?.length || 0;
      const skippedCount = (data.skipped_fixtures || []).length;
      const aiCount = (data.variants || []).filter(v => v.source === 'ai').length;
      const srcMsg = aiCount > 0 ? 'AI-generated layout.' : 'AI unavailable — algorithm used as fallback.';
      const removedMsg = data.ai_fixtures_removed ? ` ⚠ ${data.ai_fixtures_removed} fixture(s) were outside boundary and auto-removed.` : '';
      const skippedMsg = skippedCount > 0 ? ` ⚠ ${skippedCount} fixture(s) could not be placed — see below.` : '';
      setStatusMessage(`${count} fixtures placed. ${srcMsg}${removedMsg}${skippedMsg}`);
    } catch (err) {
      setStatusMessage('Error: ' + err.message);
    } finally {
      setIsGenerating(false);
    }
  };

  // ── Save edited layout ──────────────────────────────────────────────────────
  const saveEditedLayout = async () => {
    if (!fileId || !placements.length) return;
    await fetch('http://localhost:5000/render-edited-layout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_id: fileId, placements, store_boundary: storeBoundary }),
    }).catch(() => {});
  };

  // ── Download DXF ────────────────────────────────────────────────────────────
  const handleDownloadDxf = async () => {
    if (!fileId) return;
    let url;
    if (editMode) {
      await saveEditedLayout();
      url = `http://localhost:5000/download-ai-layout/${fileId}?edited=1`;
    } else {
      url = `http://localhost:5000/download-ai-layout/${fileId}?variant=${activeVariant}`;
    }
    const res = await fetch(url);
    if (!res.ok) { setStatusMessage('Download failed'); return; }
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = editMode ? 'titan_layout_edited.dxf' : `titan_layout_v${activeVariant + 1}.dxf`;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
  };

  // ── Download PDF ────────────────────────────────────────────────────────────
  const handleDownloadPdf = async () => {
    if (!fileId || !placements.length) return;
    setStatusMessage('Generating PDF…');
    const variantName = layoutVariants[activeVariant]?.name || 'Store Layout';
    const res = await fetch('http://localhost:5000/generate-pdf', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        file_id: fileId, placements, store_boundary: storeBoundary,
        requirements, variant_name: variantName,
      }),
    });
    if (!res.ok) { setStatusMessage('PDF generation failed'); return; }
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'titan_store_layout.pdf';
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
    setStatusMessage('PDF downloaded.');
  };

  const canGenerate = fileId && requirements && constraints.selectedFixtures?.length > 0 && !isGenerating;
  const hasLayout   = layoutVariants.length > 0 && placements.length > 0;

  return (
    <div className="App">
      <header className="app-header">
        <div className="app-header-logo">
          <span className="logo-t">T</span>itan Eyewear
        </div>
        <h1>Store Layout Designer</h1>
        <p>Upload your floor plan, set requirements, and generate CAD-ready layouts in seconds</p>
      </header>

      <main className="app-main">
        <div className="workflow-container">

          {/* ── Step 1: Upload ─────────────────────────────────────────────── */}
          <section className="step-section">
            <h2>Step 1 — Upload Store Plan</h2>
            <div className="upload-zones">
              <div className="upload-zone-wrapper">
                <div className="zone-label">
                  <span>DXF File</span>
                  <span className="zone-badge zone-badge-required">Required</span>
                </div>
                <FileUpload onUploadSuccess={handleFileUpload} />
                <p className="hint-text">Provides exact wall boundaries and dimensions</p>
              </div>
              {/* <div className="upload-zone-wrapper">
                <div className="zone-label">
                  <span>Reference Image</span>
                  <span className="zone-badge zone-badge-optional">Recommended</span>
                </div>
                <ReferenceImageUpload
                  onUploadSuccess={handleReferenceUpload}
                  onRemove={() => { setReferenceFileId(null); setReferenceFileExt(null); }}
                />
                <p className="hint-text">Helps AI identify entrance, glazing bays &amp; high-traffic zones</p>
              </div> */}
            </div>

            {boundary && <BoundaryPreview boundary={boundary} columns={columns} beams={beams} doors={doors} />}
            {boundaryCandidates.length > 0 && (
              <BoundaryPicker
                candidates={boundaryCandidates}
                selectedIndex={boundaryIndex}
                onSelect={(i, c) => { setBoundaryIndex(i); setBoundary(c); }}
                aiDetectedIndex={aiDetectedIndex}
                isDetecting={isDetectingBoundary}
              />
            )}

            {/* ── AI Capacity Analysis ──────────────────────────────────── */}
            {/* {isAnalysing && (
              <div className="capacity-analysing">
                <span className="btn-spinner" style={{ borderTopColor: '#667eea', borderColor: 'rgba(102,126,234,0.3)' }} />
                <span>AI is analysing store capacity…</span>
              </div>
            )} */}
            {/* {capacityAnalysis && !isAnalysing && (
              <div className="capacity-panel">
                <div className="capacity-header">
                  <span className="ai-badge">AI</span>
                  <span className="capacity-title">Store Capacity Analysis</span>
                  <span className="capacity-dims">
                    {capacityAnalysis.store_w_m} m × {capacityAnalysis.store_d_m} m
                    &nbsp;·&nbsp; {capacityAnalysis.store_area_m2} m²
                    {capacityAnalysis.store_area_sqft
                      ? <span title="Gross area from DXF polygon. Net interior area per area statement will be slightly less.">
                          &nbsp;≈ {capacityAnalysis.store_area_sqft.toLocaleString()} sq ft gross
                        </span>
                      : null}
                  </span>
                </div>
                {capacityAnalysis.summary && (
                  <p className="capacity-summary">{capacityAnalysis.summary}</p>
                )}
                {(() => {
                  const cats = {};
                  (capacityAnalysis.recommendations || []).forEach(r => {
                    if (!cats[r.category]) cats[r.category] = [];
                    cats[r.category].push(r);
                  });
                  return Object.entries(cats).map(([cat, items]) => (
                    <div key={cat} className="capacity-category">
                      <div className="capacity-cat-label">{cat}</div>
                      <div className="capacity-items">
                        {items.map((r, i) => (
                          <div key={i} className="capacity-item">
                            <span className="capacity-qty">{r.recommended_qty}×</span>
                            <span className="capacity-item-name">{r.item}</span>
                            <span className="capacity-item-reason">{r.reason}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ));
                })()}
              </div> */}
            {/* )} */}
          </section>

          {/* ── Step 2: Requirements ───────────────────────────────────────── */}
          <section className="step-section">
            <h2>Step 2 — Store Requirements</h2>
            {/* <p className="hint-text" style={{ marginBottom: '1rem' }}>
              Set glazing bays, north direction, clinic count, BOH rooms, and structural info
              so the layout engine can apply all Vastu + zoning constraints correctly.
            </p> */}
            <RequirementsForm
              onComplete={setRequirements}
              disabled={!fileId}
            />
          </section>

          {/* ── Step 3: Select Fixtures ────────────────────────────────────── */}
          <section className="step-section">
            <h2>Step 3 — Select Fixtures</h2>
            {/* <p className="hint-text" style={{ marginBottom: '0.5rem' }}>
              Choose fixtures from the catalog. Grouped by type — use "Select all" per group for speed.
              Minimum 900 mm clearance is enforced automatically.
            </p> */}
            <ConstraintSelector
              constraints={constraints}
              onChange={setConstraints}
              disabled={!fileId || !requirements}
            />
          </section>

          {/* ── Step 4: Generate ───────────────────────────────────────────── */}
          <section className="step-section">
            <h2>Step 4 — Generate Layout</h2>

            <button
              className="ai-suggest-btn"
              onClick={handleGenerateLayout}
              disabled={!canGenerate}
            >
              {isGenerating
                ? <><span className="btn-spinner" /> Generating layout…</>
                : 'Generate Layout'}
            </button>

            {!requirements && fileId && (
              <p className="hint-text warn-text">Complete Step 2 (Requirements) first.</p>
            )}
            {requirements && !constraints.selectedFixtures?.length && fileId && (
              <p className="hint-text warn-text">Select at least one fixture in Step 3 to continue.</p>
            )}
            {statusMessage && (
              <p className={`status-msg${statusMessage.startsWith('Error') ? ' status-msg-error' : ''}`}>{statusMessage}</p>
            )}
            {isGenerating && (
              <div className="generating-progress">
                <div className="generating-bar" />
                <span className="generating-label">AI is designing your store layout — this takes 30–60 seconds…</span>
              </div>
            )}

            {/* AI Layout Concept (structured 10-section output) */}
            {aiLayoutConcept && (
              <LayoutConceptPanel data={aiLayoutConcept} />
            )}

            {/* Variant tabs */}
            {hasLayout && (
              <>
                <VariantTabs
                  variants={layoutVariants}
                  activeIdx={activeVariant}
                  onSelect={switchVariant}
                />

                {/* <p className="variant-desc">
                  {layoutVariants[activeVariant]?.description}
                </p> */}

                {/* Placement source indicator */}
                {/* <div className="variant-source-row">
                  {layoutVariants[activeVariant]?.source === 'ai' ? (
                    <span className="variant-source-ai">
                      <span className="variant-source-dot ai-dot" />
                      Placed by GPT AI — all fixture positions are AI-recommended
                    </span>
                  ) : (
                    <span className="variant-source-algo">
                      <span className="variant-source-dot algo-dot" />
                      Placed by algorithm (AI unavailable for this variant)
                    </span>
                  )}
                </div> */}

                {/* AI explanation */}
                {/* {aiExplanation && (
                  <div className="ai-explanation">
                    <span className="ai-badge">AI</span>
                    <p>{aiExplanation}</p>
                  </div>
                )} */}

                {/* View mode toggle */}
                <div className="view-controls">
                  <div className="view-toggle-group">
                    <button
                      className={`view-toggle-btn${viewMode === '2d' ? ' active' : ''}`}
                      onClick={() => setViewMode('2d')}
                      type="button"
                    >2D View</button>
                    <button
                      className={`view-toggle-btn${viewMode === '3d' ? ' active' : ''}`}
                      onClick={() => setViewMode('3d')}
                      type="button"
                    >3D View</button>
                  </div>
                  {viewMode === '2d' && (
                    <button
                      className={`edit-toggle-btn${editMode ? ' edit-active' : ''}`}
                      onClick={() => setEditMode(v => !v)}
                      type="button"
                    >
                      {editMode ? 'Done Editing' : 'Edit Fixtures'}
                    </button>
                  )}
                </div>

                {editMode && viewMode === '2d' && (
                  <p className="hint-text" style={{ color: '#e67e22', marginBottom: '8px' }}>
                    <strong>Drag</strong> to move · <strong>Click</strong> to select · <strong>↻ button</strong> or <strong>double-click</strong> to rotate 90°
                  </p>
                )}

                <ZoneLegend placements={placements} columns={columns} beams={beams} doors={doors} />

                <div className="layout-view-wrapper">
                  <Compass compass={compass} />
                  {viewMode === '2d'
                    ? <Layout2DEdit
                        placements={placements}
                        setPlacements={setPlacements}
                        storeBoundary={storeBoundary}
                        editMode={editMode}
                        columns={columns}
                        beams={beams}
                        doors={doors}
                      />
                    : <Layout3DView
                        placements={placements}
                        storeBoundary={storeBoundary}
                      />
                  }
                </div>

                <p className="fixture-count">
                  {placements.length} fixtures placed
                  {skippedFixtures.length > 0 && (
                    <span className="skipped-count"> · {skippedFixtures.length} could not be placed</span>
                  )}
                </p>

                {skippedFixtures.length > 0 && (
                  <div className="skipped-fixtures-panel">
                    <div className="skipped-fixtures-header">
                      <span className="skipped-icon">⚠</span>
                      <span className="skipped-title">
                        {skippedFixtures.length} fixture{skippedFixtures.length !== 1 ? 's' : ''} could not be placed
                      </span>
                      <span className="skipped-subtitle">— store may be too small or too many fixtures selected</span>
                    </div>
                    <ul className="skipped-fixtures-list">
                      {skippedFixtures.map((s, i) => (
                        <li key={i} className="skipped-fixture-item">
                          <span className="skipped-fixture-name">{s.fixture}</span>
                          <span className="skipped-fixture-size">{s.size_mm}</span>
                          <span className="skipped-fixture-reason">{s.reason}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="download-btn-row">
                  <button className="download-dxf-btn" onClick={handleDownloadDxf}>
                    <svg viewBox="0 0 24 24" width="16" height="16">
                      <path fill="currentColor" d="M5 20h14v-2H5m14-9h-4V3H9v6H5l7 7 7-7z"/>
                    </svg>
                    Download DXF{editMode ? ' (Edited)' : ''}
                  </button>
                  <button className="download-pdf-btn" onClick={handleDownloadPdf}>
                    <svg viewBox="0 0 24 24" width="16" height="16">
                      <path fill="currentColor" d="M20 2H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-8.5 7.5c0 .83-.67 1.5-1.5 1.5H9v2H7.5V7H10c.83 0 1.5.67 1.5 1.5v1zm5 2c0 .83-.67 1.5-1.5 1.5h-2.5V7H15c.83 0 1.5.67 1.5 1.5v3zm4-3H19v1h1.5V11H19v2h-1.5V7H20.5v1.5zM9 9.5h1v-1H9v1zM4 6H2v14c0 1.1.9 2 2 2h14v-2H4V6zm10 5.5h1v-3h-1v3z"/>
                    </svg>
                    Download PDF
                  </button>
                </div>
              </>
            )}
          </section>

        </div>
      </main>
    </div>
  );
}

export default App;
