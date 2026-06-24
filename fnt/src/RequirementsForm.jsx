import { useState } from 'react';

const TIER_OPTIONS = [
  { value: 'STANDARD',  label: 'Standard',  desc: 'Balanced display + service area' },
  { value: 'MID PREMIUM',   label: 'Mid Premium',   desc: 'Open plan, luxury first' },
  { value: 'PREMIUM',  label: 'Premium',  desc: 'Maximise fixtures, premium experience' },
];

const WALKWAY_OPTIONS = [
  { value: 1200, label: '900mm', desc: 'Compact — small stores' },
  { value: 1500, label: '1050mm', desc: 'Standard — recommended' },
  { value: 1800, label: '1200mm', desc: 'Spacious — premium / accessible' },
];


const CLINIC_TYPE_OPTIONS = [
  { value: 'PHOROPTER', label: 'Phoropter Clinic', desc: '3050 × 2440 mm — full refraction room' },
  { value: 'NORMAL',    label: 'Normal Clinic',    desc: '2745 × 2135 mm — standard exam room' },
];

const CEILING_OPTIONS = [
  { value: 2700, label: '2.7 m', desc: 'Low — adapt fixture heights' },
  { value: 3000, label: '3.0 m', desc: 'Standard — premium fixtures OK' },
  { value: 3300, label: '3.3 m', desc: 'High — full premium height' },
  { value: 3600, label: '3.6 m', desc: 'Very high — feature ceiling possible' },
];

const DEFAULT = {
  branch_name:        '',
  store_tier:         'PREMIUM',
  walkway_width:      1500,
  checkout_count:     1,
  // Glazing + orientation
  north_direction:    'FRONT',
  bay_big_side:       'LEFT',
  // Clinic
  clinic_count:       2,
  clinic_type:        'PHOROPTER',   // legacy fallback (all same type)
  clinic_types:       ['PHOROPTER', 'PHOROPTER'],  // per-clinic type array
  // BOH inclusions
  has_pantry:         true,
  has_toilet:         true,
  has_fitting_lab:    true,
  has_storage:        true,
  has_electrical:     true,
  has_fr_room:        true,
  has_fitting_rooms:  true,
  // Structural
  ceiling_height:     3000,
  has_pillar_line:    false,
  pillar_line_axis:   'X',
  // Legacy (kept for backward compat)
  entrance_wall:      'FRONT',
  has_kids_section:   false,
  has_contact_lens_bar: false,
  has_optometrist:    false,
};

