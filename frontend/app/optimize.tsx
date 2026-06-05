import { useEffect, useRef, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator, Alert, Linking, Platform } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useAuth, apiFetch } from '../src/auth';
import { colors } from '../src/theme';
import ScreenHeader from '../src/ScreenHeader';

type SupplierGroup = {
  supplier_id: string;
  supplier_name: string;
  supplier_phone?: string;
  items: { name: string; quantity: number; unit_price: number; line_total: number }[];
  total: number;
};

type OptimizeResult = {
  unavailable: string[];
  per_item: { plan: any[]; total: number; savings_vs_max: number };
  single_supplier: { options: SupplierGroup[]; best: SupplierGroup | null; savings_vs_max: number };
  smart_split: { groups: SupplierGroup[]; items_summary: any[]; total: number; savings_vs_max: number };
  summary: { cheapest_total: number; most_expensive_total: number; max_savings: number };
};

const fmt = (n: number) => Math.round(n).toLocaleString();

export default function Optimize() {
  const { token } = useAuth();
  const router = useRouter();
  const params = useLocalSearchParams<{ items?: string }>();
  const [loading, setLoading] = useState(true);
  const [result, setResult] = useState<OptimizeResult | null>(null);
  const [tab, setTab] = useState<'split' | 'single'>('split');
  const [committed, setCommitted] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [cumulativeSavings, setCumulativeSavings] = useState<number | null>(null);
  const [completedOrders, setCompletedOrders] = useState<number>(0);
  const commitIdRef = useRef<string>('');

  useEffect(() => {
    if (!token) return; // wait for AsyncStorage hydration
    (async () => {
      try {
        const items = params.items ? JSON.parse(params.items as string) : [];
        if (!items.length) {
          Alert.alert('فارغ', 'لا توجد أدوية لتحليلها');
          router.replace('/home');
          return;
        }
        const [res, sav]: any = await Promise.all([
          apiFetch('/orders/optimize', { method: 'POST', body: JSON.stringify({ items }) }, token),
          apiFetch('/pharmacy/savings', {}, token).catch(() => ({ cumulative_savings: 0, completed_orders: 0 })),
        ]);
        setResult(res);
        setCumulativeSavings(sav?.cumulative_savings || 0);
        setCompletedOrders(sav?.completed_orders || 0);
      } catch (e: any) {
        Alert.alert('خطأ', e.message || 'فشل التحليل');
        router.replace('/home');
      } finally {
        setLoading(false);
      }
    })();
  }, [token]);

  const sendWhatsApp = (group: SupplierGroup) => {
    const lines = group.items.map((it, i) => `${i + 1}. ${it.name} × ${it.quantity} = ${fmt(it.line_total)} د.ع`).join('\n');
    const msg = `طلبية:\n\n${lines}\n\nالمجموع: ${fmt(group.total)} د.ع`;
    const phone = (group.supplier_phone || '').replace(/[^\d]/g, '');
    const url = phone ? `https://wa.me/${phone}?text=${encodeURIComponent(msg)}` : `https://wa.me/?text=${encodeURIComponent(msg)}`;
    Linking.openURL(url);
  };

  const confirmOrder = async (groups: SupplierGroup[]) => {
    if (committed || committing) return;
    if (!groups || groups.length === 0) return;
    Alert.alert(
      'تثبيت الطلبية',
      `سيتم إرسال طلبية لكل مذخر (${groups.length}). المذاخر ستحتاج لقبول الطلبية أولاً، ثم تجهيزها وتوصيلها. تأكد من الاستلام لتفعيل احتساب العمولة (4%) عند إكمال الطلبية. هل تريد المتابعة؟`,
      [
        { text: 'إلغاء', style: 'cancel' },
        { text: 'تأكيد الطلب', style: 'default', onPress: async () => {
          setCommitting(true);
          try {
            // Generate idempotent commit_id
            if (!commitIdRef.current) {
              commitIdRef.current = `c_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
            }
            const worstTotal = result?.summary?.most_expensive_total || 0;
            const actualTotal = groups.reduce((s, g) => s + g.total, 0);
            // Distribute proportionally
            const savings_total = Math.max(0, worstTotal - actualTotal);
            const savings_per_group = groups.map(g => actualTotal > 0
              ? Math.round((savings_total * g.total) / actualTotal)
              : 0);
            const payload = {
              commit_id: commitIdRef.current,
              groups: groups.map(g => ({
                supplier_id: g.supplier_id,
                supplier_name: g.supplier_name,
                total: g.total,
                items: g.items.map(it => ({ name: it.name, quantity: it.quantity, unit_price: it.unit_price })),
              })),
              savings_estimate_total: savings_total,
              savings_per_group,
            };
            const res: any = await apiFetch('/orders/optimize/commit', { method: 'POST', body: JSON.stringify(payload) }, token);
            setCommitted(true);
            Alert.alert(
              '✅ تم إرسال الطلب',
              `تم إنشاء ${res.created} طلبية. سيتم إشعار المذاخر للقبول.`,
              [{ text: 'عرض طلبياتي', onPress: () => router.replace('/pharmacy-orders' as any) }],
            );
          } catch (e: any) {
            Alert.alert('خطأ', e.message || 'فشل التثبيت');
          } finally {
            setCommitting(false);
          }
        }},
      ],
    );
  };

  const copyAll = (groups: SupplierGroup[]) => {
    const txt = groups.map(g => {
      const lines = g.items.map((it, i) => `${i + 1}. ${it.name} × ${it.quantity}`).join('\n');
      return `📦 ${g.supplier_name}\n${lines}\nالمجموع: ${fmt(g.total)} د.ع`;
    }).join('\n\n──────────\n\n');
    if (Platform.OS === 'web' && typeof navigator !== 'undefined' && navigator.clipboard) {
      navigator.clipboard.writeText(txt);
    }
    Alert.alert('تم النسخ', 'يمكنك لصق النص الآن أو أخذ لقطة شاشة');
  };

  if (loading) {
    return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} size="large" /><Text style={styles.loadTxt}>جاري المقارنة بين المذاخر...</Text></View></SafeAreaView>;
  }

  if (!result) return null;

  const split = result.smart_split;
  const single = result.single_supplier;
  const summary = result.summary;
  const noOffers = !split.groups.length && !single.options.length;

  return (
    <SafeAreaView style={styles.safe}>
      <ScreenHeader title="اقتراح أفضل سعر" subtitle="مقارنة بين المذاخر" />

      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 40 }}>
        {/* Savings highlight */}
        {summary.max_savings > 0 && (
          <View style={styles.savingsCard}>
            <View style={styles.savingsIcon}><Ionicons name="trending-down" size={26} color="#fff" /></View>
            <View style={{ flex: 1, alignItems: 'flex-end' }}>
              <Text style={styles.savingsLabel}>التوفير المحتمل</Text>
              <Text style={styles.savingsValue} testID="max-savings">{fmt(summary.max_savings)} د.ع</Text>
            </View>
          </View>
        )}

        {result.unavailable.length > 0 && (
          <View style={styles.warnCard} testID="unavailable-warn">
            <Ionicons name="warning" size={20} color={colors.warning} />
            <View style={{ flex: 1 }}>
              <Text style={styles.warnTitle}>أدوية غير متوفرة عند أي مذخر:</Text>
              <Text style={styles.warnList}>{result.unavailable.join('، ')}</Text>
            </View>
          </View>
        )}

        {noOffers ? (
          <View style={styles.empty}>
            <Ionicons name="search" size={64} color={colors.textMuted} />
            <Text style={styles.emptyTxt}>لا توجد عروض مطابقة من المذاخر حالياً</Text>
          </View>
        ) : (
          <>
            {/* Tabs */}
            <View style={styles.tabs}>
              <TouchableOpacity
                testID="tab-split"
                style={[styles.tab, tab === 'split' && styles.tabActive]}
                onPress={() => setTab('split')}
              >
                <Ionicons name="git-branch" size={16} color={tab === 'split' ? '#fff' : colors.textSecondary} />
                <Text style={[styles.tabTxt, tab === 'split' && styles.tabTxtActive]}>تقسيم ذكي</Text>
                {split.groups.length > 0 && <Text style={[styles.tabBadge, tab === 'split' && styles.tabBadgeActive]}>{fmt(split.total)}</Text>}
              </TouchableOpacity>
              <TouchableOpacity
                testID="tab-single"
                style={[styles.tab, tab === 'single' && styles.tabActive]}
                onPress={() => setTab('single')}
              >
                <Ionicons name="business" size={16} color={tab === 'single' ? '#fff' : colors.textSecondary} />
                <Text style={[styles.tabTxt, tab === 'single' && styles.tabTxtActive]}>مذخر واحد</Text>
                {single.best && <Text style={[styles.tabBadge, tab === 'single' && styles.tabBadgeActive]}>{fmt(single.best.total)}</Text>}
              </TouchableOpacity>
            </View>

            {tab === 'split' ? (
              <SplitView groups={split.groups} total={split.total} savings={split.savings_vs_max} maxTotal={summary.most_expensive_total} onSend={sendWhatsApp} onCopy={() => copyAll(split.groups)} onConfirm={() => confirmOrder(split.groups)} committed={committed} committing={committing} />
            ) : (
              <SingleSupplierView options={single.options} maxTotal={summary.most_expensive_total} onSend={sendWhatsApp} onConfirm={(g) => confirmOrder([g])} committed={committed} committing={committing} />
            )}
          </>
        )}
      </ScrollView>

      {/* Persistent cumulative savings banner (pharmacy-only) */}
      {cumulativeSavings !== null && cumulativeSavings >= 0 && (
        <View style={styles.cumBanner} testID="cumulative-savings-banner">
          <Ionicons name="ribbon" size={20} color="#fff" />
          <View style={{ flex: 1, alignItems: 'flex-end' }}>
            <Text style={styles.cumLabel}>إجمالي توفيرك مع 1PH1</Text>
            <Text style={styles.cumValue} testID="cumulative-savings-value">
              {fmt(cumulativeSavings)} د.ع
              {completedOrders > 0 ? <Text style={styles.cumSub}>  ({completedOrders} طلبية مكتملة)</Text> : null}
            </Text>
          </View>
        </View>
      )}
    </SafeAreaView>
  );
}

function SplitView({ groups, total, savings, maxTotal, onSend, onCopy, onConfirm, committed, committing }: { groups: SupplierGroup[]; total: number; savings: number; maxTotal: number; onSend: (g: SupplierGroup) => void; onCopy: () => void; onConfirm: () => void; committed: boolean; committing: boolean }) {
  if (!groups.length) return <Text style={styles.emptyTxt}>لا يوجد عرض تقسيم</Text>;
  return (
    <View style={{ gap: 12 }}>
      <View style={styles.totalCard}>
        <Text style={styles.totalLabel}>المجموع الكلي</Text>
        <Text style={styles.totalValue} testID="split-total">{fmt(total)} د.ع</Text>
        {savings > 0 && <Text style={styles.savePill}>توفير {fmt(savings)} د.ع</Text>}
      </View>

      <TouchableOpacity testID="btn-confirm-split" style={[styles.confirmBtn, committed && styles.confirmedBtn]} onPress={onConfirm} disabled={committed || committing}>
        {committing ? <ActivityIndicator color="#fff" /> : (
          <>
            <Ionicons name={committed ? 'checkmark-done' : 'lock-closed'} size={18} color="#fff" />
            <Text style={styles.confirmTxt}>{committed ? 'تم التثبيت ✓' : 'تثبيت الطلبية وحساب العمولة'}</Text>
          </>
        )}
      </TouchableOpacity>

      <TouchableOpacity testID="btn-copy-all" style={styles.copyBtn} onPress={onCopy}>
        <Ionicons name="copy-outline" size={18} color={colors.secondaryDark} />
        <Text style={styles.copyTxt}>نسخ الكل (لقطة شاشة)</Text>
      </TouchableOpacity>

      {groups.map(g => (
        <SupplierCard key={g.supplier_id} group={g} onSend={onSend} maxTotal={maxTotal} />
      ))}
    </View>
  );
}

function SingleSupplierView({ options, maxTotal, onSend, onConfirm, committed, committing }: { options: SupplierGroup[]; maxTotal: number; onSend: (g: SupplierGroup) => void; onConfirm: (g: SupplierGroup) => void; committed: boolean; committing: boolean }) {
  if (!options.length) {
    return (
      <View style={styles.empty}>
        <Ionicons name="information-circle" size={48} color={colors.textMuted} />
        <Text style={styles.emptyTxt}>لا يوجد مذخر يملك جميع الأدوية. جرّب التقسيم الذكي.</Text>
      </View>
    );
  }
  return (
    <View style={{ gap: 12 }}>
      {options.map((g, i) => (
        <View key={g.supplier_id}>
          {i === 0 && <View style={styles.bestBadge}><Ionicons name="star" size={12} color="#fff" /><Text style={styles.bestTxt}>الأرخص</Text></View>}
          <SupplierCard group={g} onSend={onSend} highlight={i === 0} maxTotal={maxTotal} />
          {i === 0 && (
            <TouchableOpacity testID={`btn-confirm-single-${g.supplier_id}`} style={[styles.confirmBtn, { marginTop: 8 }, committed && styles.confirmedBtn]} onPress={() => onConfirm(g)} disabled={committed || committing}>
              {committing ? <ActivityIndicator color="#fff" /> : (
                <>
                  <Ionicons name={committed ? 'checkmark-done' : 'lock-closed'} size={18} color="#fff" />
                  <Text style={styles.confirmTxt}>{committed ? 'تم التثبيت ✓' : 'تثبيت مع هذا المذخر'}</Text>
                </>
              )}
            </TouchableOpacity>
          )}
        </View>
      ))}
    </View>
  );
}

function SupplierCard({ group, onSend, highlight, maxTotal }: { group: SupplierGroup; onSend: (g: SupplierGroup) => void; highlight?: boolean; maxTotal?: number }) {
  const savePct = (maxTotal && maxTotal > group.total) ? Math.round(((maxTotal - group.total) / maxTotal) * 100) : 0;
  return (
    <View style={[styles.card, highlight && styles.cardHighlight]} testID={`supplier-card-${group.supplier_id}`}>
      <View style={styles.cardHead}>
        <View style={{ flex: 1, alignItems: 'flex-end' }}>
          <Text style={styles.supplierName}>{group.supplier_name}</Text>
          <Text style={styles.supplierTotal}>{fmt(group.total)} د.ع</Text>
          {savePct > 0 && (
            <View style={styles.savePctPill} testID={`savings-pct-${group.supplier_id}`}>
              <Ionicons name="trending-down" size={11} color="#166534" />
              <Text style={styles.savePctTxt}>توفير {savePct}%</Text>
            </View>
          )}
        </View>
        <View style={styles.supplierIcon}><Ionicons name="storefront" size={22} color={colors.indigo} /></View>
      </View>

      <View style={styles.itemsList}>
        {group.items.map((it, idx) => (
          <View key={idx} style={styles.itemRow}>
            <Text style={styles.itemTotal}>{fmt(it.line_total)} د.ع</Text>
            <View style={{ flex: 1, alignItems: 'flex-end' }}>
              <Text style={styles.itemName}>{it.name}</Text>
              <Text style={styles.itemSub}>{it.quantity} × {fmt(it.unit_price)} د.ع</Text>
            </View>
          </View>
        ))}
      </View>

      <TouchableOpacity testID={`btn-whatsapp-${group.supplier_id}`} style={styles.waBtn} onPress={() => onSend(group)}>
        <Ionicons name="logo-whatsapp" size={20} color="#fff" />
        <Text style={styles.waTxt}>إرسال لـ {group.supplier_name} عبر واتساب</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12 },
  loadTxt: { color: colors.textSecondary, fontSize: 14 },
  savingsCard: { backgroundColor: colors.primary, borderRadius: 18, padding: 16, flexDirection: 'row-reverse', alignItems: 'center', gap: 12, marginBottom: 12 },
  savingsIcon: { width: 44, height: 44, borderRadius: 22, backgroundColor: 'rgba(255,255,255,0.2)', alignItems: 'center', justifyContent: 'center' },
  savingsLabel: { color: 'rgba(255,255,255,0.85)', fontSize: 12 },
  savingsValue: { color: '#fff', fontWeight: '900', fontSize: 22 },
  warnCard: { backgroundColor: colors.warningLight, borderRadius: 14, padding: 12, flexDirection: 'row-reverse', gap: 10, alignItems: 'flex-start', marginBottom: 12 },
  warnTitle: { color: colors.warning, fontWeight: '800', textAlign: 'right', fontSize: 13 },
  warnList: { color: colors.textSecondary, textAlign: 'right', fontSize: 12, marginTop: 4 },
  empty: { alignItems: 'center', justifyContent: 'center', padding: 30, gap: 10 },
  emptyTxt: { color: colors.textSecondary, textAlign: 'center', fontSize: 14 },
  tabs: { flexDirection: 'row-reverse', backgroundColor: colors.surface, borderRadius: 14, padding: 4, marginBottom: 12, borderWidth: 1, borderColor: colors.border },
  tab: { flex: 1, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', paddingVertical: 12, gap: 6, borderRadius: 10 },
  tabActive: { backgroundColor: colors.primary },
  tabTxt: { color: colors.textSecondary, fontWeight: '700' },
  tabTxtActive: { color: '#fff' },
  tabBadge: { color: colors.textMuted, fontSize: 11, fontWeight: '700' },
  tabBadgeActive: { color: 'rgba(255,255,255,0.85)' },
  totalCard: { backgroundColor: colors.surface, borderRadius: 16, padding: 14, borderWidth: 1, borderColor: colors.border, alignItems: 'flex-end' },
  totalLabel: { color: colors.textSecondary, fontSize: 12 },
  totalValue: { color: colors.primary, fontWeight: '900', fontSize: 22, marginTop: 2 },
  savePill: { backgroundColor: colors.primaryLight, color: colors.primaryDark, paddingHorizontal: 10, paddingVertical: 3, borderRadius: 8, fontSize: 12, fontWeight: '800', marginTop: 6, overflow: 'hidden' },
  copyBtn: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 6, padding: 10, borderRadius: 10, backgroundColor: colors.secondaryLight },
  copyTxt: { color: colors.secondaryDark, fontWeight: '800' },
  card: { backgroundColor: colors.surface, borderRadius: 18, padding: 14, borderWidth: 1, borderColor: colors.border },
  cardHighlight: { borderColor: colors.primary, borderWidth: 2 },
  cardHead: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, paddingBottom: 10, borderBottomWidth: 1, borderBottomColor: colors.border },
  supplierIcon: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.indigoLight, alignItems: 'center', justifyContent: 'center' },
  supplierName: { fontSize: 16, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  supplierTotal: { color: colors.primary, fontWeight: '900', fontSize: 17 },
  itemsList: { paddingVertical: 8, gap: 6 },
  itemRow: { flexDirection: 'row-reverse', alignItems: 'center' },
  itemName: { color: colors.textPrimary, textAlign: 'right', fontWeight: '700', fontSize: 14 },
  itemSub: { color: colors.textMuted, fontSize: 12, textAlign: 'right' },
  itemTotal: { color: colors.secondaryDark, fontWeight: '800', fontSize: 13, marginLeft: 8 },
  waBtn: { backgroundColor: '#25D366', borderRadius: 12, paddingVertical: 12, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8, marginTop: 8 },
  waTxt: { color: '#fff', fontWeight: '800', fontSize: 14 },
  bestBadge: { position: 'absolute', top: -2, right: 14, zIndex: 1, backgroundColor: colors.primary, flexDirection: 'row-reverse', gap: 4, paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999, alignItems: 'center' },
  bestTxt: { color: '#fff', fontSize: 11, fontWeight: '800' },
  confirmBtn: { backgroundColor: colors.indigo, borderRadius: 14, paddingVertical: 14, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8, shadowColor: colors.indigo, shadowOpacity: 0.25, shadowRadius: 10, shadowOffset: { width: 0, height: 4 }, elevation: 4 },
  confirmedBtn: { backgroundColor: '#22c55e' },
  confirmTxt: { color: '#fff', fontWeight: '900', fontSize: 14 },
  // Per-supplier savings percentage pill (green)
  savePctPill: { flexDirection: 'row-reverse', alignItems: 'center', gap: 4, backgroundColor: '#dcfce7', paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999, marginTop: 4 },
  savePctTxt: { color: '#166534', fontSize: 11, fontWeight: '800' },
  // Persistent cumulative savings banner at the bottom of the screen
  cumBanner: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, backgroundColor: colors.indigo, paddingHorizontal: 16, paddingVertical: 12, borderTopLeftRadius: 18, borderTopRightRadius: 18, shadowColor: '#000', shadowOpacity: 0.15, shadowRadius: 8, shadowOffset: { width: 0, height: -2 }, elevation: 8 },
  cumLabel: { color: 'rgba(255,255,255,0.85)', fontSize: 11, fontWeight: '600', textAlign: 'right' },
  cumValue: { color: '#fff', fontWeight: '900', fontSize: 18, textAlign: 'right', marginTop: 2 },
  cumSub: { color: 'rgba(255,255,255,0.85)', fontSize: 12, fontWeight: '600' },
});
