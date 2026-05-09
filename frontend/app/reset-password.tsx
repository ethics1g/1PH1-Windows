import { useState } from 'react';
import { View, Text, StyleSheet, TextInput, TouchableOpacity, KeyboardAvoidingView, Platform, ActivityIndicator, Alert, ScrollView } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { apiFetch } from '../src/auth';
import { colors } from '../src/theme';
import ScreenHeader from '../src/ScreenHeader';

export default function ResetPassword() {
  const router = useRouter();
  const { reset_token } = useLocalSearchParams<{ reset_token: string }>();
  const [pwd, setPwd] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (pwd.length < 6) { Alert.alert('تنبيه', 'كلمة المرور يجب أن تكون 6 أحرف على الأقل'); return; }
    if (pwd !== confirm) { Alert.alert('تنبيه', 'كلمتا المرور غير متطابقتين'); return; }
    setBusy(true);
    try {
      await apiFetch('/auth/reset-password', {
        method: 'POST',
        body: JSON.stringify({ reset_token, new_password: pwd }),
      });
      Alert.alert('تم', 'تم تغيير كلمة المرور بنجاح', [
        { text: 'تسجيل الدخول', onPress: () => router.replace('/login') },
      ]);
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشلت العملية');
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
        <ScreenHeader title="رمز سري جديد" subtitle="اختر رمزاً سرياً قوياً" />
        <ScrollView contentContainerStyle={{ padding: 20 }} keyboardShouldPersistTaps="handled">
          <View style={styles.iconWrap}>
            <Ionicons name="key" size={50} color={colors.primary} />
          </View>

          <Text style={styles.label}>الرمز السري الجديد</Text>
          <TextInput testID="rp-pwd" style={styles.input} value={pwd} onChangeText={setPwd} placeholder="••••••" placeholderTextColor={colors.textMuted} secureTextEntry textAlign="right" />

          <Text style={styles.label}>تأكيد الرمز السري</Text>
          <TextInput testID="rp-confirm" style={styles.input} value={confirm} onChangeText={setConfirm} placeholder="••••••" placeholderTextColor={colors.textMuted} secureTextEntry textAlign="right" />

          <TouchableOpacity testID="rp-submit" style={[styles.submit, busy && { opacity: 0.6 }]} onPress={submit} disabled={busy}>
            {busy ? <ActivityIndicator color="#fff" /> : (
              <>
                <Ionicons name="save" size={20} color="#fff" />
                <Text style={styles.submitTxt}>حفظ كلمة المرور</Text>
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
  label: { fontSize: 13, color: colors.textSecondary, marginBottom: 6, textAlign: 'right', fontWeight: '600' },
  input: { backgroundColor: colors.surface, borderRadius: 14, paddingHorizontal: 16, paddingVertical: 14, fontSize: 16, color: colors.textPrimary, borderWidth: 1, borderColor: colors.border, marginBottom: 14 },
  submit: { backgroundColor: colors.primary, borderRadius: 16, paddingVertical: 16, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8, marginTop: 8 },
  submitTxt: { color: '#fff', fontSize: 16, fontWeight: '800' },
});
