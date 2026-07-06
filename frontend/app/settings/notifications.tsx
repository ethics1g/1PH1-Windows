import { useEffect, useState } from 'react';
import { View, Text, StyleSheet, Switch, ScrollView, ActivityIndicator, Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import ScreenHeader from '../../src/ScreenHeader';
import { colors } from '../../src/theme';
import { apiFetch, useAuth } from '../../src/auth';

type Prefs = {
  notifications_enabled: boolean;
  expiry_reminders: boolean;
  weekly_expired_report: boolean;
  admin_announcements: boolean;
  order_updates: boolean;
};

export default function NotificationPreferences() {
  const { token } = useAuth();
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const p: any = await apiFetch('/me/notification-preferences', {}, token);
        setPrefs({
          notifications_enabled: !!p.notifications_enabled,
          expiry_reminders: !!p.expiry_reminders,
          weekly_expired_report: !!p.weekly_expired_report,
          admin_announcements: !!p.admin_announcements,
          order_updates: !!p.order_updates,
        });
      } catch (e: any) { Alert.alert('خطأ', e.message); }
      finally { setLoading(false); }
    })();
  }, [token]);

  const set = async (key: keyof Prefs, val: boolean) => {
    if (!prefs) return;
    const optimistic = { ...prefs, [key]: val };
    setPrefs(optimistic);
    try {
      await apiFetch('/me/notification-preferences', { method: 'PUT', body: JSON.stringify({ [key]: val }) }, token);
    } catch (e: any) {
      setPrefs(prefs); // rollback
      Alert.alert('خطأ', e.message);
    }
  };

  if (loading || !prefs) return <SafeAreaView style={styles.safe}><ActivityIndicator style={{ marginTop: 60 }} size="large" color={colors.primary} /></SafeAreaView>;

  const master = prefs.notifications_enabled;

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <ScreenHeader title="تفضيلات الإشعارات" />
      <ScrollView contentContainerStyle={{ padding: 14 }}>
        <Row icon="notifications" title="الإشعارات" sub="تفعيل أو إيقاف جميع الإشعارات" value={master}
             onChange={(v) => set('notifications_enabled', v)} testID="pref-master" />

        <Text style={styles.section}>أنواع الإشعارات</Text>

        <Row icon="alarm" title="تذكيرات انتهاء الصلاحية" sub="90 · 30 · 7 · 1 يوم قبل الانتهاء"
             value={prefs.expiry_reminders} disabled={!master}
             onChange={(v) => set('expiry_reminders', v)} testID="pref-expiry" />
        <Row icon="warning" title="التقرير الأسبوعي" sub="قائمة الأدوية المنتهية كل 7 أيام"
             value={prefs.weekly_expired_report} disabled={!master}
             onChange={(v) => set('weekly_expired_report', v)} testID="pref-weekly" />
        <Row icon="shield-checkmark" title="إعلانات الإدارة" sub="إشعارات من مسؤول النظام"
             value={prefs.admin_announcements} disabled={!master}
             onChange={(v) => set('admin_announcements', v)} testID="pref-admin" />
        <Row icon="receipt" title="تحديثات الطلبيات" sub="قبول/تجهيز/تسليم الطلبيات"
             value={prefs.order_updates} disabled={!master}
             onChange={(v) => set('order_updates', v)} testID="pref-orders" />
      </ScrollView>
    </SafeAreaView>
  );
}

function Row({ icon, title, sub, value, onChange, disabled, testID }: any) {
  return (
    <View style={styles.row}>
      <View style={[styles.iconBox, disabled ? { opacity: 0.35 } : null]}><Ionicons name={icon} size={20} color={colors.indigo} /></View>
      <View style={{ flex: 1 }}>
        <Text style={[styles.title, disabled ? { opacity: 0.4 } : null]}>{title}</Text>
        <Text style={[styles.sub, disabled ? { opacity: 0.4 } : null]}>{sub}</Text>
      </View>
      <Switch testID={testID} value={value} onValueChange={onChange} disabled={disabled} trackColor={{ true: colors.primary, false: colors.border }} thumbColor="#fff" />
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  section: { fontSize: 13, color: colors.textMuted, marginTop: 16, marginBottom: 8, textAlign: 'right', fontWeight: '800' },
  row: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12, padding: 14, backgroundColor: colors.surface, borderRadius: 14, borderWidth: 1, borderColor: colors.border, marginBottom: 10 },
  iconBox: { width: 42, height: 42, borderRadius: 21, backgroundColor: colors.indigoLight, alignItems: 'center', justifyContent: 'center' },
  title: { fontSize: 14, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  sub: { fontSize: 12, color: colors.textMuted, textAlign: 'right', marginTop: 2 },
});
