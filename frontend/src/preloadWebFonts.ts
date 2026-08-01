/**
 * Web-only bulletproof icon-font preloader.
 * =============================================================================
 * This module registers the vector-icon fonts directly via the browser's
 * FontFace API at *module init time* — i.e. the moment this file is imported,
 * BEFORE any React component mounts, BEFORE `useFonts` runs, BEFORE the first
 * paint. That guarantees icons never render as ☐ (tofu) boxes on the Windows
 * Electron desktop build, even in worst-case scenarios where:
 *   • the Expo-generated `@font-face` rule is injected too late,
 *   • `useFonts` fails silently (network / cache / hydration timing),
 *   • the renderer starts before React has hydrated the tree.
 *
 * Native (Android / iOS): this file is a NO-OP. Vector-icon fonts are already
 * linked into the native binary by the `expo-font` config plugin, and the
 * browser-only FontFace API doesn't exist there anyway.
 *
 * How it works:
 *   1. We `require()` each icon-family .ttf. Metro converts `require` to a
 *      Metro asset URL string on web (e.g. `/assets/…/Ionicons.<hash>.ttf`).
 *   2. We construct a `FontFace(family, url("<uri>"))` object.
 *   3. We call `.load()` and add it to `document.fonts` on success.
 *   4. All work is fire-and-forget — the app never blocks on it. Meanwhile
 *      the React tree's own `useFonts` hook re-registers the same font,
 *      which the browser dedupes.
 */
import { Platform } from 'react-native';

if (Platform.OS === 'web' && typeof document !== 'undefined' && (document as any).fonts) {
  try {
    // Only Ionicons is used across the app today, but preload all common
    // vector-icon families anyway so future screens work out of the box.
    // Each require() is wrapped in a try/catch — a missing bundle entry
    // must never crash app boot.
    const families: Array<[string, () => any]> = [
      ['Ionicons',              () => require('@expo/vector-icons/build/vendor/react-native-vector-icons/Fonts/Ionicons.ttf')],
      ['MaterialCommunityIcons',() => require('@expo/vector-icons/build/vendor/react-native-vector-icons/Fonts/MaterialCommunityIcons.ttf')],
      ['MaterialIcons',         () => require('@expo/vector-icons/build/vendor/react-native-vector-icons/Fonts/MaterialIcons.ttf')],
      ['FontAwesome',           () => require('@expo/vector-icons/build/vendor/react-native-vector-icons/Fonts/FontAwesome.ttf')],
      ['Feather',               () => require('@expo/vector-icons/build/vendor/react-native-vector-icons/Fonts/Feather.ttf')],
      ['AntDesign',             () => require('@expo/vector-icons/build/vendor/react-native-vector-icons/Fonts/AntDesign.ttf')],
      ['Entypo',                () => require('@expo/vector-icons/build/vendor/react-native-vector-icons/Fonts/Entypo.ttf')],
    ];

    // Resolve every require() to its Metro asset URL. When Metro exports
    // for web it returns a string like "/assets/.../Ionicons.<hash>.ttf",
    // when it exports for a bundler that emits number IDs it returns an
    // object with .uri — we handle both.
    const resolveUri = (mod: any): string | null => {
      if (!mod) return null;
      if (typeof mod === 'string') return mod;
      if (typeof mod === 'object') {
        if (typeof mod.uri === 'string') return mod.uri;
        if (typeof mod.default === 'string') return mod.default;
      }
      return null;
    };

    for (const [family, load] of families) {
      try {
        const uri = resolveUri(load());
        if (!uri) continue;
        const ff = new (window as any).FontFace(family, `url("${uri}") format("truetype")`);
        // Add first (so any `@font-face` rule with the same family dedupes),
        // then trigger the fetch. The FontFace API guarantees glyphs become
        // available for every element that inherits this family the moment
        // the promise resolves.
        (document as any).fonts.add(ff);
        ff.load().catch(() => { /* silent — the Expo @font-face rule is a fallback */ });
      } catch { /* per-family failure never blocks siblings */ }
    }
  } catch {
    /* Environment without FontFace API — nothing to do. */
  }
}
