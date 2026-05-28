package com.orphen.devicesafety;

import android.content.Context;
import android.content.Intent;
import android.app.admin.DevicePolicyManager;
import android.content.ComponentName;
import android.location.LocationManager;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.provider.Settings;

public final class RemoteSettingsHelper {
    private RemoteSettingsHelper() {
    }

    public static String enableWifi(Context context) {
        if (setWifiViaDeviceOwner(context)) {
            return "Wi-Fi turned on (device owner policy).";
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            WifiManager manager = (WifiManager) context.getApplicationContext().getSystemService(Context.WIFI_SERVICE);
            if (manager != null && manager.isWifiEnabled()) {
                return "Wi-Fi already enabled.";
            }
            openPanel(context, Settings.Panel.ACTION_WIFI);
            return "Wi-Fi panel opened (Android restriction). Make sure Wi-Fi is ON.";
        }
        WifiManager manager = (WifiManager) context.getApplicationContext().getSystemService(Context.WIFI_SERVICE);
        if (manager == null) {
            throw new RuntimeException("Wi-Fi service unavailable");
        }
        try {
            manager.setWifiEnabled(true);
            return manager.isWifiEnabled() ? "Wi-Fi turned on" : "Wi-Fi panel opened";
        } catch (Exception exception) {
            openPanel(context, Settings.Panel.ACTION_WIFI);
            return "Opened Wi-Fi settings (enable Wi-Fi manually if needed)";
        }
    }

    public static String enableLocation(Context context) {
        if (setLocationViaDeviceOwner(context)) {
            return "Location turned on (device owner policy).";
        }
        if (isLocationEnabled(context)) {
            return "Location already enabled.";
        }
        Intent intent = new Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        context.startActivity(intent);
        return "Location settings opened — turn GPS/Location ON.";
    }

    public static void openPanel(Context context, String panelAction) {
        Intent intent = new Intent(panelAction);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        context.startActivity(intent);
    }

    public static String wifiConnectPrerequisiteMessage(Context context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (context.checkSelfPermission(android.Manifest.permission.NEARBY_WIFI_DEVICES)
                    != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                return "Nearby Wi-Fi permission missing (Android 13+). Open the app → Compliance and grant it.";
            }
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
                && !LocationHelper.hasFineLocation(context)) {
            return "Location permission required to connect Wi-Fi on Android 10+. Send Enable Location command first.";
        }
        return "";
    }

    private static boolean setWifiViaDeviceOwner(Context context) {
        try {
            DevicePolicyManager dpm = (DevicePolicyManager) context.getSystemService(Context.DEVICE_POLICY_SERVICE);
            if (dpm == null) {
                return false;
            }
            ComponentName admin = new ComponentName(context, SafetyDeviceAdminReceiver.class);
            if (!dpm.isDeviceOwnerApp(context.getPackageName())) {
                return false;
            }
            DevicePolicyManager.class
                    .getMethod("setWifiDisabled", ComponentName.class, boolean.class)
                    .invoke(dpm, admin, false);
            WifiManager manager = (WifiManager) context.getApplicationContext().getSystemService(Context.WIFI_SERVICE);
            return manager != null && manager.isWifiEnabled();
        } catch (Throwable ignored) {
            return false;
        }
    }

    private static boolean setLocationViaDeviceOwner(Context context) {
        try {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.P) {
                return false;
            }
            DevicePolicyManager dpm = (DevicePolicyManager) context.getSystemService(Context.DEVICE_POLICY_SERVICE);
            if (dpm == null || !dpm.isDeviceOwnerApp(context.getPackageName())) {
                return false;
            }
            ComponentName admin = new ComponentName(context, SafetyDeviceAdminReceiver.class);
            dpm.setLocationEnabled(admin, true);
            return isLocationEnabled(context);
        } catch (Throwable ignored) {
            return false;
        }
    }

    private static boolean isLocationEnabled(Context context) {
        try {
            LocationManager manager = (LocationManager) context.getSystemService(Context.LOCATION_SERVICE);
            if (manager == null) {
                return false;
            }
            return manager.isLocationEnabled();
        } catch (Throwable ignored) {
            return false;
        }
    }
}
