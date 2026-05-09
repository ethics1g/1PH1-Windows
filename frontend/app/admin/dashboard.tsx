import { useCallback, useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ScrollView, FlatList, ActivityIndicator,
  RefreshControl, Alert, TextInput, Modal, KeyboardAvoidingView, Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect, useRouter } from 'expo-router';
import { useAuth, apiFetch } from '../../src/auth';
import { colors } from '../../src/theme';

type TabKey = 'overview' | 'users' | 'orders' | 'products' | 'notifications' | 'audit';

const TABS: { key: TabKey; label: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { key: 'overview', label: 'الإحصاءات', icon: 'stats-chart' },
  { key: 'users', label: 'المستخدمون', icon: 'people' },
  { key: 'orders', label: 'الطلبيات', icon: 'cart' },
  { key: 'products', label: 'المنتجات', icon: 'cube' },
  { key: 'notifications', label: 'الإشعارات', icon: 'notifications' },
  { key: 'audit', label: 'السجل', icon: 'document-text' },
];

export default function AdminDashboard() {
  const { token, user, signOut } = useAuth();
  const router = useRouter();
  const [tab, setTab] = useState<TabKey>('overview');

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.header}>
        <View style={{ flex: 1 }}>
          <Text style={styles.hello}>لوحة التحكم</Text>
          <Text style={styles.who}>مرحباً، مدير</Text>
        </View>
        <TouchableOpacity testID="admin-logout" style={styles.logout} onPress={async () => { await signOut(); router.replace('/login'); }}>
          <Ionicons name="log-out-outline" size={22} color={colors.error} />
        </TouchableOpacity>
      </View>

      <View style={{ flex: 1 }}>
        {tab === 'overview' && <Overview token={token!} />}
        {tab === 'users' && <Users token={token!} />}
        {tab === 'orders' && <Orders token={token!} />}
        {tab === 'products' && <Products token={token!} />}
        {tab === 'notifications' && <Notifications token={token!} />}
        {tab === 'audit' && <AuditLogs token={token!} />}
      </View>

      <View style={styles.bottomTabs}>
        {TABS.map(t => (
          <TouchableOpacity
            key={t.key}
            testID={`admin-tab-${t.key}`}
            style={styles.tabBtn}
            onPress={() => setTab(t.key)}
          >
            <Ionicons name={t.icon} size={20} color={tab === t.key ? colors.primary : colors.textMuted} />
            <Text style={[styles.tabLabel, tab === t.key && { color: colors.primary, fontWeight: '800' }]}>{t.label}</Text>
          </TouchableOpacity>
        ))}
      </View>
    </SafeAreaView>
  );
}

// ----- Overview -----
function Overview({ token }: { token: string }) {
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const s: any = await apiFetch('/admin/stats', {}, token);
      setStats(s);
    } catch (e: any) {
      Alert.alert('خطأ', e.message);
    } finally { setLoading(false); setRefreshing(false); }
  }, [token]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (loading) return <View style={styles.center}><ActivityIndicator color={colors.primary} size="large" /></View>;
  if (!stats) return null;

  const cards = [
    { label: 'صيدليات', value: stats.pharmacies, icon: 'medical', color: '#16a34a', bg: '#dcfce7' },
    { label: 'مذاخر', value: stats.suppliers, icon: 'business', color: '#0284c7', bg: '#e0f2fe' },
    { label: 'أدوية المخزن', value: stats.medicines, icon: 'cube', color: '#d97706', bg: '#fef3c7' },
    { label: 'منتجات المذاخر', value: stats.products, icon: 'storefront', color: '#6366f1', bg: '#eef2ff' },
    { label: 'الطلبيات', value: stats.orders, icon: 'cart', color: '#db2777', bg: '#fce7f3' },
    { label: 'عمليات بيع', value: stats.sales, icon: 'receipt', color: '#059669', bg: '#d1fae5' },
    { label: 'الإيرادات (د.ع)', value: Math.round(stats.revenue).toLocaleString(), icon: 'cash', color: '#16a34a', bg: '#dcfce7', wide: true },
    { label: 'استيرادات الكتالوج', value: stats.catalog_jobs, icon: 'cloud-upload', color: '#0284c7', bg: '#e0f2fe' },
    { label: 'سجلات التدقيق', value: stats.audit_logs, icon: 'document-text', color: '#475569', bg: '#f1f5f9' },
  ];

  return (
    <ScrollView refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
      contentContainerStyle={{ padding: 16 }}>
      <View style={styles.statsGrid}>
        {cards.map((c, i) => (
          <View key={i} style={[styles.statCard, { backgroundColor: c.bg }, c.wide && { width: '100%' }]} testID={`stat-${c.label}`}>
            <View style={[styles.statIcon, { backgroundColor: '#fff' }]}>
              <Ionicons name={c.icon as any} size={20} color={c.color} />
            </View>
            <Text style={[styles.statValue, { color: c.color }]}>{c.value}</Text>
            <Text style={styles.statLabel}>{c.label}</Text>
          </View>
        ))}
      </View>
    </ScrollView>
  );
}

