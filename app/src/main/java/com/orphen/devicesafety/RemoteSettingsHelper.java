package com.orphen.devicesafety;

import android.content.Context;
import android.content.Intent;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.provider.Settings;

public final class RemoteSettingsHelper {
    private RemoteSettingsHelper() {
    }

    public static String enableWifi(Context context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            openPanel(context, Settings.Panel.ACTION_WIFI);
            return "Wi-Fi panel opened — turn Wi-Fi ON if it is off, then retry Push Wi-Fi Profile.";
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
        Intent intent = new Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        context.startActivity(intent);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            return "Location settings opened — turn Location/GPS ON (required for Wi-Fi connect on Android 10+).";
        }
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
}
