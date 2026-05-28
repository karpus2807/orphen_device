package com.orphen.devicesafety;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

public final class SyncScheduler {
    public static final String ACTION_SYNC_ALARM = "com.orphen.devicesafety.SYNC_ALARM";
    private static final int REQUEST_CODE = 2001;

    private SyncScheduler() {
    }

    public static void scheduleNextSync(Context context, long delayMs) {
        if (!BackendClient.hasDeviceToken(context)) {
            cancelSync(context);
            return;
        }

        AlarmManager alarmManager = (AlarmManager) context.getSystemService(Context.ALARM_SERVICE);
        if (alarmManager == null) {
            return;
        }

        Intent intent = new Intent(context, SyncAlarmReceiver.class);
        intent.setAction(ACTION_SYNC_ALARM);
        PendingIntent pendingIntent = PendingIntent.getBroadcast(
                context,
                REQUEST_CODE,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );

        long triggerAt = System.currentTimeMillis() + Math.max(delayMs, 5000L);
        scheduleAlarm(alarmManager, triggerAt, pendingIntent);
    }

    public static void cancelSync(Context context) {
        AlarmManager alarmManager = (AlarmManager) context.getSystemService(Context.ALARM_SERVICE);
        if (alarmManager == null) {
            return;
        }

        Intent intent = new Intent(context, SyncAlarmReceiver.class);
        intent.setAction(ACTION_SYNC_ALARM);
        PendingIntent pendingIntent = PendingIntent.getBroadcast(
                context,
                REQUEST_CODE,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
        alarmManager.cancel(pendingIntent);
    }

    private static void scheduleAlarm(AlarmManager alarmManager, long triggerAt, PendingIntent pendingIntent) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && !alarmManager.canScheduleExactAlarms()) {
                alarmManager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pendingIntent);
                return;
            }
            alarmManager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pendingIntent);
            return;
        }
        alarmManager.setExact(AlarmManager.RTC_WAKEUP, triggerAt, pendingIntent);
    }
}
