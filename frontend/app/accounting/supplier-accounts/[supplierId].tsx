import { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, ActivityIndicator, RefreshControl } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams } from 'expo-router';
import ScreenHeader from '../../../src/ScreenHeader';
import { colors } from '../../../src/theme';
import { apiFetch, useAuth } from '../../../src/auth';

export default function SupplierAccountDetail() {
  const { supplierId } = useLocalSearchParams<{ supplierId: string }>();
  const { token } = useAuth();
  const [data, setData] = useState<any>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    if (!supplierId) return;
    try {
      const r: any = await apiFetch(`/accounting/supplier-accounts/${supplierId}`, {}, token);
      setData(r);
    } catch { setData(null); }
  }, [supplierId, token]);

  useEffect(() => { load(); }, [load]);

  if (!data) return <SafeAreaView style={styles.safe}><ActivityIndicator style={{ marginTop: 60 }} size="large" color={colors.primary} /></SafeAreaView>;

  const a = data.account;
  const fmt = (n: number) => (n || 0).toLocaleString() + ' د.ع';

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <ScreenHeader title={a.supplier?.name || 'حساب المذخر'} subtitle={a.supplier?.phone || ''} />
      <ScrollView contentContainerStyle={{ padding: 14 }} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}>
        {/* Cards */}
        <View style={styles.grid}>
          <View style={[styles.card, { backgroundColor: '#eef2ff' }]}>
            <Text style={styles.cardLbl}>الإجمالي المُشترى</Text>
            <Text style={[styles.cardVal, { color: '#6366f1' }]}>{fmt(a.total_purchased)}</Text>
          </View>
          <View style={[styles.card, { backgroundColor: '#fef3c7' }]}>
            <Text style={styles.cardLbl}>مطبَّق كإرجاعات</Text>
            <Text style={[styles.cardVal, { color: '#d97706' }]}>{fmt(a.credit_applied_total)}</Text>
          </View>
          <View style={[styles.card, { backgroundColor: a.outstanding_balance > 0 ? '#fee2e2' : '#dcfce7' }]}>
            <Text style={styles.cardLbl}>مُتبقٍّ للدفع</Text>
            <Text style={[styles.cardVal, { color: a.outstanding_balance > 0 ? '#dc2626' : '#16a34a' }]}>{fmt(a.outstanding_balance)}</Text>
          </View>
          <View style={[styles.card, { backgroundColor: '#dcfce7' }]}>
            <Text style={styles.cardLbl}>رصيد دائن متاح</Text>
            <Text style={[styles.cardVal, { color: '#16a34a' }]}>{fmt(a.available_credit)}</Text>
          </View>
        </View>

        {/* Ledger */}
        <Text style={styles.section}>سجل الحساب ({data.ledger?.length || 0})</Text>
        {(data.ledger || []).length === 0 ? (
          <Text style={styles.emptyTxt}>لا توجد حركات محاسبية بعد</Text>
        ) : data.ledger.map((l: any) => (
          <View key={l.id} style={styles.ledgerRow}>
            <View style={[styles.ledgerIcon, { backgroundColor: '#dcfce7' }]}>
              <Ionicons name="return-up-back" size={18} color="#16a34a" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.ledgerDesc}>{l.description}</Text>
              <Text style={styles.ledgerDate}>{new Date(l.created_at).toLocaleString('ar-EG', { hour12: false })}</Text>
              {l.excess_to_credit > 0 ? <Text style={styles.excess}>فائض → رصيد دائن: {fmt(l.excess_to_credit)}</Text> : null}
            </View>
            <Text style={styles.ledgerAmt}>-{fmt(l.amount)}</Text>
          </View>
        ))}

        {/* Related returns */}
        {(data.returns || []).length > 0 ? (
          <>
            <Text style={styles.section}>الرواجع المكتملة ({data.returns.length})</Text>
            {data.returns.map((r: any) => (
              <View key={r.id} style={styles.item}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.itemName}>{(r.items || []).map((it: any) => it.name).join(' · ')}</Text>
                  <Text style={styles.itemDate}>{new Date(r.completed_at || r.created_at).toLocaleDateString('ar-EG')}</Text>
                </View>
                <Text style={styles.itemAmt}>{fmt(r.total)}</Text>
              </View>
            ))}
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  grid: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8 },
  card: { width: '48%', padding: 12, borderRadius: 14, alignItems: 'center' },
  cardLbl: { fontSize: 11, color: colors.textSecondary, fontWeight: '700', marginBottom: 4 },
  cardVal: { fontSize: 16, fontWeight: '900' },
  section: { fontSize: 14, fontWeight: '800', color: colors.textPrimary, marginTop: 20, marginBottom: 10, textAlign: 'right' },
  emptyTxt: { fontSize: 13, color: colors.textMuted, textAlign: 'center', padding: 20 },
  ledgerRow: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, backgroundColor: colors.surface, borderRadius: 12, padding: 10, borderWidth: 1, borderColor: colors.border, marginBottom: 6 },
  ledgerIcon: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center' },
  ledgerDesc: { fontSize: 13, fontWeight: '700', color: colors.textPrimary, textAlign: 'right' },
  ledgerDate: { fontSize: 11, color: colors.textMuted, textAlign: 'right', marginTop: 2 },
  excess: { fontSize: 11, color: '#16a34a', fontWeight: '700', marginTop: 2, textAlign: 'right' },
  ledgerAmt: { fontSize: 14, fontWeight: '900', color: '#16a34a' },
  item: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, backgroundColor: colors.surface, borderRadius: 12, padding: 10, borderWidth: 1, borderColor: colors.border, marginBottom: 6 },
  itemName: { fontSize: 13, fontWeight: '700', color: colors.textPrimary, textAlign: 'right' },
  itemDate: { fontSize: 11, color: colors.textMuted, textAlign: 'right', marginTop: 2 },
  itemAmt: { fontSize: 13, fontWeight: '900', color: colors.primary },
});
