import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { colors } from './theme';
import HeaderMenuButton from './HeaderMenuButton';

export default function ScreenHeader({
  title, subtitle, showMenu = true,
}: { title: string; subtitle?: string; showMenu?: boolean }) {
  const router = useRouter();
  return (
    <View style={styles.header}>
      <TouchableOpacity
        testID="btn-back"
        style={styles.backBtn}
        onPress={() => router.back()}
      >
        <Ionicons name="chevron-forward" size={24} color={colors.textPrimary} />
      </TouchableOpacity>
      <View style={{ flex: 1, alignItems: 'flex-end' }}>
        <Text style={styles.title}>{title}</Text>
        {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
      </View>
      {showMenu ? <HeaderMenuButton /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, padding: 18, paddingBottom: 10 },
  backBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.surface, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: colors.border },
  title: { fontSize: 20, fontWeight: '800', color: colors.textPrimary, textAlign: 'right' },
  subtitle: { fontSize: 12, color: colors.textSecondary, textAlign: 'right', marginTop: 2 },
});
