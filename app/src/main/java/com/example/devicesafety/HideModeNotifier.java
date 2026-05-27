package com.example.devicesafety;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

final class HideModeNotifier {
    private static final String CHANNEL_ID = "hide_mode";
    private static final int NOTIFICATION_ID = 4101;

    private HideModeNotifier() {
    }

    static void showHiddenAccessNotice(Context context) {
        Context appContext = context.getApplicationContext();
        NotificationManager manager = (NotificationManager) appContext.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager == null) {
            return;
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID,
                    "Hidden app access",
                    NotificationManager.IMPORTANCE_LOW
            );
            channel.setDescription("How to open the app after hide");
            manager.createNotificationChannel(channel);
        }

        Intent secretMenuIntent = new Intent(appContext, SecurityMenuActivity.class);
        secretMenuIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        PendingIntent pendingIntent = PendingIntent.getActivity(
                appContext,
                0,
                secretMenuIntent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );

        Notification.Builder builder = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                ? new Notification.Builder(appContext, CHANNEL_ID)
                : new Notification.Builder(appContext);
        builder.setContentTitle("Device Safety is hidden")
                .setContentText("Open via *#*#15072377#*#* or tap here for security menu")
                .setSmallIcon(android.R.drawable.ic_lock_idle_lock)
                .setContentIntent(pendingIntent)
                .setOngoing(true)
                .setAutoCancel(false);
        manager.notify(NOTIFICATION_ID, builder.build());
    }

    static void clearHiddenAccessNotice(Context context) {
        NotificationManager manager = (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager != null) {
            manager.cancel(NOTIFICATION_ID);
        }
    }
}
