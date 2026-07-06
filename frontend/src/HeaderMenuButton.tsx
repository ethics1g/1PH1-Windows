import { useState } from 'react';
import { TouchableOpacity, StyleSheet, View, Text } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { colors } from './theme';
import AppDrawer from './AppDrawer';
import { useNotificationBadge } from './useNotificationBadge';

/**
 * Hamburger button + inline drawer. Place inside a header (right side in RTL).
 * Shows a red badge with unread notifications count.
 */
export default function HeaderMenuButton({ testID }: { testID?: string }) {
  const [open, setOpen] = useState(false);
  const { unread } = useNotificationBadge();

  return (
    <>
      <TouchableOpacity
        testID={testID || 'btn-drawer'}
        style={styles.btn}
        onPress={() => setOpen(true)}
      >
        <Ionicons name="menu" size={24} color={colors.textPrimary} />
        {unread > 0 ? (
          <View style={styles.badge} testID="drawer-badge">
            <Text style={styles.badgeTxt}>{unread > 99 ? '99+' : String(unread)}</Text>
          </View>
        ) : null}
      </TouchableOpacity>
      <AppDrawer visible={open} onClose={() => setOpen(false)} />
    </>
  );
}

const styles = StyleSheet.create({
  btn: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.surface, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: colors.border },
  badge: { position: 'absolute', top: -3, right: -3, minWidth: 20, height: 20, borderRadius: 10, backgroundColor: colors.error, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 5, borderWidth: 2, borderColor: colors.surface },
  badgeTxt: { color: '#fff', fontSize: 10, fontWeight: '800' },
});
