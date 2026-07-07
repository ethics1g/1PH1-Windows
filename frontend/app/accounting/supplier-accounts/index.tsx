import { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator, RefreshControl } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import ScreenHeader from '../../../src/ScreenHeader';
import { colors } from '../../../src/theme';
import { apiFetch, useAuth } from '../../../src/auth';

export default function SupplierAccounts() {
  const router = useRouter();
  const { token } = useAuth();
  const [data, setData] = useState<any>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const r: any = await apiFetch('/accounting/supplier-accounts', {}, token);
      setData(r);
    } catch { setData({ items: [], total_outstanding: 0, total_available_credit: 0 }); }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  if (!data) return <SafeAreaView style={styles.safe}><ActivityIndicator style={{ marginTop: 60 }} size="large" color={colors.primary} /></SafeAreaView>;

  const fmt = (n: number) => (n || 0).toLocaleString() + ' د.ع';

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <ScreenHeader title="حسابات المذاخر" subtitle={`${data.items?.length || 0} مذخر`} />
      <ScrollView contentContainerStyle={{ padding: 14 }} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}>
        <View style={styles.grid}>
          <View style={[styles.card, { backgroundColor: '#fee2e2' }]}>
            <Text style={styles.cardLbl}>إجمالي مستحق للدفع</Text>
            <Text style={[styles.cardVal, { color: '#dc2626' }]}>{fmt(data.total_outstanding)}</Text>
          </View>
          <View style={[styles.card, { backgroundColor: '#dcfce7' }]}>
            <Text style={styles.cardLbl}>رصيد دائن متاح</Text>
            <Text style={[styles.cardVal, { color: '#16a34a' }]}>{fmt(data.total_available_credit)}</Text>
          </View>
        </View>

        {(data.items || []).length === 0 ? (
          <View style={styles.empty}>
            <Ionicons name="storefront-outline" size={54} color={colors.textMuted} />
            <Text style={styles.emptyTxt}>لا توجد طلبيات مكتملة مع أي مذخر بعد</Text>
          </View>
        ) : (data.items || []).map((it: any) => (
          <TouchableOpacity key={it.supplier_id} testID={`sa-${it.supplier_id}`} style={styles.item} onPress={() => router.push(`/accounting/supplier-accounts/${it.supplier_id}` as any)}>
            <View style={{ flex: 1 }}>
              <Text style={styles.supName}>{it.supplier_name || 'مذخر'}</Text>
              <Text style={styles.supMeta}>{it.order_count} طلبية · مُشترى: {fmt(it.total_purchased)}</Text>
              {it.available_credit > 0 ? (
                <Text style={styles.credit}>💰 رصيد دائن: {fmt(it.available_credit)}</Text>
              ) : null}
            </View>
            <View style={{ alignItems: 'flex-start' }}>
              <Text style={styles.outLbl}>مُتبقٍّ</Text>
              <Text style={[styles.outVal, it.outstanding_balance > 0 ? { color: '#dc2626' } : { color: '#16a34a' }]}>
                {fmt(it.outstanding_balance)}
              </Text>
            </View>
            <Ionicons name="chevron-back" size={20} color={colors.textMuted} />
          </TouchableOpacity>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  grid: { flexDirection: 'row-reverse', gap: 10, marginBottom: 18 },
  card: { flex: 1, padding: 14, borderRadius: 14, alignItems: 'center' },
  cardLbl: { fontSize: 11, color: colors.textSecondary, fontWeight: '700', marginBottom: 4 },
  cardVal: { fontSize: 18, fontWeight: '900' },
  item: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, backgroundColor: colors.surface, borderRadius: 14, padding: 12, borderWidth: 1, borderColor: colors.border, marginBottom: 8 },
  supName: { fontSize: 15, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  supMeta: { fontSize: 11, color: colors.textMuted, textAlign: 'right', marginTop: 3 },
  credit: { fontSize: 12, color: '#16a34a', fontWeight: '700', marginTop: 3, textAlign: 'right' },
  outLbl: { fontSize: 10, color: colors.textMuted },
  outVal: { fontSize: 15, fontWeight: '900' },
  empty: { alignItems: 'center', padding: 40, gap: 12 },
  emptyTxt: { fontSize: 13, color: colors.textMuted, textAlign: 'center' },
});
