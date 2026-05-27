package com.example.devicesafety;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.util.Base64;

public final class AudioStreamHelper {
    public static final int SAMPLE_RATE = 16000;
    private static final int CHANNEL_CONFIG = AudioFormat.CHANNEL_IN_MONO;
    private static final int AUDIO_FORMAT = AudioFormat.ENCODING_PCM_16BIT;

    private AudioStreamHelper() {
    }

    public static boolean hasMicrophonePermission(Context context) {
        return context.checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                == PackageManager.PERMISSION_GRANTED;
    }

    public static int getBufferSize() {
        int minBuffer = AudioRecord.getMinBufferSize(SAMPLE_RATE, CHANNEL_CONFIG, AUDIO_FORMAT);
        return Math.max(minBuffer, SAMPLE_RATE / 10) * 2;
    }

    public static AudioRecord createRecorder() {
        return new AudioRecord(
                MediaRecorder.AudioSource.MIC,
                SAMPLE_RATE,
                CHANNEL_CONFIG,
                AUDIO_FORMAT,
                getBufferSize()
        );
    }

    public static String encodeChunk(byte[] data, int length) {
        return Base64.encodeToString(data, 0, length, Base64.NO_WRAP);
    }
}
