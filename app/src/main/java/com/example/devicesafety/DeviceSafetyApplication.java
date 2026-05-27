package com.example.devicesafety;

import android.app.Application;

public class DeviceSafetyApplication extends Application {
    @Override
    public void onCreate() {
        super.onCreate();
        SecurityHelper.syncLocalVisibility(this);
    }
}
