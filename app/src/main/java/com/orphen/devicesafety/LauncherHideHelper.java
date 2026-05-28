package com.orphen.devicesafety;

import android.app.admin.DevicePolicyManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ShortcutInfo;
import android.content.pm.ShortcutManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

final class LauncherHideHelper {
    private static final String TAG = "LauncherHideHelper";
    private static final String LAUNCHER_MAIN_CLASS = "com.orphen.devicesafety.LauncherAlias";
    private static final String LAUNCHER_CAMO_CLASS = "com.orphen.devicesafety.LauncherCamo";
    private static final long[] HIDE_RETRY_DELAYS_MS = {500L, 2000L, 5000L};
    private static final Handler MAIN_HANDLER = new Handler(Looper.getMainLooper());

    private LauncherHideHelper() {
    }

    static ComponentName mainLauncherComponent(Context context) {
        return new ComponentName(context.getPackageName(), LAUNCHER_MAIN_CLASS);
    }

    static ComponentName camoLauncherComponent(Context context) {
        return new ComponentName(context.getPackageName(), LAUNCHER_CAMO_CLASS);
    }

    static boolean isMainLauncherEnabled(Context context) {
        return isComponentEnabled(context, mainLauncherComponent(context));
    }

    static boolean isCamoLauncherEnabled(Context context) {
        return isComponentEnabled(context, camoLauncherComponent(context));
    }

    static boolean hasVisibleLauncherEntry(Context context) {
        return isMainLauncherEnabled(context) || isCamoLauncherEnabled(context);
    }

    static void applyVisibility(Context context, boolean visible) {
        final Context appContext = context.getApplicationContext();
        if (Looper.myLooper() == Looper.getMainLooper()) {
            applyVisibilityOnMainThread(appContext, visible);
            return;
        }

        final CountDownLatch latch = new CountDownLatch(1);
        MAIN_HANDLER.post(new Runnable() {
            @Override
            public void run() {
                try {
                    applyVisibilityOnMainThread(appContext, visible);
                } finally {
                    latch.countDown();
                }
            }
        });
        try {
            latch.await(8, TimeUnit.SECONDS);
        } catch (InterruptedException ignored) {
            Thread.currentThread().interrupt();
        }
    }

    static void syncLocalVisibility(Context context) {
        boolean shouldShowMain = !SecurityHelper.isHidden(context);
        if (shouldShowMain != isMainLauncherEnabled(context)) {
            applyVisibility(context, shouldShowMain);
        }
    }

