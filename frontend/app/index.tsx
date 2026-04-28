import { useEffect } from 'react';
import { View, ActivityIndicator, StyleSheet } from 'react-native';
import { useRouter } from 'expo-router';
import { useAuth } from '../src/auth';
import { colors } from '../src/theme';

export default function Index() {
  const router = useRouter();
  const { token, role, loading } = useAuth();

  useEffect(() => {
    if (loading) return;
    if (!token) router.replace('/login');
    else if (role === 'pharmacy') router.replace('/home');
    else if (role === 'supplier') router.replace('/supplier-dashboard');
  }, [loading, token, role]);

  return (
    <View style={styles.container} testID="splash-loader">
      <ActivityIndicator size="large" color={colors.primary} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.background },
});
