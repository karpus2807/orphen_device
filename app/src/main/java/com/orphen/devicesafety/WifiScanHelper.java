package com.orphen.devicesafety;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.net.wifi.ScanResult;
import android.net.wifi.WifiConfiguration;
import android.net.wifi.WifiManager;
import android.os.Build;

import org.json.JSONArray;

import java.util.HashSet;
import java.util.List;
import java.util.Set;

public final class WifiScanHelper {
    private WifiScanHelper() {
    }

    public static JSONArray collectNearbyWifi(Context context) {
        JSONArray networks = new JSONArray();
        if (!canScanWifi(context)) {
            return networks;
        }
        try {
            WifiManager wifiManager =
                    (WifiManager) context.getApplicationContext().getSystemService(Context.WIFI_SERVICE);
            if (wifiManager == null) {
                return networks;
            }
            if (!wifiManager.isWifiEnabled()) {
                return networks;
            }
            try {
                wifiManager.startScan();
            } catch (SecurityException ignored) {
                return networks;
            }
            List<ScanResult> results = wifiManager.getScanResults();
            if (results == null || results.isEmpty()) {
                return networks;
            }
            Set<String> seen = new HashSet<>();
            String connected = TelemetryHelper.readWifiSsid(context);
            if (connected != null && connected.length() > 0) {
                seen.add(connected.toLowerCase());
                networks.put(connected);
            }
            for (ScanResult result : results) {
                if (result == null || result.SSID == null) {
                    continue;
                }
                String ssid = result.SSID.trim();
                if (ssid.length() == 0 || "<unknown ssid>".equalsIgnoreCase(ssid)) {
                    continue;
                }
                String key = ssid.toLowerCase();
                if (seen.contains(key)) {
                    continue;
                }
                seen.add(key);
                networks.put(ssid);
                if (networks.length() >= 40) {
                    break;
                }
            }
        } catch (Exception ignored) {
            return networks;
        }
        return networks;
    }

    public static JSONArray collectSavedProfiles(Context context) {
        JSONArray profiles = new JSONArray();
        try {
            WifiManager wifiManager =
                    (WifiManager) context.getApplicationContext().getSystemService(Context.WIFI_SERVICE);
            if (wifiManager == null) {
                return profiles;
            }
            if (!canScanWifi(context)) {
                return profiles;
            }
            List<WifiConfiguration> configured = wifiManager.getConfiguredNetworks();
            if (configured == null) {
                return profiles;
            }
            Set<String> seen = new HashSet<>();
            for (WifiConfiguration network : configured) {
                if (network == null) {
                    continue;
                }
                String ssid = normalizeSsid(network.SSID);
                if (ssid.length() == 0) {
                    continue;
                }
                String key = ssid.toLowerCase();
                if (seen.contains(key)) {
                    continue;
                }
                seen.add(key);
                profiles.put(ssid);
                if (profiles.length() >= 80) {
                    break;
                }
            }
        } catch (Throwable ignored) {
            return profiles;
        }
        return profiles;
    }

    private static boolean canScanWifi(Context context) {
        if (hasLocationPermission(context)) {
            return true;
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            return context.checkSelfPermission(Manifest.permission.NEARBY_WIFI_DEVICES)
                    == PackageManager.PERMISSION_GRANTED;
        }
        return false;
    }

    private static boolean hasLocationPermission(Context context) {
        return context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)
                == PackageManager.PERMISSION_GRANTED
                || context.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION)
                == PackageManager.PERMISSION_GRANTED;
    }

    private static String normalizeSsid(String ssid) {
        String value = ssid == null ? "" : ssid.trim();
        if (value.startsWith("\"") && value.endsWith("\"") && value.length() > 1) {
            value = value.substring(1, value.length() - 1);
        }
        if ("<unknown ssid>".equalsIgnoreCase(value)) {
            return "";
        }
        return value;
    }
}
