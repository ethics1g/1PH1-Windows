import React, { useRef, useState, useCallback, useEffect } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, Image, Animated, Platform,
  ActivityIndicator, BackHandler,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useRouter, useFocusEffect } from 'expo-router';
import * as Haptics from 'expo-haptics';
import { colors } from '../../src/theme';
import { apiFetch, useAuth } from '../../src/auth';
import { markAccountingUnlocked, isAccountingUnlocked } from '../../src/accountingLock';

const MAX_LEN = 12;

export default function AccountingUnlock() {
  const router = useRouter();
  const { token } = useAuth();
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const shakeAnim = useRef(new Animated.Value(0)).current;

  // If somehow the user reaches this screen while already unlocked,
  // just forward them into /accounting immediately.
  useFocusEffect(useCallback(() => {
    if (isAccountingUnlocked()) {
      router.replace('/accounting' as any);
    }
    // Reset UI state whenever screen re-focuses
    setCode('');
    setError('');
  }, [router]));

  // Android hardware back → go home instead of loop-back to /accounting
  useEffect(() => {
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      router.replace('/home' as any);
      return true;
    });
    return () => sub.remove();
  }, [router]);

  const shake = useCallback(() => {
    Animated.sequence([
      Animated.timing(shakeAnim, { toValue: 12, duration: 45, useNativeDriver: true }),
      Animated.timing(shakeAnim, { toValue: -12, duration: 45, useNativeDriver: true }),
      Animated.timing(shakeAnim, { toValue: 10, duration: 45, useNativeDriver: true }),
      Animated.timing(shakeAnim, { toValue: -10, duration: 45, useNativeDriver: true }),
      Animated.timing(shakeAnim, { toValue: 6, duration: 45, useNativeDriver: true }),
      Animated.timing(shakeAnim, { toValue: 0, duration: 45, useNativeDriver: true }),
    ]).start();
  }, [shakeAnim]);

  const submit = useCallback(async (value: string) => {
    if (!value || busy) return;
    setBusy(true);
    setError('');
    try {
      await apiFetch('/auth/verify-password', {
        method: 'POST',
        body: JSON.stringify({ password: value }),
      }, token);
      // Success
      if (Platform.OS !== 'web') {
        try { Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success); } catch {}
      }
      markAccountingUnlocked();
      router.replace('/accounting' as any);
    } catch (e) {
      // 401 or network error → same generic message, no leaks
      if (Platform.OS !== 'web') {
        try { Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error); } catch {}
      }
      shake();
      setError('رمز غير صحيح');
      setCode('');
    } finally {
      setBusy(false);
    }
  }, [busy, router, shake, token]);

  const onPressKey = useCallback((k: string) => {
    if (busy) return;
    setError('');
    if (Platform.OS !== 'web') {
      try { Haptics.selectionAsync(); } catch {}
    }
    setCode((prev) => {
      if (prev.length >= MAX_LEN) return prev;
      return prev + k;
    });
  }, [busy]);

  const onBackspace = useCallback(() => {
    if (busy) return;
    setError('');
    if (Platform.OS !== 'web') {
      try { Haptics.selectionAsync(); } catch {}
    }
    setCode((prev) => prev.slice(0, -1));
  }, [busy]);

  const onSubmit = useCallback(() => {
    if (!code || busy) return;
    submit(code);
  }, [code, submit, busy]);

  const keys: (string | { icon: string; action: 'back' | 'submit' })[] = [
    '1', '2', '3',
    '4', '5', '6',
    '7', '8', '9',
    { icon: 'backspace-outline', action: 'back' },
    '0',
    { icon: 'checkmark-outline', action: 'submit' },
  ];

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'bottom', 'left', 'right']}>
      <View style={styles.content}>
        <View style={styles.logoWrap}>
          <Image
            source={require('../../assets/branding/logo.png')}
            style={styles.logo}
            resizeMode="contain"
          />
        </View>
        <Text style={styles.title}>أدخل رمز الأمان</Text>
        <Text style={styles.subtitle}>لفتح قسم الحسابات</Text>

        <Animated.View
          testID="pin-box"
          style={[
            styles.pinBox,
            { transform: [{ translateX: shakeAnim }] },
            !!error && styles.pinBoxError,
          ]}
        >
          {code.length === 0 ? (
            <Text style={styles.pinPlaceholder}>••••</Text>
          ) : (
            <View style={styles.pinDotsWrap}>
              {Array.from({ length: code.length }).map((_, i) => (
                <View key={i} style={[styles.dot, !!error && styles.dotError]} />
              ))}
            </View>
          )}
        </Animated.View>

        <View style={styles.errorSlot}>
          {!!error && (
            <Text testID="pin-error" style={styles.errorTxt}>{error}</Text>
          )}
        </View>

        <View style={styles.keypad}>
          {keys.map((k, idx) => {
            if (typeof k === 'string') {
              return (
                <TouchableOpacity
                  key={idx}
                  testID={`key-${k}`}
                  style={styles.key}
                  onPress={() => onPressKey(k)}
                  activeOpacity={0.6}
                  disabled={busy}
                >
                  <Text style={styles.keyTxt}>{k}</Text>
                </TouchableOpacity>
              );
            }
            const isSubmit = k.action === 'submit';
            return (
              <TouchableOpacity
                key={idx}
                testID={`key-${k.action}`}
                style={[styles.key, isSubmit ? styles.keySubmit : styles.keyBack]}
                onPress={isSubmit ? onSubmit : onBackspace}
                activeOpacity={0.7}
                disabled={busy || (isSubmit && code.length === 0)}
              >
                {busy && isSubmit ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <Ionicons
                    name={k.icon as any}
                    size={26}
                    color={isSubmit ? '#fff' : colors.textPrimary}
                  />
                )}
              </TouchableOpacity>
            );
          })}
        </View>

        <TouchableOpacity
          testID="btn-cancel"
          style={styles.cancel}
          onPress={() => router.replace('/home' as any)}
        >
          <Text style={styles.cancelTxt}>إلغاء</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#f8fafc' },
  content: {
    flex: 1,
    padding: 20,
    alignItems: 'center',
    justifyContent: 'flex-start',
    paddingTop: 40,
  },
  logoWrap: {
    width: 96, height: 96, borderRadius: 24,
    backgroundColor: '#fff',
    alignItems: 'center', justifyContent: 'center',
    shadowColor: '#000', shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.08, shadowRadius: 12, elevation: 4,
    marginBottom: 20,
  },
  logo: { width: 72, height: 72 },
  title: {
    fontSize: 22, fontWeight: '900', color: colors.textPrimary,
    marginBottom: 4,
  },
  subtitle: {
    fontSize: 13, color: colors.textSecondary, marginBottom: 24,
  },
  pinBox: {
    width: '80%',
    minHeight: 60,
    borderWidth: 2,
    borderColor: colors.border,
    borderRadius: 16,
    backgroundColor: colors.surface,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 16,
    marginBottom: 6,
  },
  pinBoxError: {
    borderColor: colors.error,
    backgroundColor: '#fef2f2',
  },
  pinPlaceholder: {
    fontSize: 28, color: colors.textMuted, letterSpacing: 8,
    fontWeight: '600',
  },
  pinDotsWrap: {
    flexDirection: 'row',
    gap: 12,
    alignItems: 'center',
    minHeight: 20,
  },
  dot: {
    width: 14, height: 14, borderRadius: 7, backgroundColor: colors.primary,
  },
  dotError: {
    backgroundColor: colors.error,
  },
  errorSlot: { minHeight: 20, marginBottom: 8 },
  errorTxt: {
    color: colors.error, fontSize: 13, fontWeight: '700',
  },
  keypad: {
    flexDirection: 'row-reverse',
    flexWrap: 'wrap',
    justifyContent: 'center',
    gap: 12,
    width: '100%',
    maxWidth: 360,
    marginTop: 8,
  },
  key: {
    width: '30%',
    aspectRatio: 1.4,
    borderRadius: 20,
    backgroundColor: colors.surface,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: colors.border,
    shadowColor: '#000', shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.04, shadowRadius: 4, elevation: 1,
  },
  keyTxt: {
    fontSize: 30, fontWeight: '800', color: colors.textPrimary,
  },
  keyBack: {
    backgroundColor: '#f1f5f9',
  },
  keySubmit: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  cancel: {
    marginTop: 24, paddingVertical: 10, paddingHorizontal: 20,
  },
  cancelTxt: {
    color: colors.textSecondary, fontSize: 14, fontWeight: '700',
  },
});
