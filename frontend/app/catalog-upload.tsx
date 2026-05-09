import { useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, Alert, ScrollView, Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import * as DocumentPicker from 'expo-document-picker';
import * as FileSystem from 'expo-file-system/legacy';
import { useRouter } from 'expo-router';
import { useAuth, apiFetch } from '../src/auth';
import { colors } from '../src/theme';
import ScreenHeader from '../src/ScreenHeader';

type Picked = { name: string; mimeType: string; size?: number; uri: string; base64?: string };

export default function CatalogUpload() {
  const { token } = useAuth();
  const router = useRouter();
  const [picked, setPicked] = useState<Picked | null>(null);
  const [busy, setBusy] = useState(false);

  const pick = async () => {
    try {
      const res = await DocumentPicker.getDocumentAsync({
        type: ['application/pdf', 'image/*'],
        copyToCacheDirectory: true,
      });
      if (res.canceled || !res.assets?.length) return;
      const a = res.assets[0];
      const mime = a.mimeType || (a.name?.toLowerCase().endsWith('.pdf') ? 'application/pdf' : 'image/jpeg');
      let b64: string | undefined;
      if (Platform.OS === 'web') {
        // On web, fetch the blob URL and convert to base64
        const r = await fetch(a.uri);
        const blob = await r.blob();
        b64 = await new Promise<string>((resolve, reject) => {
          const fr = new FileReader();
          fr.onload = () => {
            const s = String(fr.result || '');
            resolve(s.includes(',') ? s.split(',')[1] : s);
          };
          fr.onerror = reject;
          fr.readAsDataURL(blob);
        });
      } else {
        b64 = await FileSystem.readAsStringAsync(a.uri, { encoding: FileSystem.EncodingType.Base64 });
      }
      setPicked({ name: a.name || 'file', mimeType: mime, size: a.size, uri: a.uri, base64: b64 });
    } catch (e: any) {
      Alert.alert('خطأ', e?.message || 'فشل اختيار الملف');
    }
  };

  const upload = async () => {
    if (!picked?.base64) {
      Alert.alert('تنبيه', 'اختر ملفاً أولاً');
      return;
    }
    setBusy(true);
    try {
      const res: any = await apiFetch('/supplier/catalog/upload', {
        method: 'POST',
        body: JSON.stringify({
          file_b64: picked.base64,
          file_type: picked.mimeType.includes('pdf') ? 'pdf' : picked.mimeType,
          filename: picked.name,
        }),
      }, token);
      Alert.alert('تم الرفع', 'بدأ تحليل الملف. ستظهر النتائج خلال دقائق.', [
        { text: 'متابعة', onPress: () => router.replace({ pathname: '/catalog-jobs' } as any) },
      ]);
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل الرفع');
    } finally {
      setBusy(false);
    }
  };

  const sizeKb = picked?.size ? Math.round(picked.size / 1024) : 0;
  const isPdf = picked?.mimeType.includes('pdf');

  return (
    <SafeAreaView style={styles.safe}>
      <ScreenHeader title="استيراد كتالوج" subtitle="ارفع PDF أو صورة قائمة الأسعار" />
      <ScrollView contentContainerStyle={{ padding: 20, gap: 14 }}>
        <View style={styles.infoCard}>
          <Ionicons name="sparkles" size={22} color={colors.primary} />
          <View style={{ flex: 1, alignItems: 'flex-end' }}>
            <Text style={styles.infoTitle}>استخراج ذكي بالـ AI</Text>
            <Text style={styles.infoSub}>سنستخرج اسم الدواء، التركيز، السعر، والكمية من ملفك تلقائياً</Text>
          </View>
        </View>

        <TouchableOpacity testID="btn-pick-file" style={styles.dropZone} onPress={pick} activeOpacity={0.8}>
          {picked ? (
            <View style={{ alignItems: 'center', gap: 8 }}>
              <Ionicons name={isPdf ? 'document-text' : 'image'} size={44} color={colors.primary} />
              <Text style={styles.fileName} numberOfLines={1}>{picked.name}</Text>
              <Text style={styles.fileMeta}>{sizeKb} KB · {isPdf ? 'PDF' : 'صورة'}</Text>
            </View>
          ) : (
            <View style={{ alignItems: 'center', gap: 8 }}>
              <Ionicons name="cloud-upload-outline" size={48} color={colors.textMuted} />
              <Text style={styles.dropTxt}>اضغط لاختيار ملف</Text>
              <Text style={styles.dropSub}>PDF أو PNG/JPG · حد أقصى 12MB</Text>
            </View>
          )}
        </TouchableOpacity>

        <TouchableOpacity
          testID="btn-upload-catalog"
          style={[styles.uploadBtn, (!picked || busy) && styles.uploadBtnDisabled]}
          onPress={upload}
          disabled={!picked || busy}
        >
          {busy ? <ActivityIndicator color="#fff" /> : (
            <>
              <Ionicons name="rocket" size={20} color="#fff" />
              <Text style={styles.uploadTxt}>بدء التحليل</Text>
            </>
          )}
        </TouchableOpacity>

        <TouchableOpacity testID="btn-jobs-history" style={styles.historyLink} onPress={() => router.push({ pathname: '/catalog-jobs' } as any)}>
          <Ionicons name="time-outline" size={18} color={colors.secondaryDark} />
          <Text style={styles.historyTxt}>سجل الاستيرادات السابقة</Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  infoCard: { backgroundColor: colors.primaryLight, borderRadius: 16, padding: 14, flexDirection: 'row-reverse', gap: 10, alignItems: 'center' },
  infoTitle: { color: colors.primaryDark, fontWeight: '800', fontSize: 14, textAlign: 'right' },
  infoSub: { color: colors.textSecondary, fontSize: 12, textAlign: 'right', marginTop: 2 },
  dropZone: { backgroundColor: colors.surface, borderWidth: 2, borderColor: colors.border, borderStyle: 'dashed', borderRadius: 18, paddingVertical: 36, alignItems: 'center' },
  dropTxt: { fontSize: 16, fontWeight: '700', color: colors.textPrimary },
  dropSub: { fontSize: 12, color: colors.textMuted },
  fileName: { fontSize: 15, fontWeight: '800', color: colors.textPrimary, maxWidth: 240 },
  fileMeta: { fontSize: 12, color: colors.textSecondary },
  uploadBtn: { backgroundColor: colors.primary, borderRadius: 16, paddingVertical: 16, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8 },
  uploadBtnDisabled: { opacity: 0.5 },
  uploadTxt: { color: '#fff', fontWeight: '800', fontSize: 16 },
  templateBtn: { backgroundColor: colors.indigoLight, borderRadius: 12, paddingVertical: 12, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 6, borderWidth: 1, borderColor: colors.indigo },
  templateTxt: { color: colors.indigo, fontWeight: '800', fontSize: 13 },
  historyLink: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 6, padding: 10 },
  historyTxt: { color: colors.secondaryDark, fontWeight: '700' },
});
