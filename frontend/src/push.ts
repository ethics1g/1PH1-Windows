import { Platform } from 'react-native';
import * as Notifications from 'expo-notifications';
import { apiFetch } from './auth';

/**
 * Request permission, obtain the native FCM/APNs token, and register it
 * with the backend so the Emergent Push relay can target this device.
 *
 * Safe to call multiple times — the backend upserts. Returns quickly and
 * NEVER throws upstream: any failure is silently logged.
 */
export async function registerForPushNotifications(userId: string, token: string) {
  if (Platform.OS === 'web') return;
  try {
    const perm = await Notifications.getPermissionsAsync();
    let status = perm.status;
    if (status !== 'granted') {
      const req = await Notifications.requestPermissionsAsync();
      status = req.status;
    }
    if (status !== 'granted') {
      console.log('[push] permission denied');
      return;
    }

    // Native device token (NOT Expo push token per playbook)
    const tokenResp: any = await Notifications.getDevicePushTokenAsync();
    const deviceToken = tokenResp?.data;
    if (!deviceToken) return;

    await apiFetch('/register-push', {
      method: 'POST',
      body: JSON.stringify({
        user_id: userId,
        platform: Platform.OS,
        device_token: deviceToken,
      }),
    }, token);
    console.log('[push] registered');
  } catch (e) {
    console.log('[push] registration failed:', String((e as any)?.message || e));
  }
}
