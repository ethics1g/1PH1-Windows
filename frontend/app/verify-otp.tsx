import { useState } from 'react';
import { View, Text, StyleSheet, TextInput, TouchableOpacity, KeyboardAvoidingView, Platform, ActivityIndicator, Alert, ScrollView } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { apiFetch } from '../src/auth';
import { colors } from '../src/theme';
import ScreenHeader from '../src/ScreenHeader';

export default function VerifyOtp() {
  const router = useRouter();
  const { phone, role } = useLocalSearchParams<{ phone: string; role: string }>();
  const [otp, setOtp] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (otp.length !== 6) {
      Alert.alert('تنبيه', 'الرمز يجب أن يكون 6 أرقام');
      return;
    }
    setBusy(true);
    try {
      const res: any = await apiFetch('/auth/verify-otp', {
        method: 'POST',
        body: JSON.stringify({ phone, role, otp }),
      });
      router.replace({ pathname: '/reset-password', params: { reset_token: res.reset_token } } as any);
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل التحقق');
    } finally {
      setBusy(false);
    }
  };

  const resend = async () => {
    setBusy(true);
    try {
      const res: any = await apiFetch('/auth/forgot-password', {
        method: 'POST',
        body: JSON.stringify({ phone, role }),
      });
      if (res.dev_otp) {
        Alert.alert('🔧 وضع التطوير', `رمز جديد: ${res.dev_otp}`);
      } else {
        Alert.alert('تم', 'تم إرسال رمز جديد');
      }
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل');
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
        <ScreenHeader title="رمز التحقق" subtitle={`أدخل الرمز المرسل إلى ${phone}`} />
        <ScrollView contentContainerStyle={{ padding: 20 }} keyboardShouldPersistTaps="handled">
          <View style={styles.iconWrap}>
            <Ionicons name="shield-checkmark" size={50} color={colors.primary} />
          </View>

          <Text style={styles.label}>رمز التحقق (6 أرقام)</Text>
          <TextInput
            testID="otp-input"
            style={styles.input}
            value={otp}
            onChangeText={(v) => setOtp(v.replace(/\D/g, '').slice(0, 6))}
            placeholder="------"
            placeholderTextColor={colors.textMuted}
            keyboardType="number-pad"
            maxLength={6}
            textAlign="center"
          />

          <TouchableOpacity testID="otp-submit" style={[styles.submit, busy && { opacity: 0.6 }]} onPress={submit} disabled={busy}>
            {busy ? <ActivityIndicator color="#fff" /> : (
              <>
                <Ionicons name="checkmark-circle" size={20} color="#fff" />
                <Text style={styles.submitTxt}>تحقق</Text>
              </>
            )}
          </TouchableOpacity>

          <TouchableOpacity testID="otp-resend" style={styles.resend} onPress={resend} disabled={busy}>
            <Text style={styles.resendTxt}>لم يصل الرمز؟ إعادة إرسال</Text>
          </TouchableOpacity>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  iconWrap: { alignItems: 'center', marginVertical: 20 },
  label: { fontSize: 13, color: colors.textSecondary, marginBottom: 6, textAlign: 'right', fontWeight: '600' },
  input: { backgroundColor: colors.surface, borderRadius: 14, paddingHorizontal: 16, paddingVertical: 18, fontSize: 28, fontWeight: '800', color: colors.textPrimary, borderWidth: 1, borderColor: colors.border, marginBottom: 16, letterSpacing: 8 },
  submit: { backgroundColor: colors.primary, borderRadius: 16, paddingVertical: 16, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8 },
  submitTxt: { color: '#fff', fontSize: 16, fontWeight: '800' },
  resend: { padding: 16, alignItems: 'center' },
  resendTxt: { color: colors.secondaryDark, fontWeight: '700' },
});
