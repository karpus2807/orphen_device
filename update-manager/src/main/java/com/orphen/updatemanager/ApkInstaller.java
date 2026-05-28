package com.orphen.updatemanager;

import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageInstaller;
import android.content.pm.PackageManager;
import android.os.Build;
import android.util.Log;

import java.io.BufferedInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

public final class ApkInstaller {
    private static final String TAG = "ApkInstaller";
    public static final String EXTRA_APK_PATH = "apk_path";
    public static final String EXTRA_PACKAGE_NAME = "package_name";
    public static final String EXTRA_TARGET_VERSION_CODE = "target_version_code";

    public static final String[] MONITORED_PACKAGES = {
            CatalogFetcher.TARGET_PACKAGE,
            "com.example.devicesafety",
    };

    private ApkInstaller() {
    }

    public static String resolveInstalledTargetPackage(Context context) {
        for (String packageName : MONITORED_PACKAGES) {
            if (isPackageInstalled(context, packageName)) {
                return packageName;
            }
        }
        return "";
    }

    public static boolean isPackageInstalled(Context context, String packageName) {
        if (packageName == null || packageName.length() == 0) {
            return false;
        }
        return getPackageInfo(context, packageName) != null;
    }

    public static int readInstalledVersionCode(Context context, String packageName) {
        PackageInfo info = getPackageInfo(context, packageName);
        if (info == null) {
            int recorded = PrefsHelper.getRecordedInstallCode(context, packageName);
            if (recorded > 0) {
                Log.i(TAG, "Using recorded version code " + recorded + " for " + packageName);
                return recorded;
            }
            return 0;
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            return (int) info.getLongVersionCode();
        }
        return info.versionCode;
    }

    public static String readInstalledVersionName(Context context, String packageName) {
        PackageInfo info = getPackageInfo(context, packageName);
        if (info == null) {
            int recorded = PrefsHelper.getRecordedInstallCode(context, packageName);
            if (recorded > 0) {
                return "v? (code " + recorded + ")";
            }
            return "";
        }
        return info.versionName == null ? "" : info.versionName;
    }

    private static PackageInfo getPackageInfo(Context context, String packageName) {
        PackageManager manager = context.getPackageManager();
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                return manager.getPackageInfo(packageName, PackageManager.PackageInfoFlags.of(0));
            }
            return manager.getPackageInfo(packageName, 0);
        } catch (PackageManager.NameNotFoundException exception) {
            Log.d(TAG, "Package not visible or missing: " + packageName);
            return null;
        } catch (Exception exception) {
            Log.w(TAG, "getPackageInfo failed for " + packageName + ": " + exception.getMessage());
            return null;
        }
    }

    public static File downloadApk(Context context, String apkUrl, String packageName, int versionCode) throws Exception {
        File dir = new File(context.getExternalFilesDir("updates"), packageName);
        if (!dir.exists() && !dir.mkdirs()) {
            throw new Exception("Cannot create update dir");
        }
        purgeApkFiles(dir, versionCode);
        File out = new File(dir, "update-" + versionCode + ".apk");
        HttpURLConnection connection = (HttpURLConnection) new URL(apkUrl).openConnection();
        connection.setConnectTimeout(30_000);
        connection.setReadTimeout(120_000);
        try {
            connection.connect();
            if (connection.getResponseCode() < 200 || connection.getResponseCode() >= 300) {
                throw new Exception("HTTP " + connection.getResponseCode());
            }
            try (InputStream input = new BufferedInputStream(connection.getInputStream());
                    FileOutputStream output = new FileOutputStream(out, false)) {
                byte[] buffer = new byte[8192];
                int read;
                while ((read = input.read(buffer)) != -1) {
                    output.write(buffer, 0, read);
                }
            }
        } finally {
            connection.disconnect();
        }
        if (out.length() < 50_000L) {
            out.delete();
            throw new Exception("Download too small");
        }
        return out;
    }

    public static void installApk(Context context, File apkFile, String packageName, int targetVersionCode) throws Exception {
        PackageInstaller installer = context.getPackageManager().getPackageInstaller();
        PackageInstaller.SessionParams params = new PackageInstaller.SessionParams(
                PackageInstaller.SessionParams.MODE_FULL_INSTALL
        );
        int sessionId = installer.createSession(params);
        PackageInstaller.Session session = installer.openSession(sessionId);
        try {
            try (FileInputStream in = new FileInputStream(apkFile);
                    OutputStream out = session.openWrite("base.apk", 0, apkFile.length())) {
                byte[] buffer = new byte[65536];
                int read;
                while ((read = in.read(buffer)) != -1) {
                    out.write(buffer, 0, read);
                }
                session.fsync(out);
            }
            Intent callback = new Intent(context, InstallResultReceiver.class);
            callback.putExtra(EXTRA_APK_PATH, apkFile.getAbsolutePath());
            callback.putExtra(EXTRA_PACKAGE_NAME, packageName);
            callback.putExtra(EXTRA_TARGET_VERSION_CODE, targetVersionCode);
            int flags = PendingIntent.FLAG_UPDATE_CURRENT;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                flags |= PendingIntent.FLAG_MUTABLE;
            }
            PendingIntent pending = PendingIntent.getBroadcast(context, sessionId, callback, flags);
            session.commit(pending.getIntentSender());
        } catch (Exception exception) {
            session.abandon();
            throw exception;
        } finally {
            session.close();
        }
        Log.i(TAG, "Install session committed for " + apkFile.getName());
    }

    /** Remove downloaded APK files after a successful install. */
    public static void deleteDownloadedApks(String apkPath, String packageName, Context context) {
        if (apkPath != null && apkPath.length() > 0) {
            File file = new File(apkPath);
            if (file.exists() && !file.delete()) {
                Log.w(TAG, "Could not delete " + apkPath);
            }
        }
        if (packageName != null && packageName.length() > 0) {
            File dir = new File(context.getExternalFilesDir("updates"), packageName);
            purgeApkFiles(dir, -1);
        }
    }

    private static void purgeApkFiles(File dir, int exceptVersionCode) {
        if (dir == null || !dir.isDirectory()) {
            return;
        }
        File[] files = dir.listFiles();
        if (files == null) {
            return;
        }
        for (File file : files) {
            if (!file.isFile() || !file.getName().endsWith(".apk")) {
                continue;
            }
            if (exceptVersionCode > 0 && file.getName().equals("update-" + exceptVersionCode + ".apk")) {
                continue;
            }
            if (!file.delete()) {
                Log.w(TAG, "Could not delete stale apk " + file.getName());
            }
        }
    }
}
