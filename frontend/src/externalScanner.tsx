/**
 * Cross-platform external barcode scanner support.
 *
 * Detects USB/Bluetooth HID scanners that behave as keyboard emulators
 * (the vast majority of barcode readers, including Zebra, Honeywell,
 * Datalogic in their default HID mode). Also works on desktop / web /
 * emulator because it listens to `keydown` events on the web build,
 * and uses a hidden auto-focused TextInput on native platforms.
 *
 * Usage from any screen:
 *
 *   useExternalScanner((barcode) => {
 *     // handle scanned barcode
 *   }, { enabled: !isBusy });
 *
 * Design notes:
 *  - We treat a burst of characters (< 60ms between keystrokes) followed
 *    by Enter as a scanner input — humans typing on a physical keyboard
 *    are slower than that.
 *  - Non-invasive: existing camera scanning (MedicineScanner) keeps
 *    working; this listener only reads events, never blocks them.
 *  - Extensible: future support for Zebra DataWedge / Honeywell
 *    Intents / SDK-based scanners can be added as additional strategies
 *    without changing consumers.
 */
import React, {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from 'react';
import { Platform, TextInput, View, StyleSheet } from 'react-native';

// ---------------- CONTEXT ----------------------------------------------

type Handler = (barcode: string) => void;

type ScannerContextValue = {
  /** Register a handler. Returns an unregister function. */
  register: (h: Handler) => () => void;
  /** How many active listeners — informational. */
  activeCount: number;
};

const ScannerContext = createContext<ScannerContextValue | null>(null);

// ---------------- PROVIDER ---------------------------------------------

const BURST_MS = 60;          // max ms between "scanner" keystrokes
const MIN_BARCODE_LEN = 4;

export function ExternalScannerProvider({ children }: { children: React.ReactNode }) {
  const handlersRef = useRef<Set<Handler>>(new Set());
  const [activeCount, setActiveCount] = useState(0);
  const bufferRef = useRef<string>('');
  const lastKeyAtRef = useRef<number>(0);
  const hiddenInputRef = useRef<TextInput>(null);

  const register = useCallback((h: Handler) => {
    handlersRef.current.add(h);
    setActiveCount(handlersRef.current.size);
    return () => {
      handlersRef.current.delete(h);
      setActiveCount(handlersRef.current.size);
    };
  }, []);

  const emit = useCallback((code: string) => {
    const trimmed = (code || '').trim();
    if (trimmed.length < MIN_BARCODE_LEN) return;
    // Fan out to all currently-registered handlers
    handlersRef.current.forEach((h) => {
      try { h(trimmed); } catch { /* isolate handler errors */ }
    });
  }, []);

  // ---- WEB: listen to window keydown events (fires anywhere on page) ----
  useEffect(() => {
    if (Platform.OS !== 'web') return;
    const handleKey = (e: any) => {
      // Skip if a form input is focused AND has real user typing
      // (we only want physical scanner traffic). We detect by burst
      // timing regardless of focus.
      const now = Date.now();
      const dt = now - lastKeyAtRef.current;
      lastKeyAtRef.current = now;
      if (e.key === 'Enter' || e.key === '\n') {
        const code = bufferRef.current;
        bufferRef.current = '';
        if (code) emit(code);
        return;
      }
      if (dt > BURST_MS && bufferRef.current.length > 0) {
        // Slow typing — reset buffer (this is a human)
        bufferRef.current = '';
      }
      if (typeof e.key === 'string' && e.key.length === 1) {
        bufferRef.current += e.key;
      }
    };
    // Cast to any for the RN-Web `document` polyfill
    const doc: any = (globalThis as any).document;
    if (!doc || !doc.addEventListener) return;
    doc.addEventListener('keydown', handleKey);
    return () => { doc.removeEventListener('keydown', handleKey); };
  }, [emit]);

  // ---- NATIVE: hidden always-focused TextInput captures HID output ----
  // HID Bluetooth scanners on iOS/Android post keystrokes to the focused
  // input. We keep a 0×0 offscreen input focused; each scan submits.
  const onSubmit = useCallback((e: any) => {
    const val = (e?.nativeEvent?.text || '') as string;
    if (val && val.length >= MIN_BARCODE_LEN) emit(val);
    // Re-focus for next scan
    hiddenInputRef.current?.clear();
    setTimeout(() => hiddenInputRef.current?.focus(), 30);
  }, [emit]);

  const value = useMemo<ScannerContextValue>(() => ({ register, activeCount }),
    [register, activeCount]);

  return (
    <ScannerContext.Provider value={value}>
      {children}
      {Platform.OS !== 'web' && (
        <View pointerEvents="none" style={styles.hiddenWrap} accessible={false}>
          <TextInput
            ref={hiddenInputRef}
            testID="hid-scanner-buffer"
            style={styles.hiddenInput}
            autoFocus={false}
            blurOnSubmit={false}
            caretHidden
            showSoftInputOnFocus={false}   // prevent virtual keyboard
            onSubmitEditing={onSubmit}
            // Only auto-focus when at least one screen is listening
            {...(activeCount > 0 ? { autoFocus: true } : {})}
          />
        </View>
      )}
    </ScannerContext.Provider>
  );
}

// ---------------- HOOK -------------------------------------------------

type Options = { enabled?: boolean };

/**
 * Subscribe the current screen to external barcode scans.
 * The callback receives the scanned string. Fully isolated per-screen —
 * mounting/unmounting cleans up automatically.
 */
export function useExternalScanner(cb: Handler, opts: Options = {}) {
  const ctx = useContext(ScannerContext);
  const cbRef = useRef(cb);
  useEffect(() => { cbRef.current = cb; }, [cb]);

  useEffect(() => {
    if (!ctx) return;
    if (opts.enabled === false) return;
    const off = ctx.register((code) => {
      try { cbRef.current?.(code); } catch { /* ignore */ }
    });
    return off;
  }, [ctx, opts.enabled]);
}

const styles = StyleSheet.create({
  hiddenWrap: {
    position: 'absolute', width: 0, height: 0, opacity: 0,
    overflow: 'hidden', top: -1000, left: -1000,
  },
  hiddenInput: { width: 0, height: 0, opacity: 0 },
});
