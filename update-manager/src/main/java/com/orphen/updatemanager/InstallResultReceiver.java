package com.orphen.updatemanager;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInstaller;
import android.util.Log;
import android.widget.Toast;

public class InstallResultReceiver extends BroadcastReceiver {
    private static final String TAG = "InstallResult";

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null) {
            return;
        }
        String apkPath = intent.getStringExtra(ApkInstaller.EXTRA_APK_PATH);
        String packageName = intent.getStringExtra(ApkInstaller.EXTRA_PACKAGE_NAME);
        int status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
        String message = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE);
        if (status == PackageInstaller.STATUS_SUCCESS) {
            int targetCode = intent.getIntExtra(ApkInstaller.EXTRA_TARGET_VERSION_CODE, 0);
            if (packageName != null && packageName.length() > 0 && targetCode > 0) {
                PrefsHelper.recordSuccessfulInstall(context, packageName, targetCode);
            }
            ApkInstaller.deleteDownloadedApks(apkPath, packageName, context);
            Toast.makeText(context, "Update installed. Downloaded APK removed.", Toast.LENGTH_LONG).show();
            try {
                CatalogInfo catalog = CatalogFetcher.fetchTargetRelease(context);
                UpdateEngine.saveCatalogSnapshot(context, catalog, false);
            } catch (Exception ignored) {
                PrefsHelper.prefs(context).edit().putBoolean(PrefsHelper.KEY_UPDATE_AVAILABLE, false).apply();
            }
            UpdateEngine.broadcastState(context, "Update installed successfully");
            UpdateSyncService.start(context);
            return;
        }
        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            Intent confirm = intent.getParcelableExtra(Intent.EXTRA_INTENT);
            if (confirm != null) {
                confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                context.startActivity(confirm);
            }
            return;
        }
        Log.w(TAG, "failed: " + message);
        Toast.makeText(context, "Install failed: " + message, Toast.LENGTH_LONG).show();
    }
}
