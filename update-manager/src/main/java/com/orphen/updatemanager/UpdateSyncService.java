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
    /** Check server every 90s so pushed updates install quickly. */
    private static final long POLL_MS = 90_000L;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable pollRunnable = new Runnable() {
        @Override
        public void run() {
            pollAndInstall();
            handler.postDelayed(this, POLL_MS);
        }
    };

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
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        handler.removeCallbacks(pollRunnable);
        pollAndInstall();
        handler.postDelayed(pollRunnable, POLL_MS);
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

    private void pollAndInstall() {
        new Thread(new Runnable() {
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
                    if (releases == null) {
                        return;
                    }
                    for (int i = 0; i < releases.length(); i++) {
                        JSONObject item = releases.getJSONObject(i);
                        String packageName = item.optString("packageName", "");
                        String apkUrl = item.optString("apkUrl", "");
                        int targetCode = item.optInt("versionCode", 0);
                        if (packageName.length() == 0 || apkUrl.length() == 0 || targetCode <= 0) {
                            continue;
                        }
                        int installed = ApkInstaller.readInstalledVersionCode(UpdateSyncService.this, packageName);
                        if (installed >= targetCode && installed > 0) {
                            continue;
                        }
                        updateNotification("Downloading " + item.optString("appLabel", packageName));
                        File apk = ApkInstaller.downloadApk(UpdateSyncService.this, apkUrl, packageName, targetCode);
                        updateNotification("Installing " + item.optString("appLabel", packageName));
                        ApkInstaller.installApk(UpdateSyncService.this, apk, packageName);
                    }
                    updateNotification("Idle — watching for updates");
                } catch (Exception exception) {
                    Log.w(TAG, "poll failed: " + exception.getMessage());
                    updateNotification("Update check failed");
                }
            }
        }).start();
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
