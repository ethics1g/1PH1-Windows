import React, { useCallback, useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ScrollView, TextInput,
  ActivityIndicator, Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import * as DocumentPicker from 'expo-document-picker';
import * as FileSystem from 'expo-file-system';
import ScreenHeader from '../../src/ScreenHeader';
import { colors } from '../../src/theme';
import { apiFetch, useAuth } from '../../src/auth';

type Item = {
  name: string;
  barcode?: string | null;
  quantity: number;
  purchase_price: number;
  selling_price?: number;
  expiry_date?: string | null;
  batch_number?: string | null;
  manufacturer?: string | null;
  strength?: string | null;
  dosage_form?: string | null;
};

export default function ExcelImport() {
  const router = useRouter();
  const { token } = useAuth();
  const [step, setStep] = useState<'pick' | 'review' | 'result'>('pick');
  const [items, setItems] = useState<Item[]>([]);
  const [parsing, setParsing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [filename, setFilename] = useState('');
  const [detected, setDetected] = useState<any>({});
  const [result, setResult] = useState<any>(null);

  // Pagination for the review list (handles 20k+ rows without freezing)
  const PAGE_SIZE = 100;
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  const pickFile = useCallback(async () => {
    try {
      const r = await DocumentPicker.getDocumentAsync({
        type: [
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          'application/vnd.ms-excel',
          'text/csv',
          '*/*',
        ],
        multiple: false,
        copyToCacheDirectory: true,
      });
      if (r.canceled || !r.assets?.[0]) return;
      const asset = r.assets[0];
      setFilename(asset.name || 'file');
      setParsing(true);
      let base64 = '';
      if ((asset as any).base64) {
        base64 = (asset as any).base64;
      } else {
        base64 = await FileSystem.readAsStringAsync(asset.uri, {
          encoding: FileSystem.EncodingType.Base64,
        });
      }
      const res: any = await apiFetch('/orders/excel/preview', {
        method: 'POST',
        body: JSON.stringify({ filename: asset.name || 'file', file_base64: base64 }),
      }, token);
      setItems((res.items || []).map((it: any) => ({
        ...it,
        selling_price: it.purchase_price ? Math.round(it.purchase_price * 1.25 * 100) / 100 : 0,
      })));
      setDetected(res.columns_detected || {});
      setVisibleCount(PAGE_SIZE);
      setStep('review');
      if ((res.items || []).length === 0) {
        Alert.alert('تنبيه', 'لم يتم استخراج أي صف من الملف. تأكد من العناوين.');
      }
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل قراءة الملف');
    } finally { setParsing(false); }
  }, [token]);

  const update = (i: number, f: keyof Item, v: any) =>
    setItems(prev => prev.map((it, idx) => idx === i ? { ...it, [f]: v } : it));

  const remove = (i: number) => setItems(prev => prev.filter((_, idx) => idx !== i));

  const submit = useCallback(async () => {
    const valid = items.filter(it => (it.name || '').trim() && Number(it.quantity) > 0);
    if (valid.length === 0) { Alert.alert('تنبيه', 'لا يوجد أصناف صالحة'); return; }
    setSaving(true);
    try {
      const r: any = await apiFetch('/orders/excel/commit', {
        method: 'POST',
        body: JSON.stringify({ items: valid }),
      }, token);
      setResult(r);
      setStep('result');
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل حفظ الأصناف');
    } finally { setSaving(false); }
  }, [items, token]);

  if (parsing) {
    return (
      <SafeAreaView style={styles.safe}>
        <ScreenHeader title="استيراد Excel" />
        <View style={styles.center}>
          <ActivityIndicator size="large" color={colors.primary} />
          <Text style={styles.hint}>جاري قراءة الملف...</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (step === 'result' && result) {
    return (
      <SafeAreaView style={styles.safe}>
        <ScreenHeader title="نتيجة الاستيراد" />
        <ScrollView contentContainerStyle={{ padding: 16 }}>
          <View style={styles.summaryCard}>
            <Stat label="إجمالي المستورد" value={result.imported} color="#16a34a" />
            <Stat label="أصناف جديدة" value={result.new} color="#2563eb" />
            <Stat label="أصناف مُحدَّثة" value={result.updated} color="#9333ea" />
            <Stat label="فشل" value={result.failed} color={result.failed > 0 ? "#dc2626" : "#64748b"} />
          </View>
          {result.errors?.length > 0 && (
            <View style={styles.errorCard}>
              <Text style={styles.errorTitle}>الأصناف الفاشلة:</Text>
              {result.errors.slice(0, 20).map((e: any, i: number) => (
                <Text key={i} style={styles.errorLine}>• الصف {e.row}: {e.name} — {e.error}</Text>
              ))}
              {result.errors.length > 20 && (
                <Text style={styles.errorLine}>...و {result.errors.length - 20} صف آخر</Text>
              )}
            </View>
          )}
          <TouchableOpacity testID="btn-done" style={styles.doneBtn} onPress={() => router.replace('/buy' as any)}>
            <Text style={styles.doneTxt}>تم</Text>
          </TouchableOpacity>
        </ScrollView>
      </SafeAreaView>
    );
  }

  if (step === 'pick') {
    return (
      <SafeAreaView style={styles.safe}>
        <ScreenHeader title="استيراد ملف Excel" subtitle="XLSX / XLS / CSV" />
        <View style={styles.pickWrap}>
          <View style={styles.pickCard}>
            <Ionicons name="document-text" size={64} color={colors.primary} />
            <Text style={styles.pickTitle}>ارفع كتالوج المذخر</Text>
            <Text style={styles.pickDesc}>يتعرف النظام تلقائياً على أعمدة الاسم، الباركود، الكمية، السعر، الصلاحية، التشغيلة، الشركة — بالعربية أو الإنجليزية.</Text>
          </View>
          <TouchableOpacity testID="btn-pick-file" style={styles.pickBtn} onPress={pickFile}>
            <Ionicons name="cloud-upload" size={22} color="#fff" />
            <Text style={styles.pickBtnTxt}>اختر الملف</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  // Review step
  const shown = items.slice(0, visibleCount);
  return (
    <SafeAreaView style={styles.safe}>
      <ScreenHeader title="مراجعة الأصناف" subtitle={`${items.length} صنف · ${filename}`} />
      <View style={styles.detectedBar}>
        <Ionicons name="information-circle" size={14} color={colors.primary} />
        <Text style={styles.detectedTxt}>الأعمدة المكتشفة: {Object.keys(detected).join('، ')}</Text>
      </View>
      <ScrollView contentContainerStyle={{ padding: 10, paddingBottom: 100 }}>
        {shown.map((it, idx) => (
          <View key={idx} style={styles.itemCard} testID={`xls-item-${idx}`}>
            <View style={styles.rowHead}>
              <Text style={styles.idx}>#{idx + 1}</Text>
              <TouchableOpacity onPress={() => remove(idx)} testID={`xls-remove-${idx}`}>
                <Ionicons name="trash-outline" size={18} color="#dc2626" />
              </TouchableOpacity>
            </View>
            <TextInput style={styles.inp} placeholder="اسم الدواء" placeholderTextColor={colors.textMuted}
              value={it.name} onChangeText={(v) => update(idx, 'name', v)} textAlign="right"
              testID={`xls-name-${idx}`} />
            <View style={styles.row3}>
              <TextInput style={[styles.inp, styles.f1]} placeholder="الكمية" keyboardType="number-pad"
                placeholderTextColor={colors.textMuted}
                value={String(it.quantity || '')} onChangeText={(v) => update(idx, 'quantity', Number(v) || 0)}
                textAlign="right" testID={`xls-qty-${idx}`} />
              <TextInput style={[styles.inp, styles.f1]} placeholder="سعر الشراء" keyboardType="decimal-pad"
                placeholderTextColor={colors.textMuted}
                value={String(it.purchase_price || '')} onChangeText={(v) => update(idx, 'purchase_price', Number(v) || 0)}
                textAlign="right" testID={`xls-price-${idx}`} />
              <TextInput style={[styles.inp, styles.f1]} placeholder="سعر البيع" keyboardType="decimal-pad"
                placeholderTextColor={colors.textMuted}
                value={String(it.selling_price || '')} onChangeText={(v) => update(idx, 'selling_price', Number(v) || 0)}
                textAlign="right" />
            </View>
            <View style={styles.row2}>
              <TextInput style={[styles.inp, styles.f1]} placeholder="الباركود" placeholderTextColor={colors.textMuted}
                value={it.barcode || ''} onChangeText={(v) => update(idx, 'barcode', v)} textAlign="right" />
              <TextInput style={[styles.inp, styles.f1]} placeholder="الصلاحية (YYYY-MM-DD)"
                placeholderTextColor={colors.textMuted}
                value={it.expiry_date || ''} onChangeText={(v) => update(idx, 'expiry_date', v)} textAlign="right" />
            </View>
            <View style={styles.row2}>
              <TextInput style={[styles.inp, styles.f1]} placeholder="التشغيلة" placeholderTextColor={colors.textMuted}
                value={it.batch_number || ''} onChangeText={(v) => update(idx, 'batch_number', v)} textAlign="right" />
              <TextInput style={[styles.inp, styles.f1]} placeholder="الشركة" placeholderTextColor={colors.textMuted}
                value={it.manufacturer || ''} onChangeText={(v) => update(idx, 'manufacturer', v)} textAlign="right" />
            </View>
          </View>
        ))}
        {visibleCount < items.length && (
          <TouchableOpacity testID="btn-load-more" style={styles.moreBtn}
            onPress={() => setVisibleCount(c => Math.min(items.length, c + PAGE_SIZE))}>
            <Text style={styles.moreTxt}>عرض المزيد ({items.length - visibleCount} متبقي)</Text>
          </TouchableOpacity>
        )}
      </ScrollView>
      <View style={styles.footer}>
        <TouchableOpacity testID="btn-commit-excel" style={styles.commitBtn}
          onPress={submit} disabled={saving}>
          {saving ? <ActivityIndicator color="#fff" /> : (
            <><Ionicons name="checkmark-circle" size={22} color="#fff" />
              <Text style={styles.commitTxt}>اعتماد وإضافة {items.length} صنف</Text></>
          )}
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

function Stat({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <View style={statStyles.card}>
      <Text style={[statStyles.val, { color }]}>{value}</Text>
      <Text style={statStyles.lbl}>{label}</Text>
    </View>
  );
}

const statStyles = StyleSheet.create({
  card: { flex: 1, alignItems: 'center', paddingVertical: 12 },
  val: { fontSize: 28, fontWeight: '900' },
  lbl: { fontSize: 12, color: colors.textSecondary, marginTop: 4 },
});

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12 },
  hint: { fontSize: 14, color: colors.textPrimary, fontWeight: '700' },
  pickWrap: { padding: 16, gap: 14 },
  pickCard: { backgroundColor: colors.surface, borderRadius: 16, padding: 24, alignItems: 'center', borderWidth: 1, borderColor: colors.border, gap: 8 },
  pickTitle: { fontSize: 17, fontWeight: '800', color: colors.textPrimary, marginTop: 8 },
  pickDesc: { fontSize: 13, color: colors.textSecondary, textAlign: 'center', lineHeight: 20 },
  pickBtn: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 10, backgroundColor: colors.primary, borderRadius: 14, paddingVertical: 14 },
  pickBtnTxt: { color: '#fff', fontSize: 15, fontWeight: '800' },
  detectedBar: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, backgroundColor: '#eff6ff', paddingVertical: 8, paddingHorizontal: 12 },
  detectedTxt: { fontSize: 11, color: colors.primary, fontWeight: '700' },
  itemCard: { backgroundColor: colors.surface, borderRadius: 10, padding: 10, marginBottom: 8, borderWidth: 1, borderColor: colors.border, gap: 6 },
  rowHead: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center' },
  idx: { fontSize: 12, fontWeight: '800', color: colors.textSecondary },
  inp: { backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8, fontSize: 13, color: colors.textPrimary },
  row3: { flexDirection: 'row-reverse', gap: 6 },
  row2: { flexDirection: 'row-reverse', gap: 6 },
  f1: { flex: 1 },
  moreBtn: { padding: 12, alignItems: 'center' },
  moreTxt: { color: colors.primary, fontSize: 13, fontWeight: '800' },
  footer: { position: 'absolute', bottom: 0, left: 0, right: 0, backgroundColor: colors.surface, padding: 12, borderTopWidth: 1, borderTopColor: colors.border },
  commitBtn: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8, backgroundColor: colors.primary, borderRadius: 12, paddingVertical: 14 },
  commitTxt: { color: '#fff', fontSize: 15, fontWeight: '800' },
  summaryCard: { flexDirection: 'row-reverse', backgroundColor: colors.surface, borderRadius: 12, borderWidth: 1, borderColor: colors.border, padding: 8, marginBottom: 12 },
  errorCard: { backgroundColor: '#fef2f2', borderRadius: 10, padding: 12, borderWidth: 1, borderColor: '#fca5a5', gap: 4, marginBottom: 12 },
  errorTitle: { fontSize: 14, fontWeight: '800', color: '#991b1b', textAlign: 'right' },
  errorLine: { fontSize: 12, color: '#991b1b', textAlign: 'right' },
  doneBtn: { backgroundColor: colors.primary, borderRadius: 12, paddingVertical: 14, alignItems: 'center' },
  doneTxt: { color: '#fff', fontSize: 15, fontWeight: '800' },
});
