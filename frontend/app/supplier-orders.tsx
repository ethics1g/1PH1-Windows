import { useCallback, useState } from 'react';
import {
  View, Text, StyleSheet, FlatList, TouchableOpacity, ActivityIndicator,
  Alert, RefreshControl, ScrollView, Modal, TextInput, KeyboardAvoidingView, Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect, useRouter } from 'expo-router';
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

export default function SupplierOrders() {
  const { token } = useAuth();
  const router = useRouter();
  const [items, setItems] = useState<any[]>([]);
  const [stats, setStats] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState('all');
  const [busy, setBusy] = useState<string | null>(null);
  const [rejectFor, setRejectFor] = useState<any | null>(null);
  const [rejectReason, setRejectReason] = useState('');

  const load = useCallback(async () => {
    try {
      const path = filter === 'all' ? '/supplier/orders' : `/supplier/orders?status=${filter}`;
      const [list, statsRes]: any = await Promise.all([
        apiFetch(path, {}, token),
        apiFetch('/supplier/orders/stats', {}, token),
      ]);
      setItems(Array.isArray(list) ? list : []);
      setStats(statsRes);
    } catch (e: any) {
      Alert.alert('خطأ', e.message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [token, filter]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const doAction = async (id: string, path: 'accept' | 'processing' | 'delivered', confirmMsg?: string) => {
    const go = async () => {
      setBusy(id);
      try {
        await apiFetch(`/supplier/orders/${id}/${path}`, { method: 'PATCH' }, token);
        await load();
      } catch (e: any) {
        Alert.alert('خطأ', e.message);
      } finally { setBusy(null); }
    };
    if (confirmMsg) {
      Alert.alert('تأكيد', confirmMsg, [
        { text: 'إلغاء', style: 'cancel' },
        { text: 'متابعة', style: 'default', onPress: go },
      ]);
    } else { await go(); }
  };

  const submitReject = async () => {
    if (!rejectFor) return;
    setBusy(rejectFor.id);
    try {
      await apiFetch(`/supplier/orders/${rejectFor.id}/reject`, {
        method: 'PATCH', body: JSON.stringify({ reason: rejectReason.trim() || undefined }),
      }, token);
      setRejectFor(null); setRejectReason('');
      await load();
    } catch (e: any) { Alert.alert('خطأ', e.message); }
    finally { setBusy(null); }
  };

  if (loading) return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;

  const visible = filter === 'all' ? items : items.filter(o => o.status === filter);

  const renderActions = (o: any) => {
    const s = o.status;
    if (s === 'pending') {
      return (
        <View style={styles.actionsRow}>
          <TouchableOpacity testID={`btn-reject-${o.id}`} style={[styles.actionBtn, styles.dangerBtn]} onPress={() => { setRejectFor(o); setRejectReason(''); }}>
            <Ionicons name="close-circle" size={16} color="#fff" />
            <Text style={styles.actionTxt}>رفض</Text>
          </TouchableOpacity>
          <TouchableOpacity testID={`btn-accept-${o.id}`} style={[styles.actionBtn, styles.primaryBtn]} onPress={() => doAction(o.id, 'accept', 'هل أنت متأكد من قبول هذه الطلبية؟')} disabled={busy === o.id}>
            {busy === o.id ? <ActivityIndicator color="#fff" size="small" /> : <><Ionicons name="checkmark-circle" size={16} color="#fff" /><Text style={styles.actionTxt}>قبول</Text></>}
          </TouchableOpacity>
        </View>
      );
    }
    if (s === 'accepted') {
      return (
        <View style={styles.actionsRow}>
          <TouchableOpacity testID={`btn-reject-${o.id}`} style={[styles.actionBtn, styles.dangerBtn]} onPress={() => { setRejectFor(o); setRejectReason(''); }}>
            <Text style={styles.actionTxt}>رفض</Text>
          </TouchableOpacity>
          <TouchableOpacity testID={`btn-processing-${o.id}`} style={[styles.actionBtn, styles.purpleBtn]} onPress={() => doAction(o.id, 'processing')} disabled={busy === o.id}>
            <Ionicons name="hourglass" size={16} color="#fff" />
            <Text style={styles.actionTxt}>بدء التجهيز</Text>
          </TouchableOpacity>
        </View>
      );
    }
    if (s === 'processing') {
      return (
        <View style={styles.actionsRow}>
          <TouchableOpacity testID={`btn-delivered-${o.id}`} style={[styles.actionBtn, styles.tealBtn]} onPress={() => doAction(o.id, 'delivered', 'تم تسليم الطلبية للصيدلية؟')} disabled={busy === o.id}>
            <Ionicons name="checkmark-done" size={16} color="#fff" />
            <Text style={styles.actionTxt}>تم التسليم</Text>
          </TouchableOpacity>
        </View>
      );
    }
    if (s === 'delivered') {
      return <Text style={styles.muted}>بانتظار تأكيد الاستلام من الصيدلية (تلقائي بعد 72 ساعة)</Text>;
    }
    return null;
  };

  return (
    <SafeAreaView style={styles.safe}>
      <ScreenHeader title="طلبياتي" subtitle={`الإيرادات: ${fmt(stats?.completed_total || 0)} د.ع · العمولة: ${fmt(stats?.commission_due_total || 0)} د.ع`} />

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
        data={visible}
        keyExtractor={(o) => o.id}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
        contentContainerStyle={{ padding: 12, gap: 10, paddingBottom: 30 }}
        ListEmptyComponent={<Text style={styles.empty}>لا توجد طلبيات</Text>}
        renderItem={({ item: o }) => {
          const meta = STATUS_META[o.status] || STATUS_META.pending;
          const hidePharm = o.status === 'pending';
          return (
            <View style={styles.card} testID={`order-${o.id}`}>
              <View style={styles.row}>
                <View style={[styles.pill, { backgroundColor: meta.bg }]}>
                  <Text style={[styles.pillTxt, { color: meta.color }]}>{meta.label}</Text>
                </View>
                <Text style={styles.dateTxt}>{new Date(o.created_at).toLocaleString('ar')}</Text>
              </View>
              <View style={styles.partyRow}>
                <Ionicons name={hidePharm ? 'lock-closed' : 'business'} size={18} color={hidePharm ? colors.warning : colors.primary} />
                <View style={{ flex: 1, alignItems: 'flex-end' }}>
                  <Text style={styles.partyName}>
                    {hidePharm ? '— محجوب حتى القبول —' : (o.pharmacy_name || 'صيدلية')}
                  </Text>
                  {!hidePharm && o.pharmacy_phone ? <Text style={styles.partyMeta}>{o.pharmacy_phone}</Text> : null}
                  {o.pharmacy_region ? <Text style={styles.partyMeta}>📍 {o.pharmacy_region}{o.pharmacy_country ? ` · ${o.pharmacy_country}` : ''}</Text> : null}
                </View>
              </View>

              <View style={styles.itemsBox}>
                {(o.items || []).slice(0, 4).map((it: any, i: number) => (
                  <Text key={i} style={styles.itemLine}>• {it.name} × {it.quantity} = {fmt((it.unit_price || 0) * it.quantity)} د.ع</Text>
                ))}
                {(o.items?.length || 0) > 4 && <Text style={styles.muted}>...و {o.items.length - 4} أخرى</Text>}
              </View>

              <View style={styles.totalRow}>
                <Text style={styles.totalLabel}>إجمالي الطلبية</Text>
                <Text style={styles.totalVal}>{fmt(o.total)} د.ع</Text>
              </View>
              {o.status === 'completed' && o.commission_amount ? (
                <Text style={styles.commissionTxt}>💰 العمولة المستحقة (4%): {fmt(o.commission_amount)} د.ع</Text>
              ) : null}
              {o.status === 'rejected' && o.rejection_reason ? (
                <Text style={styles.rejReason}>سبب الرفض: {o.rejection_reason}</Text>
              ) : null}

              {renderActions(o)}
            </View>
          );
        }}
      />

      <Modal visible={!!rejectFor} animationType="slide" transparent onRequestClose={() => setRejectFor(null)}>
        <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
          <View style={styles.modalWrap}>
            <View style={styles.modal}>
              <Text style={styles.modalTitle}>سبب الرفض (اختياري)</Text>
              <TextInput
                testID="reject-reason"
                style={styles.input}
                value={rejectReason}
                onChangeText={setRejectReason}
                placeholder="مثال: نفاد المخزون، خارج منطقة التغطية..."
                placeholderTextColor={colors.textMuted}
                textAlign="right"
                multiline
              />
              <View style={{ flexDirection: 'row-reverse', gap: 8, marginTop: 12 }}>
                <TouchableOpacity style={[styles.actionBtn, { flex: 1, backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border }]} onPress={() => setRejectFor(null)}>
                  <Text style={[styles.actionTxt, { color: colors.textPrimary }]}>إلغاء</Text>
                </TouchableOpacity>
                <TouchableOpacity testID="reject-confirm" style={[styles.actionBtn, styles.dangerBtn, { flex: 1 }]} onPress={submitReject} disabled={busy === rejectFor?.id}>
                  {busy === rejectFor?.id ? <ActivityIndicator color="#fff" /> : <Text style={styles.actionTxt}>تأكيد الرفض</Text>}
                </TouchableOpacity>
              </View>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>
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
  partyMeta: { fontSize: 11, color: colors.textSecondary },
  itemsBox: { backgroundColor: colors.background, borderRadius: 10, padding: 8, gap: 2 },
  itemLine: { fontSize: 12, color: colors.textPrimary, textAlign: 'right' },
  totalRow: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', borderTopWidth: 1, borderTopColor: colors.border, paddingTop: 8 },
  totalLabel: { fontSize: 12, color: colors.textSecondary, fontWeight: '700' },
  totalVal: { fontSize: 16, fontWeight: '900', color: colors.primary },
  commissionTxt: { fontSize: 12, color: '#166534', backgroundColor: '#dcfce7', paddingHorizontal: 8, paddingVertical: 4, borderRadius: 8, textAlign: 'right' },
  rejReason: { fontSize: 12, color: '#991b1b', backgroundColor: '#fee2e2', paddingHorizontal: 8, paddingVertical: 4, borderRadius: 8, textAlign: 'right' },
  actionsRow: { flexDirection: 'row-reverse', gap: 8, marginTop: 4 },
  actionBtn: { flex: 1, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 6, paddingVertical: 10, borderRadius: 10 },
  primaryBtn: { backgroundColor: colors.primary },
  dangerBtn: { backgroundColor: colors.error },
  purpleBtn: { backgroundColor: '#7c3aed' },
  tealBtn: { backgroundColor: '#0e7490' },
  actionTxt: { color: '#fff', fontWeight: '800', fontSize: 13 },
  muted: { fontSize: 11, color: colors.textMuted, textAlign: 'center', padding: 4 },
  empty: { textAlign: 'center', color: colors.textMuted, padding: 40 },
  modalWrap: { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', justifyContent: 'flex-end' },
  modal: { backgroundColor: '#fff', borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: 20 },
  modalTitle: { fontSize: 16, fontWeight: '800', color: colors.textPrimary, textAlign: 'right', marginBottom: 10 },
  input: { backgroundColor: colors.background, borderRadius: 10, padding: 12, minHeight: 80, borderWidth: 1, borderColor: colors.border, color: colors.textPrimary },
});
