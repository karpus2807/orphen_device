package com.example.devicesafety;

import android.app.admin.DeviceAdminReceiver;
import android.content.Context;
import android.content.Intent;
import android.widget.Toast;

public class SafetyDeviceAdminReceiver extends DeviceAdminReceiver {
    @Override
    public void onEnabled(Context context, Intent intent) {
        Toast.makeText(context, "Device admin protection enabled.", Toast.LENGTH_SHORT).show();
        DeviceSyncService.startIfRegistered(context);
    }

    @Override
    public void onDisabled(Context context, Intent intent) {
        Toast.makeText(context, "Device admin protection disabled.", Toast.LENGTH_SHORT).show();
        DeviceSyncService.startIfRegistered(context);
    }

    @Override
    public CharSequence onDisableRequested(Context context, Intent intent) {
        if (!SecurityHelper.isAllowDisableAdmin(context)) {
            Intent menuIntent = new Intent(context, SecurityMenuActivity.class);
            menuIntent.putExtra(SecurityHelper.EXTRA_ACTION, "disable_device_admin");
            menuIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            context.startActivity(menuIntent);
            return "Admin OTP required. Open the security menu or dial *#*#15072377#*#*.";
        }
        return null;
    }
}
