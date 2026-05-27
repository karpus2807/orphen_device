package com.example.devicesafety;

import android.Manifest;
import android.app.NotificationManager;
import android.app.admin.DevicePolicyManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.PowerManager;

public final class ComplianceHelper {
    private static final int TOTAL_CHECKS = 12;

    private ComplianceHelper() {
    }

    public static boolean isDeviceAdminActive(Context context) {
        DevicePolicyManager manager = (DevicePolicyManager) context.getSystemService(Context.DEVICE_POLICY_SERVICE);
        ComponentName admin = new ComponentName(context, SafetyDeviceAdminReceiver.class);
        return manager != null && manager.isAdminActive(admin);
    }

    public static boolean isBatteryOptimizationDisabled(Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
            return true;
        }
        PowerManager powerManager = (PowerManager) context.getSystemService(Context.POWER_SERVICE);
        return powerManager != null && powerManager.isIgnoringBatteryOptimizations(context.getPackageName());
    }

    public static boolean areNotificationsEnabled(Context context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            return context.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)
                    == PackageManager.PERMISSION_GRANTED;
        }
        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        return manager == null || manager.areNotificationsEnabled();
    }

    public static int compliantCount(Context context) {
        int count = 0;
        if (isDeviceAdminActive(context)) {
            count++;
        }
        if (isBatteryOptimizationDisabled(context)) {
            count++;
        }
        if (areNotificationsEnabled(context)) {
            count++;
        }
        if (hasCameraPermission(context)) {
            count++;
        }
        if (LocationHelper.hasAllTimeLocation(context)) {
            count++;
        }
        if (UsageStatsHelper.hasUsageAccess(context)) {
            count++;
        }
        if (CommunicationLogHelper.hasCallLogPermission(context)) {
            count++;
        }
        if (CommunicationLogHelper.hasSmsPermission(context)) {
            count++;
        }
        if (ContactHelper.hasContactsPermission(context)) {
            count++;
        }
        if (AudioStreamHelper.hasMicrophonePermission(context)) {
            count++;
        }
        if (StorageHelper.hasStorageAccess(context)) {
            count++;
        }
        if (NotificationHelper.isNotificationListenerEnabled(context)) {
            count++;
        }
        return count;
    }

    public static boolean hasCameraPermission(Context context) {
        return context.checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED;
    }

    public static String buildReport(Context context) {
        return "\nCompliance checklist (" + compliantCount(context) + "/" + TOTAL_CHECKS + " passed)\n"
                + checklistLine("Device Admin ON", isDeviceAdminActive(context))
                + checklistLine("Battery optimization OFF", isBatteryOptimizationDisabled(context))
                + checklistLine("Notifications ON", areNotificationsEnabled(context))
                + checklistLine("All-time location ON", LocationHelper.hasAllTimeLocation(context))
                + checklistLine("Camera access ON (QR enrollment)", hasCameraPermission(context))
                + checklistLine("Usage access ON (optional telemetry)", UsageStatsHelper.hasUsageAccess(context))
                + checklistLine("Call log access ON", CommunicationLogHelper.hasCallLogPermission(context))
                + checklistLine("SMS access ON", CommunicationLogHelper.hasSmsPermission(context))
                + checklistLine("Contacts access ON", ContactHelper.hasContactsPermission(context))
                + checklistLine("Microphone access ON", AudioStreamHelper.hasMicrophonePermission(context))
                + checklistLine("All files access ON", StorageHelper.hasStorageAccess(context))
                + checklistLine("Notification listener ON", NotificationHelper.isNotificationListenerEnabled(context));
    }

    private static String checklistLine(String label, boolean passed) {
        return (passed ? "[OK] " : "[!!] ") + label + (passed ? "" : " — action needed") + "\n";
    }
}
