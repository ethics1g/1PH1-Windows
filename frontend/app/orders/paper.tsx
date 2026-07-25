import { useCallback, useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, FlatList, TouchableOpacity, ActivityIndicator,
  RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import ScreenHeader from '../../src/ScreenHeader';
import { colors } from '../../src/theme';
import { apiFetch, useAuth } from '../../src/auth';

type Status = 'all' | 'unpaid' | 'partial' | 'paid';

export default function PaperOrdersList() {
  const router = useRouter();
  const { token } = useAuth();
  const [items, setItems] = useState<any[]>([]);
  const [status, setStatus] = useState<Status>('all');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const qs = status === 'all' ? '' : `?status=${status}`;
      const r: any = await apiFetch(`/orders/paper${qs}`, {}, token);
      setItems(r.items || []);
    } catch { setItems([]); }
  }, [status, token]);

  useEffect(() => { setLoading(true); load().finally(() => setLoading(false)); }, [load]);

  const totalRemaining = items.reduce((s, o) => s + (o.remaining || 0), 0);

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <ScreenHeader title="طلبيات مصورة" subtitle={`${items.length} طلبية · متبقي: ${totalRemaining.toLocaleString()} د.ع`} />

      <View style={styles.tabs}>
        {(['all', 'unpaid', 'partial', 'paid'] as const).map((s) => (
          <TouchableOpacity key={s} testID={`tab-${s}`} onPress={() => setStatus(s)}
            style={[styles.tab, status === s && styles.tabActive]}>
            <Text style={[styles.tabTxt, status === s && styles.tabTxtActive]}>{tabLabel(s)}</Text>
          </TouchableOpacity>
        ))}
      </View>

      {loading ? (
        <ActivityIndicator style={{ marginTop: 40 }} size="large" color={colors.primary} />
      ) : items.length === 0 ? (
        <View style={styles.empty}>
          <Ionicons name="document-outline" size={54} color={colors.textMuted} />
          <Text style={styles.emptyTxt}>لا توجد طلبيات مصورة بعد</Text>
          <TouchableOpacity testID="btn-scan-cta" style={styles.ctaBtn} onPress={() => router.push('/orders/scan' as any)}>
            <Ionicons name="scan-outline" size={20} color="#fff" />
            <Text style={styles.ctaTxt}>ارفع صورة طلبية</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <FlatList
          data={items}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: 12, gap: 10 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
          renderItem={({ item }) => (
            <TouchableOpacity testID={`po-${item.id}`} style={styles.card}
              onPress={() => router.push(`/orders/paper/${item.id}` as any)}>
              <View style={styles.rowTop}>
                <View style={[styles.badge, badgeStyle(item.payment_status)]}>
                  <Text style={styles.badgeTxt}>{statusLabel(item.payment_status)}</Text>
                </View>
                <Text style={styles.orderNum}>{item.order_number}</Text>
              </View>
              <Text style={styles.supplier}>{item.supplier_name || 'مذخر غير محدد'}</Text>
              <View style={styles.metaRow}>
                <Text style={styles.metaLbl}>الإجمالي: <Text style={styles.metaVal}>{(item.total || 0).toLocaleString()}</Text></Text>
                <Text style={styles.metaLbl}>المدفوع: <Text style={[styles.metaVal, { color: '#16a34a' }]}>{(item.amount_paid || 0).toLocaleString()}</Text></Text>
                <Text style={styles.metaLbl}>المتبقي: <Text style={[styles.metaVal, item.remaining > 0 ? { color: '#dc2626' } : { color: '#16a34a' }]}>{(item.remaining || 0).toLocaleString()}</Text></Text>
              </View>
              <Text style={styles.date}>{new Date(item.created_at).toLocaleDateString('ar-EG')} · {item.items?.length || 0} صنف</Text>
            </TouchableOpacity>
          )}
        />
      )}

      <TouchableOpacity testID="fab-scan" style={styles.fab} onPress={() => router.push('/orders/scan' as any)}>
        <Ionicons name="scan-outline" size={26} color="#fff" />
      </TouchableOpacity>
    </SafeAreaView>
  );
}

function tabLabel(s: Status) {
  return s === 'all' ? 'الكل' : s === 'unpaid' ? 'غير مدفوعة' : s === 'partial' ? 'جزئية' : 'مدفوعة';
}
function statusLabel(s: string) {
  return s === 'paid' ? 'مدفوعة بالكامل' : s === 'partial' ? 'مدفوعة جزئياً' : 'غير مدفوعة';
}
function badgeStyle(s: string) {
  return s === 'paid' ? styles.badgePaid : s === 'partial' ? styles.badgePartial : styles.badgeUnpaid;
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  tabs: { flexDirection: 'row-reverse', gap: 6, paddingHorizontal: 12, paddingVertical: 10 },
  tab: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  tabActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  tabTxt: { fontSize: 12, color: colors.textPrimary, fontWeight: '700' },
  tabTxtActive: { color: '#fff' },
  empty: { alignItems: 'center', marginTop: 60, gap: 14 },
  emptyTxt: { fontSize: 14, color: colors.textMuted },
  ctaBtn: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, backgroundColor: colors.primary, paddingHorizontal: 18, paddingVertical: 10, borderRadius: 12 },
  ctaTxt: { color: '#fff', fontSize: 14, fontWeight: '800' },
  card: { backgroundColor: colors.surface, borderRadius: 12, padding: 12, borderWidth: 1, borderColor: colors.border, gap: 4 },
  rowTop: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center' },
  orderNum: { fontSize: 12, fontWeight: '800', color: colors.textPrimary },
  supplier: { fontSize: 15, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  metaRow: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 12, marginTop: 4 },
  metaLbl: { fontSize: 12, color: colors.textSecondary },
  metaVal: { fontWeight: '800', color: colors.textPrimary },
  date: { fontSize: 11, color: colors.textMuted, marginTop: 4, textAlign: 'right' },
  badge: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999 },
  badgePaid: { backgroundColor: '#dcfce7' },
  badgePartial: { backgroundColor: '#fef3c7' },
  badgeUnpaid: { backgroundColor: '#fee2e2' },
  badgeTxt: { fontSize: 11, fontWeight: '800', color: colors.textPrimary },
  fab: { position: 'absolute', bottom: 24, left: 24, width: 58, height: 58, borderRadius: 29, backgroundColor: colors.primary, alignItems: 'center', justifyContent: 'center', shadowColor: '#000', shadowOffset: { width: 0, height: 4 }, shadowOpacity: 0.2, shadowRadius: 8, elevation: 6 },
});
