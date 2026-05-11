import { useCallback, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator, Alert, RefreshControl, FlatList, Platform, Modal, Image, Linking } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from 'expo-router';
import * as DocumentPicker from 'expo-document-picker';
import * as FileSystem from 'expo-file-system/legacy';
import { useAuth, apiFetch } from '../src/auth';
import { colors } from '../src/theme';
import ScreenHeader from '../src/ScreenHeader';

const fmt = (n: number) => Math.round(n).toLocaleString();

type Record_ = {
  id: string;
  pharmacy_name?: string;
  order_total: number;
  commission: number;
  status: 'pending' | 'submitted' | 'paid';
  source: string;
  created_at: string;
  paid_at?: string;
};

type Monthly = {
  month: string;
  total_sales: number;
  total_commission: number;
  pending_commission: number;
  paid_commission: number;
  count: number;
};

export default function CommissionsScreen() {
  const { token } = useAuth();
  const [data, setData] = useState<{ records: Record_[]; monthly: Monthly[]; outstanding: number; total_due: number; total_sales: number; rate: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [uploading, setUploading] = useState<string | null>(null);
  const [payInfo, setPayInfo] = useState<any | null>(null);
  const [payModalOpen, setPayModalOpen] = useState(false);
  const [payLoading, setPayLoading] = useState(false);

  const load = useCallback(async () => {
    try {
      const res: any = await apiFetch('/supplier/commissions', {}, token);
      setData(res);
    } catch (e: any) { Alert.alert('خطأ', e.message); }
    finally { setLoading(false); setRefreshing(false); }
  }, [token]);

  const openPayInfo = useCallback(async () => {
    setPayModalOpen(true);
    if (payInfo) return;
    setPayLoading(true);
    try {
      const res: any = await apiFetch('/payment-info', {}, token);
      setPayInfo(res);
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل تحميل معلومات الدفع');
      setPayModalOpen(false);
    } finally { setPayLoading(false); }
  }, [token, payInfo]);

  const openWhatsApp = (number: string) => {
    const phone = (number || '').replace(/[^\d]/g, '');
    if (!phone) return;
    const msg = encodeURIComponent('السلام عليكم، أريد الاستفسار عن دفع العمولة المستحقة.');
    Linking.openURL(`https://wa.me/${phone}?text=${msg}`).catch(() => {});
  };

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const uploadProof = async (recordId: string) => {
    try {
      const res = await DocumentPicker.getDocumentAsync({ type: ['image/*', 'application/pdf'], copyToCacheDirectory: true });
      if (res.canceled || !res.assets?.length) return;
      const a = res.assets[0];
      let b64: string;
      if (Platform.OS === 'web') {
        const r = await fetch(a.uri);
        const blob = await r.blob();
        b64 = await new Promise<string>((resolve, reject) => {
          const fr = new FileReader();
          fr.onload = () => { const s = String(fr.result || ''); resolve(s.includes(',') ? s.split(',')[1] : s); };
          fr.onerror = reject;
          fr.readAsDataURL(blob);
        });
      } else {
        b64 = await FileSystem.readAsStringAsync(a.uri, { encoding: FileSystem.EncodingType.Base64 });
      }
      setUploading(recordId);
      await apiFetch(`/supplier/commissions/${recordId}/upload-proof`, {
        method: 'POST',
        body: JSON.stringify({ proof_b64: b64 }),
      }, token);
      Alert.alert('تم', 'تم رفع إثبات الدفع. بانتظار تأكيد الإدارة.');
      await load();
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل الرفع');
    } finally {
      setUploading(null);
    }
  };

  if (loading) return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} size="large" /></View></SafeAreaView>;
  if (!data) return null;

  const STATUS_META: Record<string, { label: string; color: string; bg: string }> = {
    pending: { label: 'مستحقة', color: '#92400e', bg: '#fef3c7' },
    submitted: { label: 'بانتظار التأكيد', color: '#1e40af', bg: '#dbeafe' },
    paid: { label: 'مدفوعة', color: '#166534', bg: '#dcfce7' },
  };

  return (
    <SafeAreaView style={styles.safe}>
      <ScreenHeader title="عمولاتي" subtitle={`نسبة العمولة: ${(data.rate * 100).toFixed(0)}%`} />
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 40 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}>

        <View style={styles.summaryCards}>
          <SummaryCard label="مستحق عليّ" value={fmt(data.outstanding)} color={colors.error} bg="#fee2e2" icon="alert-circle" />
          <SummaryCard label="إجمالي العمولات" value={fmt(data.total_due)} color={colors.primary} bg={colors.primaryLight} icon="cash" />
          <SummaryCard label="إجمالي المبيعات" value={fmt(data.total_sales)} color={colors.secondaryDark} bg={colors.secondaryLight} icon="trending-up" />
        </View>

        <TouchableOpacity testID="btn-payment-info" style={styles.payInfoBtn} onPress={openPayInfo} activeOpacity={0.85}>
          <Ionicons name="card" size={18} color="#fff" />
          <Text style={styles.payInfoTxt}>كيف أدفع العمولة؟ (معلومات الدفع)</Text>
        </TouchableOpacity>

        {data.monthly.length > 0 && (
          <>
            <Text style={styles.sectionTitle}>📅 ملخص شهري</Text>
            {data.monthly.map(m => (
              <View key={m.month} style={styles.monthCard} testID={`month-${m.month}`}>
                <View style={styles.monthHead}>
                  <Text style={styles.monthName}>{m.month}</Text>
                  <Text style={styles.monthCount}>{m.count} طلبية</Text>
                </View>
                <View style={styles.monthRow}>
                  <Text style={styles.monthMetric}>المبيعات: <Text style={styles.metricValue}>{fmt(m.total_sales)} د.ع</Text></Text>
                </View>
                <View style={styles.monthRow}>
                  <Text style={styles.monthMetric}>العمولة: <Text style={[styles.metricValue, { color: colors.primary }]}>{fmt(m.total_commission)} د.ع</Text></Text>
                </View>
                {m.pending_commission > 0 && (
                  <View style={styles.monthRow}>
                    <Text style={[styles.monthMetric, { color: colors.error }]}>المتبقي: <Text style={styles.metricValue}>{fmt(m.pending_commission)} د.ع</Text></Text>
                  </View>
                )}
              </View>
            ))}
          </>
        )}

        <Text style={styles.sectionTitle}>📋 تفاصيل العمليات</Text>
        {data.records.length === 0 ? (
          <Text style={styles.empty}>لا توجد عمولات بعد</Text>
        ) : (
          <FlatList
            scrollEnabled={false}
            data={data.records}
            keyExtractor={(r) => r.id}
            contentContainerStyle={{ gap: 8 }}
            renderItem={({ item }) => {
              const stt = STATUS_META[item.status] || STATUS_META.pending;
              return (
                <View style={styles.recCard} testID={`rec-${item.id}`}>
                  <View style={styles.recHead}>
                    <View style={[styles.pill, { backgroundColor: stt.bg }]}>
                      <Text style={[styles.pillTxt, { color: stt.color }]}>{stt.label}</Text>
                    </View>
                    <View style={{ flex: 1, alignItems: 'flex-end' }}>
                      <Text style={styles.recPharmacy}>{item.pharmacy_name || '—'}</Text>
                      <Text style={styles.recDate}>{new Date(item.created_at).toLocaleDateString('ar')}</Text>
                    </View>
                  </View>
                  <View style={styles.recRow}>
                    <Text style={styles.recLabel}>قيمة الطلبية:</Text>
                    <Text style={styles.recValue}>{fmt(item.order_total)} د.ع</Text>
                  </View>
                  <View style={styles.recRow}>
                    <Text style={styles.recLabel}>العمولة (4%):</Text>
                    <Text style={[styles.recValue, { color: colors.primary, fontWeight: '900' }]}>{fmt(item.commission)} د.ع</Text>
                  </View>
                  {item.status === 'pending' && (
                    <TouchableOpacity testID={`upload-${item.id}`} style={styles.uploadBtn} onPress={() => uploadProof(item.id)} disabled={uploading === item.id}>
                      {uploading === item.id ? <ActivityIndicator color="#fff" /> : (
                        <>
                          <Ionicons name="cloud-upload" size={16} color="#fff" />
                          <Text style={styles.uploadTxt}>رفع إثبات الدفع</Text>
                        </>
                      )}
                    </TouchableOpacity>
                  )}
                  {item.status === 'submitted' && (
                    <View style={styles.waitBadge}>
                      <Ionicons name="hourglass" size={14} color={colors.secondaryDark} />
                      <Text style={styles.waitTxt}>بانتظار تأكيد الإدارة</Text>
                    </View>
                  )}
                </View>
              );
            }}
          />
        )}
      </ScrollView>

      <Modal visible={payModalOpen} animationType="slide" transparent onRequestClose={() => setPayModalOpen(false)}>
        <View style={styles.modalWrap}>
          <View style={styles.modal}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>💳 معلومات الدفع</Text>
              <TouchableOpacity testID="pay-modal-close" onPress={() => setPayModalOpen(false)}>
                <Ionicons name="close" size={26} color={colors.textPrimary} />
              </TouchableOpacity>
            </View>
            <ScrollView contentContainerStyle={{ gap: 12, paddingBottom: 20 }}>
              {payLoading || !payInfo ? (
                <View style={{ padding: 30 }}><ActivityIndicator color={colors.primary} /></View>
              ) : (
                <>
                  {payInfo.instructions ? (
                    <View style={styles.payNote}>
                      <Ionicons name="information-circle" size={18} color={colors.warning} />
                      <Text style={styles.payNoteTxt}>{payInfo.instructions}</Text>
                    </View>
                  ) : null}

                  {/* Zain Cash */}
                  {(payInfo.zaincash_phone || payInfo.zaincash_qr_b64) ? (
                    <View style={styles.payBlock}>
                      <Text style={styles.payBlockTitle}>💰 Zain Cash</Text>
                      {payInfo.zaincash_phone ? (
                        <Text style={styles.payRow}>الرقم: <Text style={styles.payVal}>{payInfo.zaincash_phone}</Text></Text>
                      ) : null}
                      {payInfo.zaincash_qr_b64 ? (
                        <View style={{ alignItems: 'center', marginTop: 8 }}>
                          <Image source={{ uri: `data:image/png;base64,${payInfo.zaincash_qr_b64}` }} style={styles.qrImg} resizeMode="contain" />
                          <Text style={styles.qrCaption}>امسح الـ QR للدفع عبر تطبيق Zain Cash</Text>
                        </View>
                      ) : null}
                    </View>
                  ) : null}

                  {/* WhatsApp */}
                  {payInfo.whatsapp_admin_number ? (
                    <TouchableOpacity testID="pay-wa-btn" style={styles.payWaBlock} onPress={() => openWhatsApp(payInfo.whatsapp_admin_number)}>
                      <Ionicons name="logo-whatsapp" size={26} color="#fff" />
                      <View style={{ flex: 1, alignItems: 'flex-end' }}>
                        <Text style={[styles.payBlockTitle, { color: '#fff' }]}>تواصل مع الإدارة</Text>
                        <Text style={[styles.payRow, { color: 'rgba(255,255,255,0.9)' }]}>{payInfo.whatsapp_admin_number}</Text>
                      </View>
                    </TouchableOpacity>
                  ) : null}

                  {/* Bank */}
                  {(payInfo.bank_name || payInfo.iban || payInfo.bank_account_number) ? (
                    <View style={styles.payBlock}>
                      <Text style={styles.payBlockTitle}>🏦 تحويل بنكي</Text>
                      {payInfo.bank_name ? <Text style={styles.payRow}>البنك: <Text style={styles.payVal}>{payInfo.bank_name}</Text></Text> : null}
                      {payInfo.bank_account_number ? <Text style={styles.payRow}>الحساب: <Text style={styles.payVal}>{payInfo.bank_account_number}</Text></Text> : null}
                      {payInfo.iban ? <Text style={styles.payRow}>IBAN: <Text style={styles.payVal}>{payInfo.iban}</Text></Text> : null}
                    </View>
                  ) : null}

                  {/* Stripe (future) */}
                  {payInfo.stripe_enabled ? (
                    <View style={styles.payBlock}>
                      <Text style={styles.payBlockTitle}>💳 الدفع بالبطاقة (Stripe)</Text>
                      <Text style={styles.payRow}>قريباً — الدفع بالبطاقة عبر Stripe</Text>
                    </View>
                  ) : null}

                  {!payInfo.zaincash_phone && !payInfo.zaincash_qr_b64 && !payInfo.whatsapp_admin_number && !payInfo.bank_name && !payInfo.iban ? (
                    <View style={styles.payBlock}>
                      <Text style={[styles.payRow, { textAlign: 'center', color: colors.textMuted }]}>لم يتم إعداد معلومات الدفع بعد. يرجى التواصل مع الإدارة.</Text>
                    </View>
                  ) : null}
                </>
              )}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

function SummaryCard({ label, value, color, bg, icon }: { label: string; value: string; color: string; bg: string; icon: keyof typeof Ionicons.glyphMap }) {
  return (
    <View style={[styles.sumCard, { backgroundColor: bg }]}>
      <Ionicons name={icon} size={22} color={color} />
      <Text style={[styles.sumValue, { color }]}>{value}</Text>
      <Text style={styles.sumLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  summaryCards: { flexDirection: 'row-reverse', gap: 8, marginBottom: 16 },
  sumCard: { flex: 1, borderRadius: 14, padding: 12, alignItems: 'flex-end', gap: 4 },
  sumValue: { fontSize: 18, fontWeight: '900' },
  sumLabel: { fontSize: 11, color: colors.textSecondary },
  sectionTitle: { fontSize: 15, fontWeight: '800', color: colors.textPrimary, textAlign: 'right', marginBottom: 8, marginTop: 8 },
  monthCard: { backgroundColor: colors.surface, borderRadius: 14, padding: 12, marginBottom: 8, borderWidth: 1, borderColor: colors.border, gap: 4 },
  monthHead: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 },
  monthName: { fontWeight: '900', fontSize: 16, color: colors.textPrimary },
  monthCount: { fontSize: 11, color: colors.textMuted },
  monthRow: { flexDirection: 'row-reverse' },
  monthMetric: { fontSize: 13, color: colors.textSecondary, textAlign: 'right' },
  metricValue: { fontWeight: '800', color: colors.textPrimary },
  recCard: { backgroundColor: colors.surface, borderRadius: 14, padding: 12, borderWidth: 1, borderColor: colors.border, gap: 6 },
  recHead: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8 },
  pill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 8 },
  pillTxt: { fontSize: 11, fontWeight: '800' },
  recPharmacy: { fontSize: 14, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  recDate: { fontSize: 11, color: colors.textMuted },
  recRow: { flexDirection: 'row-reverse', justifyContent: 'space-between' },
  recLabel: { fontSize: 12, color: colors.textSecondary },
  recValue: { fontSize: 13, fontWeight: '700', color: colors.textPrimary },
  uploadBtn: { backgroundColor: colors.primary, borderRadius: 10, paddingVertical: 10, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 6, marginTop: 6 },
  uploadTxt: { color: '#fff', fontWeight: '800', fontSize: 13 },
  waitBadge: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 6, paddingVertical: 6, marginTop: 4 },
  waitTxt: { color: colors.secondaryDark, fontSize: 12, fontWeight: '700' },
  empty: { textAlign: 'center', color: colors.textMuted, padding: 30 },
  // Payment Info
  payInfoBtn: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8, backgroundColor: colors.indigo, paddingVertical: 12, borderRadius: 12, marginBottom: 14 },
  payInfoTxt: { color: '#fff', fontWeight: '800', fontSize: 14 },
  modalWrap: { flex: 1, backgroundColor: 'rgba(0,0,0,0.55)', justifyContent: 'flex-end' },
  modal: { backgroundColor: '#fff', borderTopLeftRadius: 22, borderTopRightRadius: 22, padding: 20, maxHeight: '85%' },
  modalHead: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  modalTitle: { fontSize: 18, fontWeight: '900', color: colors.textPrimary },
  payNote: { flexDirection: 'row-reverse', gap: 8, alignItems: 'flex-start', backgroundColor: colors.warningLight, borderRadius: 12, padding: 12 },
  payNoteTxt: { flex: 1, color: colors.textPrimary, textAlign: 'right', fontSize: 13 },
  payBlock: { backgroundColor: colors.surface, borderRadius: 14, padding: 14, borderWidth: 1, borderColor: colors.border, gap: 6 },
  payBlockTitle: { fontSize: 15, fontWeight: '900', color: colors.textPrimary, textAlign: 'right' },
  payRow: { fontSize: 13, color: colors.textSecondary, textAlign: 'right' },
  payVal: { color: colors.textPrimary, fontWeight: '800' },
  qrImg: { width: 220, height: 220, marginVertical: 8 },
  qrCaption: { fontSize: 11, color: colors.textMuted, textAlign: 'center' },
  payWaBlock: { backgroundColor: '#16a34a', borderRadius: 14, padding: 14, flexDirection: 'row-reverse', alignItems: 'center', gap: 10 },
});
