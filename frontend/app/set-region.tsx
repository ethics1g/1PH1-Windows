import { useEffect, useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity, ActivityIndicator,
  Alert, ScrollView, KeyboardAvoidingView, Platform, FlatList,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useAuth, apiFetch } from '../src/auth';
import { colors } from '../src/theme';

export default function SetRegionScreen() {
  const router = useRouter();
  const { token, role, user, signIn } = useAuth();
  const [region, setRegion] = useState(user?.region || '');
  const [country, setCountry] = useState(user?.country || '');
  const [busy, setBusy] = useState(false);
  const [suggestions, setSuggestions] = useState<any[]>([]);
  const [loadingSugs, setLoadingSugs] = useState(false);

  const loadSuggestions = useCallback(async (q: string) => {
    if (!token) return;
    setLoadingSugs(true);
    try {
      const path = q.trim() ? `/regions/suggest?q=${encodeURIComponent(q.trim())}` : '/regions/suggest';
      const res: any = await apiFetch(path, {}, token);
      setSuggestions(Array.isArray(res) ? res : []);
    } catch {
      setSuggestions([]);
    } finally {
      setLoadingSugs(false);
    }
  }, [token]);

  useEffect(() => {
    if (!token) return;
    const t = setTimeout(() => loadSuggestions(region), 300);
    return () => clearTimeout(t);
  }, [region, token, loadSuggestions]);

  const submit = async () => {
    if (!region.trim()) {
      Alert.alert('تنبيه', 'المنطقة/المحافظة مطلوبة');
      return;
    }
    setBusy(true);
    try {
      const res: any = await apiFetch('/auth/set-region', {
        method: 'PATCH',
        body: JSON.stringify({ region: region.trim(), country: country.trim() || undefined }),
      }, token);
      // Update local user object
      if (role && user) {
        await signIn(token!, role, { ...user, region: res.region, country: res.country });
      }
      if (role === 'pharmacy') router.replace('/home');
      else if (role === 'supplier') router.replace('/supplier-dashboard');
      else router.replace('/admin/dashboard');
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل الحفظ');
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={{ padding: 22 }} keyboardShouldPersistTaps="handled">
          <View style={styles.iconCircle}>
            <Ionicons name="location" size={42} color="#fff" />
          </View>
          <Text style={styles.title}>تحديد منطقة العمل</Text>
          <Text style={styles.sub}>
            {role === 'pharmacy'
              ? 'سترى فقط المذاخر في نفس منطقتك لضمان دقة التوصيل والأسعار.'
              : role === 'supplier'
              ? 'ستظهر لمنتجاتك للصيدليات في نفس منطقتك فقط.'
              : 'حدد منطقتك للمتابعة.'}
          </Text>

          <Text style={styles.label}>المنطقة / المحافظة / المدينة *</Text>
          <TextInput
            testID="input-region"
            style={styles.input}
            value={region}
            onChangeText={setRegion}
            placeholder="مثال: بغداد، الموصل، جدة، عمّان..."
            placeholderTextColor={colors.textMuted}
            textAlign="right"
            autoFocus
          />

          {suggestions.length > 0 && (
            <View style={styles.sugBox}>
              <Text style={styles.sugTitle}>اقتراحات</Text>
              <FlatList
                data={suggestions.slice(0, 8)}
                horizontal={false}
                scrollEnabled={false}
                keyExtractor={(s: any) => s.region_normalized}
                renderItem={({ item }) => (
                  <TouchableOpacity
                    testID={`sug-${item.region_normalized}`}
                    style={styles.sugRow}
                    onPress={() => { setRegion(item.region); if (item.country) setCountry(item.country); }}
                  >
                    <Text style={styles.sugCount}>{item.count}</Text>
                    <View style={{ flex: 1, alignItems: 'flex-end' }}>
                      <Text style={styles.sugLabel}>{item.region}</Text>
                      {item.country ? <Text style={styles.sugCountry}>{item.country}</Text> : null}
                    </View>
                  </TouchableOpacity>
                )}
              />
            </View>
          )}
          {loadingSugs && <Text style={styles.muted}>...جارٍ جلب الاقتراحات</Text>}

          <Text style={styles.label}>الدولة (اختياري)</Text>
          <TextInput
            testID="input-country"
            style={styles.input}
            value={country}
            onChangeText={setCountry}
            placeholder="مثال: العراق، السعودية..."
            placeholderTextColor={colors.textMuted}
            textAlign="right"
          />

          <TouchableOpacity testID="btn-save-region" style={styles.submit} onPress={submit} disabled={busy}>
            {busy ? <ActivityIndicator color="#fff" /> : (
              <>
                <Ionicons name="checkmark" size={22} color="#fff" />
                <Text style={styles.submitTxt}>حفظ والمتابعة</Text>
              </>
            )}
          </TouchableOpacity>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  iconCircle: { alignSelf: 'center', width: 84, height: 84, borderRadius: 42, backgroundColor: colors.primary, alignItems: 'center', justifyContent: 'center', marginBottom: 16, marginTop: 12 },
  title: { fontSize: 24, fontWeight: '900', textAlign: 'center', color: colors.textPrimary, marginBottom: 6 },
  sub: { textAlign: 'center', color: colors.textSecondary, fontSize: 13, marginBottom: 22, paddingHorizontal: 12 },
  label: { fontSize: 13, color: colors.textSecondary, marginBottom: 6, textAlign: 'right', fontWeight: '700', marginTop: 10 },
  input: { backgroundColor: colors.surface, borderRadius: 14, paddingHorizontal: 16, paddingVertical: 14, fontSize: 16, color: colors.textPrimary, borderWidth: 1, borderColor: colors.border },
  sugBox: { marginTop: 8, backgroundColor: colors.surface, borderRadius: 12, padding: 8, borderWidth: 1, borderColor: colors.border },
  sugTitle: { fontSize: 11, color: colors.textMuted, textAlign: 'right', marginBottom: 6 },
  sugRow: { flexDirection: 'row-reverse', alignItems: 'center', paddingVertical: 8, paddingHorizontal: 8, borderBottomWidth: 1, borderBottomColor: colors.border },
  sugLabel: { fontSize: 14, color: colors.textPrimary, fontWeight: '700' },
  sugCountry: { fontSize: 11, color: colors.textMuted },
  sugCount: { fontSize: 11, color: colors.textMuted, backgroundColor: colors.background, paddingHorizontal: 8, paddingVertical: 2, borderRadius: 10 },
  muted: { color: colors.textMuted, fontSize: 11, textAlign: 'center', marginTop: 4 },
  submit: { marginTop: 22, backgroundColor: colors.primary, borderRadius: 16, paddingVertical: 16, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8 },
  submitTxt: { color: '#fff', fontSize: 17, fontWeight: '800' },
});
