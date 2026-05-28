package com.orphen.devicesafety;

import android.content.Context;
import android.content.Intent;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.NetworkRequest;
import android.net.wifi.WifiNetworkSpecifier;
import android.os.Build;
import android.provider.Settings;

public final class WifiProfileHelper {
    private WifiProfileHelper() {
    }

    public static String applyProfile(Context context, String payload) throws Exception {
        String ssid = BackendClient.extractJsonValue(payload, "ssid").trim();
        String password = BackendClient.extractJsonValue(payload, "password");
        String security = BackendClient.extractJsonValue(payload, "security").trim();
        if (ssid.length() == 0) {
            throw new Exception("Wi-Fi SSID is required");
        }

        String prerequisite = RemoteSettingsHelper.wifiConnectPrerequisiteMessage(context);
        if (prerequisite.length() > 0) {
            throw new Exception(prerequisite);
        }

        try {
            RemoteSettingsHelper.enableWifi(context);
        } catch (Exception ignored) {
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            WifiNetworkSpecifier.Builder builder = new WifiNetworkSpecifier.Builder().setSsid(ssid);
            if (!"OPEN".equalsIgnoreCase(security)) {
                if (password == null || password.length() == 0) {
                    throw new Exception("Wi-Fi password is required for secured networks");
                }
                builder.setWpa2Passphrase(password);
            }
            NetworkRequest request = new NetworkRequest.Builder()
                    .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
                    .setNetworkSpecifier(builder.build())
                    .build();
            ConnectivityManager manager = (ConnectivityManager) context.getSystemService(Context.CONNECTIVITY_SERVICE);
            if (manager == null) {
                throw new Exception("Connectivity service unavailable");
            }
            manager.requestNetwork(request, new ConnectivityManager.NetworkCallback() {
                @Override
                public void onAvailable(Network network) {
                }

                @Override
                public void onUnavailable() {
                }
            });
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                try {
                    Intent panel = new Intent(Settings.Panel.ACTION_INTERNET_CONNECTIVITY);
                    panel.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    context.startActivity(panel);
                } catch (Exception ignored) {
                }
            }
            return "Connecting to " + ssid + " — confirm the system Wi-Fi prompt on the device.";
        }

        Intent panelIntent = new Intent(Settings.Panel.ACTION_WIFI);
        panelIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        context.startActivity(panelIntent);
        return "Opened Wi-Fi settings for manual connection to " + ssid;
    }
}
