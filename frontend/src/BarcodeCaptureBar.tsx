/**
 * BarcodeCaptureBar
 * =============================================================================
 * A single visible input that seamlessly captures barcode data from BOTH:
 *   1. The device camera (opens a modal on tap of the camera icon).
 *   2. External USB / Bluetooth HID barcode scanners (keyboard-emulator mode).
 *
 * Design goals (per user requirement):
 *   • Any burst of characters coming from an HID scanner is routed into THIS
 *     field only — never leaks into price/quantity/name inputs regardless of
 *     which field is currently focused.
 *   • Enter and Tab characters sent by the scanner are consumed by the field
 *     itself — they NEVER trigger button clicks or navigate away from the
 *     screen. After a successful scan the field auto-refocuses so the next
 *     scan is captured without any interaction.
 *   • The visible UI does NOT change: it's the same field the app already had,
 *     just wired to be reliable.
 *
 * Detection strategy (web):
 *   Scanner bursts arrive at < 60 ms between keystrokes. Humans type slower.
 *   We attach a document-level keydown listener at the CAPTURE phase; when
 *   we detect burst timing we:
 *     – preventDefault + stopPropagation so the char doesn't type into the
 *       currently-focused input.
 *     – Buffer the char and echo it into the barcode field's state.
 *     – On Enter/Tab we submit the buffer and refocus the barcode field.
 *
 * Native (iOS/Android):
 *   Bluetooth HID scanners on native OSes route keystrokes to whichever
 *   TextInput is focused. We keep this field auto-focused as much as
 *   possible, use blurOnSubmit=false so Enter doesn't dismiss the keyboard,
 *   and refocus after every scan.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity, Platform,
  ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { colors } from './theme';

type Props = {
  /** Called with a validated barcode string once the scanner finishes a scan
   *  (either camera returns a code or HID scanner sends Enter). */
  onScan: (barcode: string) => void | Promise<void>;
  /** Opens the camera modal (tap of the camera icon). */
  onOpenCamera?: () => void;
  /** Optional starting value — useful for the Buy form where the barcode is
   *  also editable manually and persisted with the medicine. */
  value?: string;
  onChangeText?: (v: string) => void;
  /** Disable interaction while a network request is in flight. */
  disabled?: boolean;
  /** Field label shown above the input. */
  label?: string;
  placeholder?: string;
  /** When true, refocus this field automatically after every scan and while
   *  the screen is idle. Default: true. Set to false if you want to keep
   *  focus on another field (e.g., inside a modal). */
  autoFocusEnabled?: boolean;
  testID?: string;
};

const BURST_MS = 60;
const MIN_LEN = 4;

