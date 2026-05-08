import { useCallback, useState } from 'react';
import { View, Text, StyleSheet, FlatList, ActivityIndicator, RefreshControl, TouchableOpacity, Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect, useRouter } from 'expo-router';
import { useAuth, apiFetch } from '../src/auth';
import { colors } from '../src/theme';
import ScreenHeader from '../src/ScreenHeader';

type Job = {
  id: string;
  status: 'pending' | 'processing' | 'review' | 'published' | 'failed';
  progress: number;
  filename?: string;
  total_items: number;
  items_to_review: number;
  page_count: number;
  error?: string | null;
  created_at: string;
};

const STATUS_LABEL: Record<string, { label: string; color: string; bg: string }> = {
  pending: { label: 'قيد الانتظار', color: '#92400e', bg: '#fef3c7' },
  processing: { label: 'جاري المعالجة', color: '#1e40af', bg: '#dbeafe' },
  review: { label: 'بانتظار المراجعة', color: '#5b21b6', bg: '#ede9fe' },
  published: { label: 'منشور', color: '#166534', bg: '#dcfce7' },
  failed: { label: 'فشل', color: '#991b1b', bg: '#fee2e2' },
};

export default function CatalogJobs() {
  const { token } = useAuth();
  const router = useRouter();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const data: Job[] = await apiFetch('/supplier/catalog/jobs', {}, token);
      setJobs(data);
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل التحميل');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [token]);

  useFocusEffect(useCallback(() => {
    load();
    // Auto-refresh while jobs are processing
    const interval = setInterval(() => {
      load();
    }, 4000);
    return () => clearInterval(interval);
  }, [load]));

  if (loading) {
    return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} size="large" /></View></SafeAreaView>;
  }

  return (
    <SafeAreaView style={styles.safe}>
      <ScreenHeader title="سجل الاستيرادات" subtitle={`${jobs.length} ملف`} />
      {jobs.length === 0 ? (
        <View style={styles.center}>
          <Ionicons name="folder-open-outline" size={64} color={colors.textMuted} />
          <Text style={styles.emptyTxt}>لا توجد عمليات استيراد</Text>
          <TouchableOpacity testID="btn-go-upload" style={styles.uploadCta} onPress={() => router.push({ pathname: '/catalog-upload' } as any)}>
            <Ionicons name="cloud-upload" size={20} color="#fff" />
            <Text style={styles.uploadCtaTxt}>ارفع ملفك الأول</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <FlatList
          data={jobs}
          keyExtractor={(j) => j.id}
          contentContainerStyle={{ padding: 16, gap: 10 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
          renderItem={({ item }) => {
            const stt = STATUS_LABEL[item.status] || STATUS_LABEL.processing;
            const canOpen = item.status === 'review' || item.status === 'published';
            return (
              <TouchableOpacity
                testID={`job-${item.id}`}
                style={styles.jobCard}
                onPress={() => canOpen && router.push({ pathname: `/catalog-review/${item.id}` } as any)}
                disabled={!canOpen}
                activeOpacity={canOpen ? 0.7 : 1}
              >
                <View style={[styles.statusPill, { backgroundColor: stt.bg }]}>
                  <Text style={[styles.statusTxt, { color: stt.color }]}>{stt.label}</Text>
                </View>
                <View style={{ flex: 1, alignItems: 'flex-end' }}>
                  <Text style={styles.fname} numberOfLines={1}>{item.filename || 'ملف'}</Text>
                  <Text style={styles.meta}>
                    {item.total_items > 0 ? `${item.total_items} صنف` : ''}
                    {item.items_to_review > 0 ? ` · ${item.items_to_review} للمراجعة` : ''}
                    {item.page_count > 0 ? ` · ${item.page_count} صفحات` : ''}
                  </Text>
                  {(item.status === 'pending' || item.status === 'processing') && (
                    <View style={styles.progressBar}>
                      <View style={[styles.progressFill, { width: `${item.progress || 5}%` }]} />
                    </View>
                  )}
                  {item.error ? <Text style={styles.errorTxt}>{item.error}</Text> : null}
                </View>
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
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 14, padding: 30 },
  emptyTxt: { color: colors.textSecondary, fontSize: 15 },
  uploadCta: { backgroundColor: colors.primary, borderRadius: 14, paddingVertical: 12, paddingHorizontal: 22, flexDirection: 'row-reverse', gap: 8, alignItems: 'center' },
  uploadCtaTxt: { color: '#fff', fontWeight: '800' },
  jobCard: { backgroundColor: colors.surface, borderRadius: 16, padding: 14, borderWidth: 1, borderColor: colors.border, flexDirection: 'row-reverse', alignItems: 'center', gap: 10 },
  statusPill: { paddingHorizontal: 10, paddingVertical: 5, borderRadius: 8, marginLeft: 8 },
  statusTxt: { fontSize: 11, fontWeight: '800' },
  fname: { fontSize: 15, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  meta: { color: colors.textSecondary, fontSize: 12, marginTop: 2, textAlign: 'right' },
  progressBar: { height: 6, backgroundColor: colors.border, borderRadius: 3, overflow: 'hidden', width: 200, marginTop: 8 },
  progressFill: { height: '100%', backgroundColor: colors.primary },
  errorTxt: { color: colors.error, fontSize: 12, marginTop: 4 },
});
