import { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator, RefreshControl } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import ScreenHeader from '../../src/ScreenHeader';
import { colors } from '../../src/theme';
import { apiFetch, useAuth } from '../../src/auth';

type Period = 'day' | 'month' | 'year';

export default function ProfitReport() {
  const { token } = useAuth();
  const [period, setPeriod] = useState<Period>('day');
  const [data, setData] = useState<any>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const r: any = await apiFetch(`/accounting/profit-report?period=${period}`, {}, token);
      setData(r);
    } catch { setData(null); }
  }, [period, token]);
  useEffect(() => { load(); }, [load]);

  const fmt = (n: number) => (n || 0).toLocaleString();

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <ScreenHeader title="تقرير الأرباح" subtitle={period === 'day' ? 'يومي (30 يوم)' : period === 'month' ? 'شهري (هذه السنة)' : 'سنوي'} />
      <View style={styles.tabs}>
        {(['day', 'month', 'year'] as Period[]).map(p => (
          <TouchableOpacity key={p} testID={`period-${p}`} onPress={() => setPeriod(p)} style={[styles.tab, period === p && styles.tabOn]}>
            <Text style={[styles.tabTxt, period === p && styles.tabTxtOn]}>{p === 'day' ? 'يومي' : p === 'month' ? 'شهري' : 'سنوي'}</Text>
          </TouchableOpacity>
        ))}
      </View>
      {!data ? <ActivityIndicator style={{ marginTop: 40 }} size="large" color={colors.primary} /> : (
        <ScrollView contentContainerStyle={{ padding: 14 }} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}>
          <View style={styles.grid}>
            <View style={[styles.card, { backgroundColor: '#eef2ff' }]}><Text style={styles.cardLbl}>إيراد</Text><Text style={[styles.cardVal, { color: '#6366f1' }]}>{fmt(data.totals.revenue)}</Text></View>
            <View style={[styles.card, { backgroundColor: '#fef3c7' }]}><Text style={styles.cardLbl}>تكلفة</Text><Text style={[styles.cardVal, { color: '#d97706' }]}>{fmt(data.totals.cost)}</Text></View>
            <View style={[styles.card, { backgroundColor: '#dcfce7' }]}><Text style={styles.cardLbl}>ربح</Text><Text style={[styles.cardVal, { color: '#16a34a' }]}>{fmt(data.totals.profit)}</Text></View>
            <View style={[styles.card, { backgroundColor: '#f1f5f9' }]}><Text style={styles.cardLbl}>فواتير</Text><Text style={[styles.cardVal, { color: '#64748b' }]}>{data.totals.sales_count}</Text></View>
          </View>

          <Text style={styles.section}>تفصيل {period === 'day' ? 'يومي' : period === 'month' ? 'شهري' : 'سنوي'}</Text>
          {data.rows.length === 0 ? <Text style={styles.empty}>لا توجد مبيعات</Text> : data.rows.map((r: any) => (
            <View key={r.period} style={styles.row}>
              <Text style={styles.rowPeriod}>{r.period}</Text>
              <View style={{ flex: 1 }}>
                <View style={styles.rowLine}><Text style={styles.rowLbl}>إيراد</Text><Text style={styles.rowVal}>{fmt(r.revenue)}</Text></View>
                <View style={styles.rowLine}><Text style={styles.rowLbl}>تكلفة</Text><Text style={styles.rowVal}>{fmt(r.cost)}</Text></View>
                <View style={styles.rowLine}><Text style={[styles.rowLbl, { color: '#166534' }]}>ربح</Text><Text style={[styles.rowVal, { color: '#166534', fontWeight: '900' }]}>{fmt(r.profit)}</Text></View>
                <Text style={styles.rowMeta}>{r.sales_count} فواتير</Text>
              </View>
            </View>
          ))}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  tabs: { flexDirection: 'row-reverse', gap: 8, paddingHorizontal: 14, paddingBottom: 10 },
  tab: { paddingHorizontal: 20, paddingVertical: 8, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  tabOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  tabTxt: { fontSize: 13, fontWeight: '700', color: colors.textPrimary },
  tabTxtOn: { color: '#fff' },
  grid: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8 },
  card: { width: '48%', padding: 12, borderRadius: 12, alignItems: 'center' },
  cardLbl: { fontSize: 11, color: colors.textSecondary, fontWeight: '700', marginBottom: 3 },
  cardVal: { fontSize: 18, fontWeight: '900' },
  section: { fontSize: 14, fontWeight: '800', color: colors.textPrimary, marginTop: 20, marginBottom: 10, textAlign: 'right' },
  empty: { textAlign: 'center', color: colors.textMuted, padding: 20 },
  row: { flexDirection: 'row-reverse', gap: 12, backgroundColor: colors.surface, borderRadius: 12, padding: 12, borderWidth: 1, borderColor: colors.border, marginBottom: 8 },
  rowPeriod: { fontSize: 12, fontWeight: '800', color: colors.textPrimary, minWidth: 80, textAlign: 'right' },
  rowLine: { flexDirection: 'row-reverse', justifyContent: 'space-between', marginBottom: 3 },
  rowLbl: { fontSize: 12, color: colors.textSecondary },
  rowVal: { fontSize: 13, fontWeight: '800', color: colors.textPrimary },
  rowMeta: { fontSize: 10, color: colors.textMuted, textAlign: 'right', marginTop: 4 },
});
