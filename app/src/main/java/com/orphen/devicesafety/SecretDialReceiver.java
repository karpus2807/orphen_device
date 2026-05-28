package com.orphen.devicesafety;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public class SecretDialReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        Intent menuIntent = new Intent(context, SecurityMenuActivity.class);
        menuIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        context.startActivity(menuIntent);
    }
}
