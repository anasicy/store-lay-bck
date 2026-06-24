import React, { useState, useRef } from 'react';

function ReferenceImageUpload({ onUploadSuccess, onRemove }) {
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [fileName, setFileName] = useState(null);
  const fileInputRef = useRef(null);

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setIsDragging(true);
    } else if (e.type === 'dragleave') {
      setIsDragging(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    if (e.dataTransfer.files?.[0]) {
      uploadFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileSelect = (e) => {
    if (e.target.files?.[0]) {
      uploadFile(e.target.files[0]);
    }
  };

  const uploadFile = async (file) => {
    const ext = file.name.split('.').pop().toLowerCase();
    if (!['png', 'jpg', 'jpeg'].includes(ext)) {
      alert('Please upload a PNG or JPG image');
      return;
    }

    setUploading(true);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch('http://localhost:5000/upload-reference', {
        method: 'POST',
        body: formData
      });
      const data = await response.json();
      if (response.ok) {
        setPreviewUrl(URL.createObjectURL(file));
        setFileName(file.name);
        onUploadSuccess(data);
      } else {
        alert(data.error || 'Upload failed');
      }
    } catch (error) {
      console.error('Reference upload error:', error);
      alert('Failed to upload image');
    } finally {
      setUploading(false);
    }
  };

  const handleRemove = (e) => {
    e.stopPropagation();
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
    setFileName(null);
    if (fileInputRef.current) fileInputRef.current.value = '';
    onRemove?.();
  };

  if (previewUrl) {
    return (
      <div className="ref-image-success">
        <img src={previewUrl} alt="Layout reference" className="ref-image-thumb" />
        <div className="ref-image-info">
          <span className="ref-image-name">{fileName}</span>
          <span className="ref-image-badge">Ready</span>
          <button className="ref-image-remove" onClick={handleRemove}>Remove</button>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`file-upload ref-image-upload ${isDragging ? 'dragging' : ''}`}
      onDragEnter={handleDrag}
      onDragOver={handleDrag}
      onDragLeave={handleDrag}
      onDrop={handleDrop}
      onClick={() => fileInputRef.current?.click()}
    >
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileSelect}
        accept=".png,.jpg,.jpeg"
        style={{ display: 'none' }}
      />
      {uploading ? (
        <div className="upload-status">
          <div className="spinner"></div>
          <p>Uploading...</p>
        </div>
      ) : (
        <div className="upload-prompt">
          <svg className="upload-icon" viewBox="0 0 24 24" width="48" height="48">
            <path fill="currentColor" d="M8.5,13.5L11,16.5L14.5,12L19,18H5M21,19V5C21,3.89 20.1,3 19,3H5A2,2 0 0,0 3,5V19A2,2 0 0,0 5,21H19A2,2 0 0,0 21,19Z" />
          </svg>
          <p><strong>Click or drag layout image here</strong></p>
          <p className="hint">PNG or JPG · Helps AI understand zones</p>
        </div>
      )}
    </div>
  );
}

export default ReferenceImageUpload;
