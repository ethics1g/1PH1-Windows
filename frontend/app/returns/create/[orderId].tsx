import { useCallback, useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity, ScrollView, ActivityIndicator, Alert, Switch,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import ScreenHeader from '../../../src/ScreenHeader';
import { colors } from '../../../src/theme';
import { apiFetch, useAuth } from '../../../src/auth';

const REASONS: Array<{ key: string; label: string; icon: any }> = [
  { key: 'expired', label: 'منتهي الصلاحية', icon: 'alarm' },
  { key: 'damaged', label: 'تالف', icon: 'warning' },
  { key: 'wrong_item', label: 'منتج خاطئ', icon: 'swap-horizontal' },
  { key: 'ordered_by_mistake', label: 'طلب بالخطأ', icon: 'close-circle' },
  { key: 'other', label: 'أخرى', icon: 'ellipsis-horizontal' },
];

export default function CreateReturn() {
  const router = useRouter();
  const { orderId } = useLocalSearchParams<{ orderId: string }>();
  const { token } = useAuth();
  const [order, setOrder] = useState<any>(null);
  const [selections, setSelections] = useState<Record<string, { picked: boolean; qty: number; max: number }>>({});
  const [reason, setReason] = useState('expired');
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const r: any = await apiFetch(`/pharmacy/orders/${orderId}`, {}, token);
        setOrder(r);
        const map: any = {};
        (r.items || []).forEach((it: any, idx: number) => {
          map[`${it.name}_${idx}`] = { picked: false, qty: it.quantity, max: it.quantity };
        });
        setSelections(map);
      } catch (e: any) { Alert.alert('خطأ', e.message); }
    })();
  }, [orderId, token]);

  const toggle = (key: string) => setSelections((s) => ({ ...s, [key]: { ...s[key], picked: !s[key].picked } }));
  const setQty = (key: string, q: number) => setSelections((s) => ({ ...s, [key]: { ...s[key], qty: Math.max(1, Math.min(q, s[key].max)) } }));

  const submit = async () => {
    const items = (order?.items || []).map((it: any, idx: number) => {
      const sel = selections[`${it.name}_${idx}`];
      if (!sel?.picked) return null;
      return {
        medicine_id: it.medicine_id || null,
        name: it.name,
        quantity: sel.qty,
        unit_price: it.unit_price || it.price || 0,
      };
    }).filter(Boolean);
    if (items.length === 0) { Alert.alert('تنبيه', 'اختر منتجاً واحداً على الأقل'); return; }
    setBusy(true);
    try {
      const r: any = await apiFetch('/returns', {
        method: 'POST',
        body: JSON.stringify({
          original_order_id: orderId,
          items,
          reason,
          notes: notes.trim() || undefined,
        }),
      }, token);
      Alert.alert('✅ تم', `تم إرسال طلب الإرجاع. قيمة الإرجاع: ${r.total.toLocaleString()} د.ع`,
        [{ text: 'موافق', onPress: () => router.replace('/pharmacy-orders?tab=returns' as any) }]);
    } catch (e: any) { Alert.alert('خطأ', e.message); }
    finally { setBusy(false); }
  };

  if (!order) return <SafeAreaView style={styles.safe}><ActivityIndicator style={{ marginTop: 60 }} size="large" color={colors.primary} /></SafeAreaView>;

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <ScreenHeader title="طلب إرجاع" subtitle={`من: ${order.supplier_name || 'المذخر'}`} />
      <ScrollView contentContainerStyle={{ padding: 14, paddingBottom: 40 }} keyboardShouldPersistTaps="handled">
        <Text style={styles.section}>اختر المنتجات</Text>
        {(order.items || []).map((it: any, idx: number) => {
          const key = `${it.name}_${idx}`;
          const sel = selections[key];
          if (!sel) return null;
          return (
            <View key={key} style={styles.itemCard}>
              <Switch value={sel.picked} onValueChange={() => toggle(key)} trackColor={{ true: colors.primary, false: colors.border }} thumbColor="#fff" testID={`ret-toggle-${idx}`} />
              <View style={{ flex: 1 }}>
                <Text style={styles.itemName}>{it.name}</Text>
                <Text style={styles.itemMeta}>المشترى: {it.quantity} · السعر: {(it.unit_price || it.price || 0).toLocaleString()} د.ع</Text>
              </View>
              {sel.picked ? (
                <View style={styles.qtyBox}>
                  <TouchableOpacity onPress={() => setQty(key, sel.qty - 1)} style={styles.qtyBtn}><Ionicons name="remove" size={16} color={colors.textPrimary} /></TouchableOpacity>
                  <Text style={styles.qtyTxt}>{sel.qty}</Text>
                  <TouchableOpacity onPress={() => setQty(key, sel.qty + 1)} style={styles.qtyBtn}><Ionicons name="add" size={16} color={colors.textPrimary} /></TouchableOpacity>
                </View>
              ) : null}
            </View>
          );
        })}

        <Text style={styles.section}>سبب الإرجاع</Text>
        <View style={styles.reasonGrid}>
          {REASONS.map((r) => (
            <TouchableOpacity key={r.key} testID={`reason-${r.key}`} onPress={() => setReason(r.key)} style={[styles.reasonBtn, reason === r.key && styles.reasonActive]}>
              <Ionicons name={r.icon} size={16} color={reason === r.key ? '#fff' : colors.textPrimary} />
              <Text style={[styles.reasonTxt, reason === r.key && { color: '#fff' }]}>{r.label}</Text>
            </TouchableOpacity>
          ))}
        </View>

        <Text style={styles.section}>ملاحظات (اختياري)</Text>
        <TextInput
          testID="ret-notes"
          style={styles.notes}
          value={notes}
          onChangeText={setNotes}
          placeholder="أدخل تفاصيل إضافية..."
          placeholderTextColor={colors.textMuted}
          textAlign="right"
          multiline
          maxLength={1000}
        />

        <TouchableOpacity testID="btn-submit-return" style={styles.submit} onPress={submit} disabled={busy}>
          {busy ? <ActivityIndicator color="#fff" /> : (
            <>
              <Ionicons name="send" size={18} color="#fff" />
              <Text style={styles.submitTxt}>إرسال طلب الإرجاع</Text>
            </>
          )}
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  section: { fontSize: 14, fontWeight: '800', color: colors.textPrimary, marginTop: 20, marginBottom: 10, textAlign: 'right' },
  itemCard: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, backgroundColor: colors.surface, borderRadius: 12, padding: 12, borderWidth: 1, borderColor: colors.border, marginBottom: 8 },
  itemName: { fontSize: 14, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  itemMeta: { fontSize: 11, color: colors.textMuted, textAlign: 'right', marginTop: 3 },
  qtyBox: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6 },
  qtyBtn: { width: 28, height: 28, borderRadius: 14, backgroundColor: colors.background, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: colors.border },
  qtyTxt: { fontSize: 14, fontWeight: '800', minWidth: 20, textAlign: 'center' },
  reasonGrid: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8 },
  reasonBtn: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  reasonActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  reasonTxt: { fontSize: 12, fontWeight: '700', color: colors.textPrimary },
  notes: { backgroundColor: colors.surface, borderRadius: 12, borderWidth: 1, borderColor: colors.border, padding: 12, minHeight: 90, textAlignVertical: 'top', fontSize: 14, color: colors.textPrimary },
  submit: { flexDirection: 'row-reverse', gap: 8, backgroundColor: colors.primary, borderRadius: 14, paddingVertical: 14, alignItems: 'center', justifyContent: 'center', marginTop: 20 },
  submitTxt: { color: '#fff', fontSize: 15, fontWeight: '800' },
});
