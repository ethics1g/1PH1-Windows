import { useCallback, useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput, Alert, ActivityIndicator, RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import ScreenHeader from '../../src/ScreenHeader';
import { colors } from '../../src/theme';
import { apiFetch, useAuth } from '../../src/auth';

export default function CustomerDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const { token } = useAuth();
  const [data, setData] = useState<any>(null);
  const [amount, setAmount] = useState('');
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const r: any = await apiFetch(`/customers/${id}`, {}, token);
      setData(r);
    } catch (e: any) { Alert.alert('خطأ', e.message); }
  }, [id, token]);

  useEffect(() => { load(); }, [load]);

  const receive = async () => {
    const n = parseFloat(amount);
    if (!n || n <= 0) { Alert.alert('تنبيه', 'أدخل مبلغ صحيح'); return; }
    if (n > (data?.customer?.remaining_balance || 0) + 0.01) {
      Alert.alert('تنبيه', `المبلغ أكبر من الرصيد المتبقي (${data?.customer?.remaining_balance?.toLocaleString()} د.ع)`);
      return;
    }
    setBusy(true);
    try {
      const r: any = await apiFetch(`/customers/${id}/payment`, {
        method: 'POST',
        body: JSON.stringify({ amount: n, notes: notes.trim() || undefined }),
      }, token);
      Alert.alert('✅ تم', `تم استلام ${n.toLocaleString()} د.ع.\nالمتبقي: ${r.remaining_balance.toLocaleString()} د.ع${r.customer_status === 'paid' ? '\n\n🎉 تم تسديد الدين بالكامل!' : ''}`);
      setAmount(''); setNotes('');
      await load();
    } catch (e: any) { Alert.alert('خطأ', e.message); }
    finally { setBusy(false); }
  };

  if (!data) return <SafeAreaView style={styles.safe}><ActivityIndicator style={{ marginTop: 60 }} size="large" color={colors.primary} /></SafeAreaView>;

  const c = data.customer;

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <ScreenHeader title={c.name} subtitle={c.phone || 'بدون رقم هاتف'} />
      <ScrollView
        contentContainerStyle={{ padding: 14, paddingBottom: 40 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
      >
        {/* Summary */}
        <View style={styles.grid}>
          <View style={[styles.card, { backgroundColor: '#eef2ff' }]}>
            <Text style={styles.cardLbl}>إجمالي الدين</Text>
            <Text style={[styles.cardVal, { color: '#6366f1' }]}>{(c.total_debt || 0).toLocaleString()}</Text>
            <Text style={styles.cardSub}>د.ع</Text>
          </View>
          <View style={[styles.card, { backgroundColor: '#dcfce7' }]}>
            <Text style={styles.cardLbl}>المُسدَّد</Text>
            <Text style={[styles.cardVal, { color: '#16a34a' }]}>{(c.total_paid || 0).toLocaleString()}</Text>
            <Text style={styles.cardSub}>د.ع</Text>
          </View>
          <View style={[styles.card, { backgroundColor: c.remaining_balance > 0 ? '#fee2e2' : '#dcfce7' }]}>
            <Text style={styles.cardLbl}>المتبقي</Text>
            <Text style={[styles.cardVal, { color: c.remaining_balance > 0 ? '#dc2626' : '#16a34a' }]}>{(c.remaining_balance || 0).toLocaleString()}</Text>
            <Text style={styles.cardSub}>{c.status === 'paid' ? '✅ مسدد' : 'د.ع'}</Text>
          </View>
        </View>

        {/* Receive payment */}
        {c.remaining_balance > 0 ? (
          <View style={styles.payBox}>
            <Text style={styles.sectionTitle}>استلام دفعة</Text>
            <TextInput testID="pay-amount" style={styles.input} value={amount} onChangeText={setAmount} keyboardType="decimal-pad" placeholder="المبلغ (د.ع)" placeholderTextColor={colors.textMuted} textAlign="right" />
            <TextInput testID="pay-notes" style={[styles.input, { height: 60, textAlignVertical: 'top' }]} value={notes} onChangeText={setNotes} placeholder="ملاحظات (اختياري)" placeholderTextColor={colors.textMuted} textAlign="right" multiline />
            <TouchableOpacity testID="btn-receive" style={styles.receiveBtn} onPress={receive} disabled={busy}>
              {busy ? <ActivityIndicator color="#fff" /> : (
                <>
                  <Ionicons name="cash" size={18} color="#fff" />
                  <Text style={styles.receiveTxt}>استلام الدفعة</Text>
                </>
              )}
            </TouchableOpacity>
          </View>
        ) : (
          <View style={styles.paidNote}>
            <Ionicons name="checkmark-done-circle" size={22} color="#16a34a" />
            <Text style={styles.paidTxt}>تم تسديد الدين بالكامل</Text>
          </View>
        )}

        {/* Payment history */}
        <Text style={styles.sectionTitle}>سجل الدفعات ({data.payments?.length || 0})</Text>
        {(!data.payments || data.payments.length === 0) ? (
          <Text style={styles.emptyTxt}>لا توجد دفعات مسجلة</Text>
        ) : data.payments.map((p: any) => (
          <View key={p.id} testID={`pay-${p.id}`} style={styles.payItem}>
            <View style={[styles.payIcon, { backgroundColor: p.kind === 'initial' ? '#eef2ff' : '#dcfce7' }]}>
              <Ionicons name={p.kind === 'initial' ? 'flag' : 'cash'} size={16} color={p.kind === 'initial' ? '#6366f1' : '#16a34a'} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.payAmt}>{(p.amount || 0).toLocaleString()} د.ع</Text>
              <Text style={styles.payDate}>{new Date(p.created_at).toLocaleString('ar-EG', { hour12: false })}</Text>
              {p.notes ? <Text style={styles.payNotes}>{p.notes}</Text> : null}
            </View>
            <Text style={styles.payRem}>متبقي: {(p.remaining_after || 0).toLocaleString()}</Text>
          </View>
        ))}

        {/* Related sales */}
        {data.sales && data.sales.length > 0 ? (
          <>
            <Text style={styles.sectionTitle}>مبيعات آجلة ({data.sales.length})</Text>
            {data.sales.map((s: any) => (
              <View key={s.id} style={styles.saleItem}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.saleAmt}>{((s.revenue || s.total) || 0).toLocaleString()} د.ع</Text>
                  <Text style={styles.payDate}>{new Date(s.created_at).toLocaleString('ar-EG', { hour12: false })}</Text>
                  <Text style={styles.saleItems} numberOfLines={2}>{(s.items || []).map((it: any) => `${it.name} × ${it.quantity}`).join(' · ')}</Text>
                </View>
                {s.outstanding > 0 ? <Text style={styles.saleOut}>باقٍ: {s.outstanding.toLocaleString()}</Text> : null}
              </View>
            ))}
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  grid: { flexDirection: 'row-reverse', gap: 8 },
  card: { flex: 1, padding: 12, borderRadius: 14, alignItems: 'center' },
  cardLbl: { fontSize: 11, color: colors.textSecondary, fontWeight: '700', marginBottom: 4 },
  cardVal: { fontSize: 20, fontWeight: '900' },
  cardSub: { fontSize: 10, color: colors.textMuted, marginTop: 2 },
  sectionTitle: { fontSize: 14, fontWeight: '800', color: colors.textPrimary, marginTop: 20, marginBottom: 10, textAlign: 'right' },
  payBox: { backgroundColor: colors.surface, borderRadius: 14, borderWidth: 1, borderColor: colors.border, padding: 12, marginTop: 20 },
  input: { backgroundColor: colors.background, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 15, color: colors.textPrimary, borderWidth: 1, borderColor: colors.border, marginBottom: 10 },
  receiveBtn: { flexDirection: 'row-reverse', gap: 8, backgroundColor: colors.primary, borderRadius: 12, paddingVertical: 13, alignItems: 'center', justifyContent: 'center' },
  receiveTxt: { color: '#fff', fontSize: 15, fontWeight: '800' },
  paidNote: { flexDirection: 'row-reverse', gap: 10, backgroundColor: '#dcfce7', padding: 14, borderRadius: 14, alignItems: 'center', marginTop: 20 },
  paidTxt: { fontSize: 14, fontWeight: '800', color: '#166534' },
  emptyTxt: { fontSize: 12, color: colors.textMuted, textAlign: 'center', padding: 20 },
  payItem: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, backgroundColor: colors.surface, borderRadius: 12, padding: 10, borderWidth: 1, borderColor: colors.border, marginBottom: 8 },
  payIcon: { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center' },
  payAmt: { fontSize: 14, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  payDate: { fontSize: 11, color: colors.textMuted, textAlign: 'right', marginTop: 2 },
  payNotes: { fontSize: 11, color: colors.textSecondary, textAlign: 'right', marginTop: 2 },
  payRem: { fontSize: 11, color: colors.textMuted, fontWeight: '700' },
  saleItem: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, backgroundColor: colors.surface, borderRadius: 12, padding: 10, borderWidth: 1, borderColor: colors.border, marginBottom: 8 },
  saleAmt: { fontSize: 14, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  saleItems: { fontSize: 11, color: colors.textSecondary, textAlign: 'right', marginTop: 4 },
  saleOut: { fontSize: 11, color: '#dc2626', fontWeight: '800' },
});
