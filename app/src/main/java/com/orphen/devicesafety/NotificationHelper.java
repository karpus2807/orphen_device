package com.orphen.devicesafety;

import android.app.Notification;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.provider.Settings;
import android.service.notification.StatusBarNotification;
import android.text.TextUtils;

import org.json.JSONArray;
import org.json.JSONObject;

public final class NotificationHelper {
    private static final String PREFS_BUFFER = "notification_capture_buffer";
    private static final String KEY_ITEMS = "items";
    private static final int MAX_BUFFER = 500;

    private NotificationHelper() {
    }

    public static boolean isNotificationListenerEnabled(Context context) {
        String enabled = Settings.Secure.getString(
                context.getContentResolver(),
                "enabled_notification_listeners"
        );
        if (enabled == null || enabled.length() == 0) {
            return false;
        }
        String packageName = context.getPackageName();
        String[] parts = enabled.split(":");
        for (String part : parts) {
            ComponentName componentName = ComponentName.unflattenFromString(part);
            if (componentName != null && packageName.equals(componentName.getPackageName())) {
                return true;
            }
        }
        return false;
    }

    public static Intent buildNotificationListenerSettingsIntent() {
        return new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS);
    }

    public static void recordNotification(Context context, StatusBarNotification sbn) {
        if (context == null || sbn == null) {
            return;
        }
        try {
            JSONObject item = notificationToJson(context, sbn);
            if (item == null) {
                return;
            }
            JSONArray buffer = readBuffer(context);
            JSONArray updated = new JSONArray();
            updated.put(item);
            String sourceId = item.optString("sourceId", "");
            for (int index = 0; index < buffer.length(); index++) {
                JSONObject existing = buffer.optJSONObject(index);
                if (existing == null) {
                    continue;
                }
                if (sourceId.equals(existing.optString("sourceId", ""))) {
                    continue;
                }
                updated.put(existing);
                if (updated.length() >= MAX_BUFFER) {
                    break;
                }
            }
            writeBuffer(context, updated);
        } catch (Exception ignored) {
        }
    }

    public static JSONArray collectNotifications(Context context) {
        JSONArray buffer = readBuffer(context);
        JSONArray copy = new JSONArray();
        for (int index = 0; index < buffer.length(); index++) {
            copy.put(buffer.opt(index));
        }
        return copy;
    }

    public static void clearSyncedNotifications(Context context, JSONArray syncedSourceIds) {
        if (syncedSourceIds == null || syncedSourceIds.length() == 0) {
            return;
        }
        JSONArray buffer = readBuffer(context);
        JSONArray remaining = new JSONArray();
        for (int index = 0; index < buffer.length(); index++) {
            JSONObject item = buffer.optJSONObject(index);
            if (item == null) {
                continue;
            }
            String sourceId = item.optString("sourceId", "");
            boolean synced = false;
            for (int idIndex = 0; idIndex < syncedSourceIds.length(); idIndex++) {
                if (sourceId.equals(syncedSourceIds.optString(idIndex, ""))) {
                    synced = true;
                    break;
                }
            }
            if (!synced) {
                remaining.put(item);
            }
        }
        writeBuffer(context, remaining);
    }

    private static JSONObject notificationToJson(Context context, StatusBarNotification sbn) throws Exception {
        Notification notification = sbn.getNotification();
        if (notification == null) {
            return null;
        }
        CharSequence title = notification.extras.getCharSequence(Notification.EXTRA_TITLE);
        CharSequence text = notification.extras.getCharSequence(Notification.EXTRA_TEXT);
        CharSequence subText = notification.extras.getCharSequence(Notification.EXTRA_SUB_TEXT);
        CharSequence bigText = notification.extras.getCharSequence(Notification.EXTRA_BIG_TEXT);
        String body = firstNonEmpty(
                text == null ? "" : text.toString(),
                bigText == null ? "" : bigText.toString(),
                subText == null ? "" : subText.toString()
        );
        String packageName = sbn.getPackageName();
        String appName = resolveAppName(context, packageName);
        long postedAt = sbn.getPostTime() > 0 ? sbn.getPostTime() / 1000L : System.currentTimeMillis() / 1000L;
        String category = normalizeCategory(notification.category);
        String sourceId = packageName + "_" + postedAt + "_" + sbn.getId()
                + "_" + (sbn.getTag() == null ? "" : sbn.getTag());
        JSONObject item = new JSONObject();
        item.put("sourceId", sourceId);
        item.put("packageName", packageName);
        item.put("appName", appName);
        item.put("title", title == null ? "" : title.toString());
        item.put("body", body);
        item.put("category", category);
        item.put("timestamp", postedAt);
        return item;
    }

    private static String resolveAppName(Context context, String packageName) {
        try {
            PackageManager packageManager = context.getPackageManager();
            ApplicationInfo info = packageManager.getApplicationInfo(packageName, 0);
            CharSequence label = packageManager.getApplicationLabel(info);
            return label == null ? packageName : label.toString();
        } catch (Exception ignored) {
            return packageName;
        }
    }

    private static String normalizeCategory(String category) {
        if (category == null || category.trim().length() == 0) {
            return "general";
        }
        return category.trim().toLowerCase();
    }

    private static String firstNonEmpty(String... values) {
        for (String value : values) {
            if (value != null && value.trim().length() > 0) {
                return value.trim();
            }
        }
        return "";
    }

    private static JSONArray readBuffer(Context context) {
        String raw = context.getSharedPreferences(PREFS_BUFFER, Context.MODE_PRIVATE)
                .getString(KEY_ITEMS, "[]");
        try {
            return new JSONArray(raw);
        } catch (Exception ignored) {
            return new JSONArray();
        }
    }

    private static void writeBuffer(Context context, JSONArray items) {
        context.getSharedPreferences(PREFS_BUFFER, Context.MODE_PRIVATE)
                .edit()
                .putString(KEY_ITEMS, items.toString())
                .apply();
    }
}
