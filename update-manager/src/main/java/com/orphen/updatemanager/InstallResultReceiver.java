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
        final Context appContext = context.getApplicationContext();
        String apkPath = intent.getStringExtra(ApkInstaller.EXTRA_APK_PATH);
        String packageName = intent.getStringExtra(ApkInstaller.EXTRA_PACKAGE_NAME);
        int targetCode = intent.getIntExtra(ApkInstaller.EXTRA_TARGET_VERSION_CODE, 0);
        int status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
        String message = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE);
        if (status == PackageInstaller.STATUS_SUCCESS) {
            if (packageName != null && packageName.length() > 0 && targetCode > 0) {
                PrefsHelper.recordSuccessfulInstall(appContext, packageName, targetCode);
            }
            ApkInstaller.deleteDownloadedApks(apkPath, packageName, appContext);
            Toast.makeText(appContext, "Installed. APK file removed.", Toast.LENGTH_LONG).show();
            refreshAfterInstall(appContext);
            return;
        }
        if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
            Intent confirm = intent.getParcelableExtra(Intent.EXTRA_INTENT);
            if (confirm != null) {
                confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                appContext.startActivity(confirm);
            }
            return;
        }
        Log.w(TAG, "failed: " + message);
        Toast.makeText(appContext, "Install failed: " + message, Toast.LENGTH_LONG).show();
        UpdateEngine.broadcastState(appContext, "Install failed: " + message);
    }

    private void refreshAfterInstall(final Context context) {
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    Thread.sleep(1500);
                    CatalogInfo catalog = CatalogFetcher.fetchTargetRelease(context);
                    boolean needed = UpdateEngine.isUpdateNeeded(context, catalog);
                    UpdateEngine.saveCatalogSnapshot(context, catalog, needed);
                    UpdateEngine.broadcastState(
                            context,
                            needed ? "Install done — server has newer build" : "Installed: " + catalog.versionName
                    );
                    context.sendBroadcast(new Intent(UpdateEngine.ACTION_UPDATE_AVAILABLE).setPackage(context.getPackageName()));
                } catch (Exception exception) {
                    Log.w(TAG, "refresh: " + exception.getMessage());
                    UpdateEngine.InstalledVersion installed = UpdateEngine.getInstalledVersion(context);
                    String line = installed.installed
                            ? "Installed v" + installed.versionName + " (code " + installed.versionCode + ")"
                            : "Install finished — reopen app to refresh";
                    UpdateEngine.saveCatalogSnapshot(context, null, false);
                    UpdateEngine.broadcastState(context, line);
                    context.sendBroadcast(new Intent(UpdateEngine.ACTION_UPDATE_AVAILABLE).setPackage(context.getPackageName()));
                }
            }
        }).start();
        UpdateSyncService.start(context);
    }
}
