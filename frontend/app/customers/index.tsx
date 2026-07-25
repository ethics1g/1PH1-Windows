import { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, TextInput, FlatList, TouchableOpacity, ActivityIndicator, RefreshControl } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import ScreenHeader from '../../src/ScreenHeader';
import { colors } from '../../src/theme';
import { apiFetch, useAuth } from '../../src/auth';

export default function CustomersList() {
  const router = useRouter();
  const { token } = useAuth();
  const [q, setQ] = useState('');
  const [scope, setScope] = useState<'customers' | 'suppliers'>('customers');
  const [status, setStatus] = useState<'all' | 'active' | 'paid'>('all');
  const [items, setItems] = useState<any[]>([]);
  const [suppliers, setSuppliers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      if (scope === 'customers') {
        const r: any = await apiFetch(`/customers?q=${encodeURIComponent(q)}&status=${status}&limit=200`, {}, token);
        setItems(r.items || []);
      } else {
        // Suppliers debts: combine the marketplace supplier-accounts endpoint
        // with any paper-order remaining balances (grouped by supplier name).
        const [sa, po] = await Promise.all([
          apiFetch(`/accounting/supplier-accounts`, {}, token).catch(() => ({ items: [] } as any)),
          apiFetch(`/orders/paper?status=unpaid&limit=200`, {}, token).catch(() => ({ items: [] } as any)),
        ]);
        const partials = await apiFetch(`/orders/paper?status=partial&limit=200`, {}, token).catch(() => ({ items: [] } as any));
        // Build a map keyed by supplier_id (or supplier_name if not linked)
        const map: Record<string, any> = {};
        (sa.items || []).forEach((a: any) => {
          const key = a.supplier_id || `n_${a.supplier_name}`;
          map[key] = {
            id: a.supplier_id,
            name: a.supplier_name || 'مذخر غير محدد',
            phone: null,
            total_debt: a.total_purchased || 0,
            remaining_balance: a.outstanding_balance || 0,
            paid: a.credit_applied_total || 0,
            paper_orders_count: 0,
          };
        });
        const addPaper = (o: any) => {
          const key = o.supplier_id || `n_${o.supplier_name || 'مذخر غير محدد'}`;
          if (!map[key]) {
            map[key] = {
              id: o.supplier_id,
              name: o.supplier_name || 'مذخر غير محدد',
              phone: null,
              total_debt: 0,
              remaining_balance: 0,
              paid: 0,
              paper_orders_count: 0,
            };
          }
          map[key].total_debt += o.total || 0;
          map[key].remaining_balance += o.remaining || 0;
          map[key].paid += o.amount_paid || 0;
          map[key].paper_orders_count += 1;
        };
        (po.items || []).forEach(addPaper);
        (partials.items || []).forEach(addPaper);
        let arr = Object.values(map) as any[];
        if (q.trim()) {
          const needle = q.trim().toLowerCase();
          arr = arr.filter(a => (a.name || '').toLowerCase().includes(needle));
        }
        if (status === 'active') arr = arr.filter(a => a.remaining_balance > 0);
        if (status === 'paid') arr = arr.filter(a => a.remaining_balance <= 0);
        arr.sort((a, b) => b.remaining_balance - a.remaining_balance);
        // Attach status field for badge display
        arr.forEach(a => { a.status = a.remaining_balance > 0 ? 'active' : 'paid'; });
        setSuppliers(arr);
      }
    } catch { if (scope === 'customers') setItems([]); else setSuppliers([]); }
  }, [q, status, scope, token]);

  useEffect(() => { setLoading(true); load().finally(() => setLoading(false)); }, [load]);

  const list = scope === 'customers' ? items : suppliers;
  const totalDebt = list.reduce((s, c) => s + (c.remaining_balance || 0), 0);
  const emptyText = scope === 'customers' ? 'لا توجد ديون زبائن مسجلة' : 'لا توجد ديون مذاخر مسجلة';

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <ScreenHeader title="ديون الزبائن" subtitle={`${list.length} ${scope === 'customers' ? 'زبون' : 'مذخر'} · إجمالي: ${totalDebt.toLocaleString()} د.ع`} />

      <View style={styles.scopeTabs}>
        <TouchableOpacity testID="scope-customers" onPress={() => setScope('customers')}
          style={[styles.scopeTab, scope === 'customers' && styles.scopeTabActive]}>
          <Ionicons name="people" size={16} color={scope === 'customers' ? '#fff' : colors.textPrimary} />
          <Text style={[styles.scopeTxt, scope === 'customers' && styles.scopeTxtActive]}>الزبائن</Text>
        </TouchableOpacity>
        <TouchableOpacity testID="scope-suppliers" onPress={() => setScope('suppliers')}
          style={[styles.scopeTab, scope === 'suppliers' && styles.scopeTabActive]}>
          <Ionicons name="business" size={16} color={scope === 'suppliers' ? '#fff' : colors.textPrimary} />
          <Text style={[styles.scopeTxt, scope === 'suppliers' && styles.scopeTxtActive]}>المذاخر</Text>
        </TouchableOpacity>
      </View>

      <View style={styles.searchWrap}>
        <Ionicons name="search" size={18} color={colors.textMuted} style={{ marginHorizontal: 8 }} />
        <TextInput
          testID="cust-search"
          style={styles.searchInput}
          value={q}
          onChangeText={setQ}
          placeholder={scope === 'customers' ? 'ابحث بالاسم أو الهاتف...' : 'ابحث باسم المذخر...'}
          placeholderTextColor={colors.textMuted}
          textAlign="right"
        />
      </View>

      <View style={styles.tabs}>
        {(['all', 'active', 'paid'] as const).map((s) => (
          <TouchableOpacity key={s} testID={`tab-${s}`} onPress={() => setStatus(s)} style={[styles.tab, status === s && styles.tabActive]}>
            <Text style={[styles.tabTxt, status === s && styles.tabTxtActive]}>{tabLabel(s)}</Text>
          </TouchableOpacity>
        ))}
      </View>

      {loading ? (
        <ActivityIndicator style={{ marginTop: 40 }} size="large" color={colors.primary} />
      ) : list.length === 0 ? (
        <View style={styles.empty}>
          <Ionicons name={scope === 'customers' ? 'people-outline' : 'business-outline'} size={54} color={colors.textMuted} />
          <Text style={styles.emptyTxt}>{emptyText}</Text>
        </View>
      ) : (
        <FlatList
          data={list}
          keyExtractor={(i, idx) => i.id || `sup-${idx}`}
          contentContainerStyle={{ padding: 12, gap: 10 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
          renderItem={({ item }) => (
            <TouchableOpacity
              testID={scope === 'customers' ? `cust-${item.id}` : `sup-${item.id || item.name}`}
              style={styles.card}
              onPress={() => {
                if (scope === 'customers') router.push(`/customers/${item.id}` as any);
                else if (item.id) router.push(`/accounting/supplier-accounts/${item.id}` as any);
              }}
            >
              <View style={[styles.avatar, item.status === 'paid' ? styles.avatarPaid : styles.avatarActive]}>
                <Ionicons name={scope === 'customers' ? 'person' : 'business'} size={22} color="#fff" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>{item.name}</Text>
                {item.phone ? <Text style={styles.phone}>{item.phone}</Text> : null}
                {scope === 'suppliers' && item.paper_orders_count ? (
                  <Text style={styles.phone}>{item.paper_orders_count} طلبية مصورة</Text>
                ) : null}
                <View style={styles.metaRow}>
                  <Text style={styles.metaLbl}>إجمالي: <Text style={styles.metaVal}>{(item.total_debt || 0).toLocaleString()}</Text></Text>
                  <Text style={styles.metaLbl}>متبقي: <Text style={[styles.metaVal, item.remaining_balance > 0 ? styles.warnVal : styles.paidVal]}>{(item.remaining_balance || 0).toLocaleString()}</Text></Text>
                </View>
                {item.last_payment_at ? <Text style={styles.lastPay}>آخر دفعة: {new Date(item.last_payment_at).toLocaleDateString('ar-EG')}</Text> : null}
              </View>
              <View style={[styles.statusBadge, item.status === 'paid' ? styles.badgePaid : styles.badgeActive]}>
                <Text style={styles.badgeTxt}>{item.status === 'paid' ? 'مسدد' : 'مدين'}</Text>
              </View>
            </TouchableOpacity>
          )}
        />
      )}
    </SafeAreaView>
  );
}

