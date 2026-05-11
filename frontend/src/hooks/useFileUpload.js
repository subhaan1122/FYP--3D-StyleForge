import { useState, useCallback } from 'react';
import { toast } from 'react-hot-toast';
import { FILE_CONFIG } from '../utils/constants';

const useFileUpload = (options = {}) => {
  const { maxSize = FILE_CONFIG.MAX_SIZE, acceptedTypes = FILE_CONFIG.ACCEPTED_TYPES } = options;
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [isDragging, setIsDragging] = useState(false);

  const validateFile = useCallback((file) => {
    // Check file type
    if (!acceptedTypes.includes(file.type)) {
      throw new Error(`Invalid file type. Please upload: ${acceptedTypes.join(', ')}`);
    }

    // Check file size
    if (file.size > maxSize) {
      throw new Error(`File size too large. Maximum size: ${maxSize / 1024 / 1024}MB`);
    }

    // Check dimensions (optional)
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        if (img.width < FILE_CONFIG.MIN_DIMENSIONS.width || 
            img.height < FILE_CONFIG.MIN_DIMENSIONS.height) {
          reject(new Error(`Image too small. Minimum dimensions: ${FILE_CONFIG.MIN_DIMENSIONS.width}x${FILE_CONFIG.MIN_DIMENSIONS.height}`));
        } else {
          resolve(img);
        }
      };
      img.onerror = () => reject(new Error('Failed to load image'));
      img.src = URL.createObjectURL(file);
    });
  }, [acceptedTypes, maxSize]);

  const handleFileSelect = useCallback(async (selectedFile) => {
    try {
      await validateFile(selectedFile);
      
      setFile(selectedFile);
      const previewUrl = URL.createObjectURL(selectedFile);
      setPreview(previewUrl);
      
      return { file: selectedFile, previewUrl };
    } catch (error) {
      toast.error(error.message);
      return null;
    }
  }, [validateFile]);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setIsDragging(false);
    
    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile) {
      return handleFileSelect(droppedFile);
    }
    return null;
  }, [handleFileSelect]);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const clearFile = useCallback(() => {
    if (preview) {
      URL.revokeObjectURL(preview);
    }
    setFile(null);
    setPreview(null);
  }, [preview]);

  return {
    file,
    preview,
    isDragging,
    handleFileSelect,
    handleDrop,
    handleDragOver,
    handleDragLeave,
    clearFile,
  };
};

export default useFileUpload;