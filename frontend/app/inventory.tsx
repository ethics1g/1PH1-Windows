import { useCallback, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, FlatList, ActivityIndicator, Alert, TextInput, Linking, Platform, RefreshControl } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect, useRouter } from 'expo-router';
import { useAuth, apiFetch } from '../src/auth';
import { colors } from '../src/theme';
import ScreenHeader from '../src/ScreenHeader';

type Med = { id: string; name: string; quantity: number; price: number; barcode?: string };
type OrderRow = { id: string; name: string; quantity: number };

export default function Inventory() {
  const { token } = useAuth();
  const router = useRouter();
  const [meds, setMeds] = useState<Med[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [order, setOrder] = useState<OrderRow[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const data: Med[] = await apiFetch('/medicines', {}, token);
      setMeds(data);
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل التحميل');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [token]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const addToOrder = (med: Med) => {
    const existing = order.find(o => o.id === med.id);
    if (existing) {
      setOrder(order.map(o => o.id === med.id ? { ...o, quantity: o.quantity + 1 } : o));
    } else {
      setOrder([...order, { id: med.id, name: med.name, quantity: 1 }]);
    }
  };

  const updateOrderQty = (id: string, delta: number) => {
    setOrder(order.map(o => o.id === id ? { ...o, quantity: Math.max(0, o.quantity + delta) } : o).filter(o => o.quantity > 0));
  };

  const createOrder = async () => {
    if (order.length === 0) return;
    try {
      await apiFetch('/orders', { method: 'POST', body: JSON.stringify({ items: order.map(o => ({ name: o.name, quantity: o.quantity })) }) }, token);
      const lines = order.map((o, i) => `${i + 1}. ${o.name} - العدد: ${o.quantity}`).join('\n');
      const msg = `طلبية أدوية:\n\n${lines}`;
      Alert.alert(
        'إنشاء الطلبية',
        'اختر طريقة الإرسال:',
        [
          { text: 'واتساب', onPress: () => {
            const encoded = encodeURIComponent(msg);
            Linking.openURL(`https://wa.me/?text=${encoded}`);
          }},
          { text: 'نسخ النص', onPress: () => {
            if (Platform.OS === 'web' && typeof navigator !== 'undefined' && navigator.clipboard) {
              navigator.clipboard.writeText(msg);
            }
            Alert.alert('تم', 'يمكنك لصق النص أو عمل لقطة شاشة الآن');
          }},
          { text: 'إلغاء', style: 'cancel' },
        ],
      );
      setOrder([]);
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل الإنشاء');
    }
  };

  const filtered = search.trim() ? meds.filter(m => m.name.toLowerCase().includes(search.toLowerCase())) : meds;

  if (loading) {
    return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} size="large" /></View></SafeAreaView>;
  }

  return (
    <SafeAreaView style={styles.safe}>
      <ScreenHeader title="المخزن" subtitle={`${meds.length} دواء`} />

      <View style={styles.searchBox}>
        <Ionicons name="search" size={18} color={colors.textMuted} />
        <TextInput
          testID="inventory-search"
          style={styles.searchInput}
          value={search}
          onChangeText={setSearch}
          placeholder="ابحث عن دواء"
          placeholderTextColor={colors.textMuted}
          textAlign="right"
        />
      </View>

      {meds.length === 0 ? (
        <View style={styles.center}>
          <Ionicons name="cube-outline" size={72} color={colors.textMuted} />
          <Text style={styles.emptyTxt}>المخزن فارغ. ابدأ بإضافة أدوية من شاشة الشراء</Text>
        </View>
      ) : (
        <FlatList
          data={filtered}
          keyExtractor={(i) => i.id}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
          contentContainerStyle={{ padding: 16, paddingBottom: order.length ? 180 : 20 }}
          renderItem={({ item }) => {
            const low = item.quantity <= 5;
            return (
              <TouchableOpacity
                testID={`inv-row-${item.id}`}
                style={styles.row}
                onPress={() => addToOrder(item)}
                activeOpacity={0.8}
              >
                <View style={styles.addBadge}>
                  <Ionicons name="add-circle" size={26} color={colors.primary} />
                </View>
                <View style={{ flex: 1, alignItems: 'flex-end' }}>
                  <Text style={styles.rowName}>{item.name}</Text>
                  <View style={styles.rowMeta}>
                    <Text style={[styles.qtyBadge, low ? styles.qtyLow : styles.qtyOk]}>رصيد: {item.quantity}</Text>
                    <Text style={styles.rowPrice}>{item.price.toLocaleString()} د.ع</Text>
                  </View>
                </View>
              </TouchableOpacity>
            );
          }}
        />
      )}

      {order.length > 0 && (
        <View style={styles.orderFooter}>
          <Text style={styles.orderTitle}>الطلبية الحالية ({order.length})</Text>
          <View style={{ maxHeight: 120 }}>
            <FlatList
              data={order}
              keyExtractor={(i) => i.id}
              renderItem={({ item }) => (
                <View style={styles.orderRow}>
                  <View style={styles.qtyControls}>
                    <TouchableOpacity onPress={() => updateOrderQty(item.id, 1)} style={styles.qtyBtn}><Ionicons name="add" size={16} color={colors.primary} /></TouchableOpacity>
                    <Text style={styles.qtyTxt}>{item.quantity}</Text>
                    <TouchableOpacity onPress={() => updateOrderQty(item.id, -1)} style={styles.qtyBtn}><Ionicons name="remove" size={16} color={colors.error} /></TouchableOpacity>
                  </View>
                  <Text style={styles.orderName}>{item.name}</Text>
                </View>
              )}
            />
          </View>
          <View style={styles.actionsRow}>
            <TouchableOpacity
              testID="btn-optimize"
              style={[styles.actionBtn, styles.optimizeBtn]}
              onPress={() => {
                const items = order.map(o => ({ name: o.name, quantity: o.quantity }));
                router.push({ pathname: '/optimize', params: { items: JSON.stringify(items) } } as any);
              }}
            >
              <Ionicons name="sparkles" size={18} color="#fff" />
              <Text style={styles.actionTxt}>أفضل سعر</Text>
            </TouchableOpacity>
            <TouchableOpacity testID="btn-create-order" style={[styles.actionBtn, styles.sendBtn]} onPress={createOrder}>
              <Ionicons name="paper-plane" size={18} color="#fff" />
              <Text style={styles.actionTxt}>إرسال مباشر</Text>
            </TouchableOpacity>
          </View>
        </View>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 10, padding: 30 },
  emptyTxt: { color: colors.textSecondary, fontSize: 15, textAlign: 'center' },
  searchBox: { flexDirection: 'row-reverse', alignItems: 'center', marginHorizontal: 20, marginBottom: 8, backgroundColor: colors.surface, borderRadius: 14, paddingHorizontal: 14, borderWidth: 1, borderColor: colors.border, gap: 8 },
  searchInput: { flex: 1, paddingVertical: 12, fontSize: 15, color: colors.textPrimary },
  row: { backgroundColor: colors.surface, borderRadius: 16, padding: 14, marginBottom: 10, flexDirection: 'row-reverse', alignItems: 'center', borderWidth: 1, borderColor: colors.border },
  addBadge: { marginLeft: 10 },
  rowName: { fontSize: 16, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  rowMeta: { flexDirection: 'row-reverse', gap: 8, marginTop: 4, alignItems: 'center' },
  qtyBadge: { paddingHorizontal: 10, paddingVertical: 3, borderRadius: 8, fontSize: 12, fontWeight: '700', overflow: 'hidden' },
  qtyOk: { backgroundColor: colors.primaryLight, color: colors.primaryDark },
  qtyLow: { backgroundColor: '#fee2e2', color: colors.error },
  rowPrice: { color: colors.secondaryDark, fontWeight: '800', fontSize: 13 },
  orderFooter: { position: 'absolute', bottom: 0, left: 0, right: 0, backgroundColor: '#fff', borderTopWidth: 1, borderTopColor: colors.border, padding: 14, gap: 10 },
  orderTitle: { fontWeight: '800', color: colors.textPrimary, textAlign: 'right', fontSize: 15 },
  orderRow: { flexDirection: 'row-reverse', alignItems: 'center', paddingVertical: 6 },
  orderName: { flex: 1, color: colors.textPrimary, textAlign: 'right', fontSize: 14 },
  qtyControls: { flexDirection: 'row', alignItems: 'center', gap: 8, marginLeft: 10 },
  qtyBtn: { width: 26, height: 26, borderRadius: 13, backgroundColor: colors.background, alignItems: 'center', justifyContent: 'center' },
  qtyTxt: { fontWeight: '800', minWidth: 18, textAlign: 'center' },
  actionsRow: { flexDirection: 'row-reverse', gap: 8 },
  actionBtn: { flex: 1, borderRadius: 14, paddingVertical: 13, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 6 },
  optimizeBtn: { backgroundColor: colors.indigo },
  sendBtn: { backgroundColor: colors.primary },
  actionTxt: { color: '#fff', fontWeight: '800', fontSize: 14 },
  createOrderBtn: { backgroundColor: colors.primary, borderRadius: 14, paddingVertical: 13, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8 },
  createOrderTxt: { color: '#fff', fontWeight: '800', fontSize: 16 },
});
