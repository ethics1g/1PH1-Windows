import React, { useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ScrollView, TextInput, Image,
  ActivityIndicator, Alert, Platform, Modal, FlatList,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import * as ImagePicker from 'expo-image-picker';
import ScreenHeader from '../../src/ScreenHeader';
import { colors } from '../../src/theme';
import { apiFetch, useAuth } from '../../src/auth';

type ExtractedItem = {
  name: string;
  quantity: number;
  purchase_price: number;
  selling_price?: number;
  batch_number?: string | null;
  expiry_date?: string | null;
  barcode?: string | null;
};

type Metadata = {
  supplier_name?: string | null;
  invoice_number?: string | null;
  invoice_date?: string | null;
  total?: number;
};

export default function ScanPaperOrder() {
  const router = useRouter();
  const { token } = useAuth();
  const [step, setStep] = useState<'pick' | 'review'>('pick');
  const [imageBase64, setImageBase64] = useState<string>('');
  const [imageUri, setImageUri] = useState<string>('');
  const [scanning, setScanning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [items, setItems] = useState<ExtractedItem[]>([]);
  const [supplierName, setSupplierName] = useState('');
  const [invoiceNumber, setInvoiceNumber] = useState('');
  const [invoiceDate, setInvoiceDate] = useState('');
  const [total, setTotal] = useState('');
  const [amountPaid, setAmountPaid] = useState('');
  const [notes, setNotes] = useState('');

  const pickFromGallery = useCallback(async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      Alert.alert('صلاحية مطلوبة', 'يرجى السماح بالوصول إلى الصور');
      return;
    }
    const r = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      base64: true,
      quality: 1.0,           // full resolution — OCR accuracy scales with clarity
      allowsEditing: false,
    });
    if (r.canceled || !r.assets?.[0]?.base64) return;
    setImageBase64(r.assets[0].base64!);
    setImageUri(r.assets[0].uri || '');
    await runScan(r.assets[0].base64!);
  }, []);

  const takePhoto = useCallback(async () => {
    const perm = await ImagePicker.requestCameraPermissionsAsync();
    if (!perm.granted) {
      Alert.alert('صلاحية مطلوبة', 'يرجى السماح بالوصول إلى الكاميرا لتصوير الطلبية');
      return;
    }
    const r = await ImagePicker.launchCameraAsync({
      base64: true,
      quality: 1.0,           // full resolution — better OCR on small text
      allowsEditing: false,
    });
    if (r.canceled || !r.assets?.[0]?.base64) return;
    setImageBase64(r.assets[0].base64!);
    setImageUri(r.assets[0].uri || '');
    await runScan(r.assets[0].base64!);
  }, []);

  const runScan = useCallback(async (b64: string) => {
    setScanning(true);
    try {
      const r: any = await apiFetch('/orders/scan-image', {
        method: 'POST',
        body: JSON.stringify({ image_base64: b64 }),
      }, token);
      const extracted: ExtractedItem[] = (r.items || []).map((it: any) => ({
        name: it.name || '',
        quantity: Number(it.quantity) || 0,
        purchase_price: Number(it.purchase_price) || 0,
        selling_price: Number(it.purchase_price) > 0
          ? Math.round(Number(it.purchase_price) * 1.25 * 100) / 100
          : 0,
        batch_number: it.batch_number || null,
        expiry_date: it.expiry_date || null,
      }));
      setItems(extracted);
      const m: Metadata = r.metadata || {};
      if (m.supplier_name) setSupplierName(m.supplier_name);
      if (m.invoice_number) setInvoiceNumber(m.invoice_number);
      if (m.invoice_date) setInvoiceDate(m.invoice_date);
      if (m.total) setTotal(String(m.total));
      setStep('review');
      if (extracted.length === 0) {
        // Backend now returns a smart `hint` that tells us WHY the OCR
        // failed (unreadable vs. header-only vs. tiny image). Prefer it
        // over the generic 'unclear image' message.
        const hint = (r?.hint as string) || 'يمكنك إضافة الأصناف يدوياً أو المحاولة بصورة أوضح.';
        Alert.alert('تعذّر استخراج الأصناف تلقائياً', hint);
      }
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل التعرف على الصورة');
    } finally {
      setScanning(false);
    }
  }, [token]);

  const updateItem = (idx: number, field: keyof ExtractedItem, value: any) => {
    setItems(prev => prev.map((it, i) => i === idx ? { ...it, [field]: value } : it));
  };

  const addBlankItem = () => {
    setItems(prev => [...prev, { name: '', quantity: 1, purchase_price: 0, selling_price: 0 }]);
  };

  const removeItem = (idx: number) => {
    setItems(prev => prev.filter((_, i) => i !== idx));
  };

  const linesSum = items.reduce((s, it) => s + (Number(it.quantity) || 0) * (Number(it.purchase_price) || 0), 0);
  const displayTotal = Number(total) > 0 ? Number(total) : linesSum;
  const paidNum = Number(amountPaid) || 0;
  const remaining = Math.max(0, displayTotal - paidNum);

  const submit = useCallback(async () => {
    const valid = items.filter(it => (it.name || '').trim() && Number(it.quantity) > 0);
    if (valid.length === 0) {
      Alert.alert('تنبيه', 'يجب إضافة صنف واحد على الأقل');
      return;
    }
    setSaving(true);
    try {
      const payload = {
        image_base64: imageBase64,
        supplier_name: supplierName.trim() || undefined,
        invoice_number: invoiceNumber.trim() || undefined,
        invoice_date: invoiceDate.trim() || undefined,
        total: Number(total) || 0,
        amount_paid: paidNum,
        notes: notes.trim() || undefined,
        items: valid.map(it => ({
          name: it.name.trim(),
          quantity: Number(it.quantity),
          purchase_price: Number(it.purchase_price),
          selling_price: Number(it.selling_price) || undefined,
          batch_number: (it.batch_number || '').trim() || null,
          expiry_date: (it.expiry_date || '').trim() || null,
        })),
      };
      const r: any = await apiFetch('/orders/paper', {
        method: 'POST',
        body: JSON.stringify(payload),
      }, token);
      Alert.alert(
        '✅ تم حفظ الطلبية',
        `رقم الطلبية: ${r.order_number}\nعدد الأصناف: ${r.items.length}\nالمتبقي: ${(r.remaining || 0).toLocaleString()} د.ع`,
        [{ text: 'موافق', onPress: () => router.replace('/orders/paper' as any) }],
      );
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل حفظ الطلبية');
    } finally {
      setSaving(false);
    }
  }, [items, imageBase64, supplierName, invoiceNumber, invoiceDate, total, paidNum, notes, token, router]);

  if (scanning) {
    return (
      <SafeAreaView style={styles.safe} edges={['top']}>
        <ScreenHeader title="رفع صورة الطلبية" />
        <View style={styles.centerBox}>
          <ActivityIndicator size="large" color={colors.primary} />
          <Text style={styles.hint}>جاري تحليل الصورة بالذكاء الاصطناعي...</Text>
          <Text style={styles.subHint}>قد يستغرق ذلك 15-30 ثانية</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (step === 'pick') {
    return (
      <SafeAreaView style={styles.safe} edges={['top']}>
        <ScreenHeader title="رفع صورة الطلبية" subtitle="يقرأها الذكاء الاصطناعي تلقائياً" />
        <View style={styles.pickWrap}>
          <View style={styles.pickCard}>
            <Ionicons name="scan-outline" size={64} color={colors.primary} />
            <Text style={styles.pickTitle}>ارفع صورة الفاتورة أو الوصل</Text>
            <Text style={styles.pickDesc}>سنستخرج تلقائياً: الأدوية، الكميات، الأسعار، أرقام التشغيلة وتواريخ الصلاحية.</Text>
          </View>
          <TouchableOpacity testID="btn-camera" style={styles.pickBtn} onPress={takePhoto}>
            <Ionicons name="camera" size={22} color="#fff" />
            <Text style={styles.pickBtnTxt}>تصوير من الكاميرا</Text>
          </TouchableOpacity>
          <TouchableOpacity testID="btn-gallery" style={[styles.pickBtn, styles.pickBtnAlt]} onPress={pickFromGallery}>
            <Ionicons name="image" size={22} color={colors.primary} />
            <Text style={[styles.pickBtnTxt, { color: colors.primary }]}>اختيار من المعرض</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  // REVIEW STEP
  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <ScreenHeader title="مراجعة الطلبية" subtitle={`${items.length} صنف · إجمالي: ${displayTotal.toLocaleString()} د.ع`} />
      <ScrollView contentContainerStyle={{ padding: 12, paddingBottom: 40 }} keyboardShouldPersistTaps="handled">
        {imageUri ? (
          <View style={styles.previewWrap}>
            <Image source={{ uri: imageUri }} style={styles.previewImg} resizeMode="contain" />
          </View>
        ) : null}

        <View style={styles.metaCard}>
          <Text style={styles.sectionTitle}>معلومات الطلبية</Text>
          <TextInput style={styles.metaInput} placeholder="اسم المذخر" placeholderTextColor={colors.textMuted}
            value={supplierName} onChangeText={setSupplierName} textAlign="right" testID="input-supplier" />
          <View style={{ flexDirection: 'row-reverse', gap: 8 }}>
            <TextInput style={[styles.metaInput, { flex: 1 }]} placeholder="رقم الفاتورة" placeholderTextColor={colors.textMuted}
              value={invoiceNumber} onChangeText={setInvoiceNumber} textAlign="right" testID="input-invoice" />
            <TextInput style={[styles.metaInput, { flex: 1 }]} placeholder="تاريخ الفاتورة (YYYY-MM-DD)" placeholderTextColor={colors.textMuted}
              value={invoiceDate} onChangeText={setInvoiceDate} textAlign="right" testID="input-date" />
          </View>
        </View>

        <View style={styles.itemsHeader}>
          <Text style={styles.sectionTitle}>الأصناف ({items.length})</Text>
          <TouchableOpacity testID="btn-add-item" style={styles.addBtn} onPress={addBlankItem}>
            <Ionicons name="add-circle" size={22} color={colors.primary} />
            <Text style={styles.addBtnTxt}>إضافة صنف</Text>
          </TouchableOpacity>
        </View>

        {items.map((it, idx) => (
          <View key={idx} style={styles.itemCard} testID={`item-${idx}`}>
            <View style={styles.itemHeaderRow}>
              <Text style={styles.itemIdx}>#{idx + 1}</Text>
              <TouchableOpacity testID={`item-remove-${idx}`} onPress={() => removeItem(idx)}>
                <Ionicons name="trash-outline" size={20} color="#dc2626" />
              </TouchableOpacity>
            </View>
            <TextInput style={styles.itemInput} placeholder="اسم الدواء" placeholderTextColor={colors.textMuted}
              value={it.name} onChangeText={(v) => updateItem(idx, 'name', v)} textAlign="right" testID={`item-name-${idx}`} />
            <View style={{ flexDirection: 'row-reverse', gap: 6 }}>
              <TextInput style={[styles.itemInput, { flex: 1 }]} placeholder="الكمية"
                keyboardType="number-pad" placeholderTextColor={colors.textMuted}
                value={String(it.quantity || '')} onChangeText={(v) => updateItem(idx, 'quantity', Number(v) || 0)}
                textAlign="right" testID={`item-qty-${idx}`} />
              <TextInput style={[styles.itemInput, { flex: 1 }]} placeholder="سعر الشراء"
                keyboardType="decimal-pad" placeholderTextColor={colors.textMuted}
                value={String(it.purchase_price || '')} onChangeText={(v) => updateItem(idx, 'purchase_price', Number(v) || 0)}
                textAlign="right" testID={`item-price-${idx}`} />
              <TextInput style={[styles.itemInput, { flex: 1 }]} placeholder="سعر البيع"
                keyboardType="decimal-pad" placeholderTextColor={colors.textMuted}
                value={String(it.selling_price || '')} onChangeText={(v) => updateItem(idx, 'selling_price', Number(v) || 0)}
                textAlign="right" testID={`item-sell-${idx}`} />
            </View>
            <View style={{ flexDirection: 'row-reverse', gap: 6 }}>
              <TextInput style={[styles.itemInput, { flex: 1 }]} placeholder="رقم التشغيلة (اختياري)"
                placeholderTextColor={colors.textMuted}
                value={it.batch_number || ''} onChangeText={(v) => updateItem(idx, 'batch_number', v)}
                textAlign="right" testID={`item-batch-${idx}`} />
              <TextInput style={[styles.itemInput, { flex: 1 }]} placeholder="الصلاحية (YYYY-MM-DD)"
                placeholderTextColor={colors.textMuted}
                value={it.expiry_date || ''} onChangeText={(v) => updateItem(idx, 'expiry_date', v)}
                textAlign="right" testID={`item-expiry-${idx}`} />
            </View>
          </View>
        ))}

        <View style={styles.metaCard}>
          <Text style={styles.sectionTitle}>المدفوعات</Text>
          <View style={{ flexDirection: 'row-reverse', gap: 8 }}>
            <TextInput style={[styles.metaInput, { flex: 1 }]} placeholder={`إجمالي (${linesSum.toLocaleString()} حسب الأصناف)`}
              keyboardType="decimal-pad" placeholderTextColor={colors.textMuted}
              value={total} onChangeText={setTotal} textAlign="right" testID="input-total" />
            <TextInput style={[styles.metaInput, { flex: 1 }]} placeholder="المبلغ المدفوع"
              keyboardType="decimal-pad" placeholderTextColor={colors.textMuted}
              value={amountPaid} onChangeText={setAmountPaid} textAlign="right" testID="input-paid" />
          </View>
          <View style={styles.summaryRow}>
            <Text style={styles.summaryLbl}>الإجمالي</Text>
            <Text style={styles.summaryVal}>{displayTotal.toLocaleString()} د.ع</Text>
          </View>
          <View style={styles.summaryRow}>
            <Text style={styles.summaryLbl}>المدفوع</Text>
            <Text style={[styles.summaryVal, { color: '#16a34a' }]}>{paidNum.toLocaleString()} د.ع</Text>
          </View>
          <View style={styles.summaryRow}>
            <Text style={styles.summaryLbl}>المتبقي</Text>
            <Text style={[styles.summaryVal, { color: remaining > 0 ? '#dc2626' : '#16a34a' }]}>
              {remaining.toLocaleString()} د.ع
            </Text>
          </View>
          <TextInput style={[styles.metaInput, { marginTop: 6 }]} placeholder="ملاحظات (اختياري)"
            placeholderTextColor={colors.textMuted} value={notes} onChangeText={setNotes} textAlign="right"
            testID="input-notes" />
        </View>

        <TouchableOpacity testID="btn-submit" style={styles.submitBtn} onPress={submit} disabled={saving}>
          {saving ? <ActivityIndicator color="#fff" /> : (
            <>
              <Ionicons name="checkmark-circle" size={22} color="#fff" />
              <Text style={styles.submitTxt}>حفظ وإضافة إلى المخزن</Text>
            </>
          )}
        </TouchableOpacity>
        <TouchableOpacity testID="btn-retake" style={styles.retakeBtn}
          onPress={() => { setStep('pick'); setItems([]); setImageBase64(''); setImageUri(''); }}>
          <Text style={styles.retakeTxt}>إعادة تصوير</Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  centerBox: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12 },
  hint: { fontSize: 16, color: colors.textPrimary, fontWeight: '700', marginTop: 12 },
  subHint: { fontSize: 12, color: colors.textMuted },
  pickWrap: { padding: 16, gap: 14 },
  pickCard: { backgroundColor: colors.surface, borderRadius: 16, padding: 24, alignItems: 'center', borderWidth: 1, borderColor: colors.border, gap: 8 },
  pickTitle: { fontSize: 17, fontWeight: '800', color: colors.textPrimary, marginTop: 8 },
  pickDesc: { fontSize: 13, color: colors.textSecondary, textAlign: 'center', lineHeight: 20 },
  pickBtn: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 10, backgroundColor: colors.primary, borderRadius: 14, paddingVertical: 14 },
  pickBtnAlt: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.primary },
  pickBtnTxt: { color: '#fff', fontSize: 15, fontWeight: '800' },
  previewWrap: { backgroundColor: '#000', borderRadius: 12, overflow: 'hidden', marginBottom: 10, alignItems: 'center' },
  previewImg: { width: '100%', height: 180 },
  metaCard: { backgroundColor: colors.surface, borderRadius: 14, padding: 12, marginBottom: 10, borderWidth: 1, borderColor: colors.border, gap: 8 },
  sectionTitle: { fontSize: 14, fontWeight: '800', color: colors.textPrimary, textAlign: 'right', marginBottom: 4 },
  metaInput: { backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 14, color: colors.textPrimary },
  itemsHeader: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'space-between', marginTop: 6, marginBottom: 4 },
  addBtn: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6 },
  addBtnTxt: { color: colors.primary, fontSize: 13, fontWeight: '700' },
  itemCard: { backgroundColor: colors.surface, borderRadius: 12, padding: 10, marginBottom: 8, borderWidth: 1, borderColor: colors.border, gap: 6 },
  itemHeaderRow: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'space-between' },
  itemIdx: { fontSize: 12, fontWeight: '800', color: colors.textSecondary },
  itemInput: { backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8, fontSize: 13, color: colors.textPrimary },
  summaryRow: { flexDirection: 'row-reverse', justifyContent: 'space-between', paddingVertical: 4 },
  summaryLbl: { fontSize: 13, color: colors.textSecondary, fontWeight: '600' },
  summaryVal: { fontSize: 14, color: colors.textPrimary, fontWeight: '800' },
  submitBtn: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8, backgroundColor: colors.primary, borderRadius: 14, paddingVertical: 14, marginTop: 8 },
  submitTxt: { color: '#fff', fontSize: 16, fontWeight: '800' },
  retakeBtn: { alignItems: 'center', padding: 12, marginTop: 4 },
  retakeTxt: { color: colors.textMuted, fontSize: 13, fontWeight: '700' },
});