function RequirementsForm({ onComplete, disabled }) {
  const [req, setReq]         = useState(DEFAULT);
  const [confirmed, setConfirmed] = useState(false);
  const [editing, setEditing]     = useState(false);

  const set = (key, val) => setReq(r => ({ ...r, [key]: val }));

  const handleConfirm = () => {
    // Sync entrance_wall with north_direction for backward compat
    const updated = { ...req, entrance_wall: req.north_direction };
    setReq(updated);
    setConfirmed(true);
    setEditing(false);
    onComplete(updated);
  };

  // ── Summary card ──────────────────────────────────────────────────────────
  if (confirmed && !editing) {
    const tierLabel   = TIER_OPTIONS.find(t => t.value === req.store_tier)?.label;
    const clinicTypes = req.clinic_types || Array(req.clinic_count).fill(req.clinic_type || 'PHOROPTER');
    const clinicSummary = clinicTypes.map((t, i) => {
      const label = CLINIC_TYPE_OPTIONS.find(c => c.value === t)?.label || t;
      return req.clinic_count > 1 ? `Clinic ${i+1}: ${label}` : label;
    }).join(' · ');
 

    const bohItems = [
      req.has_pantry        && 'Pantry',
      req.has_toilet        && 'Toilet',
      req.has_fitting_lab   && 'Fitting Lab',
      req.has_storage       && 'Storage',
      req.has_electrical    && 'Electrical Room',
      req.has_fr_room       && 'FR Room',
      req.has_fitting_rooms && 'Fitting Rooms',
    ].filter(Boolean);

    return (
      <div className="req-summary">
        <div className="req-summary-header">
          <span className="req-summary-badge">Requirements confirmed</span>
          <button className="req-edit-btn" onClick={() => setEditing(true)}>Edit</button>
        </div>
        <div className="req-summary-grid">
          {req.branch_name && (
            <div className="req-summary-item">
              <span className="req-summary-label">Branch</span>
              <span className="req-summary-val">{req.branch_name}</span>
            </div>
          )}
          <div className="req-summary-item">
            <span className="req-summary-label">Store type</span>
            <span className="req-summary-val">{tierLabel}</span>
          </div>
          <div className="req-summary-item">
            <span className="req-summary-label">Walkway</span>
            <span className="req-summary-val">{req.walkway_width / 1000} m</span>
          </div>
          
          <div className="req-summary-item">
            <span className="req-summary-label">Clinics</span>
            <span className="req-summary-val">{req.clinic_count}× — {clinicSummary}</span>
          </div>
          <div className="req-summary-item">
            <span className="req-summary-label">Ceiling</span>
            <span className="req-summary-val">{req.ceiling_height / 1000} m</span>
          </div>
          <div className="req-summary-item">
            <span className="req-summary-label">BOH rooms</span>
            <span className="req-summary-val">{bohItems.length ? bohItems.join(', ') : 'None'}</span>
          </div>
          {req.has_pillar_line && (
            <div className="req-summary-item">
              <span className="req-summary-label">Pillar line</span>
              <span className="req-summary-val">{req.pillar_line_axis}-axis → partition spine</span>
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── Form ──────────────────────────────────────────────────────────────────
  return (
    <div className={`req-form${disabled ? ' req-form-disabled' : ''}`}>

      {/* Branch name */}
      <div className="req-field">
        <label className="req-label">
          Branch name <span className="req-optional">(optional)</span>
        </label>
        <input
          className="req-input"
          type="text"
          placeholder="e.g. Titan Marine Drive, Raipur"
          value={req.branch_name}
          onChange={e => set('branch_name', e.target.value)}
          disabled={disabled}
        />
      </div>

      {/* Store tier */}
      <div className="req-field">
        <label className="req-label">Store type</label>
        <div className="req-options-3">
          {TIER_OPTIONS.map(opt => (
            <button
              key={opt.value}
              className={`req-card req-card-wide${req.store_tier === opt.value ? ' req-card-active' : ''}`}
              onClick={() => set('store_tier', opt.value)}
              disabled={disabled}
              type="button"
            >
              <span className="req-card-label">{opt.label}</span>
              <span className="req-card-desc">{opt.desc}</span>
            </button>
          ))}
        </div>
      </div>
      {/* ── Walkway + Checkouts ───────────────────────────────────────────── */}
      <div className="req-section-divider">Walkway</div>

      {/* Walkway width */}
      <div className="req-field">
        <label className="req-label">Minimum walkway width</label>
        <div className="req-options-3">
          {WALKWAY_OPTIONS.map(opt => (
            <button
              key={opt.value}
              className={`req-card req-card-wide${req.walkway_width === opt.value ? ' req-card-active' : ''}`}
              onClick={() => set('walkway_width', opt.value)}
              disabled={disabled}
              type="button"
            >
              <span className="req-card-label">{opt.label}</span>
              <span className="req-card-desc">{opt.desc}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Checkout count */}
  

      {/* ── Clinics ───────────────────────────────────────────────────────── */}
      <div className="req-section-divider">Clinics</div>

      {/* Clinic count */}
      <div className="req-field">
        <label className="req-label">Number of clinic rooms</label>
        <div className="req-counter-row">
          {[1, 2, 3].map(n => (
            <button
              key={n}
              className={`req-counter-btn${req.clinic_count === n ? ' req-card-active' : ''}`}
              onClick={() => {
                // Resize clinic_types array to match new count
                const currentTypes = req.clinic_types || [];
                const newTypes = Array.from({ length: n }, (_, i) =>
                  currentTypes[i] || 'PHOROPTER'
                );
                setReq(r => ({ ...r, clinic_count: n, clinic_types: newTypes,
                  clinic_type: newTypes[0] }));
              }}
              disabled={disabled}
              type="button"
            >
              {n}
            </button>
          ))}
        </div>
      </div>

      {/* Per-clinic type selection */}
      {Array.from({ length: req.clinic_count }, (_, i) => {
        const types = req.clinic_types || [];
        const currentType = types[i] || 'PHOROPTER';
        return (
          <div key={i} className="req-field">
            <label className="req-label">
              Clinic {req.clinic_count > 1 ? `${i + 1} ` : ''}type
            </label>
            <div className="req-options-2">
              {CLINIC_TYPE_OPTIONS.map(opt => (
                <button
                  key={opt.value}
                  className={`req-card req-card-wide${currentType === opt.value ? ' req-card-active' : ''}`}
                  onClick={() => {
                    const newTypes = [...(req.clinic_types || [])];
                    newTypes[i] = opt.value;
                    setReq(r => ({ ...r, clinic_types: newTypes,
                      clinic_type: newTypes[0] }));
                  }}
                  disabled={disabled}
                  type="button"
                >
                  <span className="req-card-label">{opt.label}</span>
                  <span className="req-card-desc">{opt.desc}</span>
                </button>
              ))}
            </div>
          </div>
        );
      })}

      {/* ── BOH Inclusions ────────────────────────────────────────────────── */}
      <div className="req-section-divider">BOH (Back of House) Inclusions</div>

      <div className="req-field">
        <label className="req-label">Select required BOH rooms</label>
        <div className="req-checks req-checks-grid">
          {[
            { key: 'has_pantry',        label: 'Pantry',                  note: '1800×1500 mm' },
            { key: 'has_toilet',        label: 'Toilet / Wash Room',      note: '1500×1800 mm' },
            { key: 'has_fitting_lab',   label: 'Fitting Lab',             note: '1370×1830 mm (fixed)' },
            { key: 'has_storage',       label: 'Storage Room',            note: '2000×1800 mm' },
            { key: 'has_electrical',    label: 'Electrical Room',         note: '1200×1000 mm' },
            { key: 'has_fr_room',       label: 'FR Room (Franchisee)',    note: '2400×2000 mm' },
            { key: 'has_fitting_rooms', label: 'Fitting Room(s)',         note: '1200×1200 mm ×2' },
          ].map(({ key, label, note }) => (
            <label key={key} className="req-check-label req-check-label-wide">
              <input
                type="checkbox"
                checked={req[key]}
                onChange={e => set(key, e.target.checked)}
                disabled={disabled}
              />
              <span className="req-check-text">
                <span className="req-check-name">{label}</span>
                <span className="req-check-note">{note}</span>
              </span>
            </label>
          ))}
        </div>
      </div>


      <button
        className="req-confirm-btn"
        onClick={handleConfirm}
        disabled={disabled}
        type="button"
      >
        Confirm Requirements →
      </button>
    </div>
  );
}

export default RequirementsForm;
