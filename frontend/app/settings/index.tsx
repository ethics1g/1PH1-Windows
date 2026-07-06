import { View, Text, StyleSheet, TouchableOpacity, ScrollView, Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import ScreenHeader from '../../src/ScreenHeader';
import { colors } from '../../src/theme';
import { useAuth } from '../../src/auth';

export default function Settings() {
  const router = useRouter();
  const { user, signOut } = useAuth();

  const rows: Array<{ icon: keyof typeof Ionicons.glyphMap; label: string; sub?: string; route?: string; onPress?: () => void; testID: string; danger?: boolean }> = [
    { icon: 'person-circle', label: 'المعلومات الشخصية', sub: 'الاسم والبريد الإلكتروني', route: '/settings/personal', testID: 'row-personal' },
    { icon: 'notifications', label: 'مركز الإشعارات', sub: 'جميع الإشعارات', route: '/notifications', testID: 'row-notif-center' },
    { icon: 'options', label: 'تفضيلات الإشعارات', sub: 'تفعيل/إيقاف أنواع الإشعارات', route: '/settings/notifications', testID: 'row-notif-prefs' },
    { icon: 'key', label: 'تغيير كلمة السر', sub: 'كلمة سر آمنة', route: '/settings/password', testID: 'row-password' },
    { icon: 'log-out-outline', label: 'تسجيل الخروج', route: undefined, onPress: () => {
        Alert.alert('تسجيل الخروج', 'هل تريد تسجيل الخروج؟', [
          { text: 'إلغاء', style: 'cancel' },
          { text: 'خروج', style: 'destructive', onPress: async () => { await signOut(); router.replace('/login' as any); } },
        ]);
      }, testID: 'row-logout', danger: true },
  ];

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <ScreenHeader title="إعدادات الحساب" subtitle={user?.name || ''} />
      <ScrollView contentContainerStyle={{ padding: 14 }}>
        <View style={styles.userCard}>
          <View style={styles.avatar}><Ionicons name="person" size={28} color="#fff" /></View>
          <View style={{ flex: 1 }}>
            <Text style={styles.userName}>{user?.name || '-'}</Text>
            <Text style={styles.userSub}>{user?.phone || ''}</Text>
          </View>
        </View>

        {rows.map((r) => (
          <TouchableOpacity key={r.testID} testID={r.testID} style={styles.row} onPress={() => r.route ? router.push(r.route as any) : r.onPress?.()}>
            <View style={[styles.rowIcon, r.danger ? { backgroundColor: '#fee2e2' } : null]}>
              <Ionicons name={r.icon} size={20} color={r.danger ? colors.error : colors.indigo} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={[styles.rowLabel, r.danger && { color: colors.error }]}>{r.label}</Text>
              {r.sub ? <Text style={styles.rowSub}>{r.sub}</Text> : null}
            </View>
            <Ionicons name="chevron-back" size={18} color={colors.textMuted} />
          </TouchableOpacity>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  userCard: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12, padding: 16, backgroundColor: colors.surface, borderRadius: 16, borderWidth: 1, borderColor: colors.border, marginBottom: 16 },
  avatar: { width: 60, height: 60, borderRadius: 30, backgroundColor: colors.indigo, alignItems: 'center', justifyContent: 'center' },
  userName: { fontSize: 17, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  userSub: { fontSize: 13, color: colors.textSecondary, textAlign: 'right' },
  row: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12, padding: 14, backgroundColor: colors.surface, borderRadius: 14, borderWidth: 1, borderColor: colors.border, marginBottom: 10 },
  rowIcon: { width: 42, height: 42, borderRadius: 21, backgroundColor: colors.indigoLight, alignItems: 'center', justifyContent: 'center' },
  rowLabel: { fontSize: 15, fontWeight: '700', color: colors.textPrimary, textAlign: 'right' },
  rowSub: { fontSize: 12, color: colors.textMuted, textAlign: 'right', marginTop: 2 },
});
