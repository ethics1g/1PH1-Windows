import { useCallback, useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator,
  Alert, TextInput, Image, Modal,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import ScreenHeader from '../../../src/ScreenHeader';
import { colors } from '../../../src/theme';
import { apiFetch, useAuth } from '../../../src/auth';

export default function PaperOrderDetail() {
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { token } = useAuth();
  const [order, setOrder] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [payAmount, setPayAmount] = useState('');
  const [payNotes, setPayNotes] = useState('');
  const [paying, setPaying] = useState(false);
  const [showImage, setShowImage] = useState(false);

  const load = useCallback(async () => {
    try {
      const r: any = await apiFetch(`/orders/paper/${id}`, {}, token);
      setOrder(r);
    } catch (e: any) {
      Alert.alert('خطأ', e.message);
      router.back();
    }
  }, [id, token, router]);

  useEffect(() => { setLoading(true); load().finally(() => setLoading(false)); }, [load]);

  const submitPay = useCallback(async () => {
    const amt = Number(payAmount);
    if (!amt || amt <= 0) { Alert.alert('تنبيه', 'أدخل مبلغاً صحيحاً'); return; }
    setPaying(true);
    try {
      const r: any = await apiFetch(`/orders/paper/${id}/pay`, {
        method: 'POST',
        body: JSON.stringify({ amount: amt, notes: payNotes.trim() || undefined }),
      }, token);
      Alert.alert('✅ تم تسجيل الدفعة', `المتبقي: ${(r.remaining || 0).toLocaleString()} د.ع`);
      setPayAmount(''); setPayNotes('');
      await load();
    } catch (e: any) {
      Alert.alert('خطأ', e.message);
    } finally { setPaying(false); }
  }, [payAmount, payNotes, id, token, load]);

  if (loading || !order) {
    return <SafeAreaView style={styles.safe}><ActivityIndicator style={{ marginTop: 60 }} size="large" color={colors.primary} /></SafeAreaView>;
  }

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <ScreenHeader title={order.order_number} subtitle={order.supplier_name} />
      <ScrollView contentContainerStyle={{ padding: 12, paddingBottom: 30 }}>
        {order.image_base64 ? (
          <TouchableOpacity onPress={() => setShowImage(true)} style={styles.previewWrap} testID="btn-view-image">
            <Image source={{ uri: `data:image/jpeg;base64,${order.image_base64}` }} style={styles.previewImg} resizeMode="cover" />
            <View style={styles.previewOverlay}>
              <Ionicons name="expand-outline" size={20} color="#fff" />
              <Text style={styles.previewTxt}>عرض الصورة الأصلية</Text>
            </View>
          </TouchableOpacity>
        ) : null}

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>المعلومات المالية</Text>
          <RowKV lbl="الإجمالي" val={`${(order.total || 0).toLocaleString()} د.ع`} />
          <RowKV lbl="المدفوع" val={`${(order.amount_paid || 0).toLocaleString()} د.ع`} valColor="#16a34a" />
          <RowKV lbl="المتبقي" val={`${(order.remaining || 0).toLocaleString()} د.ع`}
            valColor={(order.remaining || 0) > 0 ? '#dc2626' : '#16a34a'} />
          <RowKV lbl="الحالة" val={
            order.payment_status === 'paid' ? 'مدفوعة بالكامل' :
            order.payment_status === 'partial' ? 'مدفوعة جزئياً' : 'غير مدفوعة'
          } />
          {order.invoice_number ? <RowKV lbl="رقم الفاتورة" val={order.invoice_number} /> : null}
          {order.invoice_date ? <RowKV lbl="تاريخ الفاتورة" val={order.invoice_date} /> : null}
          <RowKV lbl="تاريخ التسجيل" val={new Date(order.created_at).toLocaleDateString('ar-EG')} />
        </View>

        <View style={styles.card}>
          <Text style={styles.sectionTitle}>الأصناف ({order.items?.length || 0})</Text>
          {(order.items || []).map((it: any, i: number) => (
            <View key={i} style={styles.itemRow}>
              <Text style={styles.itemName}>{it.name}</Text>
              <Text style={styles.itemMeta}>{it.quantity} × {(it.purchase_price || 0).toLocaleString()} = {(it.line_total || 0).toLocaleString()} د.ع</Text>
              {it.expiry_date ? <Text style={styles.itemSub}>صلاحية: {it.expiry_date}{it.batch_number ? ` · دفعة: ${it.batch_number}` : ''}</Text> : null}
            </View>
          ))}
        </View>

        {(order.payments || []).length > 0 && (
          <View style={styles.card}>
            <Text style={styles.sectionTitle}>سجل الدفعات ({order.payments.length})</Text>
            {order.payments.map((p: any) => (
              <View key={p.id} style={styles.paymentRow}>
                <Text style={styles.paymentAmt}>+{(p.amount || 0).toLocaleString()} د.ع</Text>
                <View style={{ flex: 1 }}>
                  <Text style={styles.paymentDate}>{new Date(p.at).toLocaleString('ar-EG')}</Text>
                  {p.notes ? <Text style={styles.paymentNote}>{p.notes}</Text> : null}
                </View>
              </View>
            ))}
          </View>
        )}

        {(order.remaining || 0) > 0 && (
          <View style={styles.card}>
            <Text style={styles.sectionTitle}>تسديد دفعة</Text>
            <TextInput style={styles.input} placeholder={`المبلغ (حتى ${(order.remaining || 0).toLocaleString()})`}
              placeholderTextColor={colors.textMuted} keyboardType="decimal-pad" value={payAmount}
              onChangeText={setPayAmount} textAlign="right" testID="input-pay-amount" />
            <TextInput style={styles.input} placeholder="ملاحظات (اختياري)" placeholderTextColor={colors.textMuted}
              value={payNotes} onChangeText={setPayNotes} textAlign="right" testID="input-pay-notes" />
            <TouchableOpacity testID="btn-pay" style={styles.payBtn} onPress={submitPay} disabled={paying}>
              {paying ? <ActivityIndicator color="#fff" /> : (
                <><Ionicons name="cash" size={18} color="#fff" /><Text style={styles.payTxt}>تأكيد الدفع</Text></>
              )}
            </TouchableOpacity>
          </View>
        )}
      </ScrollView>

      <Modal visible={showImage} animationType="fade" transparent onRequestClose={() => setShowImage(false)}>
        <View style={styles.modalBg}>
          <TouchableOpacity style={styles.modalClose} onPress={() => setShowImage(false)} testID="btn-close-image">
            <Ionicons name="close" size={28} color="#fff" />
          </TouchableOpacity>
          {order.image_base64 ? (
            <Image source={{ uri: `data:image/jpeg;base64,${order.image_base64}` }}
              style={styles.modalImg} resizeMode="contain" />
          ) : null}
        </View>
      </Modal>
    </SafeAreaView>
  );
}

