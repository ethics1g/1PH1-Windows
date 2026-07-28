import { useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ScrollView, ActivityIndicator, Alert, FlatList, TextInput, Modal,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useAuth, apiFetch } from '../src/auth';
import { colors } from '../src/theme';
import ScreenHeader from '../src/ScreenHeader';
import MedicineScanner from '../src/MedicineScanner';
import MedicineAutocomplete from '../src/MedicineAutocomplete';
import { useExternalScanner } from '../src/externalScanner';
import { useHidGuardedChange, useHidGuardListener } from '../src/hidGuard';
import { isDesktop, printReceipt } from '../src/desktop';

type CartItem = { medicine_id: string; name: string; price: number; quantity: number; stock: number };

export default function Sell() {
  const { token } = useAuth();
  const [scannerOpen, setScannerOpen] = useState(false);
  const [cart, setCart] = useState<CartItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [paymentType, setPaymentType] = useState<'cash' | 'credit'>('cash');
  const [creditModalOpen, setCreditModalOpen] = useState(false);
  const [customerName, setCustomerName] = useState('');
  const [customerPhone, setCustomerPhone] = useState('');
  const [customerNotes, setCustomerNotes] = useState('');
  const [amountPaid, setAmountPaid] = useState('');

  const total = cart.reduce((s, i) => s + i.price * i.quantity, 0);

  const addToCart = async (medicine: any) => {
    const existing = cart.find(c => c.medicine_id === medicine.id);
    if (existing) {
      if (existing.quantity + 1 > medicine.quantity) {
        Alert.alert('الكمية غير كافية', `متاح فقط ${medicine.quantity}`);
        return;
      }
      setCart(cart.map(c => c.medicine_id === medicine.id ? { ...c, quantity: c.quantity + 1 } : c));
    } else {
      if (medicine.quantity <= 0) { Alert.alert('نفذ المخزون'); return; }
      setCart([...cart, { medicine_id: medicine.id, name: medicine.name, price: medicine.price, quantity: 1, stock: medicine.quantity }]);
    }
  };

  const handleBarcode = async (barcode: string) => {
    setBusy(true);
    try {
      const med: any = await apiFetch(`/medicines/barcode/${encodeURIComponent(barcode)}`, {}, token);
      setScannerOpen(false);
      await addToCart(med);
    } catch (e: any) {
      Alert.alert('غير موجود', e.message || 'الدواء غير مسجل في المخزن');
    } finally {
      setBusy(false);
    }
  };

  // ---- HID scanner support (works on Android/iOS/Web) --------------
  // Sell screen has NO visible barcode field — the HID input is captured
  // GLOBALLY. Every TextInput on this screen (autocomplete + credit-modal
  // fields) uses `useHidGuardedChange` which reverts scanner-speed digit
  // bursts and streams them to the HID buffer. The listener below is
  // called with the completed barcode and adds the medicine to the cart.
  useHidGuardListener(handleBarcode, !scannerOpen && !busy);
  // Web-level doc.keydown listener — kept ON even when credit modal is
  // open so the modal's TextInputs are shielded on web too. Modal inputs
  // are ALSO protected natively via `useHidGuardedChange`.
  useExternalScanner(handleBarcode, { enabled: !scannerOpen && !busy });

  // Guarded change handlers for each modal / autocomplete input.
  const custNameGuard = useHidGuardedChange(customerName, setCustomerName);
  const custPhoneGuard = useHidGuardedChange(customerPhone, setCustomerPhone);
  const custNotesGuard = useHidGuardedChange(customerNotes, setCustomerNotes);
  const custPaidGuard = useHidGuardedChange(amountPaid, setAmountPaid);

  const handleImage = async (base64: string) => {
    setBusy(true);
    try {
      const res: any = await apiFetch('/medicines/identify', { method: 'POST', body: JSON.stringify({ image_base64: base64 }) }, token);
      const name = (res.name || '').trim();
      if (!name || name.toUpperCase().includes('UNKNOWN')) {
        Alert.alert('لم يتم التعرف', 'حاول التقاط صورة أوضح');
        return;
      }
      const all: any[] = await apiFetch('/medicines', {}, token);
      const match = all.find(m => m.name.toLowerCase().includes(name.toLowerCase()) || name.toLowerCase().includes(m.name.toLowerCase()));
      if (!match) {
        Alert.alert(`تم التعرف: ${name}`, 'لكن غير موجود في المخزن');
        return;
      }
      setScannerOpen(false);
      await addToCart(match);
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل التعرف');
    } finally {
      setBusy(false);
    }
  };

  const updateQty = (id: string, delta: number) => {
    setCart(cart.map(c => {
      if (c.medicine_id !== id) return c;
      const q = c.quantity + delta;
      if (q <= 0) return { ...c, quantity: 0 };
      if (q > c.stock) { Alert.alert('الكمية غير كافية'); return c; }
      return { ...c, quantity: q };
    }).filter(c => c.quantity > 0));
  };

  const checkout = async () => {
    if (cart.length === 0) return;
    if (paymentType === 'credit' && !customerName.trim()) {
      setCreditModalOpen(true);
      return;
    }
    setBusy(true);
    try {
      const body: any = {
        items: cart.map(c => ({ medicine_id: c.medicine_id, quantity: c.quantity })),
        payment_type: paymentType,
      };
      if (paymentType === 'credit') {
        body.customer_name = customerName.trim();
        if (customerPhone.trim()) body.customer_phone = customerPhone.trim();
        if (customerNotes.trim()) body.customer_notes = customerNotes.trim();
        const paidNum = parseFloat(amountPaid);
        if (!isNaN(paidNum) && paidNum > 0) body.amount_paid = paidNum;
      }
      const res: any = await apiFetch('/sales', {
        method: 'POST',
        body: JSON.stringify(body),
      }, token);
      const outstandingTxt = res.outstanding > 0 ? `\nمتبقي على الزبون: ${res.outstanding.toLocaleString()} د.ع` : '';

      // Auto-print thermal receipt when running inside the Electron desktop
      // shell (no-op on web/mobile). Non-blocking + non-fatal — if the printer
      // is unreachable we still surface the sale success alert to the cashier.
      if (isDesktop()) {
        printReceipt({
          pharmacyName: 'صيدلية 1PH1',
          items: cart.map(c => ({ name: c.name, quantity: c.quantity, price: c.price })),
          total: res.revenue,
          paid: paymentType === 'credit' ? (parseFloat(amountPaid) || 0) : res.revenue,
          change: paymentType === 'credit' ? undefined : 0,
          invoiceNumber: res.order_id || res.id,
          footer: paymentType === 'credit' ? 'فاتورة آجل' : 'شكراً لتعاملكم معنا',
        }).catch(() => { /* already logged */ });
      }

      Alert.alert('تم البيع', `المجموع: ${res.revenue.toLocaleString()} د.ع\nربح: ${res.profit.toLocaleString()} د.ع${outstandingTxt}`);
      setCart([]);
      setCustomerName(''); setCustomerPhone(''); setCustomerNotes(''); setAmountPaid('');
      setPaymentType('cash');
      setCreditModalOpen(false);
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل البيع');
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <ScreenHeader title="البيع" subtitle="مسح الباركود أو التعرف بالصورة" />

      <TouchableOpacity
        testID="btn-open-scanner"
        style={styles.scanBtn}
        onPress={() => setScannerOpen(true)}
        disabled={busy}
      >
        {busy ? <ActivityIndicator color="#fff" /> : (
          <>
            <Ionicons name="scan" size={26} color="#fff" />
            <Text style={styles.scanBtnTxt}>مسح الدواء بالباركود أو الصورة</Text>
          </>
        )}
      </TouchableOpacity>

      {/* Manual name search — 3rd input method */}
      <View style={{ paddingHorizontal: 14, marginBottom: 8, zIndex: 5 }}>
        <MedicineAutocomplete
          onSelect={(m) => addToCart(m)}
          placeholder="أو ابحث باسم الدواء يدوياً..."
          testID="sell-autocomplete"
        />
      </View>

      {/* Payment type selector */}
      <View style={styles.payTypeRow}>
        <TouchableOpacity testID="pay-cash" onPress={() => setPaymentType('cash')} style={[styles.payTypeBtn, paymentType === 'cash' && styles.payTypeActive]}>
          <Ionicons name="cash" size={18} color={paymentType === 'cash' ? '#fff' : colors.textPrimary} />
          <Text style={[styles.payTypeTxt, paymentType === 'cash' && styles.payTypeTxtActive]}>نقدي</Text>
        </TouchableOpacity>
        <TouchableOpacity testID="pay-credit" onPress={() => { setPaymentType('credit'); if (cart.length > 0) setCreditModalOpen(true); }} style={[styles.payTypeBtn, paymentType === 'credit' && styles.payTypeActive]}>
          <Ionicons name="time" size={18} color={paymentType === 'credit' ? '#fff' : colors.textPrimary} />
          <Text style={[styles.payTypeTxt, paymentType === 'credit' && styles.payTypeTxtActive]}>آجل</Text>
        </TouchableOpacity>
      </View>

      <View style={styles.cartHeader}>
        <Text style={styles.cartTitle}>السلة ({cart.length})</Text>
      </View>

      {cart.length === 0 ? (
        <View style={styles.empty}>
          <Ionicons name="cart-outline" size={64} color={colors.textMuted} />
          <Text style={styles.emptyTxt}>السلة فارغة</Text>
        </View>
      ) : (
        <FlatList
          data={cart}
          keyExtractor={(i) => i.medicine_id}
          contentContainerStyle={{ padding: 16, paddingBottom: 180 }}
          renderItem={({ item }) => (
            <View style={styles.cartItem} testID={`cart-item-${item.medicine_id}`}>
              <View style={styles.qtyBox}>
                <TouchableOpacity onPress={() => updateQty(item.medicine_id, 1)} style={styles.qtyBtn}><Ionicons name="add" size={18} color={colors.primary} /></TouchableOpacity>
                <Text style={styles.qtyTxt}>{item.quantity}</Text>
                <TouchableOpacity onPress={() => updateQty(item.medicine_id, -1)} style={styles.qtyBtn}><Ionicons name="remove" size={18} color={colors.error} /></TouchableOpacity>
              </View>
              <View style={{ flex: 1, alignItems: 'flex-end' }}>
                <Text style={styles.itemName}>{item.name}</Text>
                <Text style={styles.itemPrice}>{(item.price * item.quantity).toLocaleString()} د.ع</Text>
              </View>
            </View>
          )}
        />
      )}

      {cart.length > 0 && (
        <View style={styles.footer}>
          <View style={styles.totalRow}>
            <Text style={styles.totalLabel}>المجموع</Text>
            <Text style={styles.totalValue} testID="sell-total">{total.toLocaleString()} د.ع</Text>
          </View>
          <TouchableOpacity testID="btn-checkout" style={styles.checkout} onPress={checkout} disabled={busy}>
            {busy ? <ActivityIndicator color="#fff" /> : <><Ionicons name="checkmark-circle" size={22} color="#fff" /><Text style={styles.checkoutTxt}>إتمام البيع</Text></>}
          </TouchableOpacity>
        </View>
      )}

      <MedicineScanner
        visible={scannerOpen}
        onClose={() => setScannerOpen(false)}
        onBarcode={handleBarcode}
        onImage={handleImage}
        mode="sell"
      />

      {/* Credit customer modal */}
      <Modal visible={creditModalOpen} transparent animationType="slide" onRequestClose={() => setCreditModalOpen(false)}>
        <View style={styles.modalBackdrop}>
          <View style={styles.modalSheet}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>بيع آجل — بيانات الزبون</Text>
              <TouchableOpacity onPress={() => { setCreditModalOpen(false); setPaymentType('cash'); }}>
                <Ionicons name="close" size={24} color={colors.textPrimary} />
              </TouchableOpacity>
            </View>
            <ScrollView contentContainerStyle={{ padding: 14 }} keyboardShouldPersistTaps="handled">
              <Text style={styles.lbl}>اسم الزبون *</Text>
              <TextInput ref={custNameGuard.inputRef as any} testID="cust-name" style={styles.mInput} value={customerName} onChangeText={custNameGuard.onChangeText} onKeyPress={custNameGuard.onKeyPress} placeholder="مثال: أحمد محمد" placeholderTextColor={colors.textMuted} textAlign="right" blurOnSubmit={false} />

              <Text style={styles.lbl}>رقم الهاتف (اختياري)</Text>
              <TextInput ref={custPhoneGuard.inputRef as any} testID="cust-phone" style={styles.mInput} value={customerPhone} onChangeText={custPhoneGuard.onChangeText} onKeyPress={custPhoneGuard.onKeyPress} placeholder="07XX-XXX-XXXX" placeholderTextColor={colors.textMuted} textAlign="right" keyboardType="phone-pad" maxLength={20} blurOnSubmit={false} />

              <Text style={styles.lbl}>ملاحظات (اختياري)</Text>
              <TextInput ref={custNotesGuard.inputRef as any} testID="cust-notes" style={[styles.mInput, { height: 60, textAlignVertical: 'top' }]} value={customerNotes} onChangeText={custNotesGuard.onChangeText} onKeyPress={custNotesGuard.onKeyPress} multiline placeholder="أي معلومات إضافية عن الزبون..." placeholderTextColor={colors.textMuted} textAlign="right" />

              <Text style={styles.lbl}>دفعة أولية (اختياري)</Text>
              <TextInput ref={custPaidGuard.inputRef as any} testID="cust-paid" style={styles.mInput} value={amountPaid} onChangeText={custPaidGuard.onChangeText} onKeyPress={custPaidGuard.onKeyPress} placeholder={`0 (المتبقي ${total.toLocaleString()} د.ع سيُسجَّل كدين)`} placeholderTextColor={colors.textMuted} textAlign="right" keyboardType="decimal-pad" blurOnSubmit={false} />

              <TouchableOpacity testID="btn-confirm-credit" style={styles.confirmBtn} onPress={checkout} disabled={busy || !customerName.trim()}>
                {busy ? <ActivityIndicator color="#fff" /> : (
                  <>
                    <Ionicons name="checkmark-circle" size={20} color="#fff" />
                    <Text style={styles.confirmTxt}>تأكيد البيع الآجل</Text>
                  </>
                )}
              </TouchableOpacity>
            </ScrollView>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scanBtn: { marginHorizontal: 20, marginBottom: 16, backgroundColor: colors.primary, borderRadius: 18, paddingVertical: 18, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8, shadowColor: colors.primary, shadowOpacity: 0.25, shadowRadius: 12, shadowOffset: { width: 0, height: 6 }, elevation: 6 },
  scanBtnTxt: { color: '#fff', fontSize: 18, fontWeight: '800' },
  cartHeader: { paddingHorizontal: 20, paddingBottom: 8 },
  cartTitle: { fontSize: 16, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 10, paddingBottom: 100 },
  emptyTxt: { color: colors.textSecondary, fontSize: 15 },
  cartItem: { backgroundColor: colors.surface, borderRadius: 16, padding: 14, marginBottom: 10, flexDirection: 'row-reverse', alignItems: 'center', borderWidth: 1, borderColor: colors.border },
  itemName: { fontSize: 16, fontWeight: '700', color: colors.textPrimary, textAlign: 'right' },
  itemPrice: { fontSize: 14, color: colors.primary, fontWeight: '800', marginTop: 2 },
  qtyBox: { flexDirection: 'row', alignItems: 'center', gap: 10, marginLeft: 12 },
  qtyBtn: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.background, alignItems: 'center', justifyContent: 'center' },
  qtyTxt: { fontSize: 16, fontWeight: '800', color: colors.textPrimary, minWidth: 20, textAlign: 'center' },
  footer: { position: 'absolute', bottom: 0, left: 0, right: 0, backgroundColor: '#fff', borderTopWidth: 1, borderTopColor: colors.border, padding: 16, paddingBottom: 24, gap: 12 },
  totalRow: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center' },
  totalLabel: { fontSize: 16, color: colors.textSecondary, fontWeight: '700' },
  totalValue: { fontSize: 22, color: colors.primary, fontWeight: '900' },
  checkout: { backgroundColor: colors.primary, borderRadius: 16, paddingVertical: 14, flexDirection: 'row-reverse', gap: 8, alignItems: 'center', justifyContent: 'center' },
  checkoutTxt: { color: '#fff', fontSize: 17, fontWeight: '800' },
  payTypeRow: { flexDirection: 'row-reverse', gap: 10, paddingHorizontal: 20, marginBottom: 10 },
  payTypeBtn: { flex: 1, flexDirection: 'row-reverse', gap: 8, alignItems: 'center', justifyContent: 'center', paddingVertical: 12, borderRadius: 12, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  payTypeActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  payTypeTxt: { fontSize: 14, fontWeight: '800', color: colors.textPrimary },
  payTypeTxtActive: { color: '#fff' },
  modalBackdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', justifyContent: 'flex-end' },
  modalSheet: { backgroundColor: colors.background, borderTopLeftRadius: 20, borderTopRightRadius: 20, maxHeight: '85%' },
  modalHead: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', padding: 16, borderBottomWidth: 1, borderBottomColor: colors.border },
  modalTitle: { fontSize: 16, fontWeight: '800', color: colors.textPrimary },
  lbl: { fontSize: 13, color: colors.textSecondary, fontWeight: '700', marginBottom: 6, textAlign: 'right' },
  mInput: { backgroundColor: colors.surface, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, fontSize: 15, color: colors.textPrimary, borderWidth: 1, borderColor: colors.border, marginBottom: 14 },
  confirmBtn: { flexDirection: 'row-reverse', gap: 8, backgroundColor: colors.primary, borderRadius: 14, paddingVertical: 14, alignItems: 'center', justifyContent: 'center', marginTop: 6 },
  confirmTxt: { color: '#fff', fontSize: 15, fontWeight: '800' },
});
