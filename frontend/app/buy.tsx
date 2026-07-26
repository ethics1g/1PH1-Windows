import { useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, TextInput, ActivityIndicator, Alert, ScrollView,
  KeyboardAvoidingView, Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useAuth, apiFetch } from '../src/auth';
import { colors } from '../src/theme';
import ScreenHeader from '../src/ScreenHeader';
import MedicineScanner from '../src/MedicineScanner';
import ExpiryDateField from '../src/ExpiryDateField';
import { normalizeExpiryDate } from '../src/utils/dateUtils';
import { useExternalScanner } from '../src/externalScanner';

export default function Buy() {
  const router = useRouter();
  const { token } = useAuth();
  const [scannerOpen, setScannerOpen] = useState(false);
  const [name, setName] = useState('');
  const [barcode, setBarcode] = useState('');
  const [quantity, setQuantity] = useState('1');
  const [price, setPrice] = useState('');            // Selling price (السعر البيع)
  const [purchasePrice, setPurchasePrice] = useState(''); // Purchase price (سعر الشراء)
  const [expiryDate, setExpiryDate] = useState(''); // YYYY-MM-DD
  const [image, setImage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reset = () => {
    setName(''); setBarcode(''); setQuantity('1'); setPrice(''); setPurchasePrice(''); setExpiryDate(''); setImage(null);
  };

  const handleBarcode = async (bc: string) => {
    setBarcode(bc);
    setScannerOpen(false);
    try {
      const existing: any = await apiFetch(`/medicines/barcode/${encodeURIComponent(bc)}`, {}, token);
      setName(existing.name);
      setPrice(String(existing.price || ''));
      Alert.alert('موجود', `${existing.name} - الرصيد الحالي: ${existing.quantity}`);
    } catch {}
  };

  // Support external USB/Bluetooth HID barcode scanners globally on this
  // screen. Same handler used by camera scanning — no logic duplication.
  useExternalScanner(handleBarcode, { enabled: !scannerOpen && !busy });

  const handleImage = async (base64: string) => {
    setImage(base64);
    setBusy(true);
    try {
      const res: any = await apiFetch('/medicines/identify', { method: 'POST', body: JSON.stringify({ image_base64: base64 }) }, token);
      const n = (res.name || '').trim();
      if (n && !n.toUpperCase().includes('UNKNOWN')) {
        setName(n);
        setScannerOpen(false);
      } else {
        Alert.alert('لم يتم التعرف', 'أدخل الاسم يدوياً');
        setScannerOpen(false);
      }
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل التعرف');
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!name.trim() || !quantity || !price || !purchasePrice) {
      Alert.alert('تنبيه', 'اسم الدواء، الكمية، سعر الشراء، وسعر البيع مطلوبة');
      return;
    }
    if (!expiryDate.trim()) {
      Alert.alert('تنبيه', 'تاريخ انتهاء الصلاحية مطلوب');
      return;
    }
    // Flexible parse: accept 2027-4-1, 1/4/2027, 01-04-2027 etc.
    const parsed = normalizeExpiryDate(expiryDate);
    if (!parsed.ok) {
      Alert.alert('تنبيه', parsed.error);
      return;
    }
    const normalized = parsed.value;
    setBusy(true);
    try {
      await apiFetch('/medicines/buy-v2', {
        method: 'POST',
        body: JSON.stringify({
          name: name.trim(),
          barcode: barcode.trim() || null,
          quantity: parseInt(quantity) || 0,
          purchase_price: parseFloat(purchasePrice) || 0,
          selling_price: parseFloat(price) || 0,
          expiry_date: normalized,
          image_base64: image,
        }),
      }, token);
      Alert.alert('تمت الإضافة', 'تم تحديث المخزن بنجاح');
      reset();
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل الحفظ');
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
        <ScreenHeader title="الشراء" subtitle="إضافة دواء جديد للمخزن" />
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <TouchableOpacity
            testID="btn-scan-invoice"
            style={styles.invoiceScanBtn}
            onPress={() => router.push('/orders/scan' as any)}
            disabled={busy}
          >
            <Ionicons name="document-attach" size={22} color="#fff" />
            <View style={{ flex: 1 }}>
              <Text style={styles.invoiceScanTitle}>رفع صورة طلبية كاملة</Text>
              <Text style={styles.invoiceScanSub}>الذكاء الاصطناعي يستخرج كل الأدوية دفعة واحدة</Text>
            </View>
            <Ionicons name="chevron-back" size={22} color="#fff" />
          </TouchableOpacity>

          <TouchableOpacity
            testID="btn-buy-scan"
            style={styles.scanBtn}
            onPress={() => setScannerOpen(true)}
            disabled={busy}
          >
            <Ionicons name="scan" size={22} color="#fff" />
            <Text style={styles.scanBtnTxt}>مسح الباركود / صورة الدواء</Text>
          </TouchableOpacity>

          <Field label="اسم الدواء" value={name} onChange={setName} testID="buy-name" />
          <Field label="الباركود (اختياري)" value={barcode} onChange={setBarcode} testID="buy-barcode" />

          <View style={styles.row}>
            <View style={{ flex: 1 }}>
              <Field label="الكمية" value={quantity} onChange={setQuantity} testID="buy-quantity" keyboardType="numeric" />
            </View>
            <View style={{ flex: 1 }}>
              <Field label="سعر الشراء (د.ع) *" value={purchasePrice} onChange={setPurchasePrice} testID="buy-purchase-price" keyboardType="numeric" />
              <Field label="سعر البيع (د.ع) *" value={price} onChange={setPrice} testID="buy-price" keyboardType="numeric" />
            </View>
          </View>

          <ExpiryDateField
            value={expiryDate}
            onChange={setExpiryDate}
            testID="buy-expiry"
          />
          <Text style={styles.hint}>تنبيهات تلقائية: 90 يوم · 30 يوم · 7 أيام · منتهي</Text>

          <TouchableOpacity
            testID="btn-save-buy"
            style={styles.save}
            onPress={save}
            disabled={busy}
          >
            {busy ? <ActivityIndicator color="#fff" /> : (
              <><Ionicons name="checkmark-circle" size={22} color="#fff" /><Text style={styles.saveTxt}>إضافة للمخزن</Text></>
            )}
          </TouchableOpacity>
        </ScrollView>
      </KeyboardAvoidingView>

      <MedicineScanner
        visible={scannerOpen}
        onClose={() => setScannerOpen(false)}
        onBarcode={handleBarcode}
        onImage={handleImage}
        mode="buy"
      />
    </SafeAreaView>
  );
}

function Field({ label, value, onChange, testID, keyboardType }: { label: string; value: string; onChange: (v: string) => void; testID: string; keyboardType?: 'default' | 'numeric' }) {
  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        testID={testID}
        style={styles.input}
        value={value}
        onChangeText={onChange}
        keyboardType={keyboardType || 'default'}
        textAlign="right"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scroll: { padding: 20, paddingBottom: 40 },
  scanBtn: { backgroundColor: colors.secondaryDark, borderRadius: 16, paddingVertical: 16, flexDirection: 'row-reverse', gap: 8, alignItems: 'center', justifyContent: 'center', marginBottom: 16 },
  scanBtnTxt: { color: '#fff', fontSize: 16, fontWeight: '800' },
  invoiceScanBtn: { backgroundColor: '#7c3aed', borderRadius: 16, paddingVertical: 14, paddingHorizontal: 14, flexDirection: 'row-reverse', gap: 10, alignItems: 'center', marginBottom: 12 },
  invoiceScanTitle: { color: '#fff', fontSize: 15, fontWeight: '800', textAlign: 'right' },
  invoiceScanSub: { color: '#ede9fe', fontSize: 11, fontWeight: '600', textAlign: 'right', marginTop: 2 },
  field: { marginBottom: 14 },
  label: { fontSize: 13, color: colors.textSecondary, marginBottom: 6, textAlign: 'right', fontWeight: '700' },
  hint: { fontSize: 11, color: colors.textMuted, marginTop: 6, textAlign: 'right' },
  input: { backgroundColor: colors.surface, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, fontSize: 16, color: colors.textPrimary, borderWidth: 1, borderColor: colors.border },
  row: { flexDirection: 'row-reverse', gap: 12 },
  save: { backgroundColor: colors.primary, borderRadius: 16, paddingVertical: 16, flexDirection: 'row-reverse', gap: 8, alignItems: 'center', justifyContent: 'center', marginTop: 8 },
  saveTxt: { color: '#fff', fontSize: 17, fontWeight: '800' },
});
