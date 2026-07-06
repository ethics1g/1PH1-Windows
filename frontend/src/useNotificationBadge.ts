import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';
import { apiFetch, useAuth } from './auth';

/**
 * Polls /api/notifications/unread-count every 30 seconds while the app is
 * foregrounded. Returns the count for badge display and a manual refresh fn.
 */
export function useNotificationBadge() {
  const { token } = useAuth();
  const [unread, setUnread] = useState(0);
  const timerRef = useRef<any>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const r: any = await apiFetch('/notifications/unread-count', {}, token);
      setUnread(r.unread || 0);
    } catch {
      /* ignore */
    }
  }, [token]);

  useEffect(() => {
    if (!token) return;
    load();
    timerRef.current = setInterval(load, 30000);
    const sub = AppState.addEventListener('change', (s) => {
      if (s === 'active') load();
    });
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      sub.remove();
    };
  }, [token, load]);

  return { unread, refresh: load };
}
