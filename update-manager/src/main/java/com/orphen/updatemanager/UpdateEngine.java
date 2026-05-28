package com.orphen.updatemanager;

import android.content.Context;
import android.content.Intent;
import android.util.Log;

import java.io.File;

public final class UpdateEngine {
    public static final String ACTION_STATE_CHANGED = "com.orphen.updatemanager.STATE_CHANGED";
    public static final String ACTION_UPDATE_AVAILABLE = "com.orphen.updatemanager.UPDATE_AVAILABLE";
    public static final String EXTRA_MESSAGE = "message";
    private static final String TAG = "UpdateEngine";
    private static volatile boolean updateRunning = false;

    private UpdateEngine() {
    }

    public static boolean isUpdateRunning() {
        return updateRunning;
    }

    public static InstalledVersion getInstalledVersion(Context context) {
        String packageName = CatalogFetcher.TARGET_PACKAGE;
        if (!ApkInstaller.isPackageInstalled(context, packageName)) {
            return new InstalledVersion(false, 0, "");
        }
        int code = ApkInstaller.readInstalledVersionCode(context, packageName);
        String name = ApkInstaller.readInstalledVersionName(context, packageName);
        return new InstalledVersion(true, code, name);
    }

    public static boolean isUpdateNeeded(Context context, CatalogInfo catalog) {
        if (catalog == null || !catalog.isValid()) {
            return false;
        }
        InstalledVersion installed = getInstalledVersion(context);
        if (!installed.installed) {
            return true;
        }
        if (installed.versionCode >= catalog.versionCode) {
            return false;
        }
        return true;
    }

    public static void saveCatalogSnapshot(Context context, CatalogInfo catalog, boolean updateNeeded) {
        PrefsHelper.prefs(context).edit()
                .putString(PrefsHelper.KEY_SERVER_VERSION_NAME, catalog == null ? "" : catalog.versionName)
                .putInt(PrefsHelper.KEY_SERVER_VERSION_CODE, catalog == null ? 0 : catalog.versionCode)
                .putBoolean(PrefsHelper.KEY_UPDATE_AVAILABLE, updateNeeded)
                .apply();
    }

    public static void broadcastState(Context context, String message) {
        Intent intent = new Intent(ACTION_STATE_CHANGED);
        intent.putExtra("message", message);
        intent.setPackage(context.getPackageName());
        context.sendBroadcast(intent);
    }

    public static void runUpdate(final Context context, final Runnable onDone) {
        if (updateRunning) {
            broadcastState(context, "Update already in progress");
            if (onDone != null) {
                onDone.run();
            }
            return;
        }
        new Thread(new Runnable() {
            @Override
            public void run() {
                updateRunning = true;
                try {
                    broadcastState(context, "Checking server catalog…");
                    CatalogInfo catalog = CatalogFetcher.fetchTargetRelease(context);
                    if (!isUpdateNeeded(context, catalog)) {
                        saveCatalogSnapshot(context, catalog, false);
                        broadcastState(context, "Already on latest version");
                        return;
                    }
                    broadcastState(context, "Downloading " + catalog.versionName + "…");
                    File apk = ApkInstaller.downloadApk(
                            context,
                            catalog.apkUrl,
                            catalog.packageName,
                            catalog.versionCode
                    );
                    broadcastState(context, "Installing… Confirm if Android asks.");
                    ApkInstaller.installApk(context, apk, catalog.packageName, catalog.versionCode);
                    saveCatalogSnapshot(context, catalog, true);
                    broadcastState(context, "Install started — allow install when prompted");
                } catch (Exception exception) {
                    Log.w(TAG, "update failed: " + exception.getMessage());
                    broadcastState(context, "Update failed: " + exception.getMessage());
                } finally {
                    updateRunning = false;
                    if (onDone != null) {
                        onDone.run();
                    }
                }
            }
        }).start();
    }

    public static final class InstalledVersion {
        public final boolean installed;
        public final int versionCode;
        public final String versionName;

        InstalledVersion(boolean installed, int versionCode, String versionName) {
            this.installed = installed;
            this.versionCode = versionCode;
            this.versionName = versionName == null ? "" : versionName;
        }
    }
}
