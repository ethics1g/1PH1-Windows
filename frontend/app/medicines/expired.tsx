import { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, FlatList, ActivityIndicator, RefreshControl, Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import ScreenHeader from '../../src/ScreenHeader';
import { colors } from '../../src/theme';
import { apiFetch, useAuth } from '../../src/auth';

type Med = { id: string; name: string; barcode?: string; expiry_date?: string; stock: number; price?: number };

export default function ExpiredMedicines() {
  const { token } = useAuth();
  const [items, setItems] = useState<Med[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const r: any = await apiFetch('/medicines/expired-list', {}, token);
      setItems(r.items || []);
    } catch (e: any) { Alert.alert('خطأ', e.message); }
  }, [token]);

  useEffect(() => { (async () => { setLoading(true); await load(); setLoading(false); })(); }, [load]);

  const totalUnits = items.reduce((s, m) => s + (m.stock || 0), 0);

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <ScreenHeader title="الأدوية المنتهية" subtitle={items.length ? `${items.length} دواء · ${totalUnits} وحدة` : ''} />

      {loading ? (
        <View style={styles.empty}><ActivityIndicator size="large" color={colors.primary} /></View>
      ) : items.length === 0 ? (
        <View style={styles.empty}>
          <Ionicons name="checkmark-done-circle" size={64} color={colors.primary} />
          <Text style={styles.emptyTxt}>لا توجد أدوية منتهية الصلاحية 🎉</Text>
        </View>
      ) : (
        <FlatList
          data={items}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: 12, gap: 10 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
          renderItem={({ item }) => (
            <View testID={`expired-${item.id}`} style={styles.card}>
              <View style={styles.iconBox}><Ionicons name="warning" size={22} color={colors.error} /></View>
              <View style={{ flex: 1 }}>
                <Text style={styles.name} numberOfLines={2}>{item.name}</Text>
                {item.barcode ? <Text style={styles.barcode}>باركود: {item.barcode}</Text> : null}
                <View style={styles.tags}>
                  <View style={[styles.tag, styles.tagRed]}>
                    <Ionicons name="calendar" size={12} color={colors.error} />
                    <Text style={[styles.tagTxt, { color: colors.error }]}>{item.expiry_date || '-'}</Text>
                  </View>
                  <View style={[styles.tag, styles.tagWarn]}>
                    <Ionicons name="cube" size={12} color={colors.warning} />
                    <Text style={[styles.tagTxt, { color: '#92400e' }]}>{item.stock} وحدة</Text>
                  </View>
                </View>
              </View>
            </View>
          )}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  card: { flexDirection: 'row-reverse', alignItems: 'flex-start', gap: 10, backgroundColor: colors.surface, borderRadius: 14, padding: 12, borderWidth: 1, borderColor: colors.border },
  iconBox: { width: 42, height: 42, borderRadius: 21, backgroundColor: '#fee2e2', alignItems: 'center', justifyContent: 'center' },
  name: { fontSize: 15, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  barcode: { fontSize: 11, color: colors.textMuted, textAlign: 'right', marginTop: 2 },
  tags: { flexDirection: 'row-reverse', gap: 8, marginTop: 8 },
  tag: { flexDirection: 'row-reverse', alignItems: 'center', gap: 4, paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999 },
  tagRed: { backgroundColor: '#fee2e2' },
  tagWarn: { backgroundColor: colors.warningLight },
  tagTxt: { fontSize: 11, fontWeight: '700' },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12, padding: 40 },
  emptyTxt: { fontSize: 14, color: colors.textMuted, fontWeight: '700', textAlign: 'center' },
});
