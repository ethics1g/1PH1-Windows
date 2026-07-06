import { useEffect, useState } from 'react';
import { View, Text, StyleSheet, TextInput, TouchableOpacity, ScrollView, Alert, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import ScreenHeader from '../../src/ScreenHeader';
import { colors } from '../../src/theme';
import { apiFetch, useAuth } from '../../src/auth';

export default function PersonalInfo() {
  const { token } = useAuth();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [role, setRole] = useState('');
  const [region, setRegion] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const p: any = await apiFetch('/me/profile', {}, token);
        setName(p.name || '');
        setEmail(p.email || '');
        setPhone(p.phone || '');
        setRole(p.role || '');
        setRegion(p.region || '');
      } catch (e: any) { Alert.alert('خطأ', e.message); }
      finally { setLoading(false); }
    })();
  }, [token]);

  const save = async () => {
    if (!name.trim()) { Alert.alert('تنبيه', 'الاسم مطلوب'); return; }
    setSaving(true);
    try {
      await apiFetch('/me/profile', {
        method: 'PATCH',
        body: JSON.stringify({ name: name.trim(), email: email.trim() || undefined }),
      }, token);
      Alert.alert('✅ تم', 'تم تحديث المعلومات بنجاح');
    } catch (e: any) { Alert.alert('خطأ', e.message); }
    finally { setSaving(false); }
  };

  if (loading) return <SafeAreaView style={styles.safe}><ActivityIndicator style={{ marginTop: 60 }} size="large" color={colors.primary} /></SafeAreaView>;

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <ScreenHeader title="المعلومات الشخصية" />
      <ScrollView contentContainerStyle={{ padding: 16 }}>
        <Field label="الاسم" value={name} onChange={setName} testID="input-name" />
        <Field label="البريد الإلكتروني (اختياري)" value={email} onChange={setEmail} testID="input-email" keyboardType="email-address" />
        <Field label="رقم الهاتف" value={phone} onChange={() => {}} testID="input-phone" editable={false} />
        <Field label="الدور" value={roleLabel(role)} onChange={() => {}} testID="input-role" editable={false} />
        {region ? <Field label="المحافظة" value={region} onChange={() => {}} testID="input-region" editable={false} /> : null}

        <TouchableOpacity testID="btn-save" style={styles.saveBtn} onPress={save} disabled={saving}>
          {saving ? <ActivityIndicator color="#fff" /> : (
            <>
              <Ionicons name="save" size={18} color="#fff" />
              <Text style={styles.saveTxt}>حفظ التغييرات</Text>
            </>
          )}
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

function roleLabel(r?: string) { return r === 'pharmacy' ? 'صيدلية' : r === 'supplier' ? 'مذخر' : r === 'admin' ? 'مسؤول' : (r || ''); }

function Field({ label, value, onChange, testID, keyboardType, editable = true }: any) {
  return (
    <View style={{ marginBottom: 14 }}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        testID={testID}
        style={[styles.input, !editable && { backgroundColor: colors.background, color: colors.textMuted }]}
        value={value}
        onChangeText={onChange}
        editable={editable}
        keyboardType={keyboardType || 'default'}
        textAlign="right"
      />
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  label: { fontSize: 13, color: colors.textSecondary, marginBottom: 6, textAlign: 'right', fontWeight: '700' },
  input: { backgroundColor: colors.surface, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, fontSize: 15, color: colors.textPrimary, borderWidth: 1, borderColor: colors.border },
  saveBtn: { backgroundColor: colors.primary, borderRadius: 14, paddingVertical: 14, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8, marginTop: 8 },
  saveTxt: { color: '#fff', fontSize: 15, fontWeight: '800' },
});
