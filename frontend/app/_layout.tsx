import { useEffect } from 'react';
import { Platform } from 'react-native';
import { Stack, useRouter } from 'expo-router';
import * as Notifications from 'expo-notifications';
import * as Linking from 'expo-linking';
import { AuthProvider } from '../src/auth';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { ExternalScannerProvider } from '../src/externalScanner';
import { StatusBar } from 'expo-status-bar';
import { useDesktopNavigation } from '../src/desktop';

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

  // Wire Electron desktop shell (F2/F3/F4/… menu items) → expo-router.
  // No-op on iOS, Android, and plain web PWA.
  useDesktopNavigation();

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
        <ExternalScannerProvider>
        <StatusBar style="dark" />
        <Stack screenOptions={{ headerShown: false, animation: 'slide_from_right' }}>
          <Stack.Screen name="index" />
          <Stack.Screen name="login" />
          <Stack.Screen name="home" />
          <Stack.Screen name="sell" />
          <Stack.Screen name="buy" />
          <Stack.Screen name="orders/scan" />
          <Stack.Screen name="orders/paper" />
          <Stack.Screen name="orders/paper/[id]" />
          <Stack.Screen name="orders/excel-import" />
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
          <Stack.Screen name="settings/desktop" />
          <Stack.Screen name="medicines/expired" />
          <Stack.Screen name="accounting/index" />
          <Stack.Screen name="accounting/unlock" />
          <Stack.Screen name="customers/index" />
          <Stack.Screen name="customers/[id]" />
          <Stack.Screen name="returns/create/[orderId]" />
          <Stack.Screen name="returns/[id]" />
          <Stack.Screen name="supplier-returns" />
          <Stack.Screen name="accounting/supplier-accounts/index" />
          <Stack.Screen name="accounting/supplier-accounts/[supplierId]" />
          <Stack.Screen name="accounting/profit-report" />
        </Stack>
        </ExternalScannerProvider>
      </AuthProvider>
    </SafeAreaProvider>
  );
}
