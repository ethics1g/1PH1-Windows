import { useCallback, useState } from 'react';
import {
  View, Text, StyleSheet, FlatList, TouchableOpacity, ActivityIndicator,
  Alert, RefreshControl, ScrollView, Linking,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from 'expo-router';
import { useAuth, apiFetch } from '../src/auth';
import { colors } from '../src/theme';
import ScreenHeader from '../src/ScreenHeader';

const STATUS_META: Record<string, { label: string; color: string; bg: string }> = {
  pending:    { label: 'بانتظار القبول',  color: '#92400e', bg: '#fef3c7' },
  accepted:   { label: 'مقبولة',          color: '#1e40af', bg: '#dbeafe' },
  processing: { label: 'قيد التجهيز',     color: '#7c3aed', bg: '#ede9fe' },
  delivered:  { label: 'تم التسليم',      color: '#0e7490', bg: '#cffafe' },
  completed:  { label: 'مكتملة',          color: '#166534', bg: '#dcfce7' },
  rejected:   { label: 'مرفوضة',          color: '#991b1b', bg: '#fee2e2' },
};
const FILTERS: Array<{ key: string; label: string }> = [
  { key: 'all', label: 'الكل' },
  { key: 'pending', label: 'بانتظار القبول' },
  { key: 'accepted', label: 'مقبولة' },
  { key: 'processing', label: 'قيد التجهيز' },
  { key: 'delivered', label: 'تم التسليم' },
  { key: 'completed', label: 'مكتملة' },
  { key: 'rejected', label: 'مرفوضة' },
];

const fmt = (n: number) => Math.round(n || 0).toLocaleString();

export default function PharmacyOrders() {
  const { token } = useAuth();
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState('all');
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const path = filter === 'all' ? '/pharmacy/orders' : `/pharmacy/orders?status=${filter}`;
      const res: any = await apiFetch(path, {}, token);
      setItems(Array.isArray(res) ? res : []);
    } catch (e: any) { Alert.alert('خطأ', e.message); }
    finally { setLoading(false); setRefreshing(false); }
  }, [token, filter]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const confirmReceipt = async (o: any) => {
    Alert.alert('تأكيد الاستلام', `هل استلمت الطلبية من ${o.supplier_name}؟ سيتم احتساب العمولة (4%) للمذخر بعد التأكيد.`, [
      { text: 'إلغاء', style: 'cancel' },
      { text: 'تأكيد الاستلام', style: 'default', onPress: async () => {
        setBusy(o.id);
        try {
          const res: any = await apiFetch(`/pharmacy/orders/${o.id}/confirm-receipt`, { method: 'PATCH' }, token);
          Alert.alert('✅ تم', `تم إكمال الطلبية. عمولة المذخر: ${fmt(res.commission_amount || 0)} د.ع`);
          await load();
        } catch (e: any) { Alert.alert('خطأ', e.message); }
        finally { setBusy(null); }
      }},
    ]);
  };

  const callSupplier = (phone?: string) => {
    if (!phone) return;
    Linking.openURL(`tel:${phone.replace(/[^\d+]/g, '')}`);
  };

  if (loading) return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;

  return (
    <SafeAreaView style={styles.safe}>
      <ScreenHeader title="طلبياتي" subtitle="تتبع طلبياتك من المذاخر" />
      <View style={styles.tabsWrap}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: 12, gap: 6 }}>
          {FILTERS.map(f => (
            <TouchableOpacity key={f.key} testID={`flt-${f.key}`} style={[styles.tab, filter === f.key && styles.tabOn]} onPress={() => setFilter(f.key)}>
              <Text style={[styles.tabTxt, filter === f.key && styles.tabTxtOn]}>{f.label}</Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
      </View>

      <FlatList
        data={items}
        keyExtractor={(o) => o.id}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
        contentContainerStyle={{ padding: 12, gap: 10, paddingBottom: 30 }}
        ListEmptyComponent={<Text style={styles.empty}>لا توجد طلبيات</Text>}
        renderItem={({ item: o }) => {
          const meta = STATUS_META[o.status] || STATUS_META.pending;
          return (
            <View style={styles.card} testID={`order-${o.id}`}>
              <View style={styles.row}>
                <View style={[styles.pill, { backgroundColor: meta.bg }]}>
                  <Text style={[styles.pillTxt, { color: meta.color }]}>{meta.label}</Text>
                </View>
                <Text style={styles.dateTxt}>{new Date(o.created_at).toLocaleString('ar')}</Text>
              </View>
              <View style={styles.partyRow}>
                <Ionicons name="cube" size={18} color={colors.primary} />
                <View style={{ flex: 1, alignItems: 'flex-end' }}>
                  <Text style={styles.partyName}>{o.supplier_name}</Text>
                </View>
              </View>

              <View style={styles.itemsBox}>
                {(o.items || []).slice(0, 4).map((it: any, i: number) => (
                  <Text key={i} style={styles.itemLine}>• {it.name} × {it.quantity} = {fmt((it.unit_price || 0) * it.quantity)} د.ع</Text>
                ))}
                {(o.items?.length || 0) > 4 && <Text style={styles.muted}>...و {o.items.length - 4} أخرى</Text>}
              </View>

              <View style={styles.totalRow}>
                <Text style={styles.totalLabel}>الإجمالي</Text>
                <Text style={styles.totalVal}>{fmt(o.total)} د.ع</Text>
              </View>

              {o.status === 'rejected' && o.rejection_reason ? (
                <Text style={styles.rejReason}>سبب الرفض: {o.rejection_reason}</Text>
              ) : null}
              {o.status === 'completed' && o.auto_completed ? (
                <Text style={styles.muted}>تم الإكمال تلقائياً بعد 72 ساعة</Text>
              ) : null}

              {o.status === 'delivered' ? (
                <TouchableOpacity testID={`btn-confirm-${o.id}`} style={[styles.actionBtn, styles.successBtn]} onPress={() => confirmReceipt(o)} disabled={busy === o.id}>
                  {busy === o.id ? <ActivityIndicator color="#fff" /> : (
                    <>
                      <Ionicons name="checkmark-done-circle" size={18} color="#fff" />
                      <Text style={styles.actionTxt}>تأكيد الاستلام</Text>
                    </>
                  )}
                </TouchableOpacity>
              ) : null}
            </View>
          );
        }}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  tabsWrap: { paddingVertical: 8, backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  tab: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 18, backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border },
  tabOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  tabTxt: { fontSize: 12, fontWeight: '700', color: colors.textSecondary },
  tabTxtOn: { color: '#fff' },
  card: { backgroundColor: colors.surface, borderRadius: 14, padding: 12, borderWidth: 1, borderColor: colors.border, gap: 8 },
  row: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center' },
  pill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 12 },
  pillTxt: { fontSize: 11, fontWeight: '800' },
  dateTxt: { fontSize: 11, color: colors.textMuted },
  partyRow: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, backgroundColor: colors.background, borderRadius: 10, padding: 8 },
  partyName: { fontSize: 14, fontWeight: '800', color: colors.textPrimary },
  itemsBox: { backgroundColor: colors.background, borderRadius: 10, padding: 8, gap: 2 },
  itemLine: { fontSize: 12, color: colors.textPrimary, textAlign: 'right' },
  totalRow: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', borderTopWidth: 1, borderTopColor: colors.border, paddingTop: 8 },
  totalLabel: { fontSize: 12, color: colors.textSecondary, fontWeight: '700' },
  totalVal: { fontSize: 16, fontWeight: '900', color: colors.primary },
  rejReason: { fontSize: 12, color: '#991b1b', backgroundColor: '#fee2e2', paddingHorizontal: 8, paddingVertical: 4, borderRadius: 8, textAlign: 'right' },
  actionBtn: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 6, paddingVertical: 12, borderRadius: 10 },
  successBtn: { backgroundColor: '#16a34a' },
  actionTxt: { color: '#fff', fontWeight: '800', fontSize: 13 },
  muted: { fontSize: 11, color: colors.textMuted, textAlign: 'center', padding: 4 },
  empty: { textAlign: 'center', color: colors.textMuted, padding: 40 },
});
