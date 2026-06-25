// Flexible expiry-date parser and normalizer.
//
// Accepts the following common Arabic/English user inputs and normalizes them
// to the canonical "YYYY-MM-DD" string the backend stores:
//   2027-04-01
//   2027-4-1
//   2027/04/01
//   2027/4/1
//   01-04-2027   (day-month-year)
//   1-4-2027
//   01/04/2027
//   1/4/2027
//   2027-04        (year-month only — defaults to day 01)
//   2027/4
//
// Rules:
//   - Separator may be "-", "/", "." or "\".
//   - Leading zeros are NOT required.
//   - 4-digit group identifies the year side.
//   - If neither group is 4 digits, "YY" two-digit years are interpreted as 2000+YY.
//   - Returns null when input is empty / unparseable, throws RangeError when
//     digits parse but month/day are out of range (so callers can show a clear
//     "month 13 / day 32" error instead of silently accepting a junk value).

export type NormalizeResult =
  | { ok: true; value: string; date: Date }
  | { ok: false; error: string };

const SEP = /[-/.\\]/;

function pad2(n: number): string {
  return n < 10 ? `0${n}` : `${n}`;
}

function validParts(y: number, m: number, d: number): boolean {
  if (y < 1900 || y > 2100) return false;
  if (m < 1 || m > 12) return false;
  if (d < 1 || d > 31) return false;
  // Real calendar validation
  const dt = new Date(Date.UTC(y, m - 1, d));
  return (
    dt.getUTCFullYear() === y &&
    dt.getUTCMonth() === m - 1 &&
    dt.getUTCDate() === d
  );
}

/**
 * Parses a flexible user-entered date string and returns a normalized result.
 * Never throws; returns { ok: false, error } for any failure.
 */
export function normalizeExpiryDate(raw: string): NormalizeResult {
  if (raw === null || raw === undefined) return { ok: false, error: 'التاريخ مطلوب' };
  // Convert Arabic-Indic digits (٠-٩) and Eastern-Arabic-Indic (۰-۹) to ASCII
  const asciiDigits = raw
    .replace(/[\u0660-\u0669]/g, (d) => String(d.charCodeAt(0) - 0x0660))
    .replace(/[\u06F0-\u06F9]/g, (d) => String(d.charCodeAt(0) - 0x06F0))
    .trim();
  if (!asciiDigits) return { ok: false, error: 'التاريخ مطلوب' };

  // Strip surrounding whitespace and accept either spaces or our separators
  const parts = asciiDigits.split(SEP).filter((p) => p !== '');
  if (parts.length < 2 || parts.length > 3) {
    return { ok: false, error: 'صيغة التاريخ غير مفهومة. مثال: 2027-04-01 أو 1/4/2027' };
  }
  if (!parts.every((p) => /^\d+$/.test(p))) {
    return { ok: false, error: 'يجب أن يحتوي التاريخ على أرقام فقط' };
  }

  let y: number, m: number, d: number;

  // Identify the year position: first or last group with 4 digits.
  if (parts[0].length === 4) {
    // YYYY-M-D  (or YYYY-MM)
    y = parseInt(parts[0], 10);
    m = parseInt(parts[1], 10);
    d = parts.length === 3 ? parseInt(parts[2], 10) : 1;
  } else if (parts[parts.length - 1].length === 4) {
    // D-M-YYYY (default Arabic/EU ordering)
    if (parts.length === 2) {
      // M-YYYY  (e.g. 04-2027) → day 01
      d = 1;
      m = parseInt(parts[0], 10);
      y = parseInt(parts[1], 10);
    } else {
      d = parseInt(parts[0], 10);
      m = parseInt(parts[1], 10);
      y = parseInt(parts[2], 10);
    }
  } else {
    // No 4-digit group → assume DD-MM-YY with YY in the 2000s
    if (parts.length !== 3) {
      return { ok: false, error: 'يرجى إدخال السنة بأربعة أرقام (مثال: 2027)' };
    }
    d = parseInt(parts[0], 10);
    m = parseInt(parts[1], 10);
    const yy = parseInt(parts[2], 10);
    if (yy > 99) {
      return { ok: false, error: 'صيغة السنة غير صحيحة' };
    }
    y = 2000 + yy;
  }

  if (!validParts(y, m, d)) {
    return {
      ok: false,
      error: `تاريخ غير صالح: ${y}-${m}-${d}. تحقق من الشهر (1-12) واليوم (1-31).`,
    };
  }

  const value = `${y}-${pad2(m)}-${pad2(d)}`;
  return { ok: true, value, date: new Date(Date.UTC(y, m - 1, d)) };
}

/** Convenience: returns the normalized string or null on failure (no error). */
export function tryNormalizeExpiryDate(raw: string): string | null {
  const r = normalizeExpiryDate(raw);
  return r.ok ? r.value : null;
}

/** Formats a JS Date to "YYYY-MM-DD" (UTC-safe). */
export function dateToYMD(d: Date): string {
  return `${d.getUTCFullYear()}-${pad2(d.getUTCMonth() + 1)}-${pad2(d.getUTCDate())}`;
}

/** Parses "YYYY-MM-DD" into a Date or returns today if empty/invalid. */
export function ymdToDate(s: string | null | undefined): Date {
  if (!s) return new Date();
  const r = normalizeExpiryDate(s);
  return r.ok ? r.date : new Date();
}