export default function BarcodeCaptureBar({
  onScan, onOpenCamera, value, onChangeText,
  disabled = false, label = 'الباركود',
  placeholder = 'امسح بقارئ الباركود أو اضغط الكاميرا',
  autoFocusEnabled = true,
  testID = 'barcode-capture',
}: Props) {
  const inputRef = useRef<TextInput>(null);
  const bufferRef = useRef<string>('');
  const lastKeyAtRef = useRef<number>(0);
  const inBurstRef = useRef<boolean>(false);
  const [internal, setInternal] = useState<string>(value || '');
  const [busy, setBusy] = useState(false);

  // Keep controlled/uncontrolled modes in sync
  useEffect(() => {
    if (value !== undefined && value !== internal) setInternal(value);
  }, [value]);   // eslint-disable-line react-hooks/exhaustive-deps

  const setVal = useCallback((v: string) => {
    setInternal(v);
    onChangeText?.(v);
  }, [onChangeText]);

  // ------- Focus management -------------------------------------------
  const focusSelf = useCallback(() => {
    // Small delay lets modals/alerts finish closing before we grab focus.
    setTimeout(() => {
      try { inputRef.current?.focus(); } catch { /* noop */ }
    }, 30);
  }, []);

  useEffect(() => {
    if (autoFocusEnabled) focusSelf();
  }, [autoFocusEnabled, focusSelf]);

  // ------- Submit -----------------------------------------------------
  const submit = useCallback(async (raw: string) => {
    const code = (raw || '').trim();
    if (code.length < MIN_LEN) return;
    setBusy(true);
    try {
      await onScan(code);
    } catch { /* upstream handles */ }
    finally {
      setBusy(false);
      setVal('');
      bufferRef.current = '';
      if (autoFocusEnabled) focusSelf();
    }
  }, [onScan, setVal, focusSelf, autoFocusEnabled]);

  // ------- WEB: intercept keydown at capture phase --------------------
  // Redirects scanner-speed keystrokes into this field even when another
  // input (like price or quantity) is focused.
  useEffect(() => {
    if (Platform.OS !== 'web') return;
    if (!autoFocusEnabled) return;

    const doc: any = (globalThis as any).document;
    if (!doc || !doc.addEventListener) return;

    const isEditableTarget = (el: any): boolean => {
      if (!el) return false;
      const tag = (el.tagName || '').toUpperCase();
      if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
      if (tag === 'INPUT') {
        const type = (el.type || 'text').toLowerCase();
        // Only care about typeable inputs
        return ['text', 'search', 'number', 'tel', 'url', 'email', 'password'].includes(type);
      }
      if (el.isContentEditable) return true;
      return false;
    };

    const isOurField = (el: any): boolean => {
      if (!el) return false;
      // The RN TextInput on web renders as <input data-barcode-input="1">
      return el.getAttribute && el.getAttribute('data-barcode-input') === '1';
    };

    const onKeyDown = (e: any) => {
      // Ignore navigation/modifier keys entirely
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const now = Date.now();
      const dt = now - lastKeyAtRef.current;
      lastKeyAtRef.current = now;

      const active = doc.activeElement;
      const onOurField = isOurField(active);
      const onEditable = isEditableTarget(active) && !onOurField;

      const key = e.key as string;
      const isTerminator = key === 'Enter' || key === 'Tab';
      const isChar = typeof key === 'string' && key.length === 1;

      // ---- 1) If already in a burst → keep redirecting to our field ----
      if (inBurstRef.current) {
        if (isChar) {
          e.preventDefault(); e.stopPropagation();
          bufferRef.current += key;
          setVal(bufferRef.current);
          return;
        }
        if (isTerminator) {
          e.preventDefault(); e.stopPropagation();
          const code = bufferRef.current;
          inBurstRef.current = false;
          bufferRef.current = '';
          submit(code);
          return;
        }
        return;
      }

      // ---- 2) Detect NEW scanner burst (fast dt + we're not the one typing) ----
      // A burst starts when either: (a) our field IS focused and characters
      // arrive fast, or (b) another editable field is focused but chars
      // arrive at scanner speed (leak scenario the user reported).
      const looksLikeBurst = dt < BURST_MS && isChar;

      if (looksLikeBurst && !onOurField && onEditable) {
        // 🚨 SCANNER BURST leaking into another field. Redirect.
        e.preventDefault(); e.stopPropagation();
        inBurstRef.current = true;
        bufferRef.current += key;
        setVal(bufferRef.current);
        focusSelf();
        return;
      }

      // ---- 3) If our field is focused and Enter arrives → submit ------
      if (onOurField && isTerminator) {
        e.preventDefault(); e.stopPropagation();
        const code = (active.value ?? internal) as string;
        bufferRef.current = '';
        inBurstRef.current = false;
        submit(code);
        return;
      }

      // ---- 4) Track burst state even without leak, so subsequent Enter ----
      // arrives with the buffer intact when the user is on our field.
      if (onOurField && isChar) {
        if (dt < BURST_MS) {
          // Scanner-speed on our field. No preventDefault needed since the
          // char will type into our field naturally.
          bufferRef.current += key;
        } else {
          bufferRef.current = key;
        }
      }
    };

    doc.addEventListener('keydown', onKeyDown, true); // capture=true
    return () => { doc.removeEventListener('keydown', onKeyDown, true); };
  }, [submit, focusSelf, setVal, autoFocusEnabled, internal]);

  // ------- Native: onSubmitEditing fires on Enter from HID scanner ---
  const onSubmitEditing = useCallback((e: any) => {
    const v = (e?.nativeEvent?.text ?? internal) as string;
    submit(v);
  }, [submit, internal]);

  // Attach data-barcode-input="1" attribute on web so document keydown can
  // recognize our field. We use dataSet (react-native-web maps to data-*).
  const webA11yProps = Platform.OS === 'web'
    ? ({ dataSet: { barcodeInput: '1' } } as any)
    : {};

  return (
    <View style={styles.wrap}>
      {label ? <Text style={styles.label}>{label}</Text> : null}
      <View style={styles.row}>
        {onOpenCamera ? (
          <TouchableOpacity
            testID={`${testID}-camera`}
            style={styles.camBtn}
            onPress={() => { setVal(''); bufferRef.current = ''; onOpenCamera(); }}
            disabled={disabled || busy}
          >
            <Ionicons name="scan" size={22} color="#fff" />
          </TouchableOpacity>
        ) : null}
        <TextInput
          ref={inputRef}
          testID={testID}
          style={styles.input}
          value={internal}
          onChangeText={setVal}
          onSubmitEditing={onSubmitEditing}
          placeholder={placeholder}
          placeholderTextColor={colors.textMuted}
          textAlign="right"
          autoCapitalize="none"
          autoCorrect={false}
          autoFocus={autoFocusEnabled}
          blurOnSubmit={false}
          returnKeyType="send"
          editable={!disabled && !busy}
          keyboardType="default"
          {...webA11yProps}
        />
        {busy ? (
          <View style={styles.spinner}><ActivityIndicator color={colors.primary} size="small" /></View>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { marginBottom: 12 },
  label: { fontSize: 13, color: colors.textSecondary, marginBottom: 6, textAlign: 'right', fontWeight: '700' },
  row: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8 },
  input: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 16,
    color: colors.textPrimary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  camBtn: {
    width: 46, height: 46, borderRadius: 12,
    backgroundColor: colors.secondaryDark,
    alignItems: 'center', justifyContent: 'center',
  },
  spinner: { width: 24, alignItems: 'center' },
});
