import React, { useRef, useEffect, useState } from 'react';
import { Upload, X } from 'lucide-react';
import { toast } from 'react-hot-toast';
import Button from '../common/Button';
import '../../styles/components/file-uploader.css';
import { validateFileType, validateFileSize, validateFaceImage } from '../../utils/imageValidation';

const FileUploader = ({
  label = 'Upload Image',
  description = 'Drag & drop or click to upload',
  accept = 'image/*',
  maxSize = 10 * 1024 * 1024, // 10MB
  onFileSelect,
  value,
  required = false,
  disabled = false,
  showPreview = true,
  validateFace = false,
}) => {
  const fileInputRef = useRef(null);
  const [preview, setPreview] = useState(value?.previewUrl || null);
  const [isDragging, setIsDragging] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  // Sync with external value
  useEffect(() => {
    if (value?.previewUrl) {
      setPreview(value.previewUrl);
    } else if (!value) {
      setPreview(null);
    }
  }, [value]);

  // Clean up object URL on unmount
  useEffect(() => {
    return () => {
      if (preview) {
        URL.revokeObjectURL(preview);
      }
    };
  }, [preview]);

  const validateFile = async (file) => {
    try {
      // Basic validation
      validateFileType(file);
      validateFileSize(file, maxSize);
      
      // Face validation if enabled
      if (validateFace) {
        setIsLoading(true);
        await validateFaceImage(file);
        setIsLoading(false);
      }
      
      return true;
    } catch (error) {
      setIsLoading(false);
      throw error;
    }
  };

  const handleFileSelect = async (file) => {
    if (!file) return null;

    try {
      await validateFile(file);
      
      // Create preview URL
      const previewUrl = URL.createObjectURL(file);
      setPreview(previewUrl);
      
      // Create file data object
      const fileData = {
        file,
        previewUrl,
        name: file.name,
        size: file.size,
        type: file.type,
        lastModified: file.lastModified,
      };
      
      if (onFileSelect) {
        onFileSelect(fileData);
      }
      
      return fileData;
    } catch (error) {
      console.error('File validation error:', error);
      toast.error(error.message);
      
      // Clear the file input
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
      
      return null;
    }
  };

  const handleInputChange = async (event) => {
    const file = event.target.files[0];
    if (file) {
      await handleFileSelect(file);
    }
  };

  const handleDrop = async (e) => {
    e.preventDefault();
    setIsDragging(false);
    
    const file = e.dataTransfer.files[0];
    if (file) {
      await handleFileSelect(file);
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleRemove = () => {
    // Clean up object URL
    if (preview) {
      URL.revokeObjectURL(preview);
    }
    
    setPreview(null);
    setIsLoading(false);
    
    // Clear the file input
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
    
    // Notify parent
    if (onFileSelect) {
      onFileSelect(null);
    }
  };

  const handleClick = () => {
    if (!disabled && !isLoading && fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  return (
    <div className="file-uploader">
      {label && (
        <div className="file-uploader-label">
          <span>{label}</span>
          {required && <span className="required">*</span>}
        </div>
      )}
      
      {!preview ? (
        <div
          className={`file-uploader-dropzone ${isDragging ? 'dragging' : ''} ${disabled ? 'disabled' : ''} ${isLoading ? 'loading' : ''}`}
          onClick={handleClick}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept={accept}
            onChange={handleInputChange}
            disabled={disabled || isLoading}
            style={{ display: 'none' }}
          />
          
          <div className="dropzone-content">
            {isLoading ? (
              <>
                <div className="loading-spinner"></div>
                <div className="dropzone-text">
                  <p className="dropzone-title">Validating image...</p>
                  <p className="dropzone-subtitle">Checking for face detection</p>
                </div>
              </>
            ) : (
              <>
                <div className="dropzone-icon">
                  <Upload size={32} />
                </div>
                <div className="dropzone-text">
                  <p className="dropzone-title">{description}</p>
                  <p className="dropzone-subtitle">
                    Supports JPG, PNG • Max {maxSize / 1024 / 1024}MB
                    {validateFace && ' • Face required'}
                  </p>
                </div>
              </>
            )}
          </div>
        </div>
      ) : showPreview ? (
        <div className="file-preview">
          <div className="preview-image-container">
            <img src={preview} alt="Preview" />
            <div className="preview-overlay">
              <Button
                variant="ghost"
                size="small"
                onClick={handleRemove}
                className="remove-button"
                disabled={isLoading}
              >
                <X size={16} />
                Remove
              </Button>
            </div>
          </div>
          <p className="preview-filename">
            {value?.name || 'Uploaded image'}
            {value?.size && ` • ${(value.size / 1024 / 1024).toFixed(2)}MB`}
          </p>
        </div>
      ) : null}
      
      {/* Loading spinner overlay for face validation */}
      {isLoading && (
        <div className="validation-overlay">
          <div className="validation-spinner"></div>
          <p>Validating image...</p>
        </div>
      )}
    </div>
  );
};

export default FileUploader;