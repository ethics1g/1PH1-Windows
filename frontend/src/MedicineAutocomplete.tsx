import { useCallback, useEffect, useRef, useState } from 'react';
import { View, Text, StyleSheet, TextInput, TouchableOpacity, FlatList, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { colors } from './theme';
import { apiFetch, useAuth } from './auth';
import { useHidGuardedChange } from './hidGuard';

export type MedicineHit = {
  id: string;
  name: string;
  barcode?: string;
  quantity: number;
  price: number;
  purchase_price?: number;
  expiry_date?: string;
};

type Props = {
  onSelect: (m: MedicineHit) => void;
  placeholder?: string;
  autoFocus?: boolean;
  testID?: string;
};

/**
 * Autocomplete search for the pharmacy's own medicines. Fires /api/medicines/search
 * with a 200 ms debounce and shows up to 15 suggestions.
 */
export default function MedicineAutocomplete({ onSelect, placeholder, autoFocus, testID }: Props) {
  const { token } = useAuth();
  const [q, setQ] = useState('');
  const [hits, setHits] = useState<MedicineHit[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef<any>(null);

  const search = useCallback(async (val: string) => {
    setLoading(true);
    try {
      const r: any = await apiFetch(`/medicines/search?q=${encodeURIComponent(val)}&limit=15`, {}, token);
      setHits(r.items || []);
    } catch { setHits([]); }
    finally { setLoading(false); }
  }, [token]);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (!q || q.trim().length === 0) { setHits([]); return; }
    timerRef.current = setTimeout(() => search(q.trim()), 200);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [q, search]);

  // HID scanner guard — if a USB/Bluetooth HID barcode scanner sends
  // digits into this search field, revert them and route to the global
  // scanner handler (which resolves the medicine and adds to cart).
  const guard = useHidGuardedChange(q, (v) => { setQ(v); setOpen(true); });

  return (
    <View style={styles.wrap}>
      <View style={styles.inputWrap}>
        <Ionicons name="search" size={18} color={colors.textMuted} style={{ marginHorizontal: 8 }} />
        <TextInput
          testID={testID || 'ac-input'}
          style={styles.input}
          value={q}
          onChangeText={guard.onChangeText}
          onKeyPress={guard.onKeyPress}
          onFocus={() => setOpen(true)}
          placeholder={placeholder || 'ابحث عن اسم الدواء...'}
          placeholderTextColor={colors.textMuted}
          textAlign="right"
          autoFocus={autoFocus}
          autoCorrect={false}
          autoCapitalize="none"
          blurOnSubmit={false}
        />
        {q ? (
          <TouchableOpacity onPress={() => { setQ(''); setHits([]); }} style={styles.clearBtn}>
            <Ionicons name="close-circle" size={18} color={colors.textMuted} />
          </TouchableOpacity>
        ) : null}
      </View>

      {open && q.trim().length > 0 ? (
        <View style={styles.dropdown}>
          {loading ? (
            <View style={styles.loading}><ActivityIndicator size="small" color={colors.primary} /></View>
          ) : hits.length === 0 ? (
            <Text style={styles.emptyTxt}>لا توجد نتائج مطابقة في مخزنك</Text>
          ) : (
            <FlatList
              data={hits}
              keyExtractor={(i) => i.id}
              keyboardShouldPersistTaps="handled"
              renderItem={({ item }) => (
                <TouchableOpacity
                  testID={`ac-hit-${item.id}`}
                  style={styles.hit}
                  onPress={() => { onSelect(item); setQ(''); setHits([]); setOpen(false); }}
                >
                  <View style={{ flex: 1 }}>
                    <Text style={styles.hitName} numberOfLines={1}>{item.name}</Text>
                    <View style={styles.hitRow}>
                      {item.barcode ? <Text style={styles.hitMeta}>{item.barcode}</Text> : null}
                      <Text style={styles.hitMeta}>الكمية: {item.quantity}</Text>
                      <Text style={styles.hitPrice}>{item.price.toLocaleString()} د.ع</Text>
                    </View>
                  </View>
                </TouchableOpacity>
              )}
              ItemSeparatorComponent={() => <View style={{ height: 1, backgroundColor: colors.border }} />}
            />
          )}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { position: 'relative', zIndex: 10 },
  inputWrap: { flexDirection: 'row-reverse', alignItems: 'center', backgroundColor: colors.surface, borderRadius: 12, borderWidth: 1, borderColor: colors.border },
  input: { flex: 1, paddingVertical: 12, paddingHorizontal: 8, fontSize: 15, color: colors.textPrimary },
  clearBtn: { padding: 8 },
  dropdown: { position: 'absolute', top: 52, left: 0, right: 0, backgroundColor: colors.surface, borderRadius: 12, borderWidth: 1, borderColor: colors.border, maxHeight: 320, zIndex: 20, elevation: 8, shadowColor: '#000', shadowOpacity: 0.12, shadowRadius: 8, shadowOffset: { width: 0, height: 4 } },
  loading: { padding: 20, alignItems: 'center' },
  emptyTxt: { padding: 16, textAlign: 'center', color: colors.textMuted, fontSize: 13 },
  hit: { flexDirection: 'row-reverse', alignItems: 'center', padding: 12 },
  hitName: { fontSize: 14, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  hitRow: { flexDirection: 'row-reverse', gap: 10, marginTop: 3, alignItems: 'center' },
  hitMeta: { fontSize: 11, color: colors.textMuted },
  hitPrice: { marginLeft: 'auto', fontSize: 12, color: colors.primary, fontWeight: '800' },
});
