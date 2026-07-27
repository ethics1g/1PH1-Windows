/**
 * External barcode scanner support (USB / Bluetooth HID keyboard emulators)
 * =============================================================================
 * Provides a single global listener that turns rapid-keystroke bursts from an
 * HID barcode scanner into a single onScan callback — WITHOUT adding any UI.
 *
 * Guarantees (per user requirement):
 *   1. Scanner keystrokes are captured GLOBALLY on the screen, no matter which
 *      field is focused. Barcode digits NEVER leak into price/quantity/name or
 *      any other input.
 *   2. Enter and Tab characters sent by the scanner are consumed here — they
 *      cannot trigger button clicks or navigate away.
 *   3. After each successful scan, if the screen has a "target" barcode input
 *      (marked with `data-barcode-input="1"` on web or the hidden HID input on
 *      native), focus is returned to it so the next scan is captured with no
 *      user interaction.
 *
 * Web strategy (delayed-commit pattern):
 *   - We attach `keydown` at document level in the CAPTURE phase so we see
 *     every key before any focused input.
 *   - When a digit arrives and we're NOT already in a burst, we `preventDefault`
 *     immediately and buffer it, then start a 45 ms "decide" window. If a
 *     second key arrives inside that window we lock into burst mode; if not,
 *     the char was a human keystroke and we programmatically restore it into
 *     the originally-focused field (so a lone typed digit is never lost).
 *   - Inside a burst, every subsequent char is preventDefault'd and appended
 *     to the buffer until Enter/Tab arrives, at which point we emit.
 *
 * Native strategy:
 *   - A hidden zero-size `TextInput` is kept auto-focused whenever a screen
 *     is subscribed. Bluetooth HID scanners route keystrokes to it and its
 *     `onSubmitEditing` fires on Enter, calling registered handlers.
 */
