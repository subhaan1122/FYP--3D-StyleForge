import { useState, useEffect, useRef, useCallback } from 'react';
import { getJobStatus } from '../api/tryon';
import { JOB_STATUS } from '../utils/constants';

/**
 * Generic job-status polling hook.
 *
 * KEY DESIGN: onStatusUpdate and options are kept in refs so they
 * never trigger a new poll cycle or reset the attempt counter.
 * Only a change to `jobId` restarts polling.
 */
const usePolling = (jobId, onStatusUpdate, options = {}) => {
  const { interval = 2000, maxAttempts = 30 } = options;
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [isPolling, setIsPolling] = useState(false);

  const pollingRef = useRef(null);
  const attemptCountRef = useRef(0);
  const completedRef = useRef(false);

  // Keep the callback and options in refs so the poll function
  // doesn't depend on them and doesn't get re-created on every render.
  const callbackRef = useRef(onStatusUpdate);
  const intervalRef = useRef(interval);
  const maxAttemptsRef = useRef(maxAttempts);

  // Sync refs on every render (cheap, no re-render triggered)
  callbackRef.current = onStatusUpdate;
  intervalRef.current = interval;
  maxAttemptsRef.current = maxAttempts;

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearTimeout(pollingRef.current);
      pollingRef.current = null;
    }
    setIsPolling(false);
  }, []);

  const poll = useCallback(async () => {
    if (!jobId || completedRef.current) {
      stopPolling();
      return;
    }

    if (attemptCountRef.current >= maxAttemptsRef.current) {
      setError('Max polling attempts reached');
      stopPolling();
      return;
    }

    try {
      setIsPolling(true);
      attemptCountRef.current += 1;

      const response = await getJobStatus(jobId);
      const data = response.data;

      setStatus(data);
      setError(null);

      // Notify the consumer
      if (callbackRef.current) {
        callbackRef.current(data);
      }

      // Stop polling if job is complete or failed
      if (data.status === JOB_STATUS.COMPLETED || data.status === JOB_STATUS.FAILED) {
        completedRef.current = true;
        stopPolling();
        return;
      }

      // Continue polling
      pollingRef.current = setTimeout(poll, intervalRef.current);

    } catch (err) {
      console.error('Polling error:', err);
      setError(err.message);

      // Exponential backoff on errors, capped at 30 s
      const backoffDelay = Math.min(
        intervalRef.current * Math.pow(2, attemptCountRef.current),
        30000,
      );
      pollingRef.current = setTimeout(poll, backoffDelay);
    }
  }, [jobId, stopPolling]);          // ← only jobId & stopPolling

  // Start/stop polling when jobId changes
  useEffect(() => {
    completedRef.current = false;
    attemptCountRef.current = 0;
    setStatus(null);
    setError(null);

    if (jobId) {
      poll();
    } else {
      stopPolling();
    }

    return () => stopPolling();
  }, [jobId, poll, stopPolling]);

  return { status, error, isPolling, stopPolling };
};

export default usePolling;