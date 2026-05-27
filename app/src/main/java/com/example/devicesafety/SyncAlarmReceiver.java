package com.example.devicesafety;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public class SyncAlarmReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null || !SyncScheduler.ACTION_SYNC_ALARM.equals(intent.getAction())) {
            return;
        }
        if (!BackendClient.hasDeviceToken(context)) {
            SyncScheduler.cancelSync(context);
            return;
        }
        DeviceSyncService.startIfRegistered(context);
    }
}
