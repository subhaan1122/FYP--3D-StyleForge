import client from './client';
import { API_ENDPOINTS } from '../utils/constants';

const createFormData = (data) => {
  const formData = new FormData();

  if (data.user_image instanceof File) {
    formData.append('user_image', data.user_image);
  }

  if (data.garment_reference instanceof File) {
    formData.append('garment_reference', data.garment_reference);
  }

  if (data.instruction) formData.append('instruction', data.instruction);
  if (data.session_id)  formData.append('session_id',  data.session_id);

  // output_id from the 2D pipeline — the 3D service uses this
  // to locate the 2D result image (outputs/tryon_{output_id}.png)
  if (data.output_id) formData.append('output_id', data.output_id);

  return formData;
};

export const tryOn2D = async (data) => {
  const formData = createFormData(data);
  const response = await client.post(API_ENDPOINTS.TRY_ON_2D, formData);
  return response;
};

export const tryOn3D = async (data) => {
  const formData = createFormData(data);
  // 10-minute timeout: LHM 3D reconstruction can take 5-10 minutes on first run
  const response = await client.post(API_ENDPOINTS.TRY_ON_3D, formData, { timeout: 600000 });
  return response;
};

export const getJobStatus = async (jobId) => {
  return await client.get(`${API_ENDPOINTS.JOB_STATUS}/${jobId}`);
};

export const downloadModel = async (modelId) => {
  return await client.get(`${API_ENDPOINTS.DOWNLOAD_MODEL}/${modelId}`, { responseType: 'blob' });
};

export const checkBackendHealth = async () => {
  try {
    await client.get('/health');
    return true;
  } catch {
    return false;
  }
};