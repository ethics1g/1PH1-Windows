import { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Alert, ActivityIndicator, RefreshControl } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams } from 'expo-router';
import ScreenHeader from '../../src/ScreenHeader';
import { colors } from '../../src/theme';
import { apiFetch, useAuth } from '../../src/auth';

const STATUS_META: Record<string, { label: string; color: string; bg: string }> = {
  pending:          { label: 'بانتظار الموافقة', color: '#92400e', bg: '#fef3c7' },
  approved:         { label: 'تمت الموافقة',   color: '#1e40af', bg: '#dbeafe' },
  waiting_receipt:  { label: 'بانتظار استلام',  color: '#7c3aed', bg: '#ede9fe' },
  completed:        { label: 'مكتمل',           color: '#166534', bg: '#dcfce7' },
  rejected:         { label: 'مرفوض',            color: '#991b1b', bg: '#fee2e2' },
};
const REASON_LABELS: any = { expired: 'منتهي', damaged: 'تالف', wrong_item: 'خاطئ', ordered_by_mistake: 'طلب بالخطأ', other: 'أخرى' };

export default function ReturnDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { token, role } = useAuth();
  const [r, setR] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const res: any = await apiFetch(`/returns/${id}`, {}, token);
      setR(res);
    } catch (e: any) { Alert.alert('خطأ', e.message); }
  }, [id, token]);
  useEffect(() => { load(); }, [load]);

  const doAction = async (path: string, confirmMsg: string, body?: any) => {
    Alert.alert('تأكيد', confirmMsg, [
      { text: 'إلغاء', style: 'cancel' },
      { text: 'تأكيد', onPress: async () => {
          setBusy(true);
          try {
            await apiFetch(path, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined }, token);
            await load();
          } catch (e: any) { Alert.alert('خطأ', e.message); }
          finally { setBusy(false); }
        }},
    ]);
  };

  if (!r) return <SafeAreaView style={styles.safe}><ActivityIndicator style={{ marginTop: 60 }} size="large" color={colors.primary} /></SafeAreaView>;
  const meta = STATUS_META[r.status] || STATUS_META.pending;

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <ScreenHeader title="تفاصيل الإرجاع" subtitle={`قيمة: ${(r.total || 0).toLocaleString()} د.ع`} />
      <ScrollView contentContainerStyle={{ padding: 14 }} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}>
        {/* Status */}
        <View style={[styles.statusBox, { backgroundColor: meta.bg }]}>
          <Text style={[styles.statusTxt, { color: meta.color }]}>{meta.label}</Text>
          {r.rejection_reason ? <Text style={styles.rejReason}>سبب: {r.rejection_reason}</Text> : null}
        </View>

        {/* Meta */}
        <View style={styles.metaBox}>
          <MetaRow label="رقم الطلب الأصلي" value={r.original_order_id.slice(0, 12) + '...'} />
          <MetaRow label={role === 'pharmacy' ? 'المذخر' : 'الصيدلية'} value={role === 'pharmacy' ? (r.supplier_name || '-') : (r.pharmacy_name || '-')} />
          <MetaRow label="السبب" value={REASON_LABELS[r.reason] || r.reason} />
          <MetaRow label="تاريخ الإنشاء" value={new Date(r.created_at).toLocaleString('ar-EG', { hour12: false })} />
          {r.notes ? <MetaRow label="ملاحظات" value={r.notes} /> : null}
        </View>

        {/* Items */}
        <Text style={styles.section}>المنتجات ({(r.items || []).length})</Text>
        {(r.items || []).map((it: any, i: number) => (
          <View key={i} style={styles.item}>
            <View style={{ flex: 1 }}>
              <Text style={styles.itemName}>{it.name}</Text>
              <Text style={styles.itemMeta}>الكمية: {it.quantity} · السعر: {(it.unit_price || 0).toLocaleString()} د.ع</Text>
            </View>
            <Text style={styles.itemTotal}>{(it.quantity * it.unit_price).toLocaleString()}</Text>
          </View>
        ))}

        {/* Timeline */}
        <Text style={styles.section}>الجدول الزمني</Text>
        {(r.timeline || []).map((t: any, i: number) => (
          <View key={i} style={styles.tlRow}>
            <View style={[styles.tlDot, { backgroundColor: STATUS_META[t.status]?.color || colors.textMuted }]} />
            <View style={{ flex: 1 }}>
              <Text style={styles.tlStatus}>{STATUS_META[t.status]?.label || t.status}</Text>
              <Text style={styles.tlDate}>{new Date(t.at).toLocaleString('ar-EG', { hour12: false })}</Text>
            </View>
          </View>
        ))}

        {/* Actions */}
        <View style={{ marginTop: 20, gap: 10 }}>
          {role === 'supplier' && r.status === 'pending' ? (
            <>
              <TouchableOpacity testID="btn-approve" style={[styles.actBtn, styles.actGreen]} onPress={() => doAction(`/returns/${id}/approve`, 'هل تم الموافقة على طلب الإرجاع؟')} disabled={busy}>
                {busy ? <ActivityIndicator color="#fff" /> : (<><Ionicons name="checkmark-done" size={18} color="#fff" /><Text style={styles.actTxt}>موافقة</Text></>)}
              </TouchableOpacity>
              <TouchableOpacity testID="btn-reject" style={[styles.actBtn, styles.actRed]} onPress={() => doAction(`/returns/${id}/reject`, 'هل تريد رفض طلب الإرجاع؟', { reason: 'مرفوض من المذخر' })} disabled={busy}>
                <Ionicons name="close-circle" size={18} color="#fff" /><Text style={styles.actTxt}>رفض</Text>
              </TouchableOpacity>
            </>
          ) : null}
          {role === 'supplier' && (r.status === 'approved' || r.status === 'waiting_receipt') ? (
            <TouchableOpacity testID="btn-confirm" style={[styles.actBtn, styles.actGreen]} onPress={() => doAction(`/returns/${id}/confirm-receipt`, 'تأكيد استلام المنتجات المرتجعة؟')} disabled={busy}>
              {busy ? <ActivityIndicator color="#fff" /> : (<><Ionicons name="cube" size={18} color="#fff" /><Text style={styles.actTxt}>تأكيد الاستلام</Text></>)}
            </TouchableOpacity>
          ) : null}
          {role === 'pharmacy' && r.status === 'approved' ? (
            <TouchableOpacity testID="btn-mark-shipped" style={[styles.actBtn, { backgroundColor: colors.indigo }]} onPress={() => doAction(`/returns/${id}/mark-shipped`, 'هل قمت بإرسال المرتجع للمذخر؟')} disabled={busy}>
              {busy ? <ActivityIndicator color="#fff" /> : (<><Ionicons name="send" size={18} color="#fff" /><Text style={styles.actTxt}>تم الإرسال</Text></>)}
            </TouchableOpacity>
          ) : null}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function MetaRow({ label, value }: any) {
  return <View style={styles.metaRow}><Text style={styles.metaLbl}>{label}</Text><Text style={styles.metaVal}>{value}</Text></View>;
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  statusBox: { padding: 14, borderRadius: 14, alignItems: 'center' },
  statusTxt: { fontSize: 15, fontWeight: '800' },
  rejReason: { fontSize: 12, color: '#991b1b', marginTop: 6 },
  metaBox: { backgroundColor: colors.surface, borderRadius: 14, borderWidth: 1, borderColor: colors.border, padding: 12, marginTop: 12 },
  metaRow: { flexDirection: 'row-reverse', justifyContent: 'space-between', paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: colors.border, gap: 12 },
  metaLbl: { fontSize: 12, color: colors.textSecondary, textAlign: 'right' },
  metaVal: { fontSize: 12, color: colors.textPrimary, fontWeight: '800', textAlign: 'left', flex: 1 },
  section: { fontSize: 14, fontWeight: '800', color: colors.textPrimary, marginTop: 18, marginBottom: 8, textAlign: 'right' },
  item: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, backgroundColor: colors.surface, borderRadius: 10, padding: 10, borderWidth: 1, borderColor: colors.border, marginBottom: 6 },
  itemName: { fontSize: 13, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  itemMeta: { fontSize: 11, color: colors.textMuted, textAlign: 'right', marginTop: 2 },
  itemTotal: { fontSize: 13, fontWeight: '800', color: colors.primary },
  tlRow: { flexDirection: 'row-reverse', alignItems: 'flex-start', gap: 10, backgroundColor: colors.surface, borderRadius: 10, padding: 10, borderWidth: 1, borderColor: colors.border, marginBottom: 6 },
  tlDot: { width: 12, height: 12, borderRadius: 6, marginTop: 4 },
  tlStatus: { fontSize: 13, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  tlDate: { fontSize: 11, color: colors.textMuted, textAlign: 'right', marginTop: 2 },
  actBtn: { flexDirection: 'row-reverse', gap: 8, borderRadius: 14, paddingVertical: 14, alignItems: 'center', justifyContent: 'center' },
  actGreen: { backgroundColor: '#16a34a' },
  actRed: { backgroundColor: '#dc2626' },
  actTxt: { color: '#fff', fontSize: 15, fontWeight: '800' },
});
