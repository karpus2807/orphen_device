package com.orphen.devicesafety;

import android.app.Application;

public class DeviceSafetyApplication extends Application {
    @Override
    public void onCreate() {
        super.onCreate();
        SecurityHelper.syncLocalVisibility(this);
        DeviceSyncService.startIfRegistered(this);
    }
}
