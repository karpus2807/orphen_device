package com.orphen.devicesafety;

import android.content.Context;
import android.content.Intent;

public final class SecurityHelper {
    public static final String EXTRA_ACTION = "securityAction";
    public static final String PREF_APP_LOCKED = "appLocked";
    public static final String PREF_APP_HIDDEN = "appHidden";
    public static final String PREF_ALLOW_UNINSTALL_UNTIL = "allowUninstallUntil";
    public static final String PREF_ALLOW_DISABLE_ADMIN_UNTIL = "allowDisableAdminUntil";
    public static final String PREF_ALLOW_ENABLE_ADMIN_UNTIL = "allowEnableAdminUntil";
    private static final long TEMP_GRANT_MS = 15 * 60 * 1000L;

    private SecurityHelper() {
    }

    public static boolean isLocked(Context context) {
        return BackendClient.prefs(context).getBoolean(PREF_APP_LOCKED, false);
    }

    public static void setLocked(Context context, boolean locked) {
        BackendClient.prefs(context).edit().putBoolean(PREF_APP_LOCKED, locked).apply();
        if (locked) {
            Intent lockIntent = new Intent(context, AppLockActivity.class);
            lockIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
            context.startActivity(lockIntent);
        }
    }

    public static boolean isHidden(Context context) {
        return BackendClient.prefs(context).getBoolean(PREF_APP_HIDDEN, false);
    }

    public static void setHidden(Context context, boolean hidden) {
        BackendClient.prefs(context).edit().putBoolean(PREF_APP_HIDDEN, hidden).apply();
        LauncherHideHelper.applyVisibility(context, !hidden);
    }

    public static void applyFromServer(Context context, boolean locked, boolean hidden) {
        boolean wasLocked = isLocked(context);
        boolean wasHidden = isHidden(context);
        BackendClient.prefs(context).edit()
                .putBoolean(PREF_APP_LOCKED, locked)
                .putBoolean(PREF_APP_HIDDEN, hidden)
                .apply();
        if (hidden != wasHidden) {
            LauncherHideHelper.applyVisibility(context, !hidden);
        } else {
            LauncherHideHelper.syncLocalVisibility(context);
        }
        if (locked && !wasLocked) {
            Intent lockIntent = new Intent(context, AppLockActivity.class);
            lockIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
            context.startActivity(lockIntent);
        }
    }

    public static void syncLocalVisibility(Context context) {
        LauncherHideHelper.syncLocalVisibility(context);
    }

    public static boolean isAllowUninstall(Context context) {
        long until = BackendClient.prefs(context).getLong(PREF_ALLOW_UNINSTALL_UNTIL, 0L);
        return until > System.currentTimeMillis();
    }

    public static void grantAllowUninstall(Context context) {
        BackendClient.prefs(context).edit()
                .putLong(PREF_ALLOW_UNINSTALL_UNTIL, System.currentTimeMillis() + TEMP_GRANT_MS)
                .apply();
    }

    public static boolean isAllowDisableAdmin(Context context) {
        long until = BackendClient.prefs(context).getLong(PREF_ALLOW_DISABLE_ADMIN_UNTIL, 0L);
        return until > System.currentTimeMillis();
    }

    public static void grantAllowDisableAdmin(Context context) {
        BackendClient.prefs(context).edit()
                .putLong(PREF_ALLOW_DISABLE_ADMIN_UNTIL, System.currentTimeMillis() + TEMP_GRANT_MS)
                .apply();
    }

    public static boolean isAllowEnableDeviceAdmin(Context context) {
        long until = BackendClient.prefs(context).getLong(PREF_ALLOW_ENABLE_ADMIN_UNTIL, 0L);
        return until > System.currentTimeMillis();
    }

    public static void grantEnableDeviceAdmin(Context context) {
        BackendClient.prefs(context).edit()
                .putLong(PREF_ALLOW_ENABLE_ADMIN_UNTIL, System.currentTimeMillis() + TEMP_GRANT_MS)
                .apply();
    }

    public static void performVerifiedAction(Context context, String actionType) {
        if ("unlock".equals(actionType)) {
            setLocked(context, false);
            return;
        }
        if ("unhide".equals(actionType)) {
            setHidden(context, false);
            return;
        }
        if ("hide".equals(actionType)) {
            setHidden(context, true);
            return;
        }
        if ("lock".equals(actionType)) {
            setLocked(context, true);
            return;
        }
        if ("enable_device_admin".equals(actionType)) {
            grantEnableDeviceAdmin(context);
            Intent requestIntent = new Intent(context, MainActivity.class);
            requestIntent.setAction(DeviceSyncService.ACTION_REQUEST_DEVICE_ADMIN);
            requestIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            context.startActivity(requestIntent);
            return;
        }
        if ("disable_device_admin".equals(actionType)) {
            grantAllowDisableAdmin(context);
            Intent settingsIntent = new Intent(android.provider.Settings.ACTION_SECURITY_SETTINGS);
            settingsIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            context.startActivity(settingsIntent);
            return;
        }
        if ("allow_uninstall".equals(actionType)) {
            grantAllowUninstall(context);
        }
    }
}
