import { useRef, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Modal, ActivityIndicator, Platform, TextInput, Alert } from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { Ionicons } from '@expo/vector-icons';
import { colors } from './theme';

type Props = {
  visible: boolean;
  onClose: () => void;
  onBarcode: (barcode: string) => void;
  onImage: (base64: string) => void;
  mode: 'sell' | 'buy';
};

export default function MedicineScanner({ visible, onClose, onBarcode, onImage, mode }: Props) {
  const [permission, requestPermission] = useCameraPermissions();
  const cameraRef = useRef<any>(null);
  const [capturing, setCapturing] = useState(false);
  const [manualCode, setManualCode] = useState('');
  const lastScannedRef = useRef<string>('');

  const handleBarcodeScanned = (result: { data: string }) => {
    if (!result?.data) return;
    if (result.data === lastScannedRef.current) return;
    lastScannedRef.current = result.data;
    onBarcode(result.data);
    setTimeout(() => { lastScannedRef.current = ''; }, 2000);
  };

  const handleCapture = async () => {
    if (!cameraRef.current) return;
    setCapturing(true);
    try {
      const photo = await cameraRef.current.takePictureAsync({ base64: true, quality: 0.4 });
      if (photo?.base64) onImage(photo.base64);
    } catch (e: any) {
      Alert.alert('خطأ', 'فشل التقاط الصورة');
    } finally {
      setCapturing(false);
    }
  };

  const submitManual = () => {
    if (!manualCode.trim()) return;
    onBarcode(manualCode.trim());
    setManualCode('');
  };

  const isWeb = Platform.OS === 'web';
  const permDenied = permission && !permission.granted;

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <View style={styles.container}>
        <View style={styles.header}>
          <TouchableOpacity onPress={onClose} testID="scanner-close" style={styles.closeBtn}>
            <Ionicons name="close" size={26} color="#fff" />
          </TouchableOpacity>
          <Text style={styles.headerTxt}>
            {mode === 'sell' ? 'مسح دواء للبيع' : 'مسح دواء للإضافة'}
          </Text>
          <View style={{ width: 40 }} />
        </View>

        {!isWeb && !permission ? (
          <View style={styles.center}><ActivityIndicator color="#fff" /></View>
        ) : !isWeb && permDenied ? (
          <View style={styles.center}>
            <Ionicons name="camera-outline" size={60} color="#fff" />
            <Text style={styles.permTxt}>نحتاج إذن استخدام الكاميرا</Text>
            <TouchableOpacity style={styles.permBtn} onPress={requestPermission}>
              <Text style={styles.permBtnTxt}>السماح</Text>
            </TouchableOpacity>
          </View>
        ) : !isWeb ? (
          <View style={styles.cameraWrap}>
            <CameraView
              ref={cameraRef}
              style={StyleSheet.absoluteFill}
              facing="back"
              onBarcodeScanned={handleBarcodeScanned}
              barcodeScannerSettings={{
                barcodeTypes: ['ean13', 'ean8', 'upc_a', 'upc_e', 'code128', 'code39', 'qr'],
              }}
            />
            <View style={styles.overlay} pointerEvents="none">
              <View style={styles.scanFrame}>
                <View style={[styles.corner, styles.tl]} />
                <View style={[styles.corner, styles.tr]} />
                <View style={[styles.corner, styles.bl]} />
                <View style={[styles.corner, styles.br]} />
              </View>
              <Text style={styles.hint}>وجه الكاميرا نحو الباركود أو الدواء</Text>
            </View>

            <View style={styles.bottomBar}>
              <TouchableOpacity
                testID="btn-capture-photo"
                style={styles.captureBtn}
                onPress={handleCapture}
                disabled={capturing}
              >
                {capturing ? <ActivityIndicator color="#fff" /> : (
                  <>
                    <Ionicons name="camera" size={22} color="#fff" />
                    <Text style={styles.captureTxt}>تعرف بالصورة</Text>
                  </>
                )}
              </TouchableOpacity>
            </View>
          </View>
        ) : (
          <View style={styles.webFallback}>
            <Ionicons name="barcode" size={80} color={colors.primary} />
            <Text style={styles.webTitle}>إدخال يدوي للباركود</Text>
            <Text style={styles.webHint}>الكاميرا متاحة على الهاتف. استخدم الإدخال اليدوي في النسخة التجريبية على الويب.</Text>
            <TextInput
              testID="manual-barcode-input"
              style={styles.manualInput}
              value={manualCode}
              onChangeText={setManualCode}
              placeholder="أدخل رقم الباركود"
              placeholderTextColor={colors.textMuted}
              keyboardType="default"
              textAlign="center"
            />
            <TouchableOpacity testID="btn-submit-manual-barcode" style={styles.manualBtn} onPress={submitManual}>
              <Text style={styles.manualBtnTxt}>بحث</Text>
            </TouchableOpacity>
          </View>
        )}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#000' },
  header: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'space-between', padding: 16, paddingTop: 50, backgroundColor: 'rgba(0,0,0,0.6)' },
  headerTxt: { color: '#fff', fontSize: 17, fontWeight: '800' },
  closeBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: 'rgba(255,255,255,0.15)', alignItems: 'center', justifyContent: 'center' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 14 },
  permTxt: { color: '#fff', fontSize: 16 },
  permBtn: { backgroundColor: colors.primary, paddingVertical: 12, paddingHorizontal: 24, borderRadius: 12 },
  permBtnTxt: { color: '#fff', fontWeight: '800' },
  cameraWrap: { flex: 1 },
  overlay: { ...StyleSheet.absoluteFillObject, alignItems: 'center', justifyContent: 'center' },
  scanFrame: { width: 260, height: 260, position: 'relative' },
  corner: { position: 'absolute', width: 36, height: 36, borderColor: colors.primary },
  tl: { top: 0, left: 0, borderTopWidth: 4, borderLeftWidth: 4, borderTopLeftRadius: 12 },
  tr: { top: 0, right: 0, borderTopWidth: 4, borderRightWidth: 4, borderTopRightRadius: 12 },
  bl: { bottom: 0, left: 0, borderBottomWidth: 4, borderLeftWidth: 4, borderBottomLeftRadius: 12 },
  br: { bottom: 0, right: 0, borderBottomWidth: 4, borderRightWidth: 4, borderBottomRightRadius: 12 },
  hint: { color: '#fff', marginTop: 20, fontSize: 14 },
  bottomBar: { position: 'absolute', bottom: 40, left: 0, right: 0, alignItems: 'center' },
  captureBtn: { backgroundColor: colors.primary, paddingVertical: 14, paddingHorizontal: 28, borderRadius: 30, flexDirection: 'row-reverse', gap: 8, alignItems: 'center' },
  captureTxt: { color: '#fff', fontWeight: '800', fontSize: 16 },
  webFallback: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 28, backgroundColor: colors.background, gap: 14 },
  webTitle: { fontSize: 20, fontWeight: '800', color: colors.textPrimary },
  webHint: { textAlign: 'center', color: colors.textSecondary, lineHeight: 20 },
  manualInput: { width: '100%', maxWidth: 320, backgroundColor: '#fff', borderRadius: 12, paddingVertical: 14, paddingHorizontal: 16, borderWidth: 1, borderColor: colors.border, fontSize: 16 },
  manualBtn: { backgroundColor: colors.primary, paddingVertical: 12, paddingHorizontal: 36, borderRadius: 12 },
  manualBtnTxt: { color: '#fff', fontWeight: '800', fontSize: 16 },
});
