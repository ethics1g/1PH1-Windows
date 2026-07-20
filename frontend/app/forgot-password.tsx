import { useState } from 'react';
import { View, Text, StyleSheet, TextInput, TouchableOpacity, ScrollView, KeyboardAvoidingView, Platform, ActivityIndicator, Alert } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { apiFetch } from '../src/auth';
import { colors } from '../src/theme';
import ScreenHeader from '../src/ScreenHeader';

export default function ForgotPassword() {
  const router = useRouter();
  const [phone, setPhone] = useState('');
  const [role, setRole] = useState<'pharmacy' | 'supplier'>('pharmacy');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!phone.trim()) {
      Alert.alert('تنبيه', 'أدخل رقم الهاتف');
      return;
    }
    setBusy(true);
    try {
      const res: any = await apiFetch('/auth/forgot-password', {
        method: 'POST',
        body: JSON.stringify({ phone: phone.trim(), role }),
      });
      if (res.dev_otp) {
        Alert.alert('🔧 وضع التطوير', `الرمز: ${res.dev_otp}\n\n(في الإنتاج سيُرسل عبر SMS)`, [
          { text: 'متابعة', onPress: () => router.push({ pathname: '/verify-otp', params: { phone: phone.trim(), role } } as any) },
        ]);
      } else {
        Alert.alert('تم الإرسال', 'إذا كان الرقم مسجلاً، سيتم إرسال رمز التحقق', [
          { text: 'متابعة', onPress: () => router.push({ pathname: '/verify-otp', params: { phone: phone.trim(), role } } as any) },
        ]);
      }
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل الطلب');
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
        <ScreenHeader title="نسيت الرمز السري" subtitle="سنرسل لك رمز تحقق" />
        <ScrollView contentContainerStyle={{ padding: 20 }} keyboardShouldPersistTaps="handled">
          <View style={styles.iconWrap}>
            <Ionicons name="lock-closed" size={50} color={colors.primary} />
          </View>

          <View style={styles.roleSwitch}>
            <TouchableOpacity testID="fp-role-pharmacy" style={[styles.roleBtn, role === 'pharmacy' && styles.roleActive]} onPress={() => setRole('pharmacy')}>
              <Text style={[styles.roleTxt, role === 'pharmacy' && styles.roleTxtActive]}>متجر</Text>
            </TouchableOpacity>
            <TouchableOpacity testID="fp-role-supplier" style={[styles.roleBtn, role === 'supplier' && styles.roleActive]} onPress={() => setRole('supplier')}>
              <Text style={[styles.roleTxt, role === 'supplier' && styles.roleTxtActive]}>مورد</Text>
            </TouchableOpacity>
          </View>

          <Text style={styles.label}>رقم الهاتف المسجل</Text>
          <TextInput
            testID="fp-phone"
            style={styles.input}
            value={phone}
            onChangeText={setPhone}
            placeholder="07XXXXXXXXX"
            placeholderTextColor={colors.textMuted}
            keyboardType="phone-pad"
            textAlign="right"
          />

          <TouchableOpacity testID="fp-submit" style={[styles.submit, busy && { opacity: 0.6 }]} onPress={submit} disabled={busy}>
            {busy ? <ActivityIndicator color="#fff" /> : (
              <>
                <Ionicons name="paper-plane" size={20} color="#fff" />
                <Text style={styles.submitTxt}>إرسال رمز التحقق</Text>
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
  iconWrap: { alignItems: 'center', marginVertical: 20 },
  roleSwitch: { flexDirection: 'row-reverse', backgroundColor: colors.surface, borderRadius: 14, padding: 4, marginBottom: 18, borderWidth: 1, borderColor: colors.border },
  roleBtn: { flex: 1, paddingVertical: 12, alignItems: 'center', borderRadius: 10 },
  roleActive: { backgroundColor: colors.primary },
  roleTxt: { color: colors.textSecondary, fontWeight: '700' },
  roleTxtActive: { color: '#fff' },
  label: { fontSize: 13, color: colors.textSecondary, marginBottom: 6, textAlign: 'right', fontWeight: '600' },
  input: { backgroundColor: colors.surface, borderRadius: 14, paddingHorizontal: 16, paddingVertical: 14, fontSize: 16, color: colors.textPrimary, borderWidth: 1, borderColor: colors.border, marginBottom: 16 },
  submit: { backgroundColor: colors.primary, borderRadius: 16, paddingVertical: 16, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8 },
  submitTxt: { color: '#fff', fontSize: 16, fontWeight: '800' },
});
