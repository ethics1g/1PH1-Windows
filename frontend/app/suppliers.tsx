import { useCallback, useState } from 'react';
import { View, Text, StyleSheet, FlatList, ActivityIndicator, Alert, RefreshControl, Image } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from 'expo-router';
import { useAuth, apiFetch } from '../src/auth';
import { colors } from '../src/theme';
import ScreenHeader from '../src/ScreenHeader';

type Product = { id: string; name: string; price: number; supplier_name: string; image_base64?: string; description?: string };

export default function Suppliers() {
  const { token } = useAuth();
  const [items, setItems] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const data: Product[] = await apiFetch('/marketplace', {}, token);
      setItems(data);
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل التحميل');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [token]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (loading) {
    return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} size="large" /></View></SafeAreaView>;
  }

  return (
    <SafeAreaView style={styles.safe}>
      <ScreenHeader title="المذاخر" subtitle="متجر الموردين" />

      {items.length === 0 ? (
        <View style={styles.center}>
          <Ionicons name="storefront-outline" size={72} color={colors.textMuted} />
          <Text style={styles.emptyTxt}>لا توجد منتجات معروضة حالياً</Text>
        </View>
      ) : (
        <FlatList
          data={items}
          keyExtractor={(i) => i.id}
          numColumns={2}
          columnWrapperStyle={{ gap: 12, flexDirection: 'row-reverse' }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
          contentContainerStyle={{ padding: 16, gap: 12 }}
          renderItem={({ item }) => (
            <View style={styles.card} testID={`market-item-${item.id}`}>
              <View style={styles.imgBox}>
                {item.image_base64 ? (
                  <Image source={{ uri: `data:image/jpeg;base64,${item.image_base64}` }} style={styles.img} />
                ) : (
                  <Ionicons name="medical" size={44} color={colors.indigo} />
                )}
              </View>
              <Text style={styles.name} numberOfLines={2}>{item.name}</Text>
              <View style={styles.supplierRow}>
                <Ionicons name="business" size={12} color={colors.textMuted} />
                <Text style={styles.supplier} numberOfLines={1}>{item.supplier_name}</Text>
              </View>
              <Text style={styles.price}>{item.price.toLocaleString()} د.ع</Text>
            </View>
          )}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 10, padding: 30 },
  emptyTxt: { color: colors.textSecondary, fontSize: 15, textAlign: 'center' },
  card: { flex: 1, backgroundColor: colors.surface, borderRadius: 18, padding: 12, borderWidth: 1, borderColor: colors.border, gap: 6 },
  imgBox: { height: 100, backgroundColor: colors.indigoLight, borderRadius: 14, alignItems: 'center', justifyContent: 'center', overflow: 'hidden' },
  img: { width: '100%', height: '100%' },
  name: { fontSize: 14, fontWeight: '800', color: colors.textPrimary, textAlign: 'right', marginTop: 6 },
  supplierRow: { flexDirection: 'row-reverse', alignItems: 'center', gap: 4 },
  supplier: { fontSize: 11, color: colors.textMuted },
  price: { fontSize: 15, fontWeight: '900', color: colors.primary, textAlign: 'right', marginTop: 2 },
});
