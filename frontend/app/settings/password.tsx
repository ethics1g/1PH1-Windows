import { useState } from 'react';
import { View, Text, StyleSheet, TextInput, TouchableOpacity, Alert, ActivityIndicator, ScrollView } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import ScreenHeader from '../../src/ScreenHeader';
import { colors } from '../../src/theme';
import { apiFetch, useAuth } from '../../src/auth';

export default function ChangePassword() {
  const router = useRouter();
  const { token } = useAuth();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [showCur, setShowCur] = useState(false);
  const [showNew, setShowNew] = useState(false);

  const submit = async () => {
    if (!current || !next) { Alert.alert('تنبيه', 'الرجاء ملء جميع الحقول'); return; }
    if (next.length < 6) { Alert.alert('تنبيه', 'كلمة السر الجديدة يجب أن تكون 6 أحرف على الأقل'); return; }
    if (next !== confirm) { Alert.alert('تنبيه', 'كلمة السر الجديدة غير متطابقة'); return; }
    if (next === current) { Alert.alert('تنبيه', 'يجب أن تختلف كلمة السر الجديدة عن الحالية'); return; }
    setBusy(true);
    try {
      await apiFetch('/me/password', { method: 'PATCH', body: JSON.stringify({ current_password: current, new_password: next }) }, token);
      Alert.alert('✅ تم', 'تم تغيير كلمة السر بنجاح', [{ text: 'موافق', onPress: () => router.back() }]);
    } catch (e: any) { Alert.alert('خطأ', e.message); }
    finally { setBusy(false); }
  };

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <ScreenHeader title="تغيير كلمة السر" />
      <ScrollView contentContainerStyle={{ padding: 16 }}>
        <View style={styles.tipCard}>
          <Ionicons name="shield-checkmark" size={20} color={colors.indigo} />
          <Text style={styles.tipTxt}>اختر كلمة سر قوية، لا تقل عن 6 أحرف، تحتوي على أرقام وحروف.</Text>
        </View>

        <Text style={styles.label}>كلمة السر الحالية *</Text>
        <View style={styles.inputWrap}>
          <TouchableOpacity onPress={() => setShowCur(!showCur)} style={styles.eye}><Ionicons name={showCur ? 'eye-off' : 'eye'} size={20} color={colors.textMuted} /></TouchableOpacity>
          <TextInput testID="input-current" style={styles.input} value={current} onChangeText={setCurrent} secureTextEntry={!showCur} textAlign="right" placeholder="******" placeholderTextColor={colors.textMuted} />
        </View>

        <Text style={styles.label}>كلمة السر الجديدة *</Text>
        <View style={styles.inputWrap}>
          <TouchableOpacity onPress={() => setShowNew(!showNew)} style={styles.eye}><Ionicons name={showNew ? 'eye-off' : 'eye'} size={20} color={colors.textMuted} /></TouchableOpacity>
          <TextInput testID="input-new" style={styles.input} value={next} onChangeText={setNext} secureTextEntry={!showNew} textAlign="right" placeholder="6 أحرف على الأقل" placeholderTextColor={colors.textMuted} />
        </View>

        <Text style={styles.label}>تأكيد كلمة السر الجديدة *</Text>
        <View style={styles.inputWrap}>
          <TextInput testID="input-confirm" style={styles.input} value={confirm} onChangeText={setConfirm} secureTextEntry={!showNew} textAlign="right" placeholder="******" placeholderTextColor={colors.textMuted} />
        </View>

        <TouchableOpacity testID="btn-submit" style={styles.btn} onPress={submit} disabled={busy}>
          {busy ? <ActivityIndicator color="#fff" /> : (
            <>
              <Ionicons name="key" size={18} color="#fff" />
              <Text style={styles.btnTxt}>تغيير كلمة السر</Text>
            </>
          )}
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  tipCard: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, padding: 12, backgroundColor: colors.indigoLight, borderRadius: 12, marginBottom: 20 },
  tipTxt: { flex: 1, fontSize: 12, color: colors.indigo, textAlign: 'right', fontWeight: '600' },
  label: { fontSize: 13, color: colors.textSecondary, marginBottom: 6, textAlign: 'right', fontWeight: '700' },
  inputWrap: { flexDirection: 'row-reverse', alignItems: 'center', backgroundColor: colors.surface, borderRadius: 12, borderWidth: 1, borderColor: colors.border, marginBottom: 14 },
  input: { flex: 1, paddingHorizontal: 14, paddingVertical: 12, fontSize: 15, color: colors.textPrimary },
  eye: { width: 40, alignItems: 'center' },
  btn: { backgroundColor: colors.primary, borderRadius: 14, paddingVertical: 14, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8, marginTop: 10 },
  btnTxt: { color: '#fff', fontSize: 15, fontWeight: '800' },
});
