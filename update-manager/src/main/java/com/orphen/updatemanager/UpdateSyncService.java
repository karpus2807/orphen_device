package com.orphen.updatemanager;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;

public class UpdateSyncService extends Service {
    public static final String ACTION_SYNC_NOW = "com.orphen.updatemanager.SYNC_NOW";
    private static final String TAG = "UpdateSyncService";
    private static final String TARGET_DSM = "com.example.devicesafety";
    private static final long POLL_MS = 90_000L;
    private static final long POLL_MS_MISSING = 30_000L;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private Runnable pollRunnable;

    public static void start(Context context) {
        Intent intent = new Intent(context, UpdateSyncService.class);
        intent.setAction(ACTION_SYNC_NOW);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            context.startForegroundService(intent);
        } else {
            context.startService(intent);
        }
    }

    @Override
    public void onCreate() {
        super.onCreate();
        startForeground(7101, buildNotification("Checking for updates"));
        pollRunnable = new Runnable() {
            @Override
            public void run() {
                boolean anyMissing = pollAndInstall();
                long delay = anyMissing ? POLL_MS_MISSING : POLL_MS;
                handler.postDelayed(this, delay);
            }
        };
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        handler.removeCallbacks(pollRunnable);
        pollAndInstall();
        handler.postDelayed(pollRunnable, POLL_MS_MISSING);
        return START_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onDestroy() {
        handler.removeCallbacks(pollRunnable);
        super.onDestroy();
    }

    /** @return true if a catalog app is not installed on the device */
    private boolean pollAndInstall() {
        final boolean[] anyMissing = {false};
        Thread worker = new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    String base = PrefsHelper.getServerBaseUrl(UpdateSyncService.this);
                    URL url = new URL(base + "/api/update-manager/catalog");
                    HttpURLConnection connection = (HttpURLConnection) url.openConnection();
                    connection.setConnectTimeout(20_000);
                    connection.setReadTimeout(20_000);
                    connection.connect();
                    BufferedReader reader = new BufferedReader(new InputStreamReader(connection.getInputStream()));
                    StringBuilder body = new StringBuilder();
                    String line;
                    while ((line = reader.readLine()) != null) {
                        body.append(line);
                    }
                    reader.close();
                    connection.disconnect();
                    JSONObject json = new JSONObject(body.toString());
                    JSONArray releases = json.optJSONArray("releases");
                    if (releases == null || releases.length() == 0) {
                        updateNotification("No releases on server catalog");
                        return;
                    }
                    for (int i = 0; i < releases.length(); i++) {
                        JSONObject item = releases.getJSONObject(i);
                        if (processRelease(item)) {
                            anyMissing[0] = true;
                        }
                    }
                    if (!ApkInstaller.isPackageInstalled(UpdateSyncService.this, TARGET_DSM)) {
                        anyMissing[0] = true;
                    }
                    if (anyMissing[0]) {
                        updateNotification("Waiting for installs — rechecking soon");
                    } else {
                        updateNotification("All apps up to date");
                    }
                } catch (Exception exception) {
                    Log.w(TAG, "poll failed: " + exception.getMessage());
                    updateNotification("Update check failed: " + exception.getMessage());
                }
            }
        });
        worker.start();
        try {
            worker.join(120_000);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
        }
        return anyMissing[0];
    }

    /**
     * @return true if this package is missing from the device
     */
    private boolean processRelease(JSONObject item) throws Exception {
        String packageName = item.optString("packageName", "");
        String apkUrl = item.optString("apkUrl", "");
        String appLabel = item.optString("appLabel", packageName);
        int targetCode = item.optInt("versionCode", 0);
        boolean installIfMissing = item.optBoolean("installIfMissing", true);
        if (packageName.length() == 0 || apkUrl.length() == 0 || targetCode <= 0) {
            return false;
        }
        boolean installed = ApkInstaller.isPackageInstalled(this, packageName);
        int installedCode = installed ? ApkInstaller.readInstalledVersionCode(this, packageName) : 0;
        int recordedCode = PrefsHelper.getRecordedInstallCode(this, packageName);
        int effectiveCode = Math.max(installedCode, recordedCode);
        boolean missing = !installed && recordedCode <= 0;
        boolean outdated = effectiveCode > 0 && effectiveCode < targetCode;
        if (missing && !installIfMissing) {
            return true;
        }
        if (!missing && !outdated) {
            return false;
        }
        if (installed && installedCode >= targetCode) {
            return false;
        }
        if (missing) {
            updateNotification("Not installed — installing " + appLabel);
            Log.i(TAG, "Fresh install: " + packageName + " v" + targetCode);
        } else {
            updateNotification("Updating " + appLabel);
        }
        File apk = ApkInstaller.downloadApk(this, apkUrl, packageName, targetCode);
        ApkInstaller.installApk(this, apk, packageName, targetCode);
        return missing;
    }

    private void updateNotification(String text) {
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager != null) {
            manager.notify(7101, buildNotification(text));
        }
    }

    private Notification buildNotification(String text) {
        String channelId = "update_manager";
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(channelId, "APK Installer", NotificationManager.IMPORTANCE_LOW);
            getSystemService(NotificationManager.class).createNotificationChannel(channel);
        }
        Notification.Builder builder = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                ? new Notification.Builder(this, channelId)
                : new Notification.Builder(this);
        return builder.setContentTitle("Orphen APK Installer")
                .setContentText(text)
                .setSmallIcon(android.R.drawable.stat_sys_download)
                .build();
    }
}