    private static void applyVisibilityOnMainThread(Context appContext, boolean visible) {
        if (applyDeviceOwnerVisibility(appContext, visible)) {
            if (visible) {
                HideModeNotifier.clearHiddenAccessNotice(appContext);
                setComponentEnabled(appContext, mainLauncherComponent(appContext), true);
                setComponentEnabled(appContext, camoLauncherComponent(appContext), false);
            } else {
                setComponentEnabled(appContext, mainLauncherComponent(appContext), false);
                setComponentEnabled(appContext, camoLauncherComponent(appContext), false);
                sendUserToHome(appContext);
            }
            Log.i(TAG, visible ? "Device-owner show applied" : "Device-owner hide applied");
            return;
        }

        if (visible) {
            HideModeNotifier.clearHiddenAccessNotice(appContext);
            setComponentEnabled(appContext, camoLauncherComponent(appContext), false);
            setComponentEnabled(appContext, mainLauncherComponent(appContext), true);
            if (!isMainLauncherEnabled(appContext)) {
                throw new IllegalStateException("Could not restore launcher icon");
            }
            Log.i(TAG, "Main launcher icon enabled");
            return;
        }

        // Android 10+ shows a synthesized App Info icon if every launcher entry is disabled.
        // Swap to a camouflage alias instead of leaving the launcher empty.
        // Enable camouflage first so Android never enters the synthesized App Info fallback.
        setComponentEnabled(appContext, camoLauncherComponent(appContext), true);
        setComponentEnabled(appContext, mainLauncherComponent(appContext), false);
        if (isMainLauncherEnabled(appContext)) {
            throw new IllegalStateException("Main launcher icon is still visible after hide request");
        }
        if (!isCamoLauncherEnabled(appContext)) {
            throw new IllegalStateException("Camouflage launcher entry is not enabled after hide request");
        }
        syncShortcutState(appContext, false);
        scheduleHideRetries(appContext);
        sendUserToHome(appContext);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            HideModeNotifier.showHiddenAccessNotice(appContext);
        }
        Log.i(TAG, "Launcher camouflage enabled");
    }

    private static boolean applyDeviceOwnerVisibility(Context context, boolean hidden) {
        DevicePolicyManager manager = (DevicePolicyManager) context.getSystemService(Context.DEVICE_POLICY_SERVICE);
        if (manager == null || !manager.isDeviceOwnerApp(context.getPackageName())) {
            return false;
        }
        ComponentName admin = new ComponentName(context, SafetyDeviceAdminReceiver.class);
        return manager.setApplicationHidden(admin, context.getPackageName(), hidden);
    }

    private static void setComponentEnabled(Context context, ComponentName component, boolean enabled) {
        PackageManager manager = context.getPackageManager();
        int newState = enabled
                ? PackageManager.COMPONENT_ENABLED_STATE_ENABLED
                : PackageManager.COMPONENT_ENABLED_STATE_DISABLED;
        try {
            manager.setComponentEnabledSetting(component, newState, PackageManager.DONT_KILL_APP);
        } catch (Exception firstError) {
            if (!enabled) {
                manager.setComponentEnabledSetting(
                        component,
                        PackageManager.COMPONENT_ENABLED_STATE_DISABLED_USER,
                        PackageManager.DONT_KILL_APP
                );
                return;
            }
            throw new IllegalStateException("Could not enable " + component.getClassName() + ": " + firstError.getMessage());
        }
    }

    private static boolean isComponentEnabled(Context context, ComponentName component) {
        int state = context.getPackageManager().getComponentEnabledSetting(component);
        return state == PackageManager.COMPONENT_ENABLED_STATE_DEFAULT
                || state == PackageManager.COMPONENT_ENABLED_STATE_ENABLED;
    }

    private static void scheduleHideRetries(final Context appContext) {
        for (long delayMs : HIDE_RETRY_DELAYS_MS) {
            MAIN_HANDLER.postDelayed(new Runnable() {
                @Override
                public void run() {
                    if (!SecurityHelper.isHidden(appContext)) {
                        return;
                    }
                    if (applyDeviceOwnerVisibility(appContext, true)) {
                        return;
                    }
                    if (isMainLauncherEnabled(appContext) || !isComponentEnabled(appContext, camoLauncherComponent(appContext))) {
                        Log.i(TAG, "Retrying launcher camouflage");
                        setComponentEnabled(appContext, mainLauncherComponent(appContext), false);
                        setComponentEnabled(appContext, camoLauncherComponent(appContext), true);
                    }
                }
            }, delayMs);
        }
    }

    private static void syncShortcutState(Context context, boolean visible) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N_MR1) {
            return;
        }
        ShortcutManager shortcutManager = context.getSystemService(ShortcutManager.class);
        if (shortcutManager == null) {
            return;
        }
        try {
            List<ShortcutInfo> shortcuts = shortcutManager.getDynamicShortcuts();
            if (shortcuts.isEmpty()) {
                return;
            }
            List<String> ids = new ArrayList<>();
            for (ShortcutInfo shortcut : shortcuts) {
                ids.add(shortcut.getId());
            }
            if (visible) {
                shortcutManager.enableShortcuts(ids);
            } else {
                shortcutManager.disableShortcuts(ids);
            }
        } catch (Exception ignored) {
        }
    }

    static void sendUserToHome(Context context) {
        Intent homeIntent = new Intent(Intent.ACTION_MAIN);
        homeIntent.addCategory(Intent.CATEGORY_HOME);
        homeIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            context.startActivity(homeIntent);
        } catch (Exception ignored) {
        }
    }
}
