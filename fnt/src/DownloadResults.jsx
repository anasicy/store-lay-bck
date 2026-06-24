import React from 'react';

function DownloadResults({ fileId }) {
  const handleDownload = () => {
    window.location.href = `http://localhost:5000/download/${fileId}`;
  };

  return (
    <div className="download-results">
      <button className="download-btn" onClick={handleDownload}>
        <svg viewBox="0 0 24 24" width="20" height="20">
          <path fill="currentColor" d="M5,20H19V18H5M19,9H15V3H9V9H5L12,16L19,9Z" />
        </svg>
        Download Optimized DXF
      </button>
    </div>
  );
}

export default DownloadResults;