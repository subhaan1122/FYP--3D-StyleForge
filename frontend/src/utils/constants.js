export const API_ENDPOINTS = {
  // Try-on endpoints
  TRY_ON_2D: '/api/v1/try-on/2d',
  TRY_ON_3D: '/api/v1/try-on/3d',
  
  // Status endpoints
  JOB_STATUS: '/api/v1/status',
  
  // Download endpoints
  DOWNLOAD_MODEL: '/api/v1/download',
  
  // History endpoints
  HISTORY: '/api/v1/history',
  
  // Analytics endpoints
  ANALYTICS: '/api/v1/analytics',
};

export const FILE_CONFIG = {
  MAX_SIZE: 10 * 1024 * 1024, // 10MB
  ACCEPTED_TYPES: ['image/jpeg', 'image/png', 'image/jpg'],
  MIN_DIMENSIONS: { width: 100, height: 100 },
  MAX_DIMENSIONS: { width: 4096, height: 4096 },
};

export const JOB_STATUS = {
  QUEUED: 'queued',
  PROCESSING: 'processing',
  COMPLETED: 'completed',
  FAILED: 'failed',
};