function RowKV({ lbl, val, valColor }: { lbl: string; val: string; valColor?: string }) {
  return (
    <View style={styles.kvRow}>
      <Text style={styles.kvLbl}>{lbl}</Text>
      <Text style={[styles.kvVal, valColor ? { color: valColor } : null]}>{val}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  previewWrap: { borderRadius: 12, overflow: 'hidden', marginBottom: 12, backgroundColor: '#000' },
  previewImg: { width: '100%', height: 220 },
  previewOverlay: { position: 'absolute', bottom: 0, left: 0, right: 0, flexDirection: 'row-reverse', gap: 6, alignItems: 'center', justifyContent: 'center', paddingVertical: 8, backgroundColor: 'rgba(0,0,0,0.5)' },
  previewTxt: { color: '#fff', fontSize: 12, fontWeight: '700' },
  card: { backgroundColor: colors.surface, borderRadius: 12, padding: 12, marginBottom: 10, borderWidth: 1, borderColor: colors.border, gap: 6 },
  sectionTitle: { fontSize: 14, fontWeight: '800', color: colors.textPrimary, textAlign: 'right', marginBottom: 6 },
  kvRow: { flexDirection: 'row-reverse', justifyContent: 'space-between', paddingVertical: 4 },
  kvLbl: { fontSize: 13, color: colors.textSecondary, fontWeight: '600' },
  kvVal: { fontSize: 14, fontWeight: '800', color: colors.textPrimary },
  itemRow: { paddingVertical: 8, borderTopWidth: 1, borderTopColor: colors.border, gap: 2 },
  itemName: { fontSize: 14, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  itemMeta: { fontSize: 12, color: colors.textSecondary, textAlign: 'right' },
  itemSub: { fontSize: 11, color: colors.textMuted, textAlign: 'right' },
  paymentRow: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, paddingVertical: 6, borderTopWidth: 1, borderTopColor: colors.border },
  paymentAmt: { fontSize: 14, fontWeight: '800', color: '#16a34a' },
  paymentDate: { fontSize: 12, color: colors.textPrimary, textAlign: 'right' },
  paymentNote: { fontSize: 11, color: colors.textMuted, textAlign: 'right' },
  input: { backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 14, color: colors.textPrimary, marginBottom: 6 },
  payBtn: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8, backgroundColor: colors.primary, borderRadius: 12, paddingVertical: 12, marginTop: 4 },
  payTxt: { color: '#fff', fontSize: 14, fontWeight: '800' },
  modalBg: { flex: 1, backgroundColor: 'rgba(0,0,0,0.9)', alignItems: 'center', justifyContent: 'center' },
  modalImg: { width: '100%', height: '100%' },
  modalClose: { position: 'absolute', top: 40, right: 20, zIndex: 10, backgroundColor: 'rgba(0,0,0,0.5)', width: 42, height: 42, borderRadius: 21, alignItems: 'center', justifyContent: 'center' },
});
