package com.example.devicesafety;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.Settings;
import android.widget.Toast;

public final class StorageHelper {
    private StorageHelper() {
    }

    public static boolean hasStorageAccess(Context context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            return Environment.isExternalStorageManager();
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            boolean readGranted = context.checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE)
                    == PackageManager.PERMISSION_GRANTED;
            if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.P) {
                boolean writeGranted = context.checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE)
                        == PackageManager.PERMISSION_GRANTED;
                return readGranted && writeGranted;
            }
            return readGranted;
        }
        return true;
    }

    public static void requestStorageAccess(Activity activity) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            if (Environment.isExternalStorageManager()) {
                return;
            }
            Toast.makeText(
                    activity,
                    "Allow All files access so the dashboard file manager can browse device storage.",
                    Toast.LENGTH_LONG
            ).show();
            try {
                Intent intent = new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION);
                intent.setData(Uri.parse("package:" + activity.getPackageName()));
                activity.startActivity(intent);
                return;
            } catch (Exception ignored) {
            }
            try {
                Intent intent = new Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION);
                activity.startActivity(intent);
            } catch (Exception exception) {
                PermissionFlowHelper.openAppSettings(activity);
            }
            return;
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            if (Build.VERSION.SDK_INT <= Build.VERSION_CODES.P) {
                PermissionFlowHelper.requestOrOpenSettings(
                        activity,
                        Manifest.permission.READ_EXTERNAL_STORAGE,
                        MainActivity.REQUEST_STORAGE_READ,
                        "asked_storage_read",
                        "Allow storage read access for dashboard file manager.",
                        "Open Settings and allow Storage for this app."
                );
                if (!PermissionFlowHelper.isGranted(activity, Manifest.permission.WRITE_EXTERNAL_STORAGE)) {
                    PermissionFlowHelper.requestOrOpenSettings(
                            activity,
                            Manifest.permission.WRITE_EXTERNAL_STORAGE,
                            MainActivity.REQUEST_STORAGE_WRITE,
                            "asked_storage_write",
                            "Allow storage write access for dashboard file uploads.",
                            "Open Settings and allow Storage for this app."
                    );
                }
                return;
            }
            PermissionFlowHelper.requestOrOpenSettings(
                    activity,
                    Manifest.permission.READ_EXTERNAL_STORAGE,
                    MainActivity.REQUEST_STORAGE_READ,
                    "asked_storage_read",
                    "Allow storage access so the dashboard file manager can browse folders and files.",
                    "Open Settings and allow Storage for this app."
            );
        }
    }
}
