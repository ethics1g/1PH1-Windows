/**
 * HID Scanner Guard for React Native (Android / iOS)
 * =============================================================================
 * On native there is no equivalent of the web's document-level keydown
 * listener — USB/Bluetooth HID barcode scanners emit keys directly into
 * whichever TextInput is focused. This module implements the "guard"
 * pattern that fixes it *without adding any new UI*:
 *
 *   1. Every TextInput in Sell/Buy that is NOT the designated barcode field
 *      is wrapped with `useHidGuardedChange`. The hook watches `onChangeText`
 *      and measures inter-keystroke timing. If it detects a burst of DIGITS
 *      arriving faster than a human could type (< HID_BURST_MS between
 *      chars), it:
 *         a) IMMEDIATELY reverts the field to its previous value so nothing
 *            leaks visually (the setter is called with the prior string).
 *         b) Streams the digit(s) into a shared HID buffer.
 *   2. The shared buffer flushes to registered handlers when either:
 *         a) An idle period of HID_SILENCE_MS elapses (scanner finished but
 *            didn't send Enter — some models are configured this way), OR
 *         b) The scanner sends Enter/Tab (detected via `onKeyPress` on the
 *            same wrapped input).
 *   3. Enter/Tab from the scanner is intercepted by the wrapped input's
 *      `onKeyPress` handler — the wrapper returns focus to the barcode
 *      field if one is registered, so subsequent scans go to it directly.
 *
 * This works on:
 *   - Android devices and Android emulators with any USB HID scanner
 *   - iOS devices with Bluetooth HID scanners
 *   - Web (in addition to the existing document.keydown interception)
 */
import { useCallback, useEffect, useRef } from 'react';

const HID_BURST_MS = 60;         // max gap between chars inside a scanner burst
const HID_SILENCE_MS = 90;       // idle timeout to flush buffer
const HID_MIN_LEN = 4;           // minimum barcode length

type Handler = (barcode: string) => void;

// ---- Global module state (shared across all guarded fields) -----------
const handlers = new Set<Handler>();
let hidBuffer = '';
let lastKeyAt = 0;
let flushTimer: any = null;
let refocusFn: (() => void) | null = null;

// Clear + flush helpers
const flush = () => {
  const buf = hidBuffer;
  hidBuffer = '';
  if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
  if (buf.length >= HID_MIN_LEN) {
    handlers.forEach((h) => {
      try { h(buf); } catch { /* isolate handler errors */ }
    });
    // After a valid scan, hand focus back to the designated barcode input
    // so the operator can scan the next item without touching the screen.
    if (refocusFn) {
      try { setTimeout(refocusFn, 30); } catch { /* noop */ }
    }
  }
};

const scheduleFlush = () => {
  if (flushTimer) clearTimeout(flushTimer);
  flushTimer = setTimeout(flush, HID_SILENCE_MS);
};

/**
 * Register a global handler that receives the completed barcode.
 * Only ONE handler is typically active per screen (Sell or Buy).
 */
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

/**
 * Register a callback that returns focus to the designated barcode input
 * after each successful scan.
 */
export function useHidRefocus(focusFn: () => void, enabled: boolean = true) {
  useEffect(() => {
    if (!enabled) return;
    refocusFn = focusFn;
    return () => { if (refocusFn === focusFn) refocusFn = null; };
  }, [focusFn, enabled]);
}

/**
 * Feed characters into the HID buffer manually (used by wrapped inputs
 * when a burst is detected).
 */
function feedChars(chars: string) {
  if (!chars) return;
  hidBuffer += chars;
  scheduleFlush();
}

/**
 * Terminator (Enter/Tab) — flush immediately.
 */
function terminatorReceived() {
  if (flushTimer) { clearTimeout(flushTimer); flushTimer = null; }
  flush();
}

/**
 * Hook: wraps an input's `onChangeText` so that scanner-speed digit bursts
 * are diverted to the HID handler instead of remaining in the field.
 *
 * Returns { onChangeText, onKeyPress } to spread onto the TextInput.
 *
 * Use for EVERY TextInput in Sell/Buy EXCEPT the designated barcode field
 * itself.
 */
export function useHidGuardedChange(
  value: string,
  setValue: (v: string) => void,
) {
  // Keep a mutable snapshot so we can revert to the previous value quickly.
  const valueRef = useRef<string>(value);
  useEffect(() => { valueRef.current = value; }, [value]);

  const lastLocalKeyAt = useRef<number>(0);

  const onChangeText = useCallback((next: string) => {
    const prev = valueRef.current;
    const now = Date.now();

    // Compute the delta (chars added at the end — RN inputs on Android almost
    // always append; we're not doing complex mid-string edits from HID).
    if (next.length > prev.length) {
      const added = next.substring(prev.length);
      const allDigits = added.length > 0 && /^\d+$/.test(added);
      const dtLocal = now - lastLocalKeyAt.current;
      const dtGlobal = now - lastKeyAt;

      // Burst detection: fast timing globally + added chars are digits.
      // dtGlobal accounts for the case where the burst started on another
      // input and moved here mid-way (unlikely but safe).
      const isBurst =
        (dtLocal < HID_BURST_MS || dtGlobal < HID_BURST_MS || hidBuffer.length > 0)
        && allDigits;

      lastLocalKeyAt.current = now;
      lastKeyAt = now;

      if (isBurst) {
        // Revert — do NOT call setValue(next). The visible field stays at prev.
        feedChars(added);
        return;
      }
    } else {
      lastLocalKeyAt.current = now;
      lastKeyAt = now;
    }

    // Otherwise: normal typing, let the field update.
    valueRef.current = next;
    setValue(next);
  }, [setValue]);

  const onKeyPress = useCallback((e: any) => {
    const key = e?.nativeEvent?.key;
    if (key === 'Enter' || key === 'Tab' || key === 'Backspace') {
      // Only Enter/Tab may terminate a scanner burst. If we have a pending
      // buffer, flush it as a barcode.
      if ((key === 'Enter' || key === 'Tab') && hidBuffer.length >= HID_MIN_LEN) {
        // Prevent the Enter from also submitting the form — on RN there's
        // no preventDefault, but consuming here + returning focus to the
        // barcode field neutralises typical follow-on behavior.
        terminatorReceived();
      }
    }
  }, []);

  return { onChangeText, onKeyPress } as const;
}

/**
 * Direct API — mostly for advanced integrations (e.g., the web
 * document-level listener that also feeds this buffer). Not needed for
 * the guarded-input pattern above.
 */
export const _hidInternal = {
  feedChars,
  terminatorReceived,
  flush,
};