import React, {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from 'react';
import { Platform, TextInput, View, StyleSheet } from 'react-native';

// ---------------- CONTEXT ----------------------------------------------

type Handler = (barcode: string) => void;

type ScannerContextValue = {
  register: (h: Handler) => () => void;
  activeCount: number;
};

const ScannerContext = createContext<ScannerContextValue | null>(null);

// Tunables
const HOLD_MS = 45;          // window to decide "burst vs. human" for FIRST char
const BURST_CONT_MS = 65;    // max gap between chars inside a burst
const MIN_BARCODE_LEN = 4;

// ---------------- PROVIDER ---------------------------------------------

export function ExternalScannerProvider({ children }: { children: React.ReactNode }) {
  const handlersRef = useRef<Set<Handler>>(new Set());
  const [activeCount, setActiveCount] = useState(0);
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
    handlersRef.current.forEach((h) => {
      try { h(trimmed); } catch { /* isolate handler errors */ }
    });
    // After emit, focus the designated barcode input on the current screen
    // (if any) so continuous scanning works without touching the screen.
    if (Platform.OS === 'web') {
      const doc: any = (globalThis as any).document;
      const target = doc && doc.querySelector && doc.querySelector('[data-barcode-input="1"]');
      if (target && typeof target.focus === 'function') {
        setTimeout(() => { try { target.focus(); } catch { /* noop */ } }, 30);
      }
    } else {
      setTimeout(() => { try { hiddenInputRef.current?.focus(); } catch { /* noop */ } }, 30);
    }
  }, []);

  // -------- WEB: document-level keydown with delayed-commit ------------
  useEffect(() => {
    if (Platform.OS !== 'web') return;
    if (activeCount === 0) return;      // only intercept while a screen listens

    const doc: any = (globalThis as any).document;
    if (!doc || !doc.addEventListener) return;

    const isEditable = (el: any): boolean => {
      if (!el) return false;
      const tag = (el.tagName || '').toUpperCase();
      if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
      if (tag === 'INPUT') {
        const t = (el.type || 'text').toLowerCase();
        return ['text', 'search', 'number', 'tel', 'url', 'email', 'password'].includes(t);
      }
      return !!el.isContentEditable;
    };
    const isBarcodeTarget = (el: any): boolean =>
      !!(el && el.getAttribute && el.getAttribute('data-barcode-input') === '1');

    // Programmatic value-set that triggers React's onChange
    const restoreToField = (el: any, chars: string) => {
      if (!el || !chars) return;
      try {
        const w: any = globalThis as any;
        const proto = w.HTMLInputElement && w.HTMLInputElement.prototype;
        const setter = proto && Object.getOwnPropertyDescriptor(proto, 'value')?.set;
        const next = (el.value || '') + chars;
        if (setter) setter.call(el, next); else el.value = next;
        el.dispatchEvent(new Event('input', { bubbles: true }));
      } catch { /* best-effort */ }
    };

    let buffer = '';
    let originTarget: any = null;
    let holdTimer: any = null;
    let lastKeyAt = 0;

    const clearHold = () => { if (holdTimer) { clearTimeout(holdTimer); holdTimer = null; } };

    const flush = (asBarcode: boolean) => {
      clearHold();
      const buf = buffer;
      const tgt = originTarget;
      buffer = '';
      originTarget = null;
      if (!buf) return;
      if (asBarcode && buf.length >= MIN_BARCODE_LEN) {
        emit(buf);
      } else if (!asBarcode && tgt) {
        // Not a scanner burst — put char(s) back where they belong so lone
        // human keystrokes are never lost.
        restoreToField(tgt, buf);
      }
    };

    const onKeyDown = (e: any) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const now = Date.now();
      const dt = now - lastKeyAt;
      lastKeyAt = now;

      const key = e.key as string;
      const isChar = typeof key === 'string' && key.length === 1;
      const isTerminator = key === 'Enter' || key === 'Tab';
      const isDigit = isChar && key >= '0' && key <= '9';

      const active = doc.activeElement;
      const onBarcode = isBarcodeTarget(active);
      const onOtherEditable = !onBarcode && isEditable(active);

      // -------- Path A: designated barcode field is focused --------
      // Chars type into it normally. On Enter/Tab we emit its value.
      if (onBarcode) {
        if (isTerminator) {
          e.preventDefault(); e.stopPropagation();
          const v = (active.value || '') as string;
          try {
            const w: any = globalThis as any;
            const proto = w.HTMLInputElement && w.HTMLInputElement.prototype;
            const setter = proto && Object.getOwnPropertyDescriptor(proto, 'value')?.set;
            if (setter) setter.call(active, ''); else active.value = '';
            active.dispatchEvent(new Event('input', { bubbles: true }));
          } catch { /* noop */ }
          emit(v);
        }
        return;
      }

      // -------- Path B: already inside a burst on some other field --------
      if (buffer && dt < BURST_CONT_MS) {
        if (isChar) {
          e.preventDefault(); e.stopPropagation();
          buffer += key;
          clearHold();
          holdTimer = setTimeout(() => flush(true), HOLD_MS + 30);
          return;
        }
        if (isTerminator) {
          e.preventDefault(); e.stopPropagation();
          flush(true);
          return;
        }
        return;
      }

      // -------- Path C: fresh keystroke on a non-barcode input --------
      // We only intercept DIGITS here (barcodes are numeric). Human text
      // typing (letters, Arabic characters) is never touched.
      if (onOtherEditable && isDigit) {
        e.preventDefault(); e.stopPropagation();
        buffer = key;
        originTarget = active;
        clearHold();
        holdTimer = setTimeout(() => flush(false), HOLD_MS);
        return;
      }

      // -------- Path D: fresh keystroke with no editable focus --------
      // Scanner may fire while nothing is focused — still capture it.
      if (!onOtherEditable && isDigit) {
        e.preventDefault(); e.stopPropagation();
        buffer = key;
        originTarget = null;                       // nowhere to restore to
        clearHold();
        holdTimer = setTimeout(() => flush(false), HOLD_MS);
      }
      // Enter/Tab with no buffer → let through (real user Enter).
    };

    doc.addEventListener('keydown', onKeyDown, true);
    return () => {
      doc.removeEventListener('keydown', onKeyDown, true);
      clearHold();
    };
  }, [emit, activeCount]);

  // -------- NATIVE: hidden always-focused input catches HID output ----
  const onNativeSubmit = useCallback((e: any) => {
    const val = (e?.nativeEvent?.text || '') as string;
    if (val && val.length >= MIN_BARCODE_LEN) emit(val);
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
            showSoftInputOnFocus={false}
            onSubmitEditing={onNativeSubmit}
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
 * Subscribe the current screen to external barcode scans. The callback
 * receives the scanned string. Isolated per-screen — mounting/unmounting
 * cleans up automatically.
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
