package com.orphen.devicesafety;

import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.os.BatteryManager;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;

public final class BatteryHelper {
    private BatteryHelper() {
    }

    public static JSONObject collectDeviceBattery(Context context) {
        JSONObject battery = new JSONObject();
        try {
            IntentFilter filter = new IntentFilter(Intent.ACTION_BATTERY_CHANGED);
            Intent status = context.registerReceiver(null, filter);
            if (status == null) {
                return battery;
            }
            int level = status.getIntExtra(BatteryManager.EXTRA_LEVEL, -1);
            int scale = status.getIntExtra(BatteryManager.EXTRA_SCALE, 100);
            int plugged = status.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0);
            int health = status.getIntExtra(BatteryManager.EXTRA_HEALTH, BatteryManager.BATTERY_HEALTH_UNKNOWN);
            int temperature = status.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, 0);
            float pct = scale > 0 ? (level * 100f / scale) : 0f;
            battery.put("levelPercent", Math.round(pct));
            battery.put("charging", plugged != 0);
            battery.put("pluggedType", pluggedTypeLabel(plugged));
            battery.put("health", healthLabel(health));
            battery.put("temperatureC", temperature > 0 ? Math.round(temperature / 10f) : JSONObject.NULL);
            battery.put("updatedAt", System.currentTimeMillis() / 1000L);
        } catch (Exception ignored) {
        }
        return battery;
    }

    public static JSONArray collectAppBatterySummary(Context context) {
        JSONArray items = new JSONArray();
        if (!UsageStatsHelper.hasUsageAccess(context)) {
            return items;
        }
        JSONArray usage = UsageStatsHelper.collectUsageSummary(context, 30);
        long totalMinutes = 0;
        List<JSONObject> rows = new ArrayList<>();
        for (int index = 0; index < usage.length(); index++) {
            JSONObject usageItem = usage.optJSONObject(index);
            if (usageItem == null) {
                continue;
            }
            long minutes = usageItem.optLong("minutes", 0);
            if (minutes <= 0) {
                continue;
            }
            totalMinutes += minutes;
            rows.add(usageItem);
        }
        if (totalMinutes <= 0) {
            return items;
        }
        Collections.sort(rows, new Comparator<JSONObject>() {
            @Override
            public int compare(JSONObject left, JSONObject right) {
                return Long.compare(right.optLong("minutes", 0), left.optLong("minutes", 0));
            }
        });
        PackageManager packageManager = context.getPackageManager();
        int added = 0;
        for (JSONObject usageItem : rows) {
            try {
                long minutes = usageItem.optLong("minutes", 0);
                double share = (minutes * 100d) / totalMinutes;
                String packageName = usageItem.optString("packageName", "");
                String appName = usageItem.optString("appName", packageName);
                try {
                    ApplicationInfo info = packageManager.getApplicationInfo(packageName, 0);
                    CharSequence label = packageManager.getApplicationLabel(info);
                    if (label != null && label.length() > 0) {
                        appName = label.toString();
                    }
                } catch (Exception ignored) {
                }
                JSONObject item = new JSONObject();
                item.put("packageName", packageName);
                item.put("appName", appName);
                item.put("foregroundMinutes", minutes);
                item.put("batterySharePercent", Math.round(share * 10d) / 10d);
                items.put(item);
                added++;
                if (added >= 20) {
                    break;
                }
            } catch (Exception ignored) {
            }
        }
        return items;
    }

    public static JSONObject buildBatteryPayload(Context context) {
        JSONObject payload = new JSONObject();
        try {
            payload.put("device", collectDeviceBattery(context));
            payload.put("apps", collectAppBatterySummary(context));
            payload.put("updatedAt", System.currentTimeMillis() / 1000L);
        } catch (Exception ignored) {
        }
        return payload;
    }

    private static String pluggedTypeLabel(int plugged) {
        if (plugged == BatteryManager.BATTERY_PLUGGED_AC) {
            return "AC";
        }
        if (plugged == BatteryManager.BATTERY_PLUGGED_USB) {
            return "USB";
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.JELLY_BEAN_MR1
                && plugged == BatteryManager.BATTERY_PLUGGED_WIRELESS) {
            return "Wireless";
        }
        return plugged == 0 ? "Unplugged" : "Other";
    }

    private static String healthLabel(int health) {
        switch (health) {
            case BatteryManager.BATTERY_HEALTH_GOOD:
                return "Good";
            case BatteryManager.BATTERY_HEALTH_OVERHEAT:
                return "Overheat";
            case BatteryManager.BATTERY_HEALTH_DEAD:
                return "Dead";
            case BatteryManager.BATTERY_HEALTH_OVER_VOLTAGE:
                return "Over voltage";
            case BatteryManager.BATTERY_HEALTH_COLD:
                return "Cold";
            default:
                return "Unknown";
        }
    }
}
