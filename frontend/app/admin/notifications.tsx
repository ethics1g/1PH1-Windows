import { useCallback, useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity, ScrollView, Alert, ActivityIndicator, Modal, Platform
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import DateTimePicker from '@react-native-community/datetimepicker';
import ScreenHeader from '../../src/ScreenHeader';
import { colors } from '../../src/theme';
import { apiFetch, useAuth } from '../../src/auth';

type Audience = 'all' | 'role' | 'region' | 'ids';

export default function AdminNotifications() {
  const { token, user, role } = useAuth();
  const isAdmin = role === 'admin';

  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [audience, setAudience] = useState<Audience>('all');
  const [role, setRole] = useState('pharmacy');
  const [region, setRegion] = useState('');
  const [ids, setIds] = useState('');
  const [scheduled, setScheduled] = useState<Date | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [sending, setSending] = useState(false);

  const [summary, setSummary] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);

  const load = useCallback(async () => {
    if (!isAdmin) return;
    try {
      const [s, h]: any = await Promise.all([
        apiFetch('/admin/notifications/audience-summary', {}, token),
        apiFetch('/admin/notifications/history?limit=20', {}, token),
      ]);
      setSummary(s);
      setHistory(h.items || []);
    } catch (e: any) {
      Alert.alert('خطأ', e.message);
    }
  }, [token, isAdmin]);

  useEffect(() => { load(); }, [load]);

  const send = async () => {
    if (!title.trim() || !body.trim()) { Alert.alert('تنبيه', 'العنوان والنص مطلوبان'); return; }
    const payload: any = { title: title.trim(), body: body.trim(), audience_mode: audience };
    if (audience === 'role') payload.role = role;
    if (audience === 'region') payload.region = region.trim();
    if (audience === 'ids') payload.ids = ids.split(/[,\s]+/).filter(Boolean);
    if (scheduled) payload.scheduled_for = scheduled.toISOString();

    setSending(true);
    try {
      const r: any = await apiFetch('/admin/notifications/send', { method: 'POST', body: JSON.stringify(payload) }, token);
      if (r.status === 'scheduled') {
        Alert.alert('✅ مجدول', `تم جدولة الإشعار لـ ${new Date(r.run_at).toLocaleString('ar-EG')}`);
      } else {
        Alert.alert('✅ تم الإرسال', `المستلمون: ${r.total} · تم التسليم: ${r.delivered} · فشل: ${r.failed}`);
      }
      setTitle(''); setBody(''); setScheduled(null); setIds('');
      await load();
    } catch (e: any) { Alert.alert('خطأ', e.message); }
    finally { setSending(false); }
  };

  const cancelBatch = async (bid: string) => {
    Alert.alert('إلغاء الجدولة', 'هل تريد إلغاء هذا الإشعار المجدول؟', [
      { text: 'إغلاق', style: 'cancel' },
      { text: 'إلغاء', style: 'destructive', onPress: async () => {
          try {
            await apiFetch(`/admin/notifications/scheduled/${bid}`, { method: 'DELETE' }, token);
            await load();
          } catch (e: any) { Alert.alert('خطأ', e.message); }
        } },
    ]);
  };

  if (!isAdmin) {
    return (
      <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
        <ScreenHeader title="إشعارات الإدارة" />
        <View style={styles.forbidden}>
          <Ionicons name="lock-closed" size={54} color={colors.textMuted} />
          <Text style={styles.forbiddenTxt}>هذه الصفحة مخصصة للمسؤول فقط</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <ScreenHeader title="إشعارات الإدارة" subtitle={summary ? `${summary.total} مستخدم` : ''} />

      <ScrollView contentContainerStyle={{ padding: 14 }} keyboardShouldPersistTaps="handled">
        {/* Audience summary */}
        {summary ? (
          <View style={styles.summaryCard}>
            <View style={styles.chip}><Text style={styles.chipTxt}>صيدليات: {summary.roles.pharmacy}</Text></View>
            <View style={styles.chip}><Text style={styles.chipTxt}>مذاخر: {summary.roles.supplier}</Text></View>
            <View style={styles.chip}><Text style={styles.chipTxt}>مسؤولون: {summary.roles.admin}</Text></View>
          </View>
        ) : null}

        {/* Form */}
        <Text style={styles.sectionTitle}>إرسال إشعار جديد</Text>

        <Text style={styles.label}>العنوان *</Text>
        <TextInput testID="input-title" style={styles.input} value={title} onChangeText={setTitle} textAlign="right" maxLength={140} placeholder="مثال: إعلان مهم" placeholderTextColor={colors.textMuted} />

        <Text style={styles.label}>النص *</Text>
        <TextInput testID="input-body" style={[styles.input, { height: 100, textAlignVertical: 'top' }]} value={body} onChangeText={setBody} textAlign="right" multiline maxLength={1000} placeholder="أكتب محتوى الإشعار..." placeholderTextColor={colors.textMuted} />

        <Text style={styles.label}>الجمهور المستهدف</Text>
        <View style={styles.pillRow}>
          {(['all', 'role', 'region', 'ids'] as Audience[]).map((a) => (
            <TouchableOpacity key={a} testID={`aud-${a}`} onPress={() => setAudience(a)} style={[styles.pill, audience === a && styles.pillActive]}>
              <Text style={[styles.pillTxt, audience === a && styles.pillTxtActive]}>{audLabel(a)}</Text>
            </TouchableOpacity>
          ))}
        </View>

        {audience === 'role' ? (
          <View style={{ marginTop: 8 }}>
            <Text style={styles.label}>اختر الدور</Text>
            <View style={styles.pillRow}>
              {[['pharmacy', 'صيدليات'], ['supplier', 'مذاخر'], ['admin', 'مسؤولون']].map(([k, lbl]) => (
                <TouchableOpacity key={k} testID={`role-${k}`} onPress={() => setRole(k)} style={[styles.pill, role === k && styles.pillActive]}>
                  <Text style={[styles.pillTxt, role === k && styles.pillTxtActive]}>{lbl}</Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>
        ) : null}

        {audience === 'region' ? (
          <View style={{ marginTop: 8 }}>
            <Text style={styles.label}>المحافظة</Text>
            <TextInput testID="input-region" style={styles.input} value={region} onChangeText={setRegion} textAlign="right" placeholder="مثال: بغداد" placeholderTextColor={colors.textMuted} />
          </View>
        ) : null}

        {audience === 'ids' ? (
          <View style={{ marginTop: 8 }}>
            <Text style={styles.label}>معرفات المستخدمين (مفصولة بفاصلة)</Text>
            <TextInput testID="input-ids" style={[styles.input, { height: 80, textAlignVertical: 'top' }]} value={ids} onChangeText={setIds} multiline placeholder="uuid1, uuid2, ..." placeholderTextColor={colors.textMuted} />
          </View>
        ) : null}

        {/* Schedule */}
        <Text style={styles.label}>جدولة (اختياري)</Text>
        <TouchableOpacity testID="btn-schedule" style={styles.schedBtn} onPress={() => setPickerOpen(true)}>
          <Ionicons name="time" size={18} color={colors.indigo} />
          <Text style={styles.schedTxt}>{scheduled ? scheduled.toLocaleString('ar-EG', { hour12: false }) : 'إرسال الآن (لم يتم تحديد وقت)'}</Text>
          {scheduled ? (
            <TouchableOpacity onPress={() => setScheduled(null)} style={styles.clearSchedBtn}>
              <Ionicons name="close" size={16} color={colors.error} />
            </TouchableOpacity>
          ) : null}
        </TouchableOpacity>

        {/* Send button */}
        <TouchableOpacity testID="btn-send" style={styles.sendBtn} onPress={send} disabled={sending}>
          {sending ? <ActivityIndicator color="#fff" /> : (
            <>
              <Ionicons name={scheduled ? 'time' : 'send'} size={18} color="#fff" />
              <Text style={styles.sendTxt}>{scheduled ? 'جدولة الإشعار' : 'إرسال الآن'}</Text>
            </>
          )}
        </TouchableOpacity>

        {/* History */}
        <Text style={styles.sectionTitle}>الإشعارات المرسلة (آخر 20)</Text>
        {history.length === 0 ? (
          <Text style={styles.emptyHist}>لا يوجد سجل بعد</Text>
        ) : history.map((b) => (
          <View key={b.id} testID={`batch-${b.id}`} style={styles.batchCard}>
            <View style={{ flex: 1 }}>
              <Text style={styles.batchTitle} numberOfLines={1}>{b.title}</Text>
              <Text style={styles.batchBody} numberOfLines={2}>{b.body}</Text>
              <View style={styles.batchMeta}>
                <StatPill icon="people" text={`${b.total_recipients || 0}`} />
                <StatPill icon="checkmark-done" text={`${b.delivered_count || 0}`} color={colors.primary} />
                {b.failed_count ? <StatPill icon="close-circle" text={`${b.failed_count}`} color={colors.error} /> : null}
                <View style={[styles.statPill, statusColor(b.status)]}>
                  <Text style={styles.statPillTxt}>{statusLabel(b.status)}</Text>
                </View>
              </View>
              <Text style={styles.batchTime}>
                {b.sent_at ? `أرسل ${new Date(b.sent_at).toLocaleString('ar-EG', { hour12: false })}` : b.scheduled_for ? `مجدول ${new Date(b.scheduled_for).toLocaleString('ar-EG', { hour12: false })}` : ''}
              </Text>
            </View>
            {b.status === 'scheduled' ? (
              <TouchableOpacity onPress={() => cancelBatch(b.id)} testID={`cancel-${b.id}`} style={styles.cancelBtn}>
                <Ionicons name="close" size={18} color={colors.error} />
              </TouchableOpacity>
            ) : null}
          </View>
        ))}
      </ScrollView>

      {/* Native picker */}
      {pickerOpen && Platform.OS === 'android' ? (
        <DateTimePicker
          value={scheduled || new Date(Date.now() + 60 * 60 * 1000)}
          mode="datetime"
          minimumDate={new Date()}
          onChange={(e, d) => { setPickerOpen(false); if (e.type === 'set' && d) setScheduled(d); }}
        />
      ) : null}
      {Platform.OS === 'ios' ? (
        <Modal visible={pickerOpen} transparent animationType="slide" onRequestClose={() => setPickerOpen(false)}>
          <View style={styles.modalBackdrop}>
            <View style={styles.modalSheet}>
              <View style={styles.modalHeader}>
                <TouchableOpacity onPress={() => setPickerOpen(false)}><Text style={styles.modalAction}>تم</Text></TouchableOpacity>
                <Text style={styles.modalTitle}>جدولة الإرسال</Text>
                <View style={{ width: 40 }} />
              </View>
              <DateTimePicker value={scheduled || new Date(Date.now() + 60 * 60 * 1000)} mode="datetime" display="spinner" minimumDate={new Date()} onChange={(_, d) => d && setScheduled(d)} />
            </View>
          </View>
        </Modal>
      ) : null}
    </SafeAreaView>
  );
}

function audLabel(a: Audience) {
  return a === 'all' ? 'الجميع' : a === 'role' ? 'حسب الدور' : a === 'region' ? 'حسب المحافظة' : 'مستخدمون محددون';
}
function statusLabel(s: string) { return s === 'sent' ? 'مُرسل' : s === 'scheduled' ? 'مجدول' : s === 'canceled' ? 'ملغي' : s === 'failed' ? 'فشل' : s; }
function statusColor(s: string) {
  if (s === 'sent') return { backgroundColor: '#dcfce7' };
  if (s === 'scheduled') return { backgroundColor: '#fef3c7' };
  if (s === 'canceled') return { backgroundColor: '#e5e7eb' };
  return { backgroundColor: '#fee2e2' };
}

function StatPill({ icon, text, color }: any) {
  const c = color || colors.textSecondary;
  return <View style={styles.statPill}><Ionicons name={icon} size={11} color={c} /><Text style={[styles.statPillTxt, { color: c }]}>{text}</Text></View>;
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  forbidden: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12, padding: 30 },
  forbiddenTxt: { fontSize: 14, color: colors.textSecondary, fontWeight: '700' },
  summaryCard: { flexDirection: 'row-reverse', gap: 8, marginBottom: 6 },
  chip: { backgroundColor: colors.indigoLight, paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999 },
  chipTxt: { fontSize: 12, color: colors.indigo, fontWeight: '700' },
  sectionTitle: { fontSize: 14, color: colors.textPrimary, fontWeight: '800', textAlign: 'right', marginTop: 20, marginBottom: 10 },
  label: { fontSize: 12, color: colors.textSecondary, fontWeight: '700', textAlign: 'right', marginBottom: 6, marginTop: 8 },
  input: { backgroundColor: colors.surface, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, fontSize: 15, color: colors.textPrimary, borderWidth: 1, borderColor: colors.border },
  pillRow: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8 },
  pill: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  pillActive: { backgroundColor: colors.indigo, borderColor: colors.indigo },
  pillTxt: { fontSize: 12, color: colors.textPrimary, fontWeight: '700' },
  pillTxtActive: { color: '#fff' },
  schedBtn: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, padding: 12, backgroundColor: colors.indigoLight, borderRadius: 12 },
  schedTxt: { flex: 1, fontSize: 13, color: colors.indigo, fontWeight: '700', textAlign: 'right' },
  clearSchedBtn: { width: 26, height: 26, borderRadius: 13, backgroundColor: '#fee2e2', alignItems: 'center', justifyContent: 'center' },
  sendBtn: { backgroundColor: colors.primary, borderRadius: 14, paddingVertical: 14, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8, marginTop: 14 },
  sendTxt: { color: '#fff', fontSize: 15, fontWeight: '800' },
  emptyHist: { fontSize: 13, color: colors.textMuted, textAlign: 'center', padding: 20 },
  batchCard: { flexDirection: 'row-reverse', gap: 10, backgroundColor: colors.surface, borderRadius: 14, padding: 12, borderWidth: 1, borderColor: colors.border, marginBottom: 8 },
  batchTitle: { fontSize: 14, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  batchBody: { fontSize: 12, color: colors.textSecondary, textAlign: 'right', marginTop: 2 },
  batchMeta: { flexDirection: 'row-reverse', gap: 6, marginTop: 8, flexWrap: 'wrap' },
  batchTime: { fontSize: 10, color: colors.textMuted, textAlign: 'right', marginTop: 6 },
  statPill: { flexDirection: 'row-reverse', alignItems: 'center', gap: 4, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999, backgroundColor: '#f1f5f9' },
  statPillTxt: { fontSize: 10, fontWeight: '800' },
  cancelBtn: { width: 32, height: 32, borderRadius: 16, backgroundColor: '#fee2e2', alignItems: 'center', justifyContent: 'center' },
  modalBackdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.4)', justifyContent: 'flex-end' },
  modalSheet: { backgroundColor: '#fff', borderTopLeftRadius: 16, borderTopRightRadius: 16, paddingBottom: 12 },
  modalHeader: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', padding: 14, borderBottomWidth: 1, borderBottomColor: colors.border },
  modalTitle: { fontSize: 15, fontWeight: '800', color: colors.textPrimary },
  modalAction: { fontSize: 15, color: colors.primary, fontWeight: '800' },
});
