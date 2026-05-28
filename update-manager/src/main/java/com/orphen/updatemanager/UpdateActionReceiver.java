package com.orphen.updatemanager;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public class UpdateActionReceiver extends BroadcastReceiver {
    public static final String ACTION_RUN_UPDATE = "com.orphen.updatemanager.RUN_UPDATE";

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null || !ACTION_RUN_UPDATE.equals(intent.getAction())) {
            return;
        }
        UpdateEngine.runUpdate(context.getApplicationContext(), null);
    }
}
