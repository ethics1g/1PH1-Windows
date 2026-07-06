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
  const [status, setStatus] = useState<'all' | 'active' | 'paid'>('all');
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const r: any = await apiFetch(`/customers?q=${encodeURIComponent(q)}&status=${status}&limit=200`, {}, token);
      setItems(r.items || []);
    } catch { setItems([]); }
  }, [q, status, token]);

  useEffect(() => { setLoading(true); load().finally(() => setLoading(false)); }, [load]);

  const totalDebt = items.reduce((s, c) => s + (c.remaining_balance || 0), 0);

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <ScreenHeader title="ديون الزبائن" subtitle={`${items.length} زبون · إجمالي: ${totalDebt.toLocaleString()} د.ع`} />

      <View style={styles.searchWrap}>
        <Ionicons name="search" size={18} color={colors.textMuted} style={{ marginHorizontal: 8 }} />
        <TextInput
          testID="cust-search"
          style={styles.searchInput}
          value={q}
          onChangeText={setQ}
          placeholder="ابحث بالاسم أو الهاتف..."
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
      ) : items.length === 0 ? (
        <View style={styles.empty}>
          <Ionicons name="people-outline" size={54} color={colors.textMuted} />
          <Text style={styles.emptyTxt}>لا توجد ديون مسجلة</Text>
        </View>
      ) : (
        <FlatList
          data={items}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: 12, gap: 10 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
          renderItem={({ item }) => (
            <TouchableOpacity testID={`cust-${item.id}`} style={styles.card} onPress={() => router.push(`/customers/${item.id}` as any)}>
              <View style={[styles.avatar, item.status === 'paid' ? styles.avatarPaid : styles.avatarActive]}>
                <Ionicons name="person" size={22} color="#fff" />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>{item.name}</Text>
                {item.phone ? <Text style={styles.phone}>{item.phone}</Text> : null}
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
