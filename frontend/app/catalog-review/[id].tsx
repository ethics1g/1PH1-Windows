import { useCallback, useState } from 'react';
import {
  View, Text, StyleSheet, FlatList, ActivityIndicator, RefreshControl,
  TouchableOpacity, Alert, TextInput, Modal, ScrollView, KeyboardAvoidingView, Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect, useLocalSearchParams, useRouter } from 'expo-router';
import { useAuth, apiFetch } from '../../src/auth';
import { colors } from '../../src/theme';
import ScreenHeader from '../../src/ScreenHeader';

type ItemExtracted = { name: string; strength?: string | null; dosage_form?: string | null; manufacturer?: string | null; price: number; quantity: number };
type Item = {
  id: string;
  raw_text: string;
  extracted: ItemExtracted;
  match_status: 'auto' | 'needs_review' | 'approved' | 'rejected';
  match_confidence: number;
  suggested_canonical_name?: string | null;
  approved_name?: string | null;
};
type JobResp = { job: any; items: Item[]; grouped: Record<string, Item[]> };

export default function CatalogReview() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { token } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<JobResp | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [editing, setEditing] = useState<Item | null>(null);
  const [publishing, setPublishing] = useState(false);

  const load = useCallback(async () => {
    try {
      const r: JobResp = await apiFetch(`/supplier/catalog/jobs/${id}`, {}, token);
      setData(r);
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل التحميل');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [id, token]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const patchItem = async (itemId: string, body: any) => {
    try {
      await apiFetch(`/supplier/catalog/items/${itemId}`, { method: 'PATCH', body: JSON.stringify(body) }, token);
      await load();
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل الحفظ');
    }
  };

  const publish = async () => {
    setPublishing(true);
    try {
      const r: any = await apiFetch(`/supplier/catalog/jobs/${id}/publish`, { method: 'POST' }, token);
      Alert.alert('تم النشر', `تم إنشاء ${r.created} وتحديث ${r.updated} منتج`, [
        { text: 'حسناً', onPress: () => router.replace({ pathname: '/supplier-dashboard' } as any) },
      ]);
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل النشر');
    } finally {
      setPublishing(false);
    }
  };

  if (loading) {
    return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} size="large" /></View></SafeAreaView>;
  }
  if (!data) return null;

  const auto = data.grouped.auto || [];
  const review = data.grouped.needs_review || [];
  const approved = data.grouped.approved || [];
  const rejected = data.grouped.rejected || [];
  const willPublish = auto.length + approved.length;
  const isPublished = data.job?.status === 'published';

  return (
    <SafeAreaView style={styles.safe}>
      <ScreenHeader title="مراجعة الاستيراد" subtitle={`${data.items.length} صنف · ${review.length} يحتاج مراجعة`} />

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 120 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}>

        <View style={styles.summary}>
          <SummaryCell label="تلقائي" value={auto.length} color={colors.primary} />
          <SummaryCell label="مراجعة" value={review.length} color={colors.warning} />
          <SummaryCell label="معتمد" value={approved.length} color={colors.secondaryDark} />
          <SummaryCell label="مرفوض" value={rejected.length} color={colors.error} />
        </View>

        {review.length > 0 && <SectionTitle title="🔎 تحتاج مراجعة" />}
        {review.map(it => <ReviewRow key={it.id} item={it} onEdit={() => setEditing(it)} onApprove={() => patchItem(it.id, { match_status: 'approved', approved_name: it.extracted.name })} onReject={() => patchItem(it.id, { match_status: 'rejected' })} />)}

        {auto.length > 0 && <SectionTitle title="✅ تم الاستخراج تلقائياً" />}
        {auto.slice(0, 30).map(it => <AutoRow key={it.id} item={it} onEdit={() => setEditing(it)} onReject={() => patchItem(it.id, { match_status: 'rejected' })} />)}
        {auto.length > 30 && <Text style={styles.moreTxt}>... و {auto.length - 30} صنف آخر</Text>}

        {approved.length > 0 && <SectionTitle title="👍 معتمد للنشر" />}
        {approved.map(it => <AutoRow key={it.id} item={it} onEdit={() => setEditing(it)} onReject={() => patchItem(it.id, { match_status: 'rejected' })} />)}
      </ScrollView>

      {!isPublished && (
        <View style={styles.footer}>
          <TouchableOpacity testID="btn-publish" style={[styles.publishBtn, publishing && { opacity: 0.5 }]} onPress={publish} disabled={publishing || willPublish === 0}>
            {publishing ? <ActivityIndicator color="#fff" /> : (
              <>
                <Ionicons name="rocket" size={20} color="#fff" />
                <Text style={styles.publishTxt}>نشر {willPublish} منتج للسوق</Text>
              </>
            )}
          </TouchableOpacity>
        </View>
      )}
      {isPublished && (
        <View style={styles.footer}>
          <View style={styles.publishedBanner}>
            <Ionicons name="checkmark-circle" size={22} color={colors.primary} />
            <Text style={styles.publishedTxt}>تم النشر · {data.job?.published_count || willPublish} منتج</Text>
          </View>
        </View>
      )}

      {editing && <EditModal item={editing} onClose={() => setEditing(null)} onSave={async (patch) => { await patchItem(editing.id, patch); setEditing(null); }} />}
    </SafeAreaView>
  );
}

