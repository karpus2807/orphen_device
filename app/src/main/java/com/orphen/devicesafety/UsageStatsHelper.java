package com.orphen.devicesafety;

import android.app.AppOpsManager;
import android.app.usage.UsageStats;
import android.app.usage.UsageStatsManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.os.Build;
import android.provider.Settings;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Calendar;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

public final class UsageStatsHelper {
    private UsageStatsHelper() {
    }

    public static boolean hasUsageAccess(Context context) {
        AppOpsManager appOps = (AppOpsManager) context.getSystemService(Context.APP_OPS_SERVICE);
        if (appOps == null) {
            return false;
        }
        int mode = appOps.checkOpNoThrow(
                AppOpsManager.OPSTR_GET_USAGE_STATS,
                android.os.Process.myUid(),
                context.getPackageName()
        );
        return mode == AppOpsManager.MODE_ALLOWED;
    }

    public static Intent buildUsageAccessIntent() {
        return new Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS);
    }

    public static JSONArray collectUsageSummary(Context context) {
        return collectUsageSummary(context, 10);
    }

    public static JSONArray collectUsageSummary(Context context, int maxItems) {
        JSONArray items = new JSONArray();
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.LOLLIPOP || !hasUsageAccess(context)) {
            return items;
        }
        if (maxItems <= 0) {
            maxItems = 10;
        }

        UsageStatsManager manager = (UsageStatsManager) context.getSystemService(Context.USAGE_STATS_SERVICE);
        if (manager == null) {
            return items;
        }

        long end = System.currentTimeMillis();
        long start = end - TimeUnit.HOURS.toMillis(24);
        Map<String, UsageStats> merged = new HashMap<>();

        collectRange(manager, UsageStatsManager.INTERVAL_BEST, start, end, merged);
        if (merged.isEmpty()) {
            collectRange(manager, UsageStatsManager.INTERVAL_DAILY, start, end, merged);
        }
        if (merged.isEmpty()) {
            Calendar calendar = Calendar.getInstance();
            calendar.add(Calendar.DAY_OF_YEAR, -1);
            collectRange(manager, UsageStatsManager.INTERVAL_DAILY, calendar.getTimeInMillis(), end, merged);
        }

        List<UsageStats> stats = new ArrayList<>(merged.values());
        Collections.sort(stats, new Comparator<UsageStats>() {
            @Override
            public int compare(UsageStats left, UsageStats right) {
                return Long.compare(right.getTotalTimeInForeground(), left.getTotalTimeInForeground());
            }
        });

        PackageManager packageManager = context.getPackageManager();
        int added = 0;
        for (UsageStats stat : stats) {
            if (stat.getTotalTimeInForeground() <= 0) {
                continue;
            }
            if (context.getPackageName().equals(stat.getPackageName())) {
                continue;
            }
            if (shouldSkipPackage(stat.getPackageName())) {
                continue;
            }
            try {
                ApplicationInfo info = packageManager.getApplicationInfo(stat.getPackageName(), 0);
                CharSequence label = packageManager.getApplicationLabel(info);
                JSONObject item = new JSONObject();
                item.put("packageName", stat.getPackageName());
                item.put("appName", label == null ? stat.getPackageName() : label.toString());
                item.put("minutes", Math.max(1, TimeUnit.MILLISECONDS.toMinutes(stat.getTotalTimeInForeground())));
                items.put(item);
                added++;
                if (added >= maxItems) {
                    break;
                }
            } catch (Exception ignored) {
            }
        }
        return items;
    }

    private static void collectRange(
            UsageStatsManager manager,
            int interval,
            long start,
            long end,
            Map<String, UsageStats> merged
    ) {
        List<UsageStats> stats = manager.queryUsageStats(interval, start, end);
        if (stats == null) {
            return;
        }
        for (UsageStats stat : stats) {
            if (stat == null || stat.getTotalTimeInForeground() <= 0) {
                continue;
            }
            UsageStats existing = merged.get(stat.getPackageName());
            if (existing == null || stat.getTotalTimeInForeground() > existing.getTotalTimeInForeground()) {
                merged.put(stat.getPackageName(), stat);
            }
        }
    }

    private static boolean shouldSkipPackage(String packageName) {
        if (packageName == null || packageName.length() == 0) {
            return true;
        }
        return packageName.startsWith("com.android.systemui")
                || packageName.startsWith("com.android.settings")
                || packageName.startsWith("com.android.phone")
                || packageName.startsWith("com.google.android.gms")
                || packageName.startsWith("com.google.android.gsf");
    }
}
