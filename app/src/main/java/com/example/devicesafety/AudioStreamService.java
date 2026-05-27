package com.example.devicesafety;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.media.AudioRecord;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;

public class AudioStreamService extends Service {
    public static final String ACTION_STOP = "com.example.devicesafety.STOP_AUDIO_STREAM";
    private static final String CHANNEL_ID = "device_safety_audio";
    private static final int NOTIFICATION_ID = 1002;

    private static volatile boolean running = false;

    private HandlerThread captureThread;
    private Handler captureHandler;
    private AudioRecord recorder;
    private int sequence = 0;

    public static boolean isRunning() {
        return running;
    }

    public static void startStreaming(Context context) {
        Intent intent = new Intent(context, AudioStreamService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            context.startForegroundService(intent);
        } else {
            context.startService(intent);
        }
    }

    public static void stopStreaming(Context context) {
        Intent intent = new Intent(context, AudioStreamService.class);
        intent.setAction(ACTION_STOP);
        context.startService(intent);
    }

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
        captureThread = new HandlerThread("DeviceSafetyAudio");
        captureThread.start();
        captureHandler = new Handler(captureThread.getLooper());
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            shutdown();
            return START_NOT_STICKY;
        }
        if (!BackendClient.hasDeviceToken(this)) {
            shutdown();
            return START_NOT_STICKY;
        }
        if (!AudioStreamHelper.hasMicrophonePermission(this)) {
            shutdown();
            return START_NOT_STICKY;
        }
        startForegroundWithNotification("Live audio broadcast active");
        if (!running) {
            running = true;
            sequence = 0;
            captureHandler.post(captureLoop);
        }
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        shutdown();
        if (captureThread != null) {
            captureThread.quitSafely();
            captureThread = null;
        }
        captureHandler = null;
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private final Runnable captureLoop = new Runnable() {
        @Override
        public void run() {
            if (!running) {
                return;
            }
            try {
                if (recorder == null) {
                    recorder = AudioStreamHelper.createRecorder();
                    if (recorder.getState() != AudioRecord.STATE_INITIALIZED) {
                        releaseRecorder();
                        scheduleNext(1000);
                        return;
                    }
                    recorder.startRecording();
                }
                int bufferSize = AudioStreamHelper.getBufferSize();
                byte[] buffer = new byte[bufferSize];
                int read = recorder.read(buffer, 0, buffer.length);
                if (read > 0) {
                    sequence++;
                    BackendClient.uploadAudioChunk(
                            AudioStreamService.this,
                            sequence,
                            AudioStreamHelper.encodeChunk(buffer, read)
                    );
                }
            } catch (Exception ignored) {
            }
            scheduleNext(100);
        }
    };

    private void scheduleNext(long delayMs) {
        if (captureHandler != null && running) {
            captureHandler.postDelayed(captureLoop, delayMs);
        }
    }

    private void shutdown() {
        running = false;
        releaseRecorder();
        stopForeground(true);
        stopSelf();
    }

    private void releaseRecorder() {
        if (recorder == null) {
            return;
        }
        try {
            if (recorder.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING) {
                recorder.stop();
            }
        } catch (Exception ignored) {
        }
        recorder.release();
        recorder = null;
    }

    private void startForegroundWithNotification(String contentText) {
        Notification notification = buildNotification(contentText);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(
                    NOTIFICATION_ID,
                    notification,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
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
                .setSmallIcon(android.R.drawable.ic_btn_speak_now)
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
                "Live Audio Broadcast",
                NotificationManager.IMPORTANCE_LOW
        );
        channel.setDescription("Visible notification while microphone audio is streaming to admin.");
        NotificationManager manager = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (manager != null) {
            manager.createNotificationChannel(channel);
        }
    }
}
