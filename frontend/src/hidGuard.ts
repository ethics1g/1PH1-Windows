/**
 * HID Scanner Guard for React Native (Android / iOS / Web)
 * =============================================================================
 * Cross-platform guard that prevents USB / Bluetooth HID barcode-scanner
 * output from leaking into any TextInput OTHER than the designated barcode
 * field. Works by observing `onChangeText`, holding fresh single-digit input
 * for a short decision window (HOLD_MS), and reverting the native input via
 * `setNativeProps` the instant a burst is confirmed.
 *
 * Public API:
 *   useHidGuardListener(handler, enabled)   – receive completed barcodes
 *   useHidRefocus(focusFn, enabled)         – auto-return focus after scan
 *   useHidGuardedChange(value, setValue)    – returns {onChangeText,
 *                                             onKeyPress, inputRef} to spread
 *                                             onto every non-barcode TextInput
 *
 * Rules-of-Hooks safe: `useHidGuardedChange` is always called (never behind
 * a conditional). Whether callers apply its handlers to a field is a plain
 * boolean check at render.
 */
import { useCallback, useEffect, useRef } from 'react';
import type { TextInput } from 'react-native';

const HID_BURST_MS = 60;         // max gap between chars inside a scanner burst
const HID_SILENCE_MS = 90;       // idle timeout to flush buffer
const HOLD_MS = 45;              // window to decide "human vs scanner" for FIRST digit
const HID_MIN_LEN = 4;           // minimum barcode length

type Handler = (barcode: string) => void;

// ---- Shared module state (across all guarded fields) --------------------
const handlers = new Set<Handler>();
let hidBuffer = '';
let flushTimer: any = null;
let refocusFn: (() => void) | null = null;

const flush = () => {
  const buf = hidBuffer;
  hidBuffer = '';
  if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
  if (buf.length >= HID_MIN_LEN) {
    handlers.forEach((h) => { try { h(buf); } catch { /* isolate */ } });
    if (refocusFn) {
      try { setTimeout(refocusFn, 30); } catch { /* noop */ }
    }
  }
};

const scheduleFlush = () => {
  if (flushTimer) clearTimeout(flushTimer);
  flushTimer = setTimeout(flush, HID_SILENCE_MS);
};

function feedChars(chars: string) {
  if (!chars) return;
  hidBuffer += chars;
  scheduleFlush();
}

function terminatorReceived() {
  if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
  flush();
}

// ---- Public hooks ------------------------------------------------------

export function useHidGuardListener(handler: Handler, enabled: boolean = true) {
  const ref = useRef(handler);
  useEffect(() => { ref.current = handler; }, [handler]);
  useEffect(() => {
    if (!enabled) return;
    const wrapped: Handler = (code) => { try { ref.current?.(code); } catch { /* noop */ } };
    handlers.add(wrapped);
    return () => { handlers.delete(wrapped); };
  }, [enabled]);
}

export function useHidRefocus(focusFn: () => void, enabled: boolean = true) {
  useEffect(() => {
    if (!enabled) return;
    refocusFn = focusFn;
    return () => { if (refocusFn === focusFn) refocusFn = null; };
  }, [focusFn, enabled]);
}

/**
 * Wrap a TextInput's `onChangeText` with delayed-commit burst detection.
 *
 *   • Fresh single-digit input triggers a HOLD_MS window — the value is
 *     NOT committed to React state yet. If a 2nd digit arrives inside the
 *     window (i.e. the fast rhythm of a scanner), both digits are streamed
 *     into the shared HID buffer and the native input is FORCIBLY reset to
 *     the previous value via `setNativeProps`. Nothing leaks into state.
 *   • If the HOLD window expires with only one digit, it was a human key —
 *     the digit is committed normally.
 *   • Burst continuation (`hidBuffer` already non-empty) drops every
 *     subsequent digit immediately.
 *   • Non-digit chars (letters, Arabic) are always committed → normal
 *     human typing is untouched.
 */
export function useHidGuardedChange(
  value: string,
  setValue: (v: string) => void,
) {
  const inputRef = useRef<TextInput | null>(null);
  const valueRef = useRef<string>(value);
  const lastLocalKeyAt = useRef<number>(0);
  const heldRef = useRef<{ next: string; timer: any } | null>(null);

  useEffect(() => { valueRef.current = value; }, [value]);

  // Reset the native input's text WITHOUT going through React state.
  // This is the escape-hatch that lets us "un-type" a scanner burst on
  // Android/iOS even when we deliberately skip setValue.
  const revertNative = useCallback((to: string) => {
    try { (inputRef.current as any)?.setNativeProps?.({ text: to }); }
    catch { /* older RN or web — soft revert via next render */ }
  }, []);

  const commitHeld = useCallback(() => {
    const h = heldRef.current;
    if (!h) return;
    clearTimeout(h.timer);
    heldRef.current = null;
    valueRef.current = h.next;
    setValue(h.next);
  }, [setValue]);

  const onChangeText = useCallback((next: string) => {
    const prev = valueRef.current;
    const now = Date.now();
    const dt = now - lastLocalKeyAt.current;
    lastLocalKeyAt.current = now;

    if (next.length > prev.length) {
      const added = next.substring(prev.length);
      const allDigits = added.length > 0 && /^\d+$/.test(added);

      // -------- Case A: burst continuation ----------------------------
      // The shared HID buffer already has content → we're mid-burst. Every
      // additional digit is diverted and the native input is reset.
      if (allDigits && hidBuffer.length > 0) {
        feedChars(added);
        revertNative(prev);
        return;
      }

      // -------- Case B: we're currently holding a pending digit -------
      if (heldRef.current) {
        clearTimeout(heldRef.current.timer);
        const heldNext = heldRef.current.next;
        const heldAdded = heldNext.substring(prev.length);
        heldRef.current = null;

        if (allDigits && dt < HID_BURST_MS) {
          // Burst confirmed by fast second digit → stream both, revert native
          feedChars(heldAdded + added);
          revertNative(prev);
          return;
        }
        // Slow second key or non-digit → commit everything (`next` already
        // contains both the held char and the new one)
        valueRef.current = next;
        setValue(next);
        return;
      }

      // -------- Case C: fresh single digit → HOLD ---------------------
      if (allDigits && added.length === 1) {
        heldRef.current = {
          next,
          timer: setTimeout(commitHeld, HOLD_MS),
        };
        return;
      }

      // -------- Case D: multi-char paste or non-digit → commit --------
      valueRef.current = next;
      setValue(next);
      return;
    }

    // -------- Length shrunk (delete/backspace) → commit -------------
    if (heldRef.current) {
      clearTimeout(heldRef.current.timer);
      heldRef.current = null;
    }
    valueRef.current = next;
    setValue(next);
  }, [setValue, commitHeld, revertNative]);

  const onKeyPress = useCallback((e: any) => {
    const key = e?.nativeEvent?.key;
    if (key === 'Enter' || key === 'Tab') {
      // Cancel any pending human-hold; the terminator arrived so this
      // was a scanner burst.
      if (heldRef.current) {
        clearTimeout(heldRef.current.timer);
        heldRef.current = null;
      }
      if (hidBuffer.length >= HID_MIN_LEN) terminatorReceived();
    }
  }, []);

  return { onChangeText, onKeyPress, inputRef } as const;
}

// Direct internal handle (used by the web document-level listener)
export const _hidInternal = { feedChars, terminatorReceived, flush };