function tabLabel(s: string) { return s === 'all' ? 'الكل' : s === 'active' ? 'مدين' : 'مسدد'; }

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  searchWrap: { flexDirection: 'row-reverse', alignItems: 'center', marginHorizontal: 12, backgroundColor: colors.surface, borderRadius: 12, borderWidth: 1, borderColor: colors.border },
  searchInput: { flex: 1, paddingVertical: 12, paddingHorizontal: 8, fontSize: 15, color: colors.textPrimary },
  scopeTabs: { flexDirection: 'row-reverse', gap: 8, paddingHorizontal: 12, paddingTop: 10, paddingBottom: 4 },
  scopeTab: { flex: 1, flexDirection: 'row-reverse', gap: 6, alignItems: 'center', justifyContent: 'center', paddingVertical: 10, borderRadius: 10, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  scopeTabActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  scopeTxt: { fontSize: 13, fontWeight: '800', color: colors.textPrimary },
  scopeTxtActive: { color: '#fff' },
  tabs: { flexDirection: 'row-reverse', gap: 8, paddingHorizontal: 12, paddingVertical: 10 },
  tab: { paddingHorizontal: 14, paddingVertical: 7, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  tabActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  tabTxt: { fontSize: 12, color: colors.textPrimary, fontWeight: '700' },
  tabTxtActive: { color: '#fff' },
  card: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, backgroundColor: colors.surface, borderRadius: 14, padding: 12, borderWidth: 1, borderColor: colors.border },
  avatar: { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center' },
  avatarActive: { backgroundColor: '#dc2626' },
  avatarPaid: { backgroundColor: '#16a34a' },
  name: { fontSize: 15, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  phone: { fontSize: 12, color: colors.textMuted, textAlign: 'right' },
  metaRow: { flexDirection: 'row-reverse', gap: 14, marginTop: 4 },
  metaLbl: { fontSize: 11, color: colors.textSecondary },
  metaVal: { fontWeight: '800', color: colors.textPrimary },
  warnVal: { color: '#dc2626' },
  paidVal: { color: '#16a34a' },
  lastPay: { fontSize: 10, color: colors.textMuted, marginTop: 2 },
  statusBadge: { paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999 },
  badgeActive: { backgroundColor: '#fee2e2' },
  badgePaid: { backgroundColor: '#dcfce7' },
  badgeTxt: { fontSize: 11, fontWeight: '800', color: colors.textPrimary },
  empty: { alignItems: 'center', marginTop: 60, gap: 12 },
  emptyTxt: { fontSize: 14, color: colors.textMuted },
});
