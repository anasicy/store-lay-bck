import React from 'react';

function LayoutPreview({ data }) {
  if (!data || !data.bounds) return null;

  const bounds = data.bounds;
  const width = bounds.max[0] - bounds.min[0];
  const height = bounds.max[1] - bounds.min[1];
  
  const viewBox = `${bounds.min[0]} ${bounds.min[1]} ${width} ${height}`;

  return (
    <div className="layout-preview">
      <div className="preview-stats">
        <p><strong>Entities:</strong> {data.entities.length}</p>
        <p><strong>Dimensions:</strong> {width.toFixed(2)} × {height.toFixed(2)}</p>
      </div>
      
      <svg 
        className="preview-svg"
        viewBox={viewBox}
        preserveAspectRatio="xMidYMid meet"
      >
        {data.entities.map((entity, index) => {
          if (!entity.bbox) return null;
          
          const bbox = entity.bbox;
          const w = bbox.max[0] - bbox.min[0];
          const h = bbox.max[1] - bbox.min[1];
          
          return (
            <rect 
              key={index}
              x={bbox.min[0]}
              y={bbox.min[1]}
              width={w}
              height={h}
              fill="none"
              stroke="#3498db"
              strokeWidth={Math.max(width, height) * 0.002}
            />
          );
        })}
      </svg>
    </div>
  );
}

export default LayoutPreview;