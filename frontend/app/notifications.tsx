import { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, FlatList, Alert, RefreshControl, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { apiFetch, useAuth } from '../src/auth';
import ScreenHeader from '../src/ScreenHeader';
import { colors } from '../src/theme';

type Notif = {
  id: string; title: string; body: string; type: string;
  data?: any; read: boolean; created_at: string;
};

const TYPE_ICONS: Record<string, { icon: keyof typeof import('@expo/vector-icons/build/Ionicons').Ionicons.glyphMap; color: string; bg: string }> = {
  admin: { icon: 'shield-checkmark', color: '#6366f1', bg: '#eef2ff' },
  expiry_reminder: { icon: 'alarm', color: '#d97706', bg: '#fef3c7' },
  expired_weekly: { icon: 'warning', color: '#dc2626', bg: '#fee2e2' },
  order: { icon: 'receipt', color: '#0284c7', bg: '#e0f2fe' },
  system: { icon: 'information-circle', color: '#64748b', bg: '#f1f5f9' },
};

export default function NotificationCenter() {
  const router = useRouter();
  const { token } = useAuth();
  const [items, setItems] = useState<Notif[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const r: any = await apiFetch('/notifications?limit=100', {}, token);
      setItems(r.items || []);
    } catch (e: any) {
      Alert.alert('خطأ', e.message);
    }
  }, [token]);

  useEffect(() => { (async () => { setLoading(true); await load(); setLoading(false); })(); }, [load]);

  const onOpen = async (n: Notif) => {
    // Mark as read
    if (!n.read) {
      try { await apiFetch(`/notifications/${n.id}/read`, { method: 'PATCH' }, token); } catch {}
      setItems((prev) => prev.map((x) => x.id === n.id ? { ...x, read: true } : x));
    }
    // Deep-link if provided
    const screen = n.data?.screen as string | undefined;
    if (screen) router.push(screen as any);
  };

  const onDelete = (n: Notif) => {
    Alert.alert('حذف الإشعار', 'هل تريد حذفه؟', [
      { text: 'إلغاء', style: 'cancel' },
      { text: 'حذف', style: 'destructive', onPress: async () => {
          try {
            await apiFetch(`/notifications/${n.id}`, { method: 'DELETE' }, token);
            setItems((prev) => prev.filter((x) => x.id !== n.id));
          } catch (e: any) { Alert.alert('خطأ', e.message); }
        } },
    ]);
  };

  const markAllRead = async () => {
    try {
      await apiFetch('/notifications/read-all', { method: 'PATCH' }, token);
      setItems((prev) => prev.map((x) => ({ ...x, read: true })));
    } catch (e: any) { Alert.alert('خطأ', e.message); }
  };

  const clearAll = () => {
    Alert.alert('حذف الكل', 'سيتم حذف جميع الإشعارات نهائياً.', [
      { text: 'إلغاء', style: 'cancel' },
      { text: 'حذف الكل', style: 'destructive', onPress: async () => {
          try {
            await apiFetch('/notifications', { method: 'DELETE' }, token);
            setItems([]);
          } catch (e: any) { Alert.alert('خطأ', e.message); }
        } },
    ]);
  };

  const renderItem = ({ item }: { item: Notif }) => {
    const meta = TYPE_ICONS[item.type] || TYPE_ICONS.system;
    return (
      <TouchableOpacity testID={`notif-${item.id}`} style={[styles.card, !item.read && styles.unread]} onPress={() => onOpen(item)} onLongPress={() => onDelete(item)}>
        <View style={[styles.iconBox, { backgroundColor: meta.bg }]}>
          <Ionicons name={meta.icon} size={22} color={meta.color} />
        </View>
        <View style={{ flex: 1 }}>
          <View style={styles.rowTop}>
            <Text style={styles.title} numberOfLines={1}>{item.title}</Text>
            {!item.read ? <View style={styles.dot} /> : null}
          </View>
          <Text style={styles.body} numberOfLines={3}>{item.body}</Text>
          <Text style={styles.time}>{new Date(item.created_at).toLocaleString('ar-EG', { hour12: false })}</Text>
        </View>
        <TouchableOpacity onPress={() => onDelete(item)} testID={`notif-del-${item.id}`} style={styles.delBtn}>
          <Ionicons name="trash-outline" size={18} color={colors.error} />
        </TouchableOpacity>
      </TouchableOpacity>
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <ScreenHeader title="مركز الإشعارات" subtitle={`${items.length} إشعار`} />

      {items.length > 0 ? (
        <View style={styles.toolbar}>
          <TouchableOpacity testID="btn-mark-all" style={styles.tbBtn} onPress={markAllRead}>
            <Ionicons name="checkmark-done" size={16} color={colors.primary} />
            <Text style={styles.tbTxt}>قراءة الكل</Text>
          </TouchableOpacity>
          <TouchableOpacity testID="btn-clear-all" style={styles.tbBtn} onPress={clearAll}>
            <Ionicons name="trash" size={16} color={colors.error} />
            <Text style={[styles.tbTxt, { color: colors.error }]}>حذف الكل</Text>
          </TouchableOpacity>
        </View>
      ) : null}

      {loading ? (
        <View style={styles.empty}><ActivityIndicator size="large" color={colors.primary} /></View>
      ) : items.length === 0 ? (
        <View style={styles.empty}>
          <Ionicons name="notifications-off" size={54} color={colors.textMuted} />
          <Text style={styles.emptyTxt}>لا توجد إشعارات</Text>
        </View>
      ) : (
        <FlatList
          data={items}
          keyExtractor={(i) => i.id}
          renderItem={renderItem}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
          contentContainerStyle={{ padding: 12, gap: 10 }}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  toolbar: { flexDirection: 'row-reverse', paddingHorizontal: 14, gap: 12, paddingBottom: 6 },
  tbBtn: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, paddingHorizontal: 10, paddingVertical: 6, backgroundColor: colors.surface, borderRadius: 999, borderWidth: 1, borderColor: colors.border },
  tbTxt: { fontSize: 12, fontWeight: '700', color: colors.primary },
  card: { flexDirection: 'row-reverse', alignItems: 'flex-start', gap: 10, backgroundColor: colors.surface, borderRadius: 14, padding: 12, borderWidth: 1, borderColor: colors.border },
  unread: { borderColor: colors.indigo, backgroundColor: '#eef2ff' },
  iconBox: { width: 42, height: 42, borderRadius: 21, alignItems: 'center', justifyContent: 'center' },
  rowTop: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, marginBottom: 3 },
  title: { flex: 1, fontSize: 14, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.indigo },
  body: { fontSize: 13, color: colors.textSecondary, textAlign: 'right', lineHeight: 18 },
  time: { fontSize: 10, color: colors.textMuted, marginTop: 4, textAlign: 'right' },
  delBtn: { width: 34, height: 34, alignItems: 'center', justifyContent: 'center', borderRadius: 17, backgroundColor: '#fee2e2' },
  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12 },
  emptyTxt: { fontSize: 14, color: colors.textMuted, fontWeight: '600' },
});
