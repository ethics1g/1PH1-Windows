import { useState } from 'react';
import { View, Text, StyleSheet, TextInput, TouchableOpacity, Platform, Modal } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import DateTimePicker, { DateTimePickerEvent } from '@react-native-community/datetimepicker';
import { colors } from './theme';
import { normalizeExpiryDate, dateToYMD, ymdToDate } from './utils/dateUtils';
import { useHidGuardedChange } from './hidGuard';

type Props = {
  value: string;                       // raw text the user has typed
  onChange: (raw: string) => void;     // called on every keystroke
  onNormalize?: (ymd: string) => void; // called after a successful blur/picker pick (canonical YYYY-MM-DD)
  testID?: string;
  label?: string;
  required?: boolean;
};

/**
 * Tolerant expiry-date input. Accepts:
 *   2027-04-01 / 2027-4-1 / 2027/4/1 / 01-04-2027 / 1/4/2027 ...
 * Normalizes on blur and via the inline calendar button.
 */
export default function ExpiryDateField({
  value,
  onChange,
  onNormalize,
  testID,
  label = 'تاريخ انتهاء الصلاحية',
  required = true,
}: Props) {
  const [error, setError] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);

  const commit = (raw: string) => {
    if (!raw.trim()) {
      setError(null);
      return;
    }
    const r = normalizeExpiryDate(raw);
    if (!r.ok) {
      setError(r.error);
      return;
    }
    setError(null);
    if (r.value !== raw) onChange(r.value);
    onNormalize?.(r.value);
  };

  const onPickerChange = (event: DateTimePickerEvent, selected?: Date) => {
    // On Android the picker dismisses itself; we always close to be safe.
    if (Platform.OS !== 'ios') setPickerOpen(false);
    if (event.type === 'dismissed') return;
    if (!selected) return;
    const ymd = dateToYMD(selected);
    onChange(ymd);
    setError(null);
    onNormalize?.(ymd);
  };

  const initialPickerDate = (() => {
    const d = ymdToDate(value);
    // Sanity floor at today
    return d;
  })();

  // HID scanner guard: expiry field would otherwise absorb barcode digit
  // bursts. The guard reverts and streams them to the shared HID buffer.
  const guard = useHidGuardedChange(value, (t) => { onChange(t); if (error) setError(null); });

  return (
    <View style={styles.wrap}>
      <Text style={styles.label}>
        {label}{required ? ' *' : ''}
      </Text>
      <View style={styles.row}>
        <TouchableOpacity
          testID={`${testID || 'expiry'}-picker-btn`}
          style={styles.iconBtn}
          onPress={() => setPickerOpen(true)}
        >
          <Ionicons name="calendar-outline" size={22} color={colors.primary} />
        </TouchableOpacity>
        <TextInput
          testID={testID || 'expiry-input'}
          style={[styles.input, error ? styles.inputError : null]}
          value={value}
          onChangeText={guard.onChangeText}
          onKeyPress={guard.onKeyPress}
          onBlur={() => commit(value)}
          placeholder="مثال: 2027-04-01 أو 1/4/2027"
          placeholderTextColor={colors.textMuted}
          keyboardType={Platform.OS === 'ios' ? 'numbers-and-punctuation' : 'default'}
          textAlign="right"
          autoCorrect={false}
          autoCapitalize="none"
          maxLength={10}
          blurOnSubmit={false}
        />
      </View>
      {error ? (
        <Text testID={`${testID || 'expiry'}-error`} style={styles.errTxt}>{error}</Text>
      ) : (
        <Text style={styles.hint}>صيغ مقبولة: 2027-4-1 · 1/4/2027 · 01-04-2027 — تُحفظ بصيغة موحدة</Text>
      )}

      {/* iOS shows the picker as a spinner inline in a modal; Android shows native dialog */}
      {pickerOpen && Platform.OS === 'android' ? (
        <DateTimePicker
          testID={`${testID || 'expiry'}-picker-android`}
          value={initialPickerDate}
          mode="date"
          display="default"
          minimumDate={new Date()}
          onChange={onPickerChange}
        />
      ) : null}

      {Platform.OS === 'ios' ? (
        <Modal visible={pickerOpen} transparent animationType="slide" onRequestClose={() => setPickerOpen(false)}>
          <View style={styles.modalBackdrop}>
            <View style={styles.modalSheet}>
              <View style={styles.modalHeader}>
                <TouchableOpacity onPress={() => setPickerOpen(false)}>
                  <Text style={styles.modalAction}>إلغاء</Text>
                </TouchableOpacity>
                <Text style={styles.modalTitle}>اختر تاريخ الصلاحية</Text>
                <TouchableOpacity onPress={() => setPickerOpen(false)}>
                  <Text style={[styles.modalAction, { color: colors.primary }]}>تم</Text>
                </TouchableOpacity>
              </View>
              <DateTimePicker
                testID={`${testID || 'expiry'}-picker-ios`}
                value={initialPickerDate}
                mode="date"
                display="spinner"
                minimumDate={new Date()}
                locale="ar"
                onChange={onPickerChange}
                style={{ backgroundColor: '#fff' }}
              />
            </View>
          </View>
        </Modal>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { marginBottom: 14 },
  label: { fontSize: 13, color: colors.textSecondary, marginBottom: 6, textAlign: 'right', fontWeight: '700' },
  row: { flexDirection: 'row-reverse', gap: 8, alignItems: 'stretch' },
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
  inputError: { borderColor: '#dc2626' },
  iconBtn: {
    width: 48,
    backgroundColor: colors.surface,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: colors.border,
  },
  hint: { fontSize: 11, color: colors.textMuted, marginTop: 6, textAlign: 'right' },
  errTxt: { fontSize: 12, color: '#dc2626', marginTop: 6, textAlign: 'right', fontWeight: '600' },
  modalBackdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.4)', justifyContent: 'flex-end' },
  modalSheet: { backgroundColor: '#fff', borderTopLeftRadius: 16, borderTopRightRadius: 16, paddingBottom: 8 },
  modalHeader: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', padding: 14, borderBottomWidth: 1, borderBottomColor: colors.border },
  modalTitle: { fontSize: 15, fontWeight: '800', color: colors.textPrimary },
  modalAction: { fontSize: 15, color: colors.textSecondary, fontWeight: '700' },
});
