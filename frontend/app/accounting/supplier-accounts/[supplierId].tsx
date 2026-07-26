import { useCallback, useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, ActivityIndicator, RefreshControl,
  TouchableOpacity, TextInput, Alert,
} from 'react-native';
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
  const [unpaid, setUnpaid] = useState<any[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [amount, setAmount] = useState('');
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const [showInvoices, setShowInvoices] = useState(false);

  const load = useCallback(async () => {
    if (!supplierId) return;
    try {
      const [r, u]: [any, any] = await Promise.all([
        apiFetch(`/accounting/supplier-accounts/${supplierId}`, {}, token),
        apiFetch(`/accounting/supplier-accounts/${supplierId}/unpaid-invoices`, {}, token),
      ]);
      setData(r);
      setUnpaid(u.invoices || []);
    } catch { setData(null); }
  }, [supplierId, token]);

  useEffect(() => { load(); }, [load]);

  const pay = async () => {
    const n = parseFloat(amount);
    const remaining = data?.account?.outstanding_balance || 0;
    if (!n || n <= 0) { Alert.alert('تنبيه', 'أدخل مبلغ صحيح'); return; }
    if (n > remaining + 0.01) {
      Alert.alert('تنبيه', `المبلغ أكبر من الرصيد المتبقي (${remaining.toLocaleString()} د.ع)`);
      return;
    }
    setBusy(true);
    try {
      const r: any = await apiFetch(`/accounting/supplier-accounts/${supplierId}/pay`, {
        method: 'POST',
        body: JSON.stringify({ amount: n, notes: notes.trim() || undefined }),
      }, token);
      const allocs = r.allocations || [];
      const fully = allocs.filter((a: any) => a.fully_paid).length;
      const partial = allocs.length - fully;
      const breakdown = allocs.length
        ? `\n\n📋 تفصيل التوزيع (FIFO):\n${allocs.map((a: any, i: number) =>
            `${i + 1}. ${a.invoice_type === 'paper' ? '📄' : '🛒'} ${a.invoice_number} — ${a.amount_applied.toLocaleString()} د.ع ${a.fully_paid ? '✓ مسددة' : `(متبقٍ ${a.new_outstanding.toLocaleString()})`}`
          ).join('\n')}\n\n${fully > 0 ? `✅ فواتير مسددة كاملاً: ${fully}\n` : ''}${partial > 0 ? `⏳ فواتير مسددة جزئياً: ${partial}` : ''}`
        : '';
      Alert.alert(
        '✅ تم تسديد الدين',
        `تم دفع ${(r.amount_applied || n).toLocaleString()} د.ع.\nالمتبقي: ${r.remaining_balance.toLocaleString()} د.ع${r.supplier_status === 'paid' ? '\n\n🎉 تم تسديد جميع الديون!' : ''}${breakdown}`,
      );
      setAmount(''); setNotes('');
      await load();
    } catch (e: any) { Alert.alert('خطأ', e.message || 'فشل تسديد الدين'); }
    finally { setBusy(false); }
  };

  const setFullAmount = () => {
    const rem = data?.account?.outstanding_balance || 0;
    if (rem > 0) setAmount(String(rem));
  };

  if (!data) return <SafeAreaView style={styles.safe}><ActivityIndicator style={{ marginTop: 60 }} size="large" color={colors.primary} /></SafeAreaView>;

  const a = data.account;
  const fmt = (n: number) => (n || 0).toLocaleString() + ' د.ع';
  const paymentEntries = (data.ledger || []).filter((l: any) => l.kind === 'pharmacy_payment');
  const returnEntries = (data.ledger || []).filter((l: any) => l.kind === 'return_credit');

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <ScreenHeader title={a.supplier?.name || 'حساب المذخر'} subtitle={a.supplier?.phone || ''} />
      <ScrollView contentContainerStyle={{ padding: 14, paddingBottom: 40 }} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}>
        {/* Balance Cards */}
        <View style={styles.grid}>
          <View style={[styles.card, { backgroundColor: '#eef2ff' }]}>
            <Text style={styles.cardLbl}>الإجمالي المُشترى</Text>
            <Text style={[styles.cardVal, { color: '#6366f1' }]}>{fmt(a.total_purchased)}</Text>
          </View>
          <View style={[styles.card, { backgroundColor: '#dcfce7' }]}>
            <Text style={styles.cardLbl}>المدفوع للمذخر</Text>
            <Text style={[styles.cardVal, { color: '#16a34a' }]}>{fmt(a.invoices_paid_total || 0)}</Text>
          </View>
          <View style={[styles.card, { backgroundColor: '#fef3c7' }]}>
            <Text style={styles.cardLbl}>إرجاعات مطبَّقة</Text>
            <Text style={[styles.cardVal, { color: '#d97706' }]}>{fmt(a.credit_applied_total)}</Text>
          </View>
          <View style={[styles.card, { backgroundColor: a.outstanding_balance > 0 ? '#fee2e2' : '#dcfce7' }]}>
            <Text style={styles.cardLbl}>مُتبقٍّ للدفع</Text>
            <Text style={[styles.cardVal, { color: a.outstanding_balance > 0 ? '#dc2626' : '#16a34a' }]}>{fmt(a.outstanding_balance)}</Text>
          </View>
        </View>

        {/* Pay debt section */}
        {a.outstanding_balance > 0 ? (
          <View style={styles.payBox}>
            <View style={styles.payHead}>
              <Ionicons name="cash-outline" size={20} color={colors.primary} />
              <Text style={styles.section}>تسديد دين</Text>
            </View>
            <Text style={styles.fifoHint}>💡 يتم توزيع المبلغ تلقائياً على الفواتير من الأقدم إلى الأحدث (FIFO). لا يتم تغيير ترتيب الفواتير.</Text>
            {unpaid.length > 0 ? (
              <TouchableOpacity testID="btn-toggle-invoices" style={styles.toggleInv} onPress={() => setShowInvoices(v => !v)}>
                <Ionicons name={showInvoices ? 'chevron-up' : 'chevron-down'} size={14} color={colors.primary} />
                <Text style={styles.toggleInvTxt}>{showInvoices ? 'إخفاء' : 'عرض'} الفواتير غير المسددة ({unpaid.length})</Text>
              </TouchableOpacity>
            ) : null}
            {showInvoices && unpaid.length > 0 ? (
              <View style={styles.invList}>
                {unpaid.map((inv: any, idx: number) => (
                  <View key={inv.id} testID={`inv-${idx}`} style={styles.invRow}>
                    <Text style={styles.invIdx}>#{idx + 1}</Text>
                    <View style={{ flex: 1 }}>
                      <View style={styles.invTop}>
                        <Text style={styles.invNum}>{inv.invoice_type === 'paper' ? '📄' : '🛒'} {inv.invoice_number}</Text>
                        <Text style={styles.invDate}>{inv.created_at ? new Date(inv.created_at).toLocaleDateString('ar-EG') : '-'}</Text>
                      </View>
                      <View style={styles.invBot}>
                        <Text style={styles.invPaid}>مدفوع: {fmt(inv.paid_amount || 0)}</Text>
                        <Text style={styles.invOut}>باقٍ: {fmt(inv.outstanding)}</Text>
                      </View>
                    </View>
                  </View>
                ))}
              </View>
            ) : null}
            <TextInput testID="pay-amount" style={styles.input} value={amount} onChangeText={setAmount} keyboardType="decimal-pad" placeholder="المبلغ (د.ع)" placeholderTextColor={colors.textMuted} textAlign="right" />
            <TouchableOpacity testID="btn-full-amount" style={styles.fullBtn} onPress={setFullAmount}>
              <Ionicons name="checkmark-done" size={14} color={colors.primary} />
              <Text style={styles.fullTxt}>سداد كامل: {fmt(a.outstanding_balance)}</Text>
            </TouchableOpacity>
            <TextInput testID="pay-notes" style={[styles.input, { height: 56, textAlignVertical: 'top' }]} value={notes} onChangeText={setNotes} placeholder="ملاحظات (اختياري)" placeholderTextColor={colors.textMuted} textAlign="right" multiline />
            <TouchableOpacity testID="btn-pay-supplier" style={styles.receiveBtn} onPress={pay} disabled={busy}>
              {busy ? <ActivityIndicator color="#fff" /> : (
                <>
                  <Ionicons name="cash" size={18} color="#fff" />
                  <Text style={styles.receiveTxt}>تسديد الدين</Text>
                </>
              )}
            </TouchableOpacity>
          </View>
        ) : (
          <View style={styles.paidNote}>
            <Ionicons name="checkmark-done-circle" size={22} color="#16a34a" />
            <Text style={styles.paidTxt}>لا يوجد دين متبقٍ على هذا المذخر</Text>
          </View>
        )}

        {/* Payment History (pharmacy_payment ledger entries) */}
        <Text style={styles.section}>سجل الدفعات ({paymentEntries.length})</Text>
        {paymentEntries.length === 0 ? (
          <Text style={styles.emptyTxt}>لا توجد دفعات مسجلة</Text>
        ) : paymentEntries.map((p: any) => (
          <View key={p.id} testID={`pay-hist-${p.id}`} style={styles.payItem}>
            <View style={[styles.payIcon, { backgroundColor: '#dcfce7' }]}>
              <Ionicons name="cash" size={16} color="#16a34a" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.payAmt}>{fmt(p.amount)}</Text>
              <Text style={styles.payDate}>{new Date(p.created_at).toLocaleString('ar-EG', { hour12: false })}</Text>
              {p.description ? <Text style={styles.payNotes}>{p.description}</Text> : null}
              {p.recorded_by_name ? <Text style={styles.payBy}>بواسطة: {p.recorded_by_name}</Text> : null}
              {(p.allocations || []).length > 0 ? (
                <View style={styles.allocWrap}>
                  <Text style={styles.allocHead}>📋 فواتير مُسدَّدة ({p.allocations.length}):</Text>
                  {p.allocations.map((a: any, i: number) => (
                    <Text key={i} style={styles.allocLine}>
                      • {a.invoice_type === 'paper' ? '📄' : '🛒'} {a.invoice_number} — {(a.amount_applied || 0).toLocaleString()} د.ع {a.fully_paid ? '✓' : `(متبقٍ ${(a.new_outstanding || 0).toLocaleString()})`}
                    </Text>
                  ))}
                </View>
              ) : null}
            </View>
          </View>
        ))}

        {/* Returns Credit Applied */}
        {returnEntries.length > 0 ? (
          <>
            <Text style={styles.section}>الرواجع المطبَّقة ({returnEntries.length})</Text>
            {returnEntries.map((l: any) => (
              <View key={l.id} style={styles.ledgerRow}>
                <View style={[styles.ledgerIcon, { backgroundColor: '#fef3c7' }]}>
                  <Ionicons name="return-up-back" size={18} color="#d97706" />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.ledgerDesc}>{l.description}</Text>
                  <Text style={styles.ledgerDate}>{new Date(l.created_at).toLocaleString('ar-EG', { hour12: false })}</Text>
                  {l.excess_to_credit > 0 ? <Text style={styles.excess}>فائض → رصيد دائن: {fmt(l.excess_to_credit)}</Text> : null}
                </View>
                <Text style={styles.ledgerAmt}>-{fmt(l.amount)}</Text>
              </View>
            ))}
          </>
        ) : null}

        {/* Related orders (marketplace) */}
        {(data.orders || []).length > 0 ? (
          <>
            <Text style={styles.section}>الطلبيات ({data.orders.length}) — الأحدث أولاً</Text>
            {data.orders.map((o: any) => (
              <View key={o.id} style={styles.item}>
                <View style={{ flex: 1 }}>
                  <View style={styles.saleTopRow}>
                    <Text style={styles.itemName}>🛒 {o.order_number || (o.commit_id || o.id).slice(0, 8).toUpperCase()}</Text>
                    <StatusBadge status={o.payment_status} />
                  </View>
                  <Text style={styles.itemDate}>{new Date(o.completed_at || o.created_at).toLocaleDateString('ar-EG')}</Text>
                  {o.paid_amount > 0 ? <Text style={styles.itemPaid}>مسدد: {fmt(o.paid_amount)} • باقٍ: {fmt(o.outstanding)}</Text> : null}
                </View>
                <Text style={styles.itemAmt}>{fmt(o.total)}</Text>
              </View>
            ))}
          </>
        ) : null}

        {/* Paper orders */}
        {(data.paper_orders || []).length > 0 ? (
          <>
            <Text style={styles.section}>الطلبيات المصورة ({data.paper_orders.length})</Text>
            {data.paper_orders.map((p: any) => (
              <View key={p.id} style={styles.item}>
                <View style={{ flex: 1 }}>
                  <View style={styles.saleTopRow}>
                    <Text style={styles.itemName}>📄 {p.invoice_number || p.order_number}</Text>
                    <StatusBadge status={p.payment_status} />
                  </View>
                  <Text style={styles.itemDate}>{new Date(p.created_at).toLocaleDateString('ar-EG')}</Text>
                  {p.amount_paid > 0 && p.remaining > 0 ? <Text style={styles.itemPaid}>مسدد: {fmt(p.amount_paid)} • باقٍ: {fmt(p.remaining)}</Text> : null}
                </View>
                <Text style={styles.itemAmt}>{fmt(p.total)}</Text>
              </View>
            ))}
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

function StatusBadge({ status }: { status?: string }) {
  const conf = status === 'paid'
    ? { bg: '#dcfce7', color: '#16a34a', text: 'مسدد', icon: 'checkmark-circle' as const }
    : status === 'partial'
      ? { bg: '#fef3c7', color: '#d97706', text: 'جزئي', icon: 'ellipse' as const }
      : { bg: '#fee2e2', color: '#dc2626', text: 'غير مسدد', icon: 'alert-circle' as const };
  return (
    <View style={[badgeStyles.wrap, { backgroundColor: conf.bg }]}>
      <Ionicons name={conf.icon} size={11} color={conf.color} />
      <Text style={[badgeStyles.txt, { color: conf.color }]}>{conf.text}</Text>
    </View>
  );
}

const badgeStyles = StyleSheet.create({
  wrap: { flexDirection: 'row-reverse', gap: 3, alignItems: 'center', paddingHorizontal: 8, paddingVertical: 2, borderRadius: 8 },
  txt: { fontSize: 10, fontWeight: '800' },
});

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  grid: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8 },
  card: { width: '48%', padding: 12, borderRadius: 14, alignItems: 'center' },
  cardLbl: { fontSize: 11, color: colors.textSecondary, fontWeight: '700', marginBottom: 4 },
  cardVal: { fontSize: 16, fontWeight: '900' },
  section: { fontSize: 14, fontWeight: '800', color: colors.textPrimary, marginTop: 20, marginBottom: 10, textAlign: 'right' },
  payBox: { backgroundColor: colors.surface, borderRadius: 14, borderWidth: 1, borderColor: colors.border, padding: 12, marginTop: 16 },
  payHead: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8 },
  fifoHint: { fontSize: 11, color: colors.textSecondary, textAlign: 'right', marginBottom: 8, lineHeight: 18 },
  toggleInv: { flexDirection: 'row-reverse', gap: 4, alignSelf: 'flex-end', alignItems: 'center', paddingVertical: 6, paddingHorizontal: 10, backgroundColor: '#eef2ff', borderRadius: 8, marginBottom: 8 },
  toggleInvTxt: { fontSize: 11, color: colors.primary, fontWeight: '800' },
  invList: { backgroundColor: colors.background, borderRadius: 10, padding: 8, marginBottom: 10, gap: 6, borderWidth: 1, borderColor: colors.border },
  invRow: { flexDirection: 'row-reverse', gap: 8, backgroundColor: colors.surface, borderRadius: 8, padding: 8, borderWidth: 1, borderColor: colors.border },
  invIdx: { fontSize: 12, fontWeight: '900', color: colors.primary, minWidth: 24, textAlign: 'center' },
  invTop: { flexDirection: 'row-reverse', justifyContent: 'space-between' },
  invBot: { flexDirection: 'row-reverse', justifyContent: 'space-between', marginTop: 2 },
  invNum: { fontSize: 12, fontWeight: '800', color: colors.textPrimary },
  invDate: { fontSize: 10, color: colors.textMuted },
  invPaid: { fontSize: 10, color: '#16a34a', fontWeight: '700' },
  invOut: { fontSize: 11, color: '#dc2626', fontWeight: '800' },
  fullBtn: { flexDirection: 'row-reverse', alignSelf: 'flex-end', gap: 4, alignItems: 'center', paddingVertical: 4, paddingHorizontal: 8, backgroundColor: '#eef2ff', borderRadius: 8, marginBottom: 8 },
  fullTxt: { fontSize: 11, color: colors.primary, fontWeight: '800' },
  input: { backgroundColor: colors.background, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 15, color: colors.textPrimary, borderWidth: 1, borderColor: colors.border, marginBottom: 10 },
  receiveBtn: { flexDirection: 'row-reverse', gap: 8, backgroundColor: colors.primary, borderRadius: 12, paddingVertical: 13, alignItems: 'center', justifyContent: 'center' },
  receiveTxt: { color: '#fff', fontSize: 15, fontWeight: '800' },
  paidNote: { flexDirection: 'row-reverse', gap: 10, backgroundColor: '#dcfce7', padding: 14, borderRadius: 14, alignItems: 'center', marginTop: 16 },
  paidTxt: { fontSize: 14, fontWeight: '800', color: '#166534' },
  emptyTxt: { fontSize: 13, color: colors.textMuted, textAlign: 'center', padding: 20 },
  payItem: { flexDirection: 'row-reverse', alignItems: 'flex-start', gap: 10, backgroundColor: colors.surface, borderRadius: 12, padding: 10, borderWidth: 1, borderColor: colors.border, marginBottom: 8 },
  payIcon: { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center' },
  payAmt: { fontSize: 14, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  payDate: { fontSize: 11, color: colors.textMuted, textAlign: 'right', marginTop: 2 },
  payNotes: { fontSize: 11, color: colors.textSecondary, textAlign: 'right', marginTop: 2 },
  payBy: { fontSize: 10, color: colors.textMuted, textAlign: 'right', marginTop: 2, fontStyle: 'italic' },
  allocWrap: { marginTop: 6, paddingTop: 6, borderTopWidth: 1, borderTopColor: colors.border },
  allocHead: { fontSize: 11, fontWeight: '800', color: colors.primary, textAlign: 'right', marginBottom: 4 },
  allocLine: { fontSize: 10, color: colors.textSecondary, textAlign: 'right', lineHeight: 16 },
  ledgerRow: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, backgroundColor: colors.surface, borderRadius: 12, padding: 10, borderWidth: 1, borderColor: colors.border, marginBottom: 6 },
  ledgerIcon: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center' },
  ledgerDesc: { fontSize: 13, fontWeight: '700', color: colors.textPrimary, textAlign: 'right' },
  ledgerDate: { fontSize: 11, color: colors.textMuted, textAlign: 'right', marginTop: 2 },
  excess: { fontSize: 11, color: '#16a34a', fontWeight: '700', marginTop: 2, textAlign: 'right' },
  ledgerAmt: { fontSize: 14, fontWeight: '900', color: '#d97706' },
  item: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, backgroundColor: colors.surface, borderRadius: 12, padding: 10, borderWidth: 1, borderColor: colors.border, marginBottom: 6 },
  saleTopRow: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'space-between' },
  itemName: { fontSize: 13, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  itemDate: { fontSize: 11, color: colors.textMuted, textAlign: 'right', marginTop: 2 },
  itemPaid: { fontSize: 11, color: colors.textSecondary, textAlign: 'right', marginTop: 2 },
  itemAmt: { fontSize: 13, fontWeight: '900', color: colors.primary },
});
