package com.orphen.updatemanager;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (PrefsHelper.prefs(context).getString("serverHost", "").length() > 0) {
            UpdateSyncService.start(context);
        }
    }
}
