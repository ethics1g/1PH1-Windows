import { useCallback, useState } from 'react';
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity, FlatList,
  ActivityIndicator, Alert, KeyboardAvoidingView, Platform, ScrollView, RefreshControl, Image,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect, useRouter } from 'expo-router';
import { useAuth, apiFetch } from '../src/auth';
import { colors } from '../src/theme';

type Product = { id: string; name: string; price: number; description?: string; image_base64?: string };

export default function SupplierDashboard() {
  const { token, user, signOut } = useAuth();
  const router = useRouter();
  const [name, setName] = useState('');
  const [price, setPrice] = useState('');
  const [quantity, setQuantity] = useState('');
  const [deliveryTime, setDeliveryTime] = useState('');
  const [description, setDescription] = useState('');
  const [items, setItems] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const data: Product[] = await apiFetch('/supplier/products', {}, token);
      setItems(data);
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل التحميل');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [token]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const addProduct = async () => {
    if (!name.trim() || !price.trim()) { Alert.alert('تنبيه', 'الاسم والسعر مطلوبان'); return; }
    setBusy(true);
    try {
      await apiFetch('/supplier/products', {
        method: 'POST',
        body: JSON.stringify({
          name: name.trim(),
          price: parseFloat(price) || 0,
          quantity: parseInt(quantity) || 0,
          delivery_time: deliveryTime.trim() || null,
          description: description.trim() || null,
        }),
      }, token);
      setName(''); setPrice(''); setQuantity(''); setDeliveryTime(''); setDescription('');
      await load();
      Alert.alert('تم', 'تمت إضافة المنتج');
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل الإضافة');
    } finally {
      setBusy(false);
    }
  };

  const deleteProduct = async (id: string) => {
    try {
      await apiFetch(`/supplier/products/${id}`, { method: 'DELETE' }, token);
      await load();
    } catch (e: any) {
      Alert.alert('خطأ', e.message || 'فشل الحذف');
    }
  };

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
        <View style={styles.header}>
          <View style={{ flex: 1 }}>
            <Text style={styles.hello}>مذخر</Text>
            <Text style={styles.name}>{user?.name}</Text>
          </View>
          <TouchableOpacity testID="btn-supplier-logout" style={styles.logoutBtn} onPress={async () => { await signOut(); router.replace('/login'); }}>
            <Ionicons name="log-out-outline" size={22} color={colors.error} />
          </TouchableOpacity>
        </View>

        <View style={styles.aiCardWrap}>
          <TouchableOpacity
            testID="btn-import-catalog"
            style={styles.aiCard}
            activeOpacity={0.85}
            onPress={() => router.push({ pathname: '/catalog-upload' } as any)}
          >
            <View style={styles.aiIcon}><Ionicons name="sparkles" size={26} color="#fff" /></View>
            <View style={{ flex: 1, alignItems: 'flex-end' }}>
              <Text style={styles.aiTitle}>استيراد كتالوج بالذكاء الاصطناعي</Text>
              <Text style={styles.aiSub}>ارفع PDF أو صورة قائمة الأسعار - نستخرج الأدوية تلقائياً</Text>
            </View>
            <Ionicons name="chevron-back" size={22} color="#fff" />
          </TouchableOpacity>
        </View>

        <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ paddingBottom: 24 }} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}>
          <View style={styles.formCard}>
            <Text style={styles.formTitle}>إضافة منتج جديد</Text>
            <TextInput testID="sup-name" style={styles.input} value={name} onChangeText={setName} placeholder="اسم الدواء" placeholderTextColor={colors.textMuted} textAlign="right" />
            <TextInput testID="sup-price" style={styles.input} value={price} onChangeText={setPrice} placeholder="السعر (د.ع)" placeholderTextColor={colors.textMuted} keyboardType="numeric" textAlign="right" />
            <View style={{ flexDirection: 'row-reverse', gap: 10 }}>
              <TextInput testID="sup-quantity" style={[styles.input, { flex: 1 }]} value={quantity} onChangeText={setQuantity} placeholder="الكمية المتاحة" placeholderTextColor={colors.textMuted} keyboardType="numeric" textAlign="right" />
              <TextInput testID="sup-delivery" style={[styles.input, { flex: 1 }]} value={deliveryTime} onChangeText={setDeliveryTime} placeholder="وقت التوصيل (مثال: 24 ساعة)" placeholderTextColor={colors.textMuted} textAlign="right" />
            </View>
            <TextInput testID="sup-desc" style={[styles.input, { height: 70 }]} value={description} onChangeText={setDescription} placeholder="وصف اختياري" placeholderTextColor={colors.textMuted} multiline textAlign="right" />
            <TouchableOpacity testID="btn-add-product" style={styles.addBtn} onPress={addProduct} disabled={busy}>
              {busy ? <ActivityIndicator color="#fff" /> : <><Ionicons name="add-circle" size={22} color="#fff" /><Text style={styles.addBtnTxt}>إضافة</Text></>}
            </TouchableOpacity>
          </View>

          <Text style={styles.section}>منتجاتي ({items.length})</Text>

          {loading ? (
            <ActivityIndicator color={colors.primary} style={{ marginTop: 20 }} />
          ) : items.length === 0 ? (
            <View style={styles.empty}>
              <Ionicons name="cube-outline" size={60} color={colors.textMuted} />
              <Text style={styles.emptyTxt}>لا توجد منتجات بعد</Text>
            </View>
          ) : (
            <View style={{ paddingHorizontal: 16, gap: 10 }}>
              {items.map(item => (
                <View key={item.id} style={styles.prodRow} testID={`product-${item.id}`}>
                  <TouchableOpacity testID={`del-${item.id}`} onPress={() => deleteProduct(item.id)} style={styles.delBtn}>
                    <Ionicons name="trash" size={18} color={colors.error} />
                  </TouchableOpacity>
                  <View style={{ flex: 1, alignItems: 'flex-end' }}>
                    <Text style={styles.prodName}>{item.name}</Text>
                    <Text style={styles.prodPrice}>{item.price.toLocaleString()} د.ع</Text>
                    {item.description ? <Text style={styles.prodDesc} numberOfLines={2}>{item.description}</Text> : null}
                  </View>
                </View>
              ))}
            </View>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: 'row-reverse', alignItems: 'center', padding: 20 },
  hello: { color: colors.textSecondary, fontSize: 13, textAlign: 'right' },
  name: { color: colors.textPrimary, fontSize: 20, fontWeight: '800', textAlign: 'right' },
  logoutBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: '#fee2e2', alignItems: 'center', justifyContent: 'center' },
  formCard: { backgroundColor: colors.surface, marginHorizontal: 16, borderRadius: 18, padding: 16, borderWidth: 1, borderColor: colors.border, gap: 10 },
  formTitle: { fontSize: 16, fontWeight: '800', color: colors.textPrimary, textAlign: 'right', marginBottom: 4 },
  input: { backgroundColor: colors.background, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, fontSize: 15, color: colors.textPrimary, borderWidth: 1, borderColor: colors.border },
  addBtn: { backgroundColor: colors.primary, borderRadius: 12, paddingVertical: 12, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8, marginTop: 4 },
  addBtnTxt: { color: '#fff', fontWeight: '800', fontSize: 15 },
  section: { fontSize: 16, fontWeight: '800', color: colors.textPrimary, textAlign: 'right', marginHorizontal: 20, marginTop: 20, marginBottom: 10 },
  empty: { alignItems: 'center', gap: 8, padding: 30 },
  emptyTxt: { color: colors.textSecondary },
  prodRow: { backgroundColor: colors.surface, borderRadius: 14, padding: 14, flexDirection: 'row-reverse', alignItems: 'center', borderWidth: 1, borderColor: colors.border },
  delBtn: { width: 36, height: 36, borderRadius: 18, backgroundColor: '#fee2e2', alignItems: 'center', justifyContent: 'center', marginLeft: 10 },
  prodName: { fontSize: 15, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  prodPrice: { color: colors.primary, fontWeight: '800', marginTop: 2 },
  prodDesc: { color: colors.textSecondary, fontSize: 12, textAlign: 'right', marginTop: 2 },
});
