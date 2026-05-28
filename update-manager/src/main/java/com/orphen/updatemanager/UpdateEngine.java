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
        android.content.SharedPreferences.Editor editor = PrefsHelper.prefs(context).edit()
                .putLong(PrefsHelper.KEY_LAST_REFRESH_AT, System.currentTimeMillis())
                .putBoolean(PrefsHelper.KEY_UPDATE_AVAILABLE, updateNeeded);
        if (catalog == null) {
            editor.putString(PrefsHelper.KEY_SERVER_VERSION_NAME, "")
                    .putInt(PrefsHelper.KEY_SERVER_VERSION_CODE, 0)
                    .putString(PrefsHelper.KEY_CATALOG_APP_LABEL, "")
                    .putString(PrefsHelper.KEY_CATALOG_APK_URL, "");
        } else {
            editor.putString(PrefsHelper.KEY_SERVER_VERSION_NAME, catalog.versionName)
                    .putInt(PrefsHelper.KEY_SERVER_VERSION_CODE, catalog.versionCode)
                    .putString(PrefsHelper.KEY_CATALOG_APP_LABEL, catalog.appLabel)
                    .putString(PrefsHelper.KEY_CATALOG_APK_URL, catalog.apkUrl);
        }
        editor.apply();
    }

    public static String buildVersionSummary(Context context, CatalogInfo catalog, boolean updateNeeded) {
        InstalledVersion installed = getInstalledVersion(context);
        StringBuilder summary = new StringBuilder();
        if (catalog != null && catalog.appLabel != null && catalog.appLabel.length() > 0) {
            summary.append(catalog.appLabel).append("\n");
        }
        summary.append("Package: ").append(CatalogFetcher.TARGET_PACKAGE).append("\n\n");
        if (installed.installed) {
            summary.append("Installed: ")
                    .append(installed.versionName)
                    .append(" (code ")
                    .append(installed.versionCode)
                    .append(")\n");
        } else {
            summary.append("Installed: Not installed on this phone\n");
        }
        if (catalog != null && catalog.versionCode > 0) {
            summary.append("Server catalog: ")
                    .append(catalog.versionName)
                    .append(" (code ")
                    .append(catalog.versionCode)
                    .append(")\n");
            if (catalog.apkUrl != null && catalog.apkUrl.length() > 0) {
                summary.append("APK: ").append(catalog.apkUrl).append("\n");
            }
        } else {
            summary.append("Server catalog: —\n");
        }
        summary.append("\n");
        if (catalog == null || !catalog.isValid()) {
            summary.append("Status: Catalog unavailable");
        } else if (!installed.installed) {
            summary.append("Status: App missing — install from server");
        } else if (installed.versionCode >= catalog.versionCode) {
            summary.append("Status: Up to date");
        } else {
            summary.append("Status: Update available (")
                    .append(installed.versionCode)
                    .append(" → ")
                    .append(catalog.versionCode)
                    .append(")");
        }
        if (updateNeeded) {
            summary.append(" — tap Update");
        }
        summary.append("\nServer: ").append(PrefsHelper.getServerBaseUrl(context));
        long refreshedAt = PrefsHelper.prefs(context).getLong(PrefsHelper.KEY_LAST_REFRESH_AT, 0L);
        if (refreshedAt > 0L) {
            summary.append("\nLast refresh: ")
                    .append(android.text.format.DateFormat.format("yyyy-MM-dd HH:mm:ss", refreshedAt));
        }
        return summary.toString();
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
