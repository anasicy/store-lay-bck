import React from 'react';

function AISuggestions({ data }) {
  if (!data) return null;

  const { summary, placements = [], warnings = [] } = data;

  return (
    <div className="ai-suggestions-panel">
      <div className="ai-suggestions-header">
        <span className="ai-badge">AI</span>
        <h3>Layout Recommendations</h3>
      </div>

      {summary && (
        <p className="ai-summary">{summary}</p>
      )}

      {placements.length > 0 && (
        <div className="placement-table-wrapper">
          <table className="placement-table">
            <thead>
              <tr>
                <th>Fixture</th>
                <th>Zone</th>
                <th>Position</th>
                <th>Reasoning</th>
              </tr>
            </thead>
            <tbody>
              {placements.map((p, i) => (
                <tr key={i}>
                  <td className="fixture-cell">{p.fixture}</td>
                  <td><span className="zone-badge">{p.zone}</span></td>
                  <td>{p.position_hint}</td>
                  <td className="reasoning-cell">{p.reasoning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {warnings.length > 0 && (
        <div className="warning-list">
          <strong>Warnings:</strong>
          <ul>
            {warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default AISuggestions;