import { useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ScrollView, ActivityIndicator, Alert, FlatList,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useAuth, apiFetch } from '../src/auth';
import { colors } from '../src/theme';
import ScreenHeader from '../src/ScreenHeader';
import MedicineScanner from '../src/MedicineScanner';

type CartItem = { medicine_id: string; name: string; price: number; quantity: number; stock: number };

export default function Sell() {
  const { token } = useAuth();
  const [scannerOpen, setScannerOpen] = useState(false);
  const [cart, setCart] = useState<CartItem[]>([]);
  const [busy, setBusy] = useState(false);

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
    setBusy(true);
    try {
      const res: any = await apiFetch('/medicines/sell', {
        method: 'POST',
        body: JSON.stringify({ items: cart.map(c => ({ medicine_id: c.medicine_id, quantity: c.quantity })) }),
      }, token);
      Alert.alert('تم البيع', `المجموع: ${res.total.toLocaleString()} د.ع`);
      setCart([]);
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
            <Text style={styles.scanBtnTxt}>مسح الدواء</Text>
          </>
        )}
      </TouchableOpacity>

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
});
