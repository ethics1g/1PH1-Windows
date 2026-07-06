import { useEffect, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, Modal, Animated, Easing, Pressable, Alert, ScrollView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { colors } from './theme';
import { useAuth } from './auth';

type Item = {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  route?: string;
  onPress?: () => void;
  testID: string;
  color?: string;
  danger?: boolean;
  adminOnly?: boolean;
};

export default function AppDrawer({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const router = useRouter();
  const { user, signOut } = useAuth();
  const slide = useRef(new Animated.Value(1)).current; // 1=hidden(right), 0=visible

  useEffect(() => {
    Animated.timing(slide, {
      toValue: visible ? 0 : 1,
      duration: 220,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: true,
    }).start();
  }, [visible, slide]);

  const go = (route: string) => {
    onClose();
    setTimeout(() => router.push(route as any), 180);
  };

  const items: Item[] = [
    { icon: 'person-circle', label: 'الملف الشخصي', route: '/settings/personal', testID: 'drawer-profile' },
    { icon: 'notifications', label: 'مركز الإشعارات', route: '/notifications', testID: 'drawer-notifications' },
    { icon: 'settings', label: 'إعدادات الحساب', route: '/settings', testID: 'drawer-settings' },
    { icon: 'key', label: 'تغيير كلمة السر', route: '/settings/password', testID: 'drawer-password' },
    { icon: 'notifications-outline', label: 'تفضيلات الإشعارات', route: '/settings/notifications', testID: 'drawer-notif-prefs' },
    { icon: 'shield-checkmark', label: 'إشعارات الإدارة', route: '/admin/notifications', testID: 'drawer-admin-notif', adminOnly: true, color: colors.indigo },
    { icon: 'log-out-outline', label: 'تسجيل الخروج', onPress: () => {
        Alert.alert('تسجيل الخروج', 'هل تريد تسجيل الخروج؟', [
          { text: 'إلغاء', style: 'cancel' },
          { text: 'خروج', style: 'destructive', onPress: async () => {
              onClose();
              await signOut();
              router.replace('/login' as any);
            } },
        ]);
      }, testID: 'drawer-logout', danger: true },
  ];

  const translateX = slide.interpolate({ inputRange: [0, 1], outputRange: [0, 320] });

  return (
    <Modal visible={visible} transparent animationType="none" onRequestClose={onClose}>
      <Pressable style={styles.backdrop} onPress={onClose} />
      <Animated.View style={[styles.sheet, { transform: [{ translateX }] }]}>
        <SafeAreaView style={{ flex: 1 }} edges={['top', 'right', 'bottom']}>
          <View style={styles.headerBox}>
            <View style={styles.avatar}>
              <Ionicons name="person" size={26} color="#fff" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.userName} numberOfLines={1}>{user?.name || 'المستخدم'}</Text>
              <Text style={styles.userSub}>{user?.phone || ''}</Text>
              <Text style={styles.userRole}>{roleLabel(user?.role)}</Text>
            </View>
            <TouchableOpacity onPress={onClose} testID="drawer-close" style={styles.closeBtn}>
              <Ionicons name="close" size={24} color={colors.textPrimary} />
            </TouchableOpacity>
          </View>

          <ScrollView contentContainerStyle={{ paddingVertical: 8 }}>
            {items
              .filter((it) => !it.adminOnly || user?.role === 'admin')
              .map((it) => (
              <TouchableOpacity
                key={it.testID}
                testID={it.testID}
                style={styles.item}
                onPress={() => (it.route ? go(it.route) : it.onPress?.())}
              >
                <Ionicons
                  name={it.icon}
                  size={22}
                  color={it.danger ? colors.error : (it.color || colors.textPrimary)}
                />
                <Text style={[styles.itemLabel, it.danger && { color: colors.error }, it.color ? { color: it.color } : null]}>
                  {it.label}
                </Text>
                <Ionicons name="chevron-back" size={18} color={colors.textMuted} />
              </TouchableOpacity>
            ))}
          </ScrollView>

          <View style={styles.footer}>
            <Text style={styles.footerTxt}>1PH1 · إدارة الصيدلية</Text>
          </View>
        </SafeAreaView>
      </Animated.View>
    </Modal>
  );
}

function roleLabel(r?: string) {
  return r === 'admin' ? 'مسؤول النظام' : r === 'supplier' ? 'مذخر' : r === 'pharmacy' ? 'صيدلية' : '';
}

const styles = StyleSheet.create({
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(0,0,0,0.45)' },
  sheet: {
    position: 'absolute', top: 0, right: 0, bottom: 0, width: 300,
    backgroundColor: colors.surface,
    shadowColor: '#000', shadowOpacity: 0.15, shadowRadius: 10, shadowOffset: { width: -4, height: 0 }, elevation: 12,
  },
  headerBox: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, padding: 16, borderBottomWidth: 1, borderBottomColor: colors.border },
  avatar: { width: 52, height: 52, borderRadius: 26, backgroundColor: colors.indigo, alignItems: 'center', justifyContent: 'center' },
  userName: { fontSize: 15, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  userSub: { fontSize: 12, color: colors.textSecondary, textAlign: 'right' },
  userRole: { fontSize: 11, color: colors.indigo, textAlign: 'right', marginTop: 2, fontWeight: '700' },
  closeBtn: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.background },
  item: {
    flexDirection: 'row-reverse', alignItems: 'center', gap: 12,
    paddingHorizontal: 18, paddingVertical: 14,
  },
  itemLabel: { flex: 1, fontSize: 15, color: colors.textPrimary, textAlign: 'right', fontWeight: '600' },
  footer: { padding: 14, borderTopWidth: 1, borderTopColor: colors.border, alignItems: 'center' },
  footerTxt: { fontSize: 11, color: colors.textMuted, fontWeight: '600' },
});
