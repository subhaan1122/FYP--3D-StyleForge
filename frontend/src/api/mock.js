// Mock data for testing - Using reliable GLB files
const mock2DResults = [
  'https://images.unsplash.com/photo-1523381210434-271e8be1f52b?w=512&h=512&fit=crop&crop=faces',
  'https://images.unsplash.com/photo-1552374196-c4e7ffc6e126?w=512&h=512&fit=crop&crop=faces',
  'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=512&h=512&fit=crop&crop=faces',
];

// RELIABLE TEST 3D MODELS (GLB format)
const mock3DModels = [
  'https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Models/master/2.0/Duck/glTF-Binary/Duck.glb',
  'https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Models/master/2.0/Fox/glTF-Binary/Fox.glb',
  'https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Models/master/2.0/BoomBox/glTF-Binary/BoomBox.glb',
];

// Simulate delay
const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));

// Track which jobs have been completed
const completedJobs = new Set();

// Mock API functions
export const mockTryOn2D = async (data) => {
  await delay(1000);
  
  const jobId = `mock_2d_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  completedJobs.delete(jobId);
  
  return {
    data: {
      job_id: jobId,
      status: 'processing',
      estimated_time_seconds: 5,
    }
  };
};

export const mockTryOn3D = async (data) => {
  await delay(1000);
  
  const jobId = `mock_3d_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  completedJobs.delete(jobId);
  
  // Return a reliable test model
  const modelUrl = mock3DModels[Math.floor(Math.random() * mock3DModels.length)];
  
  return {
    data: {
      job_id: jobId,
      status: 'processing',
      estimated_time_seconds: 10,
      preview_model: modelUrl, // For testing
    }
  };
};

export const mockGetJobStatus = async (jobId) => {
  await delay(1000);
  
  // If already completed, return completed status
  if (completedJobs.has(jobId)) {
    const is2D = jobId.includes('2d');
    const randomIndex = Math.floor(Math.random() * (is2D ? mock2DResults.length : mock3DModels.length));
    
    return {
      data: {
        job_id: jobId,
        status: 'completed',
        progress: 100,
        result: is2D 
          ? { 
              preview_url: mock2DResults[randomIndex],
              metadata: { 
                ssim: 0.82,
                fid: 28.5,
                generation_time: 12.3
              }
            }
          : { 
              download_url: mock3DModels[randomIndex],
              model_id: `model_${Date.now()}`,
              format: 'glb',
              file_size: '1.2MB'
            }
      }
    };
  }
  
  // First 2 calls return processing, then completed
  const attemptCount = parseInt(localStorage.getItem(`attempt_${jobId}`) || '0') + 1;
  localStorage.setItem(`attempt_${jobId}`, attemptCount.toString());
  
  const is2D = jobId.includes('2d');
  
  if (attemptCount >= 2) { // Complete on 2nd attempt
    completedJobs.add(jobId);
    
    const randomIndex = Math.floor(Math.random() * (is2D ? mock2DResults.length : mock3DModels.length));
    
    return {
      data: {
        job_id: jobId,
        status: 'completed',
        progress: 100,
        result: is2D 
          ? { 
              preview_url: mock2DResults[randomIndex],
              metadata: { 
                ssim: 0.82,
                fid: 28.5,
                generation_time: 12.3
              }
            }
          : { 
              download_url: mock3DModels[randomIndex],
              model_id: `model_${Date.now()}`,
              format: 'glb',
              file_size: '1.2MB'
            }
      }
    };
  } else {
    // Still processing
    return {
      data: {
        job_id: jobId,
        status: 'processing',
        progress: Math.floor(Math.random() * 70) + 20,
        estimated_time_seconds: is2D ? 3 : 8,
        stage: is2D ? 'generating_garment' : 'reconstructing_3d'
      }
    };
  }
};

export const mockDownloadModel = async (modelId) => {
  await delay(500);
  
  // Create a realistic mock GLB file
  const mockGlbHeader = new Uint8Array([
    0x67, 0x6C, 0x54, 0x46, // glTF magic
    0x02, 0x00, 0x00, 0x00, // version 2
    0x58, 0x00, 0x00, 0x00  // file length
  ]);
  
  const blob = new Blob([mockGlbHeader], { type: 'model/gltf-binary' });
  
  return {
    data: blob,
    status: 200,
    statusText: 'OK',
    headers: { 
      'content-type': 'model/gltf-binary',
      'content-disposition': `attachment; filename="styleforge_model_${modelId}.glb"`
    },
    config: {}
  };
};