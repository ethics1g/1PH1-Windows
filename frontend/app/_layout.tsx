import { Stack } from 'expo-router';
import { AuthProvider } from '../src/auth';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';

export default function RootLayout() {
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
        </Stack>
      </AuthProvider>
    </SafeAreaProvider>
  );
}
