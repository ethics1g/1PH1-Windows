import { useState } from 'react';
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity, ScrollView,
  KeyboardAvoidingView, Platform, ActivityIndicator, Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useAuth, apiFetch } from '../src/auth';
import { colors } from '../src/theme';

type Mode = 'login' | 'register';
type Role = 'pharmacy' | 'supplier';

export default function Login() {
  const router = useRouter();
  const { signIn } = useAuth();
  const [role, setRole] = useState<Role>('pharmacy');
  const [mode, setMode] = useState<Mode>('login');
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [address, setAddress] = useState('');
  const [loading, setLoading] = useState(false);

  const submit = async () => {
    if (!phone.trim() || !password.trim()) {
      Alert.alert('تنبيه', 'يرجى إدخال رقم الهاتف والرمز السري');
      return;
    }
    if (mode === 'register' && (!name.trim() || !address.trim())) {
      Alert.alert('تنبيه', 'يرجى تعبئة جميع الحقول');
      return;
    }
    setLoading(true);
    try {
      const path = `/${role}/${mode === 'register' ? 'register' : 'login'}`;
      const body = mode === 'register'
        ? { name, phone, password, address }
        : { phone, password };
      const res: any = await apiFetch(path, { method: 'POST', body: JSON.stringify(body) });
      const userObj = role === 'pharmacy' ? res.pharmacy : res.supplier;
      await signIn(res.token, role, userObj);
      router.replace(role === 'pharmacy' ? '/home' : '/supplier-dashboard');
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشلت العملية');
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={{ flex: 1 }}
      >
        <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
          <View style={styles.logoWrap}>
            <View style={styles.logoCircle}>
              <Ionicons name="medkit" size={44} color="#fff" />
            </View>
            <Text style={styles.title}>صيدلية كاشير</Text>
            <Text style={styles.subtitle}>نظام ذكي للصيدليات والمذاخر</Text>
          </View>

          <View style={styles.roleSwitch}>
            <TouchableOpacity
              testID="role-pharmacy"
              style={[styles.roleBtn, role === 'pharmacy' && styles.roleBtnActive]}
              onPress={() => setRole('pharmacy')}
            >
              <Ionicons name="medical" size={18} color={role === 'pharmacy' ? '#fff' : colors.textSecondary} />
              <Text style={[styles.roleTxt, role === 'pharmacy' && styles.roleTxtActive]}>صيدلية</Text>
            </TouchableOpacity>
            <TouchableOpacity
              testID="role-supplier"
              style={[styles.roleBtn, role === 'supplier' && styles.roleBtnActive]}
              onPress={() => setRole('supplier')}
            >
              <Ionicons name="business" size={18} color={role === 'supplier' ? '#fff' : colors.textSecondary} />
              <Text style={[styles.roleTxt, role === 'supplier' && styles.roleTxtActive]}>مذخر</Text>
            </TouchableOpacity>
          </View>

          <View style={styles.tabs}>
            <TouchableOpacity
              testID="mode-login"
              style={[styles.tab, mode === 'login' && styles.tabActive]}
              onPress={() => setMode('login')}
            >
              <Text style={[styles.tabTxt, mode === 'login' && styles.tabTxtActive]}>تسجيل دخول</Text>
            </TouchableOpacity>
            <TouchableOpacity
              testID="mode-register"
              style={[styles.tab, mode === 'register' && styles.tabActive]}
              onPress={() => setMode('register')}
            >
              <Text style={[styles.tabTxt, mode === 'register' && styles.tabTxtActive]}>حساب جديد</Text>
            </TouchableOpacity>
          </View>

          {mode === 'register' && (
            <View style={styles.field}>
              <Text style={styles.label}>{role === 'pharmacy' ? 'اسم الصيدلية' : 'اسم المذخر'}</Text>
              <TextInput
                testID="input-name"
                style={styles.input}
                value={name}
                onChangeText={setName}
                placeholder={role === 'pharmacy' ? 'مثال: صيدلية الشفاء' : 'مثال: مذخر النور'}
                placeholderTextColor={colors.textMuted}
                textAlign="right"
              />
            </View>
          )}

          <View style={styles.field}>
            <Text style={styles.label}>رقم الهاتف</Text>
            <TextInput
              testID="input-phone"
              style={styles.input}
              value={phone}
              onChangeText={setPhone}
              placeholder="07XXXXXXXXX"
              placeholderTextColor={colors.textMuted}
              keyboardType="phone-pad"
              textAlign="right"
            />
          </View>

          <View style={styles.field}>
            <Text style={styles.label}>الرمز السري</Text>
            <TextInput
              testID="input-password"
              style={styles.input}
              value={password}
              onChangeText={setPassword}
              placeholder="••••••"
              placeholderTextColor={colors.textMuted}
              secureTextEntry
              textAlign="right"
            />
          </View>

          {mode === 'register' && (
            <View style={styles.field}>
              <Text style={styles.label}>{role === 'pharmacy' ? 'عنوان الصيدلية' : 'عنوان المذخر'}</Text>
              <TextInput
                testID="input-address"
                style={styles.input}
                value={address}
                onChangeText={setAddress}
                placeholder="المدينة، الشارع..."
                placeholderTextColor={colors.textMuted}
                textAlign="right"
              />
            </View>
          )}

          <TouchableOpacity
            testID="btn-submit-auth"
            style={styles.submit}
            onPress={submit}
            disabled={loading}
          >
            {loading ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <>
                <Ionicons name="arrow-back" size={22} color="#fff" />
                <Text style={styles.submitTxt}>{mode === 'login' ? 'دخول' : 'إنشاء حساب'}</Text>
              </>
            )}
          </TouchableOpacity>

          {mode === 'login' && (
            <TouchableOpacity
              testID="btn-forgot-password"
              style={styles.forgotLink}
              onPress={() => router.push({ pathname: '/forgot-password' } as any)}
            >
              <Text style={styles.forgotTxt}>نسيت الرمز السري؟</Text>
            </TouchableOpacity>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scroll: { padding: 24, paddingBottom: 48 },
  logoWrap: { alignItems: 'center', marginTop: 16, marginBottom: 24 },
  logoCircle: {
    width: 88, height: 88, borderRadius: 44, backgroundColor: colors.primary,
    alignItems: 'center', justifyContent: 'center',
    shadowColor: colors.primary, shadowOpacity: 0.3, shadowRadius: 16, shadowOffset: { width: 0, height: 8 }, elevation: 8,
  },
  title: { fontSize: 28, fontWeight: '800', color: colors.textPrimary, marginTop: 12 },
  subtitle: { fontSize: 14, color: colors.textSecondary, marginTop: 4 },
  roleSwitch: { flexDirection: 'row-reverse', backgroundColor: colors.surface, borderRadius: 16, padding: 4, marginBottom: 16, borderWidth: 1, borderColor: colors.border },
  roleBtn: { flex: 1, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', paddingVertical: 12, borderRadius: 12, gap: 6 },
  roleBtnActive: { backgroundColor: colors.primary },
  roleTxt: { color: colors.textSecondary, fontWeight: '700' },
  roleTxtActive: { color: '#fff' },
  tabs: { flexDirection: 'row-reverse', marginBottom: 16 },
  tab: { flex: 1, paddingVertical: 10, alignItems: 'center', borderBottomWidth: 2, borderBottomColor: colors.border },
  tabActive: { borderBottomColor: colors.primary },
  tabTxt: { color: colors.textSecondary, fontWeight: '600' },
  tabTxtActive: { color: colors.primary, fontWeight: '800' },
  field: { marginBottom: 14 },
  label: { fontSize: 13, color: colors.textSecondary, marginBottom: 6, textAlign: 'right', fontWeight: '600' },
  input: {
    backgroundColor: colors.surface, borderRadius: 14, paddingHorizontal: 16, paddingVertical: 14,
    fontSize: 16, color: colors.textPrimary, borderWidth: 1, borderColor: colors.border,
  },
  submit: {
    backgroundColor: colors.primary, borderRadius: 16, paddingVertical: 16,
    flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8,
    marginTop: 16, shadowColor: colors.primary, shadowOpacity: 0.3, shadowRadius: 12, shadowOffset: { width: 0, height: 6 }, elevation: 6,
  },
  submitTxt: { color: '#fff', fontSize: 17, fontWeight: '800' },
  forgotLink: { padding: 16, alignItems: 'center' },
  forgotTxt: { color: colors.secondaryDark, fontWeight: '700', fontSize: 14 },
});
