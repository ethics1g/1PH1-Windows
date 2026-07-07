import { useCallback, useState } from 'react';
import { View, Text, StyleSheet, FlatList, TouchableOpacity, ScrollView, ActivityIndicator, RefreshControl, Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter, useFocusEffect } from 'expo-router';
import ScreenHeader from '../src/ScreenHeader';
import { colors } from '../src/theme';
import { apiFetch, useAuth } from '../src/auth';

const STATUS_META: Record<string, { label: string; color: string; bg: string }> = {
  pending:          { label: 'بانتظار الموافقة', color: '#92400e', bg: '#fef3c7' },
  approved:         { label: 'موافق', color: '#1e40af', bg: '#dbeafe' },
  waiting_receipt:  { label: 'بانتظار الاستلام', color: '#7c3aed', bg: '#ede9fe' },
  completed:        { label: 'مكتمل', color: '#166534', bg: '#dcfce7' },
  rejected:         { label: 'مرفوض', color: '#991b1b', bg: '#fee2e2' },
};
const FILTERS = ['all', 'pending', 'approved', 'waiting_receipt', 'completed', 'rejected'];

export default function SupplierReturns() {
  const router = useRouter();
  const { token } = useAuth();
  const [items, setItems] = useState<any[]>([]);
  const [filter, setFilter] = useState('all');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const q = filter === 'all' ? '' : `?status=${filter}`;
      const r: any = await apiFetch(`/returns${q}`, {}, token);
      setItems(r.items || []);
    } catch (e: any) { Alert.alert('خطأ', e.message); }
    finally { setLoading(false); setRefreshing(false); }
  }, [token, filter]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <ScreenHeader title="الرواجع" subtitle={`${items.length} طلب إرجاع`} />
      <View style={styles.tabsWrap}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: 12, gap: 6 }}>
          {FILTERS.map(f => (
            <TouchableOpacity key={f} testID={`sr-flt-${f}`} onPress={() => setFilter(f)} style={[styles.tab, filter === f && styles.tabOn]}>
              <Text style={[styles.tabTxt, filter === f && styles.tabTxtOn]}>{f === 'all' ? 'الكل' : STATUS_META[f]?.label || f}</Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
      </View>
      {loading ? <ActivityIndicator style={{ marginTop: 40 }} size="large" color={colors.primary} /> : (
        <FlatList
          data={items}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: 12, gap: 10 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          ListEmptyComponent={<Text style={styles.empty}>لا توجد طلبات إرجاع</Text>}
          renderItem={({ item }) => {
            const meta = STATUS_META[item.status] || STATUS_META.pending;
            return (
              <TouchableOpacity testID={`sr-${item.id}`} style={styles.card} onPress={() => router.push(`/returns/${item.id}` as any)}>
                <View style={styles.rowTop}>
                  <View style={[styles.pill, { backgroundColor: meta.bg }]}>
                    <Text style={[styles.pillTxt, { color: meta.color }]}>{meta.label}</Text>
                  </View>
                  <Text style={styles.date}>{new Date(item.created_at).toLocaleDateString('ar-EG')}</Text>
                </View>
                <View style={styles.pharm}>
                  <Ionicons name="storefront" size={16} color={colors.indigo} />
                  <Text style={styles.pharmTxt}>{item.pharmacy_name || 'صيدلية'}</Text>
                </View>
                <View style={styles.itemsBox}>
                  {(item.items || []).slice(0, 3).map((it: any, i: number) => (
                    <Text key={i} style={styles.itemLine}>• {it.name} × {it.quantity}</Text>
                  ))}
                </View>
                <Text style={styles.total}>القيمة: {(item.total || 0).toLocaleString()} د.ع</Text>
              </TouchableOpacity>
            );
          }}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  tabsWrap: { paddingVertical: 10 },
  tab: { paddingHorizontal: 14, paddingVertical: 7, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  tabOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  tabTxt: { fontSize: 12, fontWeight: '700', color: colors.textPrimary },
  tabTxtOn: { color: '#fff' },
  card: { backgroundColor: colors.surface, borderRadius: 14, padding: 12, borderWidth: 1, borderColor: colors.border },
  rowTop: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center' },
  pill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999 },
  pillTxt: { fontSize: 11, fontWeight: '800' },
  date: { fontSize: 11, color: colors.textMuted },
  pharm: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, marginTop: 8 },
  pharmTxt: { fontSize: 14, fontWeight: '800', color: colors.textPrimary },
  itemsBox: { marginTop: 6 },
  itemLine: { fontSize: 12, color: colors.textSecondary, textAlign: 'right' },
  total: { marginTop: 8, fontSize: 13, fontWeight: '800', color: colors.primary, textAlign: 'right' },
  empty: { textAlign: 'center', color: colors.textMuted, padding: 40 },
});