function SummaryCell({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <View style={styles.cell}>
      <Text style={[styles.cellValue, { color }]}>{value}</Text>
      <Text style={styles.cellLabel}>{label}</Text>
    </View>
  );
}

function SectionTitle({ title }: { title: string }) {
  return <Text style={styles.sectionTitle}>{title}</Text>;
}

function ReviewRow({ item, onEdit, onApprove, onReject }: { item: Item; onEdit: () => void; onApprove: () => void; onReject: () => void }) {
  return (
    <View style={[styles.row, { borderColor: colors.warning }]} testID={`item-${item.id}`}>
      <View style={{ flex: 1, alignItems: 'flex-end' }}>
        <Text style={styles.itemName}>{item.extracted.name}</Text>
        <Text style={styles.itemMeta}>
          {[item.extracted.strength, item.extracted.dosage_form, item.extracted.manufacturer].filter(Boolean).join(' · ')}
        </Text>
        <View style={styles.priceRow}>
          <Text style={styles.priceTxt}>{Math.round(item.extracted.price).toLocaleString()} د.ع</Text>
          <Text style={styles.qtyTxt}>الكمية: {item.extracted.quantity}</Text>
        </View>
        {item.suggested_canonical_name ? (
          <Text style={styles.suggest}>اقتراح: {item.suggested_canonical_name} · ثقة {Math.round(item.match_confidence * 100)}%</Text>
        ) : null}
      </View>
      <View style={styles.actions}>
        <TouchableOpacity testID={`btn-edit-${item.id}`} style={styles.iconBtn} onPress={onEdit}><Ionicons name="create-outline" size={18} color={colors.secondaryDark} /></TouchableOpacity>
        <TouchableOpacity testID={`btn-approve-${item.id}`} style={[styles.iconBtn, { backgroundColor: colors.primaryLight }]} onPress={onApprove}><Ionicons name="checkmark" size={18} color={colors.primary} /></TouchableOpacity>
        <TouchableOpacity testID={`btn-reject-${item.id}`} style={[styles.iconBtn, { backgroundColor: '#fee2e2' }]} onPress={onReject}><Ionicons name="close" size={18} color={colors.error} /></TouchableOpacity>
      </View>
    </View>
  );
}

function AutoRow({ item, onEdit, onReject }: { item: Item; onEdit: () => void; onReject: () => void }) {
  return (
    <View style={[styles.row, { borderColor: colors.border }]} testID={`item-${item.id}`}>
      <View style={{ flex: 1, alignItems: 'flex-end' }}>
        <Text style={styles.itemName}>{item.extracted.name}</Text>
        <Text style={styles.itemMeta}>
          {[item.extracted.strength, item.extracted.dosage_form].filter(Boolean).join(' · ')}
        </Text>
        <View style={styles.priceRow}>
          <Text style={styles.priceTxt}>{Math.round(item.extracted.price).toLocaleString()} د.ع</Text>
          <Text style={styles.qtyTxt}>الكمية: {item.extracted.quantity}</Text>
        </View>
      </View>
      <View style={styles.actions}>
        <TouchableOpacity style={styles.iconBtn} onPress={onEdit}><Ionicons name="create-outline" size={18} color={colors.secondaryDark} /></TouchableOpacity>
        <TouchableOpacity style={[styles.iconBtn, { backgroundColor: '#fee2e2' }]} onPress={onReject}><Ionicons name="close" size={18} color={colors.error} /></TouchableOpacity>
      </View>
    </View>
  );
}

