import { useState } from 'react';

// ── Fixture catalog ───────────────────────────────────────────────────────────
const FIXTURE_GROUPS = [
  {
    group: 'Floor Fixtures — Islands',
    fixtures: [
      { name: 'DOUBLE SIDE ISLAND UNIT 2.54W', l: 2545, d: 1074, h: 1104 },
      { name: 'SINGLE SIDE ISLAND UNIT 2.54W', l: 2545, d: 581,  h: 1104 },
    ],
  },

  {
    group: 'Floor Fixtures — SG Floor Mount',
    fixtures: [
      { name: 'SUNGLASS UNIT - FLOOR MOUNT - 1.22W LH', l: 1236, d: 450, h: 2250 },
      { name: 'SUNGLASS UNIT - FLOOR MOUNT - 1.22W RH', l: 1236, d: 450, h: 2250 },
    ],
  },
    {
    group: 'Floor Fixtures — Transaction / Center Tables',
    fixtures: [
      { name: 'TRANSACTION TABLE 0.75 DIA-CORIAN', l: 828, d: 828, h: 770 },
      { name: 'CENTER TABLE 0.6D',                 l: 730, d: 730, h: 450 },
    ],
  },
  {
    group: 'Wall Fixtures — IB Frames',
    fixtures: [
      { name: 'IB FRAME UNIT 2.25W', l: 2225, d: 400, h: 2250 },
      { name: 'IB FRAME UNIT 1.29W', l: 1292, d: 400, h: 2250 },
    ],
  },
  {
    group: 'Wall Fixtures — Lux Units',
    fixtures: [
      { name: 'LUXURY UNIT OPEN TOP 0.82W',  l: 820, d: 400, h: 2275 },
      { name: 'LUXURY UNIT GLASS TOP 0.82W', l: 820, d: 400, h: 2275 },
    ],
  },
  {
    group: 'Wall Fixtures — End Portal',
    fixtures: [
      { name: 'END PORTAL WOOD-MIRROR', l: 120, d: 95, h: 1000 },
    ],
  },
  {
    group: 'Wall Fixtures — Affordable (Fastrack / M&W)',
    fixtures: [
      { name: 'AFFORDABLE FASTRACK EYEWEAR UNIT 2.25W', l: 2225, d: 400, h: 2250 },
      { name: 'AFFORDABLE FASTRACK EYEWEAR UNIT 1.29W', l: 1290, d: 400, h: 2250 },
      { name: 'AFFORDABLE MEN AND WOMEN UNIT 2.25W',    l: 2223, d: 400, h: 2250 },
      { name: 'AFFORDABLE MEN AND WOMEN UNIT 1.29W',    l: 1290, d: 400, h: 2250 },
    ],
  },
  {
    group: 'Wall Fixtures — Kids',
    fixtures: [
      { name: 'PREM KIDS DISPLAY UNIT LGP 1.00W', l: 1000, d: 400, h: 2250 },
    ],
  },

  {
    group: 'Wall Fixtures — SG Wall',
    fixtures: [
      { name: 'SUNGLASS UNIT - WALL MOUNT - 1.22W LH', l: 1236, d: 450, h: 2250 },
      { name: 'SUNGLASS UNIT - WALL MOUNT - 1.22W RH', l: 1236, d: 450, h: 2250 },
    ],
  },
  {
    group: 'Wall Fixtures — SG Angular Wall',
    fixtures: [
      { name: 'SUNGLASS ANGULAR UNIT -WALL MOUNT LH', l: 1386, d: 600, h: 2250 },
      { name: 'SUNGLASS ANGULAR UNIT -WALL MOUNT RH', l: 1386, d: 600, h: 2250 },
    ],
  },

  {
    group: 'Cash Counter',
    fixtures: [
      { name: 'CASH COUNTER L SHAPED 2.30W',  l: 2300, d: 1000, h: 1100 },
      { name: 'CASH COUNTER 1.20W',           l: 1200, d: 600,  h: 1100 },
      { name: 'CASH COUNTER 1.80W',           l: 1800, d: 600,  h: 1100 },
      { name: 'CASH COUNTER L SHAPED 1.3W LH', l: 1300, d: 1350, h: 1100 },
      { name: 'CASH COUNTER L SHAPED 1.3W RH', l: 1300, d: 1350, h: 1100 },
    ],
  },
  {
    group: 'Clinic Fixtures',
    fixtures: [
      { name: 'CLINIC TRAN TABLE WOOD TOP-1.25W', l: 1250, d: 350, h: 740 },
      { name: 'SMALL CLINIC TABLE 0.45W',         l: 450,  d: 350, h: 740 },
    ],
  },
];

// Flat list for search
const ALL_FIXTURES = FIXTURE_GROUPS.flatMap(g => g.fixtures);

