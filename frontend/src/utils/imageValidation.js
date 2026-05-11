export const validateFaceImage = (imageFile) => {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      // Basic validation - check dimensions
      if (img.width < 300 || img.height < 300) {
        reject(new Error('Image too small. Please upload a larger image (minimum 300x300).'));
        return;
      }
      
      // Check aspect ratio (typical for portraits)
      const aspectRatio = img.width / img.height;
      if (aspectRatio < 0.5 || aspectRatio > 2) {
        reject(new Error('Please upload a front-facing portrait photo.'));
        return;
      }
      
      // You could integrate face detection here later
      resolve(true);
    };
    img.onerror = () => reject(new Error('Failed to load image'));
    img.src = URL.createObjectURL(imageFile);
  });
};

export const validateFileType = (file) => {
  const validTypes = ['image/jpeg', 'image/png', 'image/jpg', 'image/webp'];
  if (!validTypes.includes(file.type)) {
    throw new Error('Invalid file type. Please upload JPEG, PNG, or WebP images.');
  }
};

export const validateFileSize = (file) => {
  const maxSize = 10 * 1024 * 1024; // 10MB
  if (file.size > maxSize) {
    throw new Error(`File too large. Maximum size is ${maxSize / 1024 / 1024}MB.`);
  }
};