// ----- Users -----
function Users({ token }: { token: string }) {
  const [users, setUsers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<'all' | 'pharmacy' | 'supplier'>('all');

  const load = useCallback(async () => {
    try {
      const path = filter === 'all' ? '/admin/users' : `/admin/users?role=${filter}`;
      const data: any[] = await apiFetch(path, {}, token);
      setUsers(data);
    } catch (e: any) { Alert.alert('خطأ', e.message); }
    finally { setLoading(false); setRefreshing(false); }
  }, [token, filter]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const toggle = async (u: any) => {
    try {
      await apiFetch(`/admin/users/${u.role}/${u.id}`, { method: 'PATCH', body: JSON.stringify({ disabled: !u.disabled }) }, token);
      await load();
    } catch (e: any) { Alert.alert('خطأ', e.message); }
  };

  const remove = (u: any) => {
    Alert.alert('حذف نهائي؟', `سيتم حذف ${u.name} وجميع بياناته`, [
      { text: 'إلغاء', style: 'cancel' },
      { text: 'حذف', style: 'destructive', onPress: async () => {
        try { await apiFetch(`/admin/users/${u.role}/${u.id}`, { method: 'DELETE' }, token); await load(); }
        catch (e: any) { Alert.alert('خطأ', e.message); }
      }},
    ]);
  };

  return (
    <View style={{ flex: 1 }}>
      <View style={styles.filterRow}>
        {(['all', 'pharmacy', 'supplier'] as const).map(f => (
          <TouchableOpacity key={f} testID={`users-filter-${f}`} style={[styles.chip, filter === f && styles.chipActive]} onPress={() => setFilter(f)}>
            <Text style={[styles.chipTxt, filter === f && styles.chipTxtActive]}>
              {f === 'all' ? 'الكل' : f === 'pharmacy' ? 'صيدليات' : 'مذاخر'}
            </Text>
          </TouchableOpacity>
        ))}
      </View>
      {loading ? <View style={styles.center}><ActivityIndicator color={colors.primary} /></View> : (
        <FlatList
          data={users}
          keyExtractor={(u) => `${u.role}-${u.id}`}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
          contentContainerStyle={{ padding: 12, gap: 8 }}
          renderItem={({ item }) => (
            <View style={[styles.userCard, item.disabled && { opacity: 0.6 }]} testID={`user-row-${item.id}`}>
              <View style={styles.actions}>
                <TouchableOpacity style={[styles.iconBtn, { backgroundColor: '#fee2e2' }]} testID={`del-user-${item.id}`} onPress={() => remove(item)}>
                  <Ionicons name="trash" size={16} color={colors.error} />
                </TouchableOpacity>
                <TouchableOpacity style={[styles.iconBtn, { backgroundColor: item.disabled ? colors.primaryLight : '#fef3c7' }]} testID={`toggle-user-${item.id}`} onPress={() => toggle(item)}>
                  <Ionicons name={item.disabled ? 'play' : 'pause'} size={16} color={item.disabled ? colors.primary : colors.warning} />
                </TouchableOpacity>
              </View>
              <View style={{ flex: 1, alignItems: 'flex-end' }}>
                <Text style={styles.userName}>{item.name}</Text>
                <Text style={styles.userMeta}>{item.phone} · {item.role === 'pharmacy' ? 'صيدلية' : 'مذخر'}{item.disabled ? ' · معطل' : ''}</Text>
                <Text style={styles.userMeta}>{item.address}</Text>
              </View>
            </View>
          )}
          ListEmptyComponent={<Text style={styles.empty}>لا يوجد مستخدمون</Text>}
        />
      )}
    </View>
  );
}

// ----- Orders -----
function Orders({ token }: { token: string }) {
  const [orders, setOrders] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<string>('all');

  const STATUS_META: Record<string, { label: string; color: string; bg: string }> = {
    pending: { label: 'قيد الانتظار', color: '#92400e', bg: '#fef3c7' },
    confirmed: { label: 'مؤكدة', color: '#1e40af', bg: '#dbeafe' },
    delivered: { label: 'مسلّمة', color: '#166534', bg: '#dcfce7' },
    cancelled: { label: 'ملغاة', color: '#991b1b', bg: '#fee2e2' },
  };

  const load = useCallback(async () => {
    try {
      const path = filter === 'all' ? '/admin/orders' : `/admin/orders?status=${filter}`;
      const data: any[] = await apiFetch(path, {}, token);
      setOrders(data);
    } catch (e: any) { Alert.alert('خطأ', e.message); }
    finally { setLoading(false); setRefreshing(false); }
  }, [token, filter]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const updateStatus = async (id: string, status: string) => {
    try { await apiFetch(`/admin/orders/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) }, token); await load(); }
    catch (e: any) { Alert.alert('خطأ', e.message); }
  };

  return (
    <View style={{ flex: 1 }}>
      <View style={styles.filterRow}>
        {['all', 'pending', 'confirmed', 'delivered', 'cancelled'].map(f => (
          <TouchableOpacity key={f} testID={`orders-filter-${f}`} style={[styles.chip, filter === f && styles.chipActive]} onPress={() => setFilter(f)}>
            <Text style={[styles.chipTxt, filter === f && styles.chipTxtActive]}>
              {f === 'all' ? 'الكل' : STATUS_META[f]?.label || f}
            </Text>
          </TouchableOpacity>
        ))}
      </View>
      {loading ? <View style={styles.center}><ActivityIndicator color={colors.primary} /></View> : (
        <FlatList
          data={orders}
          keyExtractor={(o) => o.id}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
          contentContainerStyle={{ padding: 12, gap: 8 }}
          renderItem={({ item }) => {
            const stt = STATUS_META[item.status] || STATUS_META.pending;
            return (
              <View style={styles.orderCard} testID={`order-${item.id}`}>
                <View style={styles.orderHead}>
                  <View style={[styles.statusPill, { backgroundColor: stt.bg }]}>
                    <Text style={[styles.statusTxt, { color: stt.color }]}>{stt.label}</Text>
                  </View>
                  <View style={{ flex: 1, alignItems: 'flex-end' }}>
                    <Text style={styles.orderName}>{item.pharmacy_name}</Text>
                    <Text style={styles.orderMeta}>{item.items?.length || 0} صنف · {new Date(item.created_at).toLocaleDateString('ar')}</Text>
                  </View>
                </View>
                <View style={styles.orderActions}>
                  {['confirmed', 'delivered', 'cancelled'].map(s => (
                    <TouchableOpacity key={s} testID={`order-set-${s}-${item.id}`} style={[styles.miniBtn, item.status === s && { backgroundColor: colors.primary }]} onPress={() => updateStatus(item.id, s)}>
                      <Text style={[styles.miniBtnTxt, item.status === s && { color: '#fff' }]}>{STATUS_META[s].label}</Text>
                    </TouchableOpacity>
                  ))}
                </View>
              </View>
            );
          }}
          ListEmptyComponent={<Text style={styles.empty}>لا توجد طلبيات</Text>}
        />
      )}
    </View>
  );
}

// ----- Products -----
function Products({ token }: { token: string }) {
  const [products, setProducts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState('');

  const load = useCallback(async () => {
    try {
      const data: any[] = await apiFetch('/admin/products', {}, token);
      setProducts(data);
    } catch (e: any) { Alert.alert('خطأ', e.message); }
    finally { setLoading(false); setRefreshing(false); }
  }, [token]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const remove = (p: any) => {
    Alert.alert('حذف؟', `سيتم حذف ${p.name}`, [
      { text: 'إلغاء', style: 'cancel' },
      { text: 'حذف', style: 'destructive', onPress: async () => {
        try { await apiFetch(`/admin/products/${p.kind}/${p.id}`, { method: 'DELETE' }, token); await load(); }
        catch (e: any) { Alert.alert('خطأ', e.message); }
      }},
    ]);
  };

  const filtered = search.trim() ? products.filter(p => p.name.toLowerCase().includes(search.toLowerCase())) : products;

  return (
    <View style={{ flex: 1 }}>
      <View style={styles.searchBox}>
        <Ionicons name="search" size={16} color={colors.textMuted} />
        <TextInput testID="prod-search" style={styles.searchInput} value={search} onChangeText={setSearch} placeholder="ابحث..." placeholderTextColor={colors.textMuted} textAlign="right" />
      </View>
      {loading ? <View style={styles.center}><ActivityIndicator color={colors.primary} /></View> : (
        <FlatList
          data={filtered}
          keyExtractor={(p) => `${p.kind}-${p.id}`}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
          contentContainerStyle={{ padding: 12, gap: 8 }}
          renderItem={({ item }) => (
            <View style={styles.userCard} testID={`prod-row-${item.id}`}>
              <TouchableOpacity testID={`del-prod-${item.id}`} style={[styles.iconBtn, { backgroundColor: '#fee2e2' }]} onPress={() => remove(item)}>
                <Ionicons name="trash" size={16} color={colors.error} />
              </TouchableOpacity>
              <View style={{ flex: 1, alignItems: 'flex-end' }}>
                <Text style={styles.userName}>{item.name}</Text>
                <Text style={styles.userMeta}>
                  {item.kind === 'medicine' ? 'مخزن صيدلية' : 'منتج مذخر'} · 
                  {' '}{Math.round(item.price || 0).toLocaleString()} د.ع · 
                  كمية: {item.quantity || 0}
                </Text>
                {item.supplier_name && <Text style={styles.userMeta}>المذخر: {item.supplier_name}</Text>}
              </View>
            </View>
          )}
          ListEmptyComponent={<Text style={styles.empty}>لا توجد منتجات</Text>}
        />
      )}
    </View>
  );
}

// ----- Notifications -----
function Notifications({ token }: { token: string }) {
  const [list, setList] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [audience, setAudience] = useState<'all' | 'pharmacy' | 'supplier'>('all');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { const data: any[] = await apiFetch('/admin/notifications', {}, token); setList(data); }
    catch (e: any) { Alert.alert('خطأ', e.message); }
    finally { setLoading(false); }
  }, [token]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const send = async () => {
    if (!title.trim() || !body.trim()) { Alert.alert('تنبيه', 'العنوان والمحتوى مطلوبان'); return; }
    setBusy(true);
    try {
      await apiFetch('/admin/notifications', { method: 'POST', body: JSON.stringify({ title, body, audience }) }, token);
      setTitle(''); setBody(''); setOpen(false);
      await load();
    } catch (e: any) { Alert.alert('خطأ', e.message); }
    finally { setBusy(false); }
  };

  const remove = async (id: string) => {
    try { await apiFetch(`/admin/notifications/${id}`, { method: 'DELETE' }, token); await load(); }
    catch (e: any) { Alert.alert('خطأ', e.message); }
  };

  return (
    <View style={{ flex: 1 }}>
      <TouchableOpacity testID="notif-compose" style={styles.composeBtn} onPress={() => setOpen(true)}>
        <Ionicons name="megaphone" size={20} color="#fff" />
        <Text style={styles.composeTxt}>إرسال إشعار جديد</Text>
      </TouchableOpacity>
      {loading ? <View style={styles.center}><ActivityIndicator color={colors.primary} /></View> : (
        <FlatList
          data={list}
          keyExtractor={(n) => n.id}
          contentContainerStyle={{ padding: 12, gap: 8 }}
          renderItem={({ item }) => (
            <View style={styles.notifCard} testID={`notif-${item.id}`}>
              <TouchableOpacity testID={`del-notif-${item.id}`} style={[styles.iconBtn, { backgroundColor: '#fee2e2' }]} onPress={() => remove(item.id)}>
                <Ionicons name="trash" size={16} color={colors.error} />
              </TouchableOpacity>
              <View style={{ flex: 1, alignItems: 'flex-end' }}>
                <Text style={styles.notifTitle}>{item.title}</Text>
                <Text style={styles.notifBody} numberOfLines={2}>{item.body}</Text>
                <Text style={styles.userMeta}>الفئة: {item.audience === 'all' ? 'الكل' : item.audience === 'pharmacy' ? 'الصيدليات' : 'المذاخر'}</Text>
              </View>
            </View>
          )}
          ListEmptyComponent={<Text style={styles.empty}>لا توجد إشعارات</Text>}
        />
      )}

      <Modal visible={open} animationType="slide" transparent onRequestClose={() => setOpen(false)}>
        <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={styles.modalWrap}>
          <View style={styles.modal}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>إشعار جديد</Text>
              <TouchableOpacity onPress={() => setOpen(false)}><Ionicons name="close" size={24} color={colors.textPrimary} /></TouchableOpacity>
            </View>
            <Text style={styles.label}>العنوان</Text>
            <TextInput testID="notif-title" style={styles.input} value={title} onChangeText={setTitle} textAlign="right" />
            <Text style={styles.label}>المحتوى</Text>
            <TextInput testID="notif-body" style={[styles.input, { height: 80 }]} value={body} onChangeText={setBody} multiline textAlign="right" />
            <Text style={styles.label}>الفئة المستهدفة</Text>
            <View style={styles.filterRow}>
              {(['all', 'pharmacy', 'supplier'] as const).map(a => (
                <TouchableOpacity key={a} testID={`notif-aud-${a}`} style={[styles.chip, audience === a && styles.chipActive]} onPress={() => setAudience(a)}>
                  <Text style={[styles.chipTxt, audience === a && styles.chipTxtActive]}>
                    {a === 'all' ? 'الكل' : a === 'pharmacy' ? 'صيدليات' : 'مذاخر'}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
            <TouchableOpacity testID="notif-send" style={[styles.composeBtn, { marginTop: 14 }]} onPress={send} disabled={busy}>
              {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.composeTxt}>إرسال</Text>}
            </TouchableOpacity>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </View>
  );
}

// ----- Audit Logs -----
function AuditLogs({ token }: { token: string }) {
  const [logs, setLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<string>('all');

  const ACTIONS = ['all', 'login', 'login_failed', 'password_change', 'user_disabled', 'user_enabled', 'user_deleted', 'product_deleted'];

  const load = useCallback(async () => {
    try {
      const path = filter === 'all' ? '/admin/audit-logs' : `/admin/audit-logs?action=${filter}`;
      const data: any[] = await apiFetch(path, {}, token);
      setLogs(data);
    } catch (e: any) { Alert.alert('خطأ', e.message); }
    finally { setLoading(false); setRefreshing(false); }
  }, [token, filter]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <View style={{ flex: 1 }}>
      <ScrollView horizontal contentContainerStyle={styles.filterScroll} showsHorizontalScrollIndicator={false}>
        {ACTIONS.map(a => (
          <TouchableOpacity key={a} testID={`audit-filter-${a}`} style={[styles.chip, filter === a && styles.chipActive]} onPress={() => setFilter(a)}>
            <Text style={[styles.chipTxt, filter === a && styles.chipTxtActive]}>{a === 'all' ? 'الكل' : a}</Text>
          </TouchableOpacity>
        ))}
      </ScrollView>
      {loading ? <View style={styles.center}><ActivityIndicator color={colors.primary} /></View> : (
        <FlatList
          data={logs}
          keyExtractor={(l) => l.id}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
          contentContainerStyle={{ padding: 12, gap: 6 }}
          renderItem={({ item }) => (
            <View style={styles.auditCard} testID={`audit-${item.id}`}>
              <Ionicons name="ellipse" size={8} color={item.action.includes('failed') || item.action.includes('deleted') || item.action.includes('disabled') ? colors.error : colors.primary} style={{ marginLeft: 8 }} />
              <View style={{ flex: 1, alignItems: 'flex-end' }}>
                <Text style={styles.auditAction}>{item.action}</Text>
                <Text style={styles.userMeta}>
                  {item.actor?.role || ''} {item.actor?.phone || item.actor?.id?.slice(0, 8) || ''}
                  {' · '}{new Date(item.timestamp).toLocaleString('ar')}
                </Text>
              </View>
            </View>
          )}
          ListEmptyComponent={<Text style={styles.empty}>لا توجد سجلات</Text>}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: 'row-reverse', alignItems: 'center', padding: 18, paddingBottom: 8 },
  hello: { color: colors.textSecondary, fontSize: 12, textAlign: 'right' },
  who: { color: colors.textPrimary, fontSize: 20, fontWeight: '800', textAlign: 'right' },
  logout: { width: 40, height: 40, borderRadius: 20, backgroundColor: '#fee2e2', alignItems: 'center', justifyContent: 'center' },
  bottomTabs: { flexDirection: 'row-reverse', backgroundColor: '#fff', borderTopWidth: 1, borderTopColor: colors.border, paddingVertical: 6, paddingBottom: 12 },
  tabBtn: { flex: 1, alignItems: 'center', gap: 2, paddingVertical: 4 },
  tabLabel: { fontSize: 10, color: colors.textMuted },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 30 },
  empty: { textAlign: 'center', color: colors.textMuted, padding: 30 },
  // Stats
  statsGrid: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 10 },
  statCard: { width: '48%', borderRadius: 16, padding: 14, alignItems: 'flex-end', gap: 4 },
  statIcon: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  statValue: { fontSize: 22, fontWeight: '900', marginTop: 4 },
  statLabel: { fontSize: 12, color: colors.textSecondary },
  // Filter chips
  filterRow: { flexDirection: 'row-reverse', gap: 6, padding: 10, paddingTop: 12 },
  filterScroll: { paddingHorizontal: 10, paddingVertical: 12, gap: 6, flexDirection: 'row-reverse' },
  chip: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 20, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipTxt: { fontSize: 12, color: colors.textSecondary, fontWeight: '700' },
  chipTxtActive: { color: '#fff' },
  // User/product cards
  userCard: { backgroundColor: colors.surface, borderRadius: 14, padding: 12, flexDirection: 'row-reverse', alignItems: 'center', borderWidth: 1, borderColor: colors.border, gap: 8 },
  userName: { fontSize: 15, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  userMeta: { fontSize: 11, color: colors.textSecondary, textAlign: 'right', marginTop: 2 },
  actions: { flexDirection: 'row', gap: 6 },
  iconBtn: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center' },
  // Search
  searchBox: { flexDirection: 'row-reverse', alignItems: 'center', marginHorizontal: 12, marginTop: 12, backgroundColor: colors.surface, borderRadius: 12, paddingHorizontal: 12, borderWidth: 1, borderColor: colors.border, gap: 6 },
  searchInput: { flex: 1, paddingVertical: 10, fontSize: 14, color: colors.textPrimary },
  // Order
  orderCard: { backgroundColor: colors.surface, borderRadius: 14, padding: 12, borderWidth: 1, borderColor: colors.border, gap: 8 },
  orderHead: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8 },
  orderName: { fontSize: 14, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  orderMeta: { fontSize: 11, color: colors.textSecondary, textAlign: 'right' },
  statusPill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 8 },
  statusTxt: { fontSize: 11, fontWeight: '800' },
  orderActions: { flexDirection: 'row-reverse', gap: 6, flexWrap: 'wrap' },
  miniBtn: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8, backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border },
  miniBtnTxt: { fontSize: 11, color: colors.textSecondary, fontWeight: '700' },
  // Notifications
  composeBtn: { backgroundColor: colors.primary, borderRadius: 12, paddingVertical: 12, marginHorizontal: 12, marginTop: 12, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 6 },
  composeTxt: { color: '#fff', fontWeight: '800', fontSize: 14 },
  notifCard: { backgroundColor: colors.surface, borderRadius: 14, padding: 12, flexDirection: 'row-reverse', alignItems: 'center', borderWidth: 1, borderColor: colors.border, gap: 8 },
  notifTitle: { fontSize: 14, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  notifBody: { fontSize: 12, color: colors.textSecondary, textAlign: 'right', marginTop: 2 },
  // Audit
  auditCard: { backgroundColor: colors.surface, borderRadius: 10, padding: 10, flexDirection: 'row-reverse', alignItems: 'center', borderWidth: 1, borderColor: colors.border },
  auditAction: { fontSize: 13, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  // Modal
  modalWrap: { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', justifyContent: 'flex-end' },
  modal: { backgroundColor: '#fff', borderTopLeftRadius: 22, borderTopRightRadius: 22, padding: 20 },
  modalHead: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  modalTitle: { fontSize: 18, fontWeight: '800', color: colors.textPrimary },
  label: { fontSize: 12, color: colors.textSecondary, marginBottom: 6, textAlign: 'right', fontWeight: '600', marginTop: 8 },
  input: { backgroundColor: colors.background, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 14, borderWidth: 1, borderColor: colors.border },
});
