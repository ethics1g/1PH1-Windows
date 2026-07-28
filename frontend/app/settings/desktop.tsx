/**
 * Desktop-only settings screen for the Electron Windows shell.
 *
 * All logic here is a NO-OP on iOS/Android/web PWA — the underlying
 * `pharmaDesktop` bridge is only present when the app is wrapped by
 * `/app/electron/main.js`. On non-desktop platforms the screen shows
 * a friendly info card explaining that these settings only apply to
 * the Windows desktop build.
 *
 * Provides:
 *   • Backend URL configuration with a "Test connection" button that
 *     hits `GET {url}/api/health` (falls back to `GET {url}/api/`).
 *   • Thermal printer picker (loaded via `desktop().listPrinters()`),
 *     paper size (58mm/80mm), and cash-drawer toggle.
 *   • A4 printer picker.
 *   • "Print test page" and "Kick cash drawer" buttons that call the
 *     matching IPC handlers in main.js.
 *   • Live application version / Electron / Chromium info.
 */
import { useEffect, useMemo, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TextInput, TouchableOpacity,
  ActivityIndicator, Alert, Switch, Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import ScreenHeader from '../../src/ScreenHeader';
import { colors } from '../../src/theme';
import { isDesktop, desktop } from '../../src/desktop';

type PrinterInfo = {
  name: string;
  displayName: string;
  isDefault?: boolean;
  status?: number;
  description?: string;
};

type AppInfo = {
  version: string;
  electron: string;
  platform: string;
  arch: string;
  userData: string;
  logFile: string;
};

type Settings = {
  frontendUrl: string;
  thermalPrinterName: string;
  thermalPageSize: '58mm' | '80mm';
  a4PrinterName: string;
  kickCashDrawer: boolean;
  zoomFactor: number;
};

const DEFAULT_SETTINGS: Settings = {
  frontendUrl: '',
  thermalPrinterName: '',
  thermalPageSize: '80mm',
  a4PrinterName: '',
  kickCashDrawer: false,
  zoomFactor: 1.0,
};

export default function DesktopSettings() {
  const onDesktop = isDesktop();
  const api = useMemo(() => (onDesktop ? desktop() : null), [onDesktop]);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null); // key currently being persisted
  const [testingUrl, setTestingUrl] = useState(false);
  const [testingPrinter, setTestingPrinter] = useState(false);
  const [testingDrawer, setTestingDrawer] = useState(false);

  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [urlDraft, setUrlDraft] = useState('');
  const [printers, setPrinters] = useState<PrinterInfo[]>([]);
  const [appInfo, setAppInfo] = useState<AppInfo | null>(null);

  // Bootstrap: load settings, printers, and app info from the main process.
  useEffect(() => {
    if (!api) { setLoading(false); return; }
    (async () => {
      try {
        const [all, list, info] = await Promise.all([
          api.settings.all(),
          api.listPrinters(),
          api.app.info(),
        ]);
        const merged = { ...DEFAULT_SETTINGS, ...(all || {}) } as Settings;
        setSettings(merged);
        setUrlDraft(merged.frontendUrl || '');
        setPrinters(Array.isArray(list) ? list : []);
        setAppInfo(info || null);
      } catch (e: any) {
        console.warn('desktop settings load failed', e && e.message);
      } finally {
        setLoading(false);
      }
    })();
  }, [api]);

  const persist = async <K extends keyof Settings>(key: K, value: Settings[K]) => {
    if (!api) return;
    setSaving(String(key));
    try {
      await api.settings.set(String(key), value as any);
      setSettings(prev => ({ ...prev, [key]: value }));
    } catch (e: any) {
      Alert.alert('فشل الحفظ', e?.message || 'تعذّر حفظ الإعداد');
    } finally {
      setSaving(null);
    }
  };

  const saveUrl = async () => {
    const clean = urlDraft.trim().replace(/\/+$/, '');
    if (!/^https?:\/\//i.test(clean)) {
      Alert.alert('رابط غير صالح', 'يجب أن يبدأ الرابط بـ https:// أو http://');
      return;
    }
    await persist('frontendUrl', clean);
    setUrlDraft(clean);
    if (api?.app?.reload) {
      Alert.alert('تم الحفظ', 'سيتم إعادة تحميل التطبيق لاستخدام الرابط الجديد.', [
        { text: 'لاحقاً', style: 'cancel' },
        { text: 'إعادة التحميل الآن', onPress: () => api.app.reload().catch(() => {}) },
      ]);
    }
  };

  const testConnection = async () => {
    const url = urlDraft.trim().replace(/\/+$/, '');
    if (!/^https?:\/\//i.test(url)) {
      Alert.alert('رابط غير صالح', 'أدخل رابطاً يبدأ بـ https:// أو http://');
      return;
    }
    setTestingUrl(true);
    // Try /api/health then /api/ then /
    const candidates = [`${url}/api/health`, `${url}/api/`, `${url}/`];
    let ok = false; let status = 0; let sample = '';
    for (const target of candidates) {
      try {
        const ac = new AbortController();
        const t = setTimeout(() => ac.abort(), 6000);
        const r = await fetch(target, { method: 'GET', signal: ac.signal });
        clearTimeout(t);
        status = r.status;
        // 200-399 counts as reachable; 404 also counts since it proves DNS/TCP works.
        if (r.status < 500) {
          try { sample = (await r.text()).slice(0, 60); } catch { /* noop */ }
          ok = true;
          break;
        }
      } catch { /* try next */ }
    }
    setTestingUrl(false);
    if (ok) {
      Alert.alert('نجح الاتصال ✅',
        `الخادم يستجيب.\nHTTP ${status}\n${sample ? sample + '…' : ''}`);
    } else {
      Alert.alert('فشل الاتصال ❌',
        'لم يتم الوصول إلى الخادم. تحقق من الرابط ومن اتصال الإنترنت.');
    }
  };

  const testPrinter = async () => {
    if (!api) return;
    if (!settings.thermalPrinterName) {
      Alert.alert('لم يتم اختيار طابعة', 'الرجاء اختيار الطابعة الحرارية أولاً.');
      return;
    }
    setTestingPrinter(true);
    try {
      await api.print.testThermal();
      Alert.alert('نجحت الطباعة ✅', 'راجع الطابعة — تمّت طباعة صفحة الاختبار.');
    } catch (e: any) {
      Alert.alert('فشل الطباعة ❌', e?.message || 'تحقّق من الطابعة والاتصال.');
    } finally {
      setTestingPrinter(false);
    }
  };

  const testCashDrawer = async () => {
    if (!api) return;
    if (!settings.thermalPrinterName) {
      Alert.alert('لم يتم اختيار طابعة', 'يتم فتح الدرج عبر الطابعة الحرارية. اختر الطابعة أولاً.');
      return;
    }
    setTestingDrawer(true);
    try {
      await api.print.kickCashDrawer();
      Alert.alert('تم إرسال الأمر ✅', 'إذا لم يفتح الدرج، تأكد من كابل RJ11/RJ12 بين الدرج والطابعة.');
    } catch (e: any) {
      Alert.alert('فشل فتح الدرج ❌', e?.message || 'تحقّق من الاتصال.');
    } finally {
      setTestingDrawer(false);
    }
  };

  // ---------- Non-desktop fallback ----------
  if (!onDesktop) {
    return (
      <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
        <ScreenHeader title="إعدادات سطح المكتب" subtitle="Windows / Electron" />
        <ScrollView contentContainerStyle={{ padding: 14 }}>
          <View style={styles.infoCard}>
            <Ionicons name="desktop-outline" size={40} color={colors.indigo} />
            <Text style={styles.infoTitle}>غير متاح على هذه المنصة</Text>
            <Text style={styles.infoText}>
              هذه الإعدادات تخص نسخة سطح المكتب (Windows) فقط.{'\n'}
              افتح التطبيق داخل مغلف Electron لعرض إعدادات الطابعة والرابط.
            </Text>
            <Text style={[styles.infoText, { marginTop: 8, fontSize: 12, color: colors.textMuted }]}>
              المنصة الحالية: {Platform.OS}
            </Text>
          </View>
        </ScrollView>
      </SafeAreaView>
    );
  }

  // ---------- Desktop loading state ----------
  if (loading) {
    return (
      <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
        <ScreenHeader title="إعدادات سطح المكتب" subtitle="Windows / Electron" />
        <View style={styles.loader}>
          <ActivityIndicator color={colors.primary} />
          <Text style={styles.loaderText}>جارٍ تحميل الإعدادات…</Text>
        </View>
      </SafeAreaView>
    );
  }

  const hasUrlChanges = urlDraft.trim().replace(/\/+$/, '') !== (settings.frontendUrl || '');

  return (
    <SafeAreaView style={styles.safe} edges={['top', 'left', 'right']}>
      <ScreenHeader title="إعدادات سطح المكتب" subtitle="Windows / Electron" />
      <ScrollView contentContainerStyle={{ padding: 14, paddingBottom: 40 }}>

        {/* ================= 1. Server URL ================= */}
        <SectionCard icon="cloud-outline" title="رابط الخادم">
          <Text style={styles.label}>Frontend URL</Text>
          <TextInput
            testID="input-frontend-url"
            style={styles.input}
            value={urlDraft}
            onChangeText={setUrlDraft}
            placeholder="https://your-app.emergent.host"
            placeholderTextColor={colors.textMuted}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            textAlign="left"
          />
          <View style={styles.rowButtons}>
            <TouchableOpacity
              testID="btn-test-connection"
              style={[styles.btn, styles.btnSecondary]}
              disabled={testingUrl}
              onPress={testConnection}
            >
              {testingUrl
                ? <ActivityIndicator color={colors.indigo} size="small" />
                : <>
                    <Ionicons name="wifi" size={16} color={colors.indigo} />
                    <Text style={styles.btnSecondaryText}>اختبار الاتصال</Text>
                  </>}
            </TouchableOpacity>
            <TouchableOpacity
              testID="btn-save-url"
              style={[styles.btn, styles.btnPrimary, !hasUrlChanges && styles.btnDisabled]}
              disabled={!hasUrlChanges || saving === 'frontendUrl'}
              onPress={saveUrl}
            >
              {saving === 'frontendUrl'
                ? <ActivityIndicator color="#fff" size="small" />
                : <>
                    <Ionicons name="save" size={16} color="#fff" />
                    <Text style={styles.btnPrimaryText}>حفظ الرابط</Text>
                  </>}
            </TouchableOpacity>
          </View>
        </SectionCard>

        {/* ================= 2. Thermal printer ================= */}
        <SectionCard icon="print-outline" title="الطابعة الحرارية (فواتير)">
          <Text style={styles.label}>الطابعة</Text>
          <PrinterList
            testIDPrefix="thermal"
            printers={printers}
            selected={settings.thermalPrinterName}
            onSelect={(name) => persist('thermalPrinterName', name)}
          />

          <Text style={[styles.label, { marginTop: 12 }]}>مقاس الورق</Text>
          <View style={styles.segmented}>
            {(['58mm', '80mm'] as const).map((size) => {
              const active = settings.thermalPageSize === size;
              return (
                <TouchableOpacity
                  key={size}
                  testID={`btn-page-${size}`}
                  style={[styles.segment, active && styles.segmentActive]}
                  onPress={() => persist('thermalPageSize', size)}
                >
                  <Text style={[styles.segmentText, active && styles.segmentTextActive]}>{size}</Text>
                </TouchableOpacity>
              );
            })}
          </View>

          <View style={styles.switchRow}>
            <View style={{ flex: 1 }}>
              <Text style={styles.switchLabel}>فتح درج الكاش تلقائياً</Text>
              <Text style={styles.switchSub}>يُفتح الدرج بعد كل فاتورة (RJ11 من الطابعة).</Text>
            </View>
            <Switch
              testID="switch-cash-drawer"
              value={!!settings.kickCashDrawer}
              onValueChange={(v) => persist('kickCashDrawer', v)}
              trackColor={{ false: colors.border, true: colors.primaryLight }}
              thumbColor={settings.kickCashDrawer ? colors.primary : '#f4f3f4'}
            />
          </View>

          <View style={[styles.rowButtons, { marginTop: 6 }]}>
            <TouchableOpacity
              testID="btn-test-drawer"
              style={[styles.btn, styles.btnSecondary]}
              disabled={testingDrawer}
              onPress={testCashDrawer}
            >
              {testingDrawer
                ? <ActivityIndicator color={colors.indigo} size="small" />
                : <>
                    <Ionicons name="cash-outline" size={16} color={colors.indigo} />
                    <Text style={styles.btnSecondaryText}>اختبار فتح الدرج</Text>
                  </>}
            </TouchableOpacity>
            <TouchableOpacity
              testID="btn-test-print"
              style={[styles.btn, styles.btnPrimary]}
              disabled={testingPrinter}
              onPress={testPrinter}
            >
              {testingPrinter
                ? <ActivityIndicator color="#fff" size="small" />
                : <>
                    <Ionicons name="print" size={16} color="#fff" />
                    <Text style={styles.btnPrimaryText}>طباعة صفحة اختبار</Text>
                  </>}
            </TouchableOpacity>
          </View>
        </SectionCard>

        {/* ================= 3. A4 printer ================= */}
        <SectionCard icon="documents-outline" title="طابعة A4 (فواتير كبيرة)">
          <Text style={styles.label}>الطابعة الافتراضية لـ A4</Text>
          <PrinterList
            testIDPrefix="a4"
            printers={[
              { name: '', displayName: 'استخدام طابعة النظام الافتراضية' } as PrinterInfo,
              ...printers,
            ]}
            selected={settings.a4PrinterName}
            onSelect={(name) => persist('a4PrinterName', name)}
          />
        </SectionCard>

        {/* ================= 4. App info ================= */}
        <SectionCard icon="information-circle-outline" title="حول التطبيق">
          <InfoRow label="الإصدار"              value={appInfo?.version || '-'} />
          <InfoRow label="Electron"             value={appInfo?.electron || '-'} />
          <InfoRow label="نظام التشغيل"          value={`${appInfo?.platform || '-'} (${appInfo?.arch || '-'})`} />
          <InfoRow label="مجلد بيانات المستخدم"  value={appInfo?.userData || '-'} mono />
          <InfoRow label="ملف السجل"             value={appInfo?.logFile || '-'} mono />

          <View style={[styles.rowButtons, { marginTop: 10 }]}>
            <TouchableOpacity
              testID="btn-open-log"
              style={[styles.btn, styles.btnSecondary]}
              onPress={() => api?.app.openLogFile().catch(() => {})}
            >
              <Ionicons name="document-text" size={16} color={colors.indigo} />
              <Text style={styles.btnSecondaryText}>فتح ملف السجل</Text>
            </TouchableOpacity>
            <TouchableOpacity
              testID="btn-reload"
              style={[styles.btn, styles.btnSecondary]}
              onPress={() => api?.app.reload().catch(() => {})}
            >
              <Ionicons name="refresh" size={16} color={colors.indigo} />
              <Text style={styles.btnSecondaryText}>إعادة تحميل</Text>
            </TouchableOpacity>
          </View>
        </SectionCard>

        <Text style={styles.footerHint}>
          الاختصارات: F2 بيع · F3 شراء · F4 مخزن · F5 زبائن · F6 محاسبة · F7 طلباتي · F8 مذاخر
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

// ---------- Sub-components ----------

function SectionCard({ icon, title, children }: { icon: keyof typeof Ionicons.glyphMap; title: string; children: React.ReactNode }) {
  return (
    <View style={styles.card}>
      <View style={styles.cardHeader}>
        <View style={styles.cardIcon}>
          <Ionicons name={icon} size={18} color={colors.indigo} />
        </View>
        <Text style={styles.cardTitle}>{title}</Text>
      </View>
      <View style={styles.cardBody}>{children}</View>
    </View>
  );
}

function PrinterList({ testIDPrefix, printers, selected, onSelect }: {
  testIDPrefix: string;
  printers: PrinterInfo[];
  selected: string;
  onSelect: (name: string) => void;
}) {
  if (!printers.length) {
    return <Text style={styles.emptyText}>لم يتم اكتشاف أي طابعة على النظام.</Text>;
  }
  return (
    <View style={{ gap: 6 }}>
      {printers.map((p, i) => {
        const isSel = (selected || '') === (p.name || '');
        const label = p.displayName || p.name || '—';
        const key = p.name || `default-${i}`;
        return (
          <TouchableOpacity
            key={key}
            testID={`${testIDPrefix}-printer-${i}`}
            style={[styles.printerRow, isSel && styles.printerRowActive]}
            onPress={() => onSelect(p.name)}
          >
            <Ionicons
              name={isSel ? 'radio-button-on' : 'radio-button-off'}
              size={20}
              color={isSel ? colors.primary : colors.textMuted}
            />
            <View style={{ flex: 1 }}>
              <Text style={styles.printerName} numberOfLines={1}>{label}</Text>
              {p.isDefault ? <Text style={styles.printerDefault}>الطابعة الافتراضية</Text> : null}
              {p.description ? <Text style={styles.printerDesc} numberOfLines={1}>{p.description}</Text> : null}
            </View>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

function InfoRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <View style={styles.infoRow}>
      <Text style={styles.infoLabel}>{label}</Text>
      <Text style={[styles.infoValue, mono && styles.infoValueMono]} numberOfLines={1} ellipsizeMode="middle">{value}</Text>
    </View>
  );
}

// ---------- Styles ----------
const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  loader: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12 },
  loaderText: { color: colors.textSecondary, fontSize: 14 },

  infoCard: { alignItems: 'center', padding: 24, backgroundColor: colors.surface, borderRadius: 16, borderWidth: 1, borderColor: colors.border, gap: 8 },
  infoTitle: { fontSize: 17, fontWeight: '800', color: colors.textPrimary, marginTop: 6 },
  infoText: { fontSize: 13, color: colors.textSecondary, textAlign: 'center', lineHeight: 20 },

  card: { backgroundColor: colors.surface, borderRadius: 16, borderWidth: 1, borderColor: colors.border, marginBottom: 14, overflow: 'hidden' },
  cardHeader: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, paddingHorizontal: 14, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.indigoLight },
  cardIcon: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.surface, alignItems: 'center', justifyContent: 'center' },
  cardTitle: { fontSize: 15, fontWeight: '800', color: colors.textPrimary, textAlign: 'right', flex: 1 },
  cardBody: { padding: 14 },

  label: { fontSize: 12, fontWeight: '700', color: colors.textSecondary, textAlign: 'right', marginBottom: 6 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 10, fontSize: 14, color: colors.textPrimary, backgroundColor: colors.background },

  rowButtons: { flexDirection: 'row-reverse', gap: 8, marginTop: 10 },
  btn: { flex: 1, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 6, paddingVertical: 12, borderRadius: 10, minHeight: 44 },
  btnPrimary: { backgroundColor: colors.primary },
  btnPrimaryText: { color: '#fff', fontWeight: '800', fontSize: 13 },
  btnSecondary: { backgroundColor: colors.indigoLight, borderWidth: 1, borderColor: colors.indigo },
  btnSecondaryText: { color: colors.indigo, fontWeight: '700', fontSize: 13 },
  btnDisabled: { opacity: 0.45 },

  segmented: { flexDirection: 'row-reverse', gap: 8 },
  segment: { flex: 1, paddingVertical: 10, borderRadius: 10, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.background, alignItems: 'center', justifyContent: 'center' },
  segmentActive: { backgroundColor: colors.primaryLight, borderColor: colors.primary },
  segmentText: { fontSize: 13, fontWeight: '700', color: colors.textSecondary },
  segmentTextActive: { color: colors.primaryDark },

  switchRow: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12, marginTop: 14, paddingVertical: 8 },
  switchLabel: { fontSize: 14, fontWeight: '700', color: colors.textPrimary, textAlign: 'right' },
  switchSub: { fontSize: 11, color: colors.textMuted, textAlign: 'right', marginTop: 2 },

  emptyText: { fontSize: 13, color: colors.textMuted, textAlign: 'right', paddingVertical: 12 },
  printerRow: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, padding: 10, borderRadius: 10, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.background },
  printerRowActive: { borderColor: colors.primary, backgroundColor: colors.primaryLight },
  printerName: { fontSize: 14, fontWeight: '700', color: colors.textPrimary, textAlign: 'right' },
  printerDefault: { fontSize: 11, color: colors.primary, textAlign: 'right', marginTop: 2 },
  printerDesc: { fontSize: 11, color: colors.textMuted, textAlign: 'right', marginTop: 2 },

  infoRow: { flexDirection: 'row-reverse', justifyContent: 'space-between', paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.border, gap: 12 },
  infoLabel: { fontSize: 12, color: colors.textSecondary, fontWeight: '700' },
  infoValue: { fontSize: 12, color: colors.textPrimary, flex: 1, textAlign: 'left' },
  infoValueMono: { fontFamily: Platform.select({ ios: 'Menlo', android: 'monospace', default: 'monospace' }), fontSize: 11 },

  footerHint: { fontSize: 11, color: colors.textMuted, textAlign: 'center', marginTop: 8, lineHeight: 18 },
});
