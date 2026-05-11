// client.js — Axios HTTP client
//
// baseURL is intentionally empty so that all requests use RELATIVE
// URLs (e.g. "/api/v1/try-on/2d").  This means every request goes
// through the Vite dev-server proxy (port 5002 → 5000) which:
//   • avoids cross-origin / CORS issues
//   • uses the 600 s proxy timeout configured in vite.config.js
//   • keeps the browser on the same origin
//
// If you need to hit a different backend, set VITE_API_BASE_URL
// in a .env file (e.g. VITE_API_BASE_URL=http://192.168.1.5:5000).
import axios from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 600000,   // 10 min — matches Vite proxy timeout for long 3D jobs
  // DO NOT set default headers here
});

// Request interceptor - SIMPLIFIED
client.interceptors.request.use(
  (config) => {
    // Only set Content-Type if it's JSON and not FormData
    if (config.data && !(config.data instanceof FormData) && !config.headers['Content-Type']) {
      config.headers['Content-Type'] = 'application/json';
    }
    
    const token = localStorage.getItem('access_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor - IMPROVED for FastAPI
client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response) {
      const status = error.response.status;
      const data = error.response.data;
      
      // FastAPI error format
      let message = 'An error occurred';
      
      if (data?.detail) {
        message = Array.isArray(data.detail) 
          ? data.detail.map(d => d.msg || d).join(', ')
          : data.detail;
      } else if (data?.message) {
        message = data.message;
      } else if (typeof data === 'string') {
        message = data;
      }
      
      console.error(`API Error ${status}:`, message);
      
      // Handle specific status codes
      switch (status) {
        case 401:
          // Unauthorized - clear token and redirect
          localStorage.removeItem('access_token');
          window.location.href = '/';
          break;
        case 403:
          message = 'You do not have permission for this action';
          break;
        case 404:
          message = 'Resource not found';
          break;
        case 422:
          message = 'Validation error: ' + message;
          break;
        case 500:
          message = 'Server error: ' + message;
          break;
      }
      
      error.apiError = { status, message, data };
    } else if (error.request) {
      // Network error
      console.error('Network error:', error.message);
      error.apiError = {
        status: 0,
        message: 'Network error. Please check your internet connection.',
        data: null
      };
    } else {
      // Request setup error
      console.error('Request error:', error.message);
      error.apiError = {
        status: -1,
        message: 'Request failed to send.',
        data: null
      };
    }
    
    return Promise.reject(error);
  }
);

export default client;