function ConstraintSelector({ constraints, onChange, disabled }) {
  const [search, setSearch] = useState('');
  const [expandedGroups, setExpandedGroups] = useState({});

  const selectedFixtures = constraints.selectedFixtures || [];
  const fixtureQuantities = constraints.fixtureQuantities || {};

  const emit = (patch) => onChange({ ...constraints, ...patch });

  const handleChange = (key, value) => emit({ [key]: value });

  const toggleFixture = (fixtureName) => {
    if (selectedFixtures.includes(fixtureName)) {
      const updatedQtys = { ...fixtureQuantities };
      delete updatedQtys[fixtureName];
      emit({
        selectedFixtures: selectedFixtures.filter(n => n !== fixtureName),
        fixtureQuantities: updatedQtys,
      });
    } else {
      emit({
        selectedFixtures: [...selectedFixtures, fixtureName],
        fixtureQuantities: { ...fixtureQuantities, [fixtureName]: 1 },
      });
    }
  };

  const updateQty = (fixtureName, delta) => {
    const current = fixtureQuantities[fixtureName] || 1;
    const next = Math.max(1, current + delta);
    emit({ fixtureQuantities: { ...fixtureQuantities, [fixtureName]: next } });
  };

  const toggleGroup = (groupName) => {
    setExpandedGroups(prev => ({ ...prev, [groupName]: !prev[groupName] }));
  };

  // groups are collapsed by default — isExpanded is true only if explicitly set to true

  const selectAllInGroup = (fixtures) => {
    const names = fixtures.map(f => f.name);
    const allSelected = names.every(n => selectedFixtures.includes(n));
    if (allSelected) {
      const updatedQtys = { ...fixtureQuantities };
      names.forEach(n => delete updatedQtys[n]);
      emit({
        selectedFixtures: selectedFixtures.filter(n => !names.includes(n)),
        fixtureQuantities: updatedQtys,
      });
    } else {
      const newQtys = { ...fixtureQuantities };
      names.forEach(n => { if (!newQtys[n]) newQtys[n] = 1; });
      emit({
        selectedFixtures: [...new Set([...selectedFixtures, ...names])],
        fixtureQuantities: newQtys,
      });
    }
  };

  const selectedCount = selectedFixtures.length;
  const isSearching = search.trim().length > 0;
  const filteredFixtures = isSearching
    ? ALL_FIXTURES.filter(f => f.name.toLowerCase().includes(search.toLowerCase()))
    : null;

  const renderFixtureRow = (fixture) => {
    const selected = selectedFixtures.includes(fixture.name);
    const qty = fixtureQuantities[fixture.name] || 1;
    return (
      <label key={fixture.name} className={`fixture-item ${selected ? 'selected' : ''}`}>
        <input
          type="checkbox"
          checked={selected}
          onChange={() => toggleFixture(fixture.name)}
          disabled={disabled}
        />
        <span className="fixture-info">
          <span className="fixture-name">{fixture.name}</span>
          <span className="fixture-dims">{fixture.l}L × {fixture.d}D × {fixture.h}H mm</span>
        </span>
        {selected && (
          <span
            className="fixture-qty-ctrl"
            onClick={e => { e.preventDefault(); e.stopPropagation(); }}
          >
            <button
              type="button"
              className="fixture-qty-btn"
              onClick={e => { e.preventDefault(); e.stopPropagation(); updateQty(fixture.name, -1); }}
              disabled={disabled || qty <= 1}
            >−</button>
            <span className="fixture-qty">{qty}</span>
            <button
              type="button"
              className="fixture-qty-btn"
              onClick={e => { e.preventDefault(); e.stopPropagation(); updateQty(fixture.name, 1); }}
              disabled={disabled}
            >+</button>
          </span>
        )}
      </label>
    );
  };

  return (
    <div className={`constraint-selector ${disabled ? 'disabled' : ''}`}>

      {/* Spacing */}
      

      {/* Fixture selector */}
      <div className="fixture-group">
        <div className="fixture-header-row">
          <label className="fixture-label">
            Fixtures ({selectedCount} selected):
          </label>
          {selectedCount > 0 && (
            <button
              className="fixture-clear-btn"
              onClick={() => emit({ selectedFixtures: [], fixtureQuantities: {} })}
              disabled={disabled}
              type="button"
            >
              Clear all
            </button>
          )}
        </div>

        <input
          type="text"
          placeholder="Search fixtures…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          disabled={disabled}
          className="fixture-search"
        />

        {/* Search results */}
        {isSearching && (
          <div className="fixture-list">
            {filteredFixtures.length === 0 && (
              <p className="fixture-empty">No fixtures match "{search}"</p>
            )}
            {filteredFixtures.map(fixture => renderFixtureRow(fixture))}
          </div>
        )}

        {/* Grouped list */}
        {!isSearching && (
          <div className="fixture-groups">
            {FIXTURE_GROUPS.map(group => {
              const isExpanded = expandedGroups[group.group] === true;
              const groupSelected = group.fixtures.filter(
                f => selectedFixtures.includes(f.name)
              ).length;
              const allGroupSelected = groupSelected === group.fixtures.length;

              return (
                <div key={group.group} className="fixture-group-section">
                  <div className="fixture-group-header">
                    <button
                      className="fixture-group-toggle"
                      onClick={() => toggleGroup(group.group)}
                      disabled={disabled}
                      type="button"
                    >
                      <span className="fixture-group-arrow">{isExpanded ? '▾' : '▸'}</span>
                      <span className="fixture-group-name">{group.group}</span>
                      <span className="fixture-group-count">
                        {groupSelected}/{group.fixtures.length}
                      </span>
                    </button>
                    <button
                      className={`fixture-group-select-all ${allGroupSelected ? 'all-selected' : ''}`}
                      onClick={() => selectAllInGroup(group.fixtures)}
                      disabled={disabled}
                      type="button"
                    >
                      {allGroupSelected ? 'Deselect all' : 'Select all'}
                    </button>
                  </div>

                  {isExpanded && (
                    <div className="fixture-list fixture-list-grouped">
                      {group.fixtures.map(fixture => renderFixtureRow(fixture))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export default ConstraintSelector;
