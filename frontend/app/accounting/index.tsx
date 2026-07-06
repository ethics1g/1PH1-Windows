import { useCallback, useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator, RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import ScreenHeader from '../../src/ScreenHeader';
import { colors } from '../../src/theme';
import { apiFetch, useAuth } from '../../src/auth';

export default function AccountingDashboard() {
  const router = useRouter();
  const { token } = useAuth();
  const [summary, setSummary] = useState<any>(null);
  const [inv, setInv] = useState<any>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, i]: any = await Promise.all([
        apiFetch('/accounting/summary', {}, token),
        apiFetch('/accounting/inventory-value', {}, token),
      ]);
      setSummary(s); setInv(i);
    } catch (e) { console.log('load err', e); }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const fmt = (n: number) => (n || 0).toLocaleString('en-US') + ' د.ع';

  if (!summary || !inv) {
    return <SafeAreaView style={styles.safe}><ActivityIndicator style={{ marginTop: 60 }} size="large" color={colors.primary} /></SafeAreaView>;
  }

  const cards = [
    { icon: 'today', title: 'ربح اليوم', value: fmt(summary.today.profit), sub: `مبيعات: ${fmt(summary.today.revenue)}`, color: '#16a34a', bg: '#dcfce7' },
    { icon: 'calendar', title: 'ربح الشهر', value: fmt(summary.month.profit), sub: `مبيعات: ${fmt(summary.month.revenue)}`, color: '#0ea5e9', bg: '#e0f2fe' },
    { icon: 'cube', title: 'قيمة المخزون', value: fmt(inv.purchase_value), sub: `${inv.units} وحدة · ${inv.sku_count} صنف`, color: '#6366f1', bg: '#eef2ff' },
    { icon: 'people', title: 'إجمالي الديون', value: fmt(summary.outstanding_debts), sub: 'اضغط للعرض', color: '#dc2626', bg: '#fee2e2', onPress: () => router.push('/customers' as any) },
  ];

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <ScreenHeader title="المحاسبة" subtitle="ملخص الأرباح والمخزون والديون" />
      <ScrollView
        contentContainerStyle={{ padding: 14, paddingBottom: 40 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
      >
        <View style={styles.grid}>
          {cards.map((c, idx) => (
            <TouchableOpacity key={idx} testID={`acc-card-${idx}`} style={[styles.card, { backgroundColor: c.bg }]} onPress={c.onPress} disabled={!c.onPress} activeOpacity={c.onPress ? 0.7 : 1}>
              <View style={[styles.cardIcon, { backgroundColor: c.color }]}><Ionicons name={c.icon as any} size={20} color="#fff" /></View>
              <Text style={styles.cardTitle}>{c.title}</Text>
              <Text style={[styles.cardValue, { color: c.color }]}>{c.value}</Text>
              <Text style={styles.cardSub}>{c.sub}</Text>
            </TouchableOpacity>
          ))}
        </View>

        <Text style={styles.sectionTitle}>تقييم المخزون</Text>
        <View style={styles.invBox}>
          <Row label="قيمة الشراء" value={fmt(inv.purchase_value)} />
          <Row label="قيمة البيع" value={fmt(inv.selling_value)} />
          <Row label="الربح المتوقع عند البيع" value={fmt(inv.expected_profit)} highlight />
          <Row label="عدد الأصناف" value={String(inv.sku_count)} />
          <Row label="إجمالي الوحدات" value={String(inv.units)} />
        </View>

        <Text style={styles.sectionTitle}>المبيعات</Text>
        <View style={styles.invBox}>
          <Row label="مبيعات اليوم" value={`${summary.today.sales_count} فاتورة`} />
          <Row label="إيرادات اليوم" value={fmt(summary.today.revenue)} />
          <Row label="ربح اليوم" value={fmt(summary.today.profit)} highlight />
          <Row label="إيرادات الشهر" value={fmt(summary.month.revenue)} />
          <Row label="ربح الشهر" value={fmt(summary.month.profit)} highlight />
        </View>

        <TouchableOpacity testID="btn-customers" style={styles.actionBtn} onPress={() => router.push('/customers' as any)}>
          <Ionicons name="people" size={18} color="#fff" />
          <Text style={styles.actionTxt}>ديون الزبائن</Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

function Row({ label, value, highlight }: any) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLbl}>{label}</Text>
      <Text style={[styles.rowVal, highlight && { color: colors.primary }]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  grid: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 10 },
  card: { width: '48%', padding: 14, borderRadius: 16, gap: 6 },
  cardIcon: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  cardTitle: { fontSize: 12, color: colors.textSecondary, fontWeight: '700' },
  cardValue: { fontSize: 18, fontWeight: '900' },
  cardSub: { fontSize: 10, color: colors.textMuted },
  sectionTitle: { fontSize: 14, fontWeight: '800', color: colors.textPrimary, marginTop: 20, marginBottom: 8, textAlign: 'right' },
  invBox: { backgroundColor: colors.surface, borderRadius: 14, borderWidth: 1, borderColor: colors.border, padding: 12 },
  row: { flexDirection: 'row-reverse', justifyContent: 'space-between', paddingVertical: 8 },
  rowLbl: { fontSize: 13, color: colors.textSecondary, textAlign: 'right' },
  rowVal: { fontSize: 14, fontWeight: '800', color: colors.textPrimary },
  actionBtn: { flexDirection: 'row-reverse', gap: 8, backgroundColor: colors.primary, borderRadius: 14, paddingVertical: 14, alignItems: 'center', justifyContent: 'center', marginTop: 20 },
  actionTxt: { color: '#fff', fontSize: 15, fontWeight: '800' },
});
