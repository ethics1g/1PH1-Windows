import { useState } from 'react';
import { View, Text, StyleSheet, TextInput, TouchableOpacity, ActivityIndicator, Alert, KeyboardAvoidingView, Platform, ScrollView } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useAuth, apiFetch } from '../../src/auth';
import { colors } from '../../src/theme';

export default function AdminChangePassword() {
  const { token, signOut } = useAuth();
  const router = useRouter();
  const [oldPwd, setOldPwd] = useState('admin123');
  const [newPwd, setNewPwd] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (newPwd.length < 6) { Alert.alert('تنبيه', 'كلمة المرور 6 أحرف على الأقل'); return; }
    if (newPwd !== confirm) { Alert.alert('تنبيه', 'كلمتا المرور غير متطابقتين'); return; }
    setBusy(true);
    try {
      await apiFetch('/admin/change-password', {
        method: 'POST',
        body: JSON.stringify({ old_password: oldPwd, new_password: newPwd }),
      }, token);
      Alert.alert('تم', 'تم تغيير كلمة المرور بنجاح', [
        { text: 'متابعة', onPress: () => router.replace('/admin/dashboard') },
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
        <ScrollView contentContainerStyle={styles.scroll}>
          <View style={styles.icon}><Ionicons name="key" size={40} color="#fff" /></View>
          <Text style={styles.title}>تغيير كلمة المرور إلزامي</Text>
          <Text style={styles.sub}>هذه عملية مرة واحدة فقط لتأمين حساب المدير</Text>

          <Text style={styles.label}>كلمة المرور الحالية</Text>
          <TextInput testID="acp-old" style={styles.input} value={oldPwd} onChangeText={setOldPwd} secureTextEntry textAlign="right" />

          <Text style={styles.label}>كلمة المرور الجديدة</Text>
          <TextInput testID="acp-new" style={styles.input} value={newPwd} onChangeText={setNewPwd} secureTextEntry textAlign="right" />

          <Text style={styles.label}>تأكيد كلمة المرور</Text>
          <TextInput testID="acp-confirm" style={styles.input} value={confirm} onChangeText={setConfirm} secureTextEntry textAlign="right" />

          <TouchableOpacity testID="acp-submit" style={[styles.btn, busy && { opacity: 0.5 }]} onPress={submit} disabled={busy}>
            {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.btnTxt}>حفظ ومتابعة</Text>}
          </TouchableOpacity>

          <TouchableOpacity onPress={async () => { await signOut(); router.replace('/login'); }} style={styles.cancel}>
            <Text style={styles.cancelTxt}>تسجيل خروج</Text>
          </TouchableOpacity>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  scroll: { padding: 24, alignItems: 'stretch' },
  icon: { width: 80, height: 80, borderRadius: 40, backgroundColor: colors.primary, alignItems: 'center', justifyContent: 'center', alignSelf: 'center', marginVertical: 20 },
  title: { fontSize: 22, fontWeight: '900', color: colors.textPrimary, textAlign: 'center', marginBottom: 6 },
  sub: { fontSize: 13, color: colors.textSecondary, textAlign: 'center', marginBottom: 24 },
  label: { fontSize: 13, color: colors.textSecondary, marginBottom: 6, textAlign: 'right', fontWeight: '600' },
  input: { backgroundColor: colors.surface, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, fontSize: 15, borderWidth: 1, borderColor: colors.border, marginBottom: 14 },
  btn: { backgroundColor: colors.primary, borderRadius: 14, paddingVertical: 14, alignItems: 'center', marginTop: 10 },
  btnTxt: { color: '#fff', fontWeight: '800', fontSize: 16 },
  cancel: { padding: 14, alignItems: 'center' },
  cancelTxt: { color: colors.error, fontWeight: '700' },
});
