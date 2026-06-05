import { View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useAuth } from '../src/auth';
import { colors } from '../src/theme';

type Tile = {
  key: string;
  title: string;
  subtitle: string;
  icon: keyof typeof Ionicons.glyphMap;
  bg: string;
  iconColor: string;
  route: string;
  testID: string;
};

const tiles: Tile[] = [
  { key: 'sell', title: 'البيع', subtitle: 'مسح الباركود والبيع السريع', icon: 'cart', bg: '#dcfce7', iconColor: '#16a34a', route: '/sell', testID: 'tile-sell' },
  { key: 'buy', title: 'الشراء', subtitle: 'إضافة الأدوية للمخزن', icon: 'cube', bg: '#e0f2fe', iconColor: '#0284c7', route: '/buy', testID: 'tile-buy' },
  { key: 'inventory', title: 'المخزن', subtitle: 'عرض وإدارة المخزون', icon: 'file-tray-stacked', bg: '#fef3c7', iconColor: '#d97706', route: '/inventory', testID: 'tile-inventory' },
  { key: 'suppliers', title: 'المذاخر', subtitle: 'متجر الموردين', icon: 'storefront', bg: '#eef2ff', iconColor: '#6366f1', route: '/suppliers', testID: 'tile-suppliers' },
  { key: 'orders', title: 'طلبياتي', subtitle: 'تتبع الطلبيات وتأكيد الاستلام', icon: 'receipt', bg: '#fce7f3', iconColor: '#be185d', route: '/pharmacy-orders', testID: 'tile-orders' },
];

export default function Home() {
  const router = useRouter();
  const { user, signOut } = useAuth();

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text style={styles.hello}>أهلاً بك</Text>
          <Text style={styles.pharmacy} testID="home-pharmacy-name">{user?.name || 'صيدلية'}</Text>
        </View>
        <TouchableOpacity
          testID="btn-logout"
          style={styles.logoutBtn}
          onPress={async () => { await signOut(); router.replace('/login'); }}
        >
          <Ionicons name="log-out-outline" size={22} color={colors.error} />
        </TouchableOpacity>
      </View>

      <ScrollView contentContainerStyle={styles.grid}>
        <View style={styles.bannerCard}>
          <View style={styles.bannerIcon}>
            <Ionicons name="sparkles" size={22} color="#fff" />
          </View>
          <View style={{ flex: 1, alignItems: 'flex-end' }}>
            <Text style={styles.bannerTitle}>كاشير ذكي بالذكاء الاصطناعي</Text>
            <Text style={styles.bannerSub}>امسح الباركود أو التقط صورة للدواء</Text>
          </View>
        </View>

        <View style={styles.tilesGrid}>
          {tiles.map((t) => (
            <TouchableOpacity
              key={t.key}
              testID={t.testID}
              style={[styles.tile, { backgroundColor: t.bg }]}
              activeOpacity={0.85}
              onPress={() => router.push(t.route as any)}
            >
              <View style={[styles.tileIcon, { backgroundColor: '#fff' }]}>
                <Ionicons name={t.icon} size={30} color={t.iconColor} />
              </View>
              <Text style={[styles.tileTitle, { color: t.iconColor }]}>{t.title}</Text>
              <Text style={styles.tileSub}>{t.subtitle}</Text>
            </TouchableOpacity>
          ))}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: 'row-reverse', alignItems: 'center', padding: 20, paddingBottom: 8 },
  hello: { color: colors.textSecondary, fontSize: 14, textAlign: 'right' },
  pharmacy: { color: colors.textPrimary, fontSize: 22, fontWeight: '800', textAlign: 'right' },
  logoutBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: '#fee2e2', alignItems: 'center', justifyContent: 'center' },
  grid: { padding: 20, paddingTop: 4 },
  bannerCard: {
    backgroundColor: colors.primary, borderRadius: 20, padding: 18,
    flexDirection: 'row-reverse', alignItems: 'center', gap: 12, marginBottom: 20,
    shadowColor: colors.primary, shadowOpacity: 0.25, shadowRadius: 14, shadowOffset: { width: 0, height: 8 }, elevation: 6,
  },
  bannerIcon: { width: 44, height: 44, borderRadius: 22, backgroundColor: 'rgba(255,255,255,0.2)', alignItems: 'center', justifyContent: 'center' },
  bannerTitle: { color: '#fff', fontSize: 16, fontWeight: '800' },
  bannerSub: { color: 'rgba(255,255,255,0.85)', fontSize: 12, marginTop: 2 },
  tilesGrid: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 14, justifyContent: 'space-between' },
  tile: {
    width: '48%', borderRadius: 24, padding: 18, minHeight: 160,
    alignItems: 'flex-end', justifyContent: 'space-between',
  },
  tileIcon: { width: 52, height: 52, borderRadius: 26, alignItems: 'center', justifyContent: 'center' },
  tileTitle: { fontSize: 20, fontWeight: '800', marginTop: 10 },
  tileSub: { fontSize: 12, color: colors.textSecondary, textAlign: 'right', marginTop: 4 },
});
