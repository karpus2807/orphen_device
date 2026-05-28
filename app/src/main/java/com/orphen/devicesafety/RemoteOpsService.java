package com.orphen.devicesafety;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;

import org.json.JSONArray;
import org.json.JSONObject;

public class RemoteOpsService extends Service {
    private static final String CHANNEL_ID = "device_safety_remote_ops";
    private static final int NOTIFICATION_ID = 1003;
    private static final long POLL_INTERVAL_MS = 1000L;

    private static volatile boolean running = false;

    private HandlerThread workerThread;
    private Handler workerHandler;
    private Runnable pollRunnable;

    public static boolean isRunning() {
        return running;
    }

    public static void startIfRegistered(Context context) {
        if (!BackendClient.hasDeviceToken(context)) {
            stopService(context);
            return;
        }
        Intent intent = new Intent(context, RemoteOpsService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            context.startForegroundService(intent);
        } else {
            context.startService(intent);
        }
    }

    public static void stopService(Context context) {
        context.stopService(new Intent(context, RemoteOpsService.class));
    }

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
        workerThread = new HandlerThread("DeviceSafetyRemoteOps");
        workerThread.start();
        workerHandler = new Handler(workerThread.getLooper());
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (!BackendClient.hasDeviceToken(this)) {
            stopSelf();
            return START_NOT_STICKY;
        }
        running = true;
        startForegroundCompat("Remote file and shell session active");
        startPollLoop();
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        running = false;
        stopPollLoop();
        if (workerThread != null) {
            workerThread.quitSafely();
            workerThread = null;
        }
        workerHandler = null;
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void startPollLoop() {
        stopPollLoop();
        pollRunnable = new Runnable() {
            @Override
            public void run() {
                pollAndExecuteJobs();
                if (workerHandler != null && pollRunnable != null) {
                    workerHandler.postDelayed(pollRunnable, POLL_INTERVAL_MS);
                }
            }
        };
        workerHandler.post(pollRunnable);
    }

    private void stopPollLoop() {
        if (workerHandler != null && pollRunnable != null) {
            workerHandler.removeCallbacks(pollRunnable);
        }
        pollRunnable = null;
    }

    private void pollAndExecuteJobs() {
        try {
            JSONObject payload = BackendClient.fetchRemoteJobsJson(this);
            if (!payload.optBoolean("sessionRequested", false) && !payload.optBoolean("sessionActive", false)) {
                stopSelf();
                return;
            }
            JSONArray jobs = payload.optJSONArray("jobs");
            if (jobs == null) {
                return;
            }
            for (int index = 0; index < jobs.length(); index++) {
                JSONObject job = jobs.getJSONObject(index);
                executeJob(job);
            }
        } catch (Exception ignored) {
        }
    }

    private void executeJob(JSONObject job) {
        String jobId = job.optString("id", "");
        String type = job.optString("type", "");
        JSONObject payload = job.optJSONObject("payload");
        if (payload == null) {
            payload = new JSONObject();
        }
        try {
            if ("list_dir".equals(type)) {
                boolean withThumbnails = payload.optBoolean("withThumbnails", true);
                JSONObject result = RemoteOpsHelper.listDirectory(
                        this,
                        payload.optString("path", RemoteOpsHelper.defaultRootPath()),
                        withThumbnails
                );
                BackendClient.completeRemoteJob(this, jobId, true, result, "");
                return;
            }
            if ("read_file".equals(type)) {
                JSONObject result = RemoteOpsHelper.readFile(this, payload.optString("path", ""));
                BackendClient.completeRemoteJob(this, jobId, true, result, "");
                return;
            }
            if ("write_file".equals(type)) {
                JSONObject upload = BackendClient.fetchRemoteUploadJson(this, payload.optString("uploadId", ""));
                byte[] data = android.util.Base64.decode(upload.optString("data", ""), android.util.Base64.DEFAULT);
                JSONObject result = RemoteOpsHelper.writeFile(this, payload.optString("path", ""), data);
                BackendClient.completeRemoteJob(this, jobId, true, result, "");
                return;
            }
            if ("shell_exec".equals(type)) {
                JSONObject result = RemoteOpsHelper.executeShell(this, payload.optString("command", ""));
                BackendClient.completeRemoteJob(this, jobId, true, result, "");
                return;
            }
            if ("file_action".equals(type)) {
                JSONArray paths = payload.optJSONArray("paths");
                JSONObject result = RemoteOpsHelper.performFileAction(
                        this,
                        payload.optString("action", ""),
                        paths,
                        payload.optString("destPath", "")
                );
                BackendClient.completeRemoteJob(this, jobId, true, result, "");
                return;
            }
            BackendClient.completeRemoteJob(this, jobId, false, new JSONObject(), "Unknown remote job type");
        } catch (Exception exception) {
            try {
                BackendClient.completeRemoteJob(this, jobId, false, new JSONObject(), exception.getMessage());
            } catch (Exception ignored) {
            }
        }
    }

    private void startForegroundCompat(String contentText) {
        Notification notification = buildNotification(contentText);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(
                    NOTIFICATION_ID,
                    notification,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
            );
            return;
        }
        startForeground(NOTIFICATION_ID, notification);
    }

    private Notification buildNotification(String contentText) {
        Intent launchIntent = new Intent(this, MainActivity.class);
        PendingIntent pendingIntent = PendingIntent.getActivity(
                this,
                0,
                launchIntent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
        Notification.Builder builder = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                ? new Notification.Builder(this, CHANNEL_ID)
                : new Notification.Builder(this);
        builder.setContentTitle("Device Safety Manager")
                .setContentText(contentText)
                .setSmallIcon(android.R.drawable.ic_menu_manage)
                .setContentIntent(pendingIntent)
                .setOngoing(true);
        return builder.build();
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                "Remote Operations",
                NotificationManager.IMPORTANCE_LOW
        );
        NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (manager != null) {
            manager.createNotificationChannel(channel);
        }
    }
}
