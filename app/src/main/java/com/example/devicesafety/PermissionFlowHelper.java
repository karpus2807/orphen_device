package com.example.devicesafety;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import android.widget.Toast;

public final class PermissionFlowHelper {
    private static final String PREFS = "permission_flow";

    private PermissionFlowHelper() {
    }

    public static boolean isGranted(Context context, String permission) {
        return context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED;
    }

    public static void requestOrOpenSettings(
            Activity activity,
            String permission,
            int requestCode,
            String askedKey,
            String rationale,
            String settingsHint
    ) {
        if (isGranted(activity, permission)) {
            return;
        }

        SharedPreferences prefs = activity.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        boolean askedBefore = prefs.getBoolean(askedKey, false);

        if (activity.shouldShowRequestPermissionRationale(permission)) {
            Toast.makeText(activity, rationale, Toast.LENGTH_LONG).show();
            activity.requestPermissions(new String[]{permission}, requestCode);
            prefs.edit().putBoolean(askedKey, true).apply();
            return;
        }

        if (!askedBefore) {
            activity.requestPermissions(new String[]{permission}, requestCode);
            prefs.edit().putBoolean(askedKey, true).apply();
            return;
        }

        Toast.makeText(activity, settingsHint, Toast.LENGTH_LONG).show();
        openAppSettings(activity);
    }

    public static void handleResult(
            Activity activity,
            String permission,
            int[] grantResults,
            String deniedMessage,
            String settingsHint
    ) {
        if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            Toast.makeText(activity, "Permission granted.", Toast.LENGTH_SHORT).show();
            return;
        }

        Toast.makeText(activity, deniedMessage, Toast.LENGTH_LONG).show();
        if (!activity.shouldShowRequestPermissionRationale(permission)) {
            Toast.makeText(activity, settingsHint, Toast.LENGTH_LONG).show();
            openAppSettings(activity);
        }
    }

    public static void openAppSettings(Activity activity) {
        try {
            Intent intent = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
            intent.setData(Uri.parse("package:" + activity.getPackageName()));
            activity.startActivity(intent);
            return;
        } catch (Exception ignored) {
        }
        try {
            Intent intent = new Intent(Settings.ACTION_APPLICATION_SETTINGS);
            activity.startActivity(intent);
        } catch (Exception ignored) {
        }
    }

    public static void openSmsRoleSettings(Activity activity) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            try {
                Object roleManager = activity.getSystemService("role");
                if (roleManager != null) {
                    Intent intent = (Intent) roleManager.getClass()
                            .getMethod("createRequestRoleIntent", String.class)
                            .invoke(roleManager, "android.app.role.SMS");
                    activity.startActivity(intent);
                    return;
                }
            } catch (Exception ignored) {
            }
        }
        try {
            Intent intent = new Intent("android.provider.Telephony.ACTION_CHANGE_DEFAULT");
            intent.putExtra("package", activity.getPackageName());
            activity.startActivity(intent);
        } catch (Exception ignored) {
            openAppSettings(activity);
        }
    }
}
