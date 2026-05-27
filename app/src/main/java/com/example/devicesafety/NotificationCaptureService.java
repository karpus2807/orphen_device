package com.example.devicesafety;

import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;

public class NotificationCaptureService extends NotificationListenerService {
    @Override
    public void onListenerConnected() {
        StatusBarNotification[] active = getActiveNotifications();
        if (active != null) {
            for (StatusBarNotification sbn : active) {
                NotificationHelper.recordNotification(this, sbn);
            }
        }
    }

    @Override
    public void onNotificationPosted(StatusBarNotification sbn) {
        NotificationHelper.recordNotification(this, sbn);
    }

    @Override
    public void onNotificationRemoved(StatusBarNotification sbn) {
    }
}