function EditModal({ item, onClose, onSave }: { item: Item; onClose: () => void; onSave: (patch: any) => void }) {
  const [name, setName] = useState(item.extracted.name);
  const [strength, setStrength] = useState(item.extracted.strength || '');
  const [price, setPrice] = useState(String(item.extracted.price || ''));
  const [qty, setQty] = useState(String(item.extracted.quantity || 0));

  return (
    <Modal visible animationType="slide" transparent onRequestClose={onClose}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={styles.modalWrap}>
        <View style={styles.modal}>
          <View style={styles.modalHead}>
            <Text style={styles.modalTitle}>تعديل المنتج</Text>
            <TouchableOpacity onPress={onClose}><Ionicons name="close" size={24} color={colors.textPrimary} /></TouchableOpacity>
          </View>
          <Text style={styles.modalLabel}>الاسم</Text>
          <TextInput testID="edit-name" style={styles.modalInput} value={name} onChangeText={setName} textAlign="right" />
          <Text style={styles.modalLabel}>التركيز</Text>
          <TextInput testID="edit-strength" style={styles.modalInput} value={strength} onChangeText={setStrength} textAlign="right" />
          <Text style={styles.modalLabel}>السعر (د.ع)</Text>
          <TextInput testID="edit-price" style={styles.modalInput} value={price} onChangeText={setPrice} keyboardType="numeric" textAlign="right" />
          <Text style={styles.modalLabel}>الكمية</Text>
          <TextInput testID="edit-qty" style={styles.modalInput} value={qty} onChangeText={setQty} keyboardType="numeric" textAlign="right" />

          <TouchableOpacity testID="btn-save-edit" style={styles.modalSave} onPress={() => onSave({
            extracted_name: name, strength: strength || null,
            price: parseFloat(price) || 0, quantity: parseInt(qty) || 0,
            approved_name: name, match_status: 'approved',
          })}>
            <Text style={styles.modalSaveTxt}>حفظ واعتماد</Text>
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  summary: { flexDirection: 'row-reverse', backgroundColor: colors.surface, borderRadius: 14, padding: 12, gap: 8, borderWidth: 1, borderColor: colors.border, marginBottom: 14 },
  cell: { flex: 1, alignItems: 'center', gap: 2 },
  cellValue: { fontSize: 22, fontWeight: '900' },
  cellLabel: { fontSize: 11, color: colors.textSecondary },
  sectionTitle: { fontSize: 14, fontWeight: '800', color: colors.textPrimary, textAlign: 'right', marginTop: 8, marginBottom: 8 },
  row: { backgroundColor: colors.surface, borderRadius: 14, padding: 12, marginBottom: 8, borderWidth: 1, flexDirection: 'row-reverse', alignItems: 'center', gap: 8 },
  itemName: { fontSize: 14, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  itemMeta: { fontSize: 11, color: colors.textSecondary, textAlign: 'right' },
  priceRow: { flexDirection: 'row-reverse', gap: 12, marginTop: 4 },
  priceTxt: { fontSize: 13, fontWeight: '800', color: colors.primary },
  qtyTxt: { fontSize: 12, color: colors.textSecondary },
  suggest: { fontSize: 11, color: colors.warning, marginTop: 4, fontStyle: 'italic' },
  actions: { flexDirection: 'row', gap: 4 },
  iconBtn: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.background, alignItems: 'center', justifyContent: 'center' },
  moreTxt: { textAlign: 'center', color: colors.textMuted, padding: 10, fontSize: 12 },
  footer: { position: 'absolute', bottom: 0, left: 0, right: 0, padding: 14, backgroundColor: '#fff', borderTopWidth: 1, borderTopColor: colors.border },
  publishBtn: { backgroundColor: colors.primary, borderRadius: 14, paddingVertical: 14, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8 },
  publishTxt: { color: '#fff', fontWeight: '800', fontSize: 16 },
  publishedBanner: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, justifyContent: 'center', paddingVertical: 8 },
  publishedTxt: { color: colors.primaryDark, fontWeight: '800' },
  modalWrap: { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', justifyContent: 'flex-end' },
  modal: { backgroundColor: '#fff', borderTopLeftRadius: 22, borderTopRightRadius: 22, padding: 20, gap: 6 },
  modalHead: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  modalTitle: { fontSize: 18, fontWeight: '800', color: colors.textPrimary },
  modalLabel: { fontSize: 12, color: colors.textSecondary, textAlign: 'right', marginTop: 4 },
  modalInput: { backgroundColor: colors.background, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 14, borderWidth: 1, borderColor: colors.border },
  modalSave: { backgroundColor: colors.primary, borderRadius: 12, paddingVertical: 12, alignItems: 'center', marginTop: 12 },
  modalSaveTxt: { color: '#fff', fontWeight: '800' },
});
