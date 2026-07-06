import { useEffect } from 'react';
import { Platform } from 'react-native';
import { Stack, useRouter } from 'expo-router';
import * as Notifications from 'expo-notifications';
import * as Linking from 'expo-linking';
import { AuthProvider } from '../src/auth';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';

// -------------------------------------------------------------------
// Emergent-managed Push Notifications — module scope setup (must be
// registered before any component renders).
// -------------------------------------------------------------------
if (Platform.OS !== 'web') {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowAlert: true,
      shouldPlaySound: true,
      shouldSetBadge: false,
      // Newer SDK fields for future compatibility
      shouldShowBanner: true,
      shouldShowList: true,
    } as any),
  });
}
if (Platform.OS === 'android') {
  Notifications.setNotificationChannelAsync('default', {
    name: 'إشعارات 1PH1',
    importance: Notifications.AndroidImportance.MAX,
    sound: 'default',
  }).catch(() => {});
}

export default function RootLayout() {
  const router = useRouter();

  // Push notification tap deep-linking (foreground + killed cold-start)
  useEffect(() => {
    if (Platform.OS === 'web') return;

    const openUrl = (url?: string) => {
      if (!url) return;
      if (url.startsWith('http')) {
        Linking.openURL(url).catch(() => {});
      } else {
        router.push(url as any);
      }
    };

    // Warm tap — user taps while the app is running
    const tapSub = Notifications.addNotificationResponseReceivedListener((resp) => {
      const data: any = resp?.notification?.request?.content?.data || {};
      openUrl(data.deeplink || data.action_url || data.screen);
    });

    // Cold-start tap — user tapped notification while app was killed
    Notifications.getLastNotificationResponseAsync().then((resp) => {
      if (!resp) return;
      const data: any = resp?.notification?.request?.content?.data || {};
      openUrl(data.deeplink || data.action_url || data.screen);
    }).catch(() => {});

    return () => { tapSub.remove(); };
  }, [router]);

  return (
    <SafeAreaProvider>
      <AuthProvider>
        <StatusBar style="dark" />
        <Stack screenOptions={{ headerShown: false, animation: 'slide_from_right' }}>
          <Stack.Screen name="index" />
          <Stack.Screen name="login" />
          <Stack.Screen name="home" />
          <Stack.Screen name="sell" />
          <Stack.Screen name="buy" />
          <Stack.Screen name="inventory" />
          <Stack.Screen name="suppliers" />
          <Stack.Screen name="supplier-dashboard" />
          <Stack.Screen name="optimize" />
          <Stack.Screen name="catalog-upload" />
          <Stack.Screen name="catalog-jobs" />
          <Stack.Screen name="catalog-review/[id]" />
          <Stack.Screen name="forgot-password" />
          <Stack.Screen name="verify-otp" />
          <Stack.Screen name="reset-password" />
          <Stack.Screen name="admin/dashboard" />
          <Stack.Screen name="admin/change-password" />
          <Stack.Screen name="admin/notifications" />
          <Stack.Screen name="commissions" />
          <Stack.Screen name="pharmacy-orders" />
          <Stack.Screen name="supplier-orders" />
          <Stack.Screen name="notifications" />
          <Stack.Screen name="settings/index" />
          <Stack.Screen name="settings/personal" />
          <Stack.Screen name="settings/password" />
          <Stack.Screen name="settings/notifications" />
          <Stack.Screen name="medicines/expired" />
          <Stack.Screen name="accounting/index" />
          <Stack.Screen name="customers/index" />
          <Stack.Screen name="customers/[id]" />
        </Stack>
      </AuthProvider>
    </SafeAreaProvider>
  );
}
