package com.orphen.updatemanager;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.util.Log;

public class UpdateSyncService extends Service {
    public static final String ACTION_START = "com.orphen.updatemanager.START_WATCH";
    private static final String TAG = "UpdateSyncService";
    private static final long POLL_MS = 10_000L;
    private static final int FG_ID = 7101;
    private static final int UPDATE_NOTIFY_ID = 7102;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private Runnable pollRunnable;

    public static void start(android.content.Context context) {
        Intent intent = new Intent(context, UpdateSyncService.class);
        intent.setAction(ACTION_START);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            context.startForegroundService(intent);
        } else {
            context.startService(intent);
        }
    }

    @Override
    public void onCreate() {
        super.onCreate();
        ensureChannels();
        startForeground(FG_ID, buildWatchNotification("Watching for updates"));
        pollRunnable = new Runnable() {
            @Override
            public void run() {
                checkCatalogOnly();
                handler.postDelayed(this, POLL_MS);
            }
        };
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        PrefsHelper.ensureDefaults(this);
        handler.removeCallbacks(pollRunnable);
        handler.post(pollRunnable);
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

    private void checkCatalogOnly() {
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    CatalogInfo catalog = CatalogFetcher.fetchTargetRelease(UpdateSyncService.this);
                    boolean needed = UpdateEngine.isUpdateNeeded(UpdateSyncService.this, catalog);
                    UpdateEngine.saveCatalogSnapshot(UpdateSyncService.this, catalog, needed);
                    if (needed) {
                        showUpdateAvailableNotification(catalog);
                        sendBroadcast(new Intent(UpdateEngine.ACTION_UPDATE_AVAILABLE).setPackage(getPackageName()));
                    } else {
                        cancelUpdateNotification();
                        UpdateEngine.broadcastState(UpdateSyncService.this, "Up to date");
                    }
                } catch (Exception exception) {
                    Log.w(TAG, "catalog check: " + exception.getMessage());
                    UpdateEngine.broadcastState(UpdateSyncService.this, "Check failed: " + exception.getMessage());
                }
            }
        }).start();
    }

    private void showUpdateAvailableNotification(CatalogInfo catalog) {
        Intent action = new Intent(this, UpdateActionReceiver.class);
        action.setAction(UpdateActionReceiver.ACTION_RUN_UPDATE);
        int updateFlags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            updateFlags |= PendingIntent.FLAG_MUTABLE;
        }
        PendingIntent updatePending = PendingIntent.getBroadcast(this, 42, action, updateFlags);

        Intent openApp = new Intent(this, MainActivity.class);
        openApp.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
        int openFlags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            openFlags |= PendingIntent.FLAG_IMMUTABLE;
        }
        PendingIntent openPending = PendingIntent.getActivity(this, 43, openApp, openFlags);

        UpdateEngine.InstalledVersion installed = UpdateEngine.getInstalledVersion(this);
        String installedText = installed.installed
                ? installed.versionName + " (" + installed.versionCode + ")"
                : "Not installed";
        String body = "Installed: " + installedText + " → Server: " + catalog.versionName + " (" + catalog.versionCode + ")";

        Notification.Builder builder = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                ? new Notification.Builder(this, "update_alert")
                : new Notification.Builder(this);
        builder.setContentTitle("Update available")
                .setContentText(body)
                .setStyle(new Notification.BigTextStyle().bigText(body))
                .setSmallIcon(android.R.drawable.stat_sys_download)
                .setContentIntent(openPending)
                .setAutoCancel(true)
                .addAction(android.R.drawable.ic_menu_upload, "Update", updatePending);

        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager != null) {
            manager.notify(UPDATE_NOTIFY_ID, builder.build());
        }
    }

    private void cancelUpdateNotification() {
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager != null) {
            manager.cancel(UPDATE_NOTIFY_ID);
        }
    }

    private void ensureChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager == null) {
            return;
        }
        NotificationChannel watch = new NotificationChannel("update_watch", "Update watch", NotificationManager.IMPORTANCE_MIN);
        watch.setShowBadge(false);
        manager.createNotificationChannel(watch);
        NotificationChannel alert = new NotificationChannel("update_alert", "Update alerts", NotificationManager.IMPORTANCE_DEFAULT);
        manager.createNotificationChannel(alert);
    }

    private Notification buildWatchNotification(String text) {
        Notification.Builder builder = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                ? new Notification.Builder(this, "update_watch")
                : new Notification.Builder(this);
        return builder.setContentTitle("Orphen APK Installer")
                .setContentText(text)
                .setSmallIcon(android.R.drawable.stat_sys_download)
                .build();
    }
}
