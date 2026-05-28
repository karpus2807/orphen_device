package com.orphen.devicesafety;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.ImageFormat;
import android.graphics.RectF;
import android.hardware.Camera;
import android.Manifest;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.Surface;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.TextView;

import com.google.zxing.BarcodeFormat;
import com.google.zxing.BinaryBitmap;
import com.google.zxing.DecodeHintType;
import com.google.zxing.MultiFormatReader;
import com.google.zxing.NotFoundException;
import com.google.zxing.PlanarYUVLuminanceSource;
import com.google.zxing.Result;
import com.google.zxing.common.HybridBinarizer;

import java.util.Collections;
import java.util.EnumMap;
import java.util.List;
import java.util.Map;

@SuppressWarnings("deprecation")
public class QrScanActivity extends Activity implements SurfaceHolder.Callback, Camera.PreviewCallback {
    public static final String EXTRA_SCAN_RESULT = "scanResult";
    private static final int REQUEST_CAMERA = 2001;
    private static final long DECODE_INTERVAL_MS = 250L;

    private SurfaceView surfaceView;
    private ScanOverlayView overlayView;
    private TextView statusText;
    private Camera camera;
    private Camera.Size previewSize;
    private int cameraDisplayOrientation;
    private boolean surfaceReady;
    private boolean processing;
    private boolean finished;
    private long lastDecodeAttemptMs;
    private MultiFormatReader reader;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(0xFF000000);

        surfaceView = new SurfaceView(this);
        root.addView(surfaceView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
        ));

        overlayView = new ScanOverlayView(this);
        root.addView(overlayView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
        ));

        statusText = new TextView(this);
        statusText.setText("Align the enrollment QR inside the square");
        statusText.setTextColor(0xFFFFFFFF);
        statusText.setTextSize(16);
        statusText.setPadding(32, 32, 32, 48);
        FrameLayout.LayoutParams statusParams = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        );
        statusParams.gravity = Gravity.BOTTOM;
        root.addView(statusText, statusParams);

        setContentView(root);

        Map<DecodeHintType, Object> hints = new EnumMap<>(DecodeHintType.class);
        hints.put(DecodeHintType.POSSIBLE_FORMATS, Collections.singletonList(BarcodeFormat.QR_CODE));
        hints.put(DecodeHintType.CHARACTER_SET, "UTF-8");
        hints.put(DecodeHintType.TRY_HARDER, Boolean.TRUE);
        reader = new MultiFormatReader();
        reader.setHints(hints);

        surfaceView.getHolder().addCallback(this);
        ensureCameraPermission();
    }

    private void ensureCameraPermission() {
        if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            return;
        }
        if (shouldShowRequestPermissionRationale(Manifest.permission.CAMERA)) {
            statusText.setText("Camera access is needed to scan the enrollment QR code.");
        }
        requestPermissions(new String[]{Manifest.permission.CAMERA}, REQUEST_CAMERA);
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != REQUEST_CAMERA) {
            return;
        }
        if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            startCameraIfReady();
            return;
        }
        statusText.setText("Camera permission is required to scan QR codes.");
        setResult(RESULT_CANCELED);
        finish();
    }

    @Override
    public void surfaceCreated(SurfaceHolder holder) {
        surfaceReady = true;
        startCameraIfReady();
    }

    @Override
    public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) {
    }

    @Override
    public void surfaceDestroyed(SurfaceHolder holder) {
        surfaceReady = false;
        stopCamera();
    }

    private void startCameraIfReady() {
        if (finished || !surfaceReady) {
            return;
        }
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            return;
        }
        if (Camera.getNumberOfCameras() == 0) {
            statusText.setText("No camera found on this device.");
            return;
        }
        stopCamera();
        try {
            camera = openBackCamera();
            Camera.Parameters params = camera.getParameters();
            params.setPreviewFormat(ImageFormat.NV21);
            List<String> focusModes = params.getSupportedFocusModes();
            if (focusModes != null && focusModes.contains(Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE)) {
                params.setFocusMode(Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE);
            }
            previewSize = choosePreviewSize(params.getSupportedPreviewSizes());
            params.setPreviewSize(previewSize.width, previewSize.height);
            camera.setParameters(params);
            cameraDisplayOrientation = getCameraDisplayOrientation();
            camera.setDisplayOrientation(cameraDisplayOrientation);
            camera.setPreviewDisplay(surfaceView.getHolder());
            camera.setPreviewCallback(this);
            camera.startPreview();
            statusText.setText("Align the enrollment QR inside the square");
        } catch (Exception exception) {
            statusText.setText("Could not open camera: " + exception.getMessage());
        }
    }

    private Camera openBackCamera() {
        int cameraId = 0;
        for (int index = 0; index < Camera.getNumberOfCameras(); index++) {
            Camera.CameraInfo info = new Camera.CameraInfo();
            Camera.getCameraInfo(index, info);
            if (info.facing == Camera.CameraInfo.CAMERA_FACING_BACK) {
                cameraId = index;
                break;
            }
        }
        return Camera.open(cameraId);
    }

    private int getCameraDisplayOrientation() {
        Camera.CameraInfo info = new Camera.CameraInfo();
        Camera.getCameraInfo(findBackCameraId(), info);
        int rotation = getWindowManager().getDefaultDisplay().getRotation();
        int degrees = 0;
        switch (rotation) {
            case Surface.ROTATION_0:
                degrees = 0;
                break;
            case Surface.ROTATION_90:
                degrees = 90;
                break;
            case Surface.ROTATION_180:
                degrees = 180;
                break;
            case Surface.ROTATION_270:
                degrees = 270;
                break;
            default:
                degrees = 0;
                break;
        }
        if (info.facing == Camera.CameraInfo.CAMERA_FACING_FRONT) {
            return (info.orientation + degrees) % 360;
        }
        return (info.orientation - degrees + 360) % 360;
    }

    private int findBackCameraId() {
        for (int index = 0; index < Camera.getNumberOfCameras(); index++) {
            Camera.CameraInfo info = new Camera.CameraInfo();
            Camera.getCameraInfo(index, info);
            if (info.facing == Camera.CameraInfo.CAMERA_FACING_BACK) {
                return index;
            }
        }
        return 0;
    }

    private Camera.Size choosePreviewSize(List<Camera.Size> sizes) {
        if (sizes == null || sizes.isEmpty()) {
            throw new IllegalStateException("Camera preview sizes unavailable");
        }
        Camera.Size best = sizes.get(0);
        float bestScore = Float.MAX_VALUE;
        for (Camera.Size size : sizes) {
            if (size.width > 1920) {
                continue;
            }
            float ratio = (float) size.width / (float) size.height;
            float ratioScore = Math.abs(ratio - (16f / 9f));
            float sizeScore = Math.abs(size.width - 1280) / 1280f;
            float score = ratioScore * 10f + sizeScore;
            if (score < bestScore) {
                bestScore = score;
                best = size;
            }
        }
        return best;
    }

    @Override
    public void onPreviewFrame(byte[] data, Camera camera) {
        if (processing || finished || data == null || previewSize == null || overlayView == null) {
            return;
        }
        long now = System.currentTimeMillis();
        if (now - lastDecodeAttemptMs < DECODE_INTERVAL_MS) {
            return;
        }
        lastDecodeAttemptMs = now;
        processing = true;

        final byte[] frame = data;
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    Result result = decodeFrame(frame);
                    if (result != null) {
                        finishWithResult(result.getText());
                    }
                } finally {
                    processing = false;
                }
            }
        }).start();
    }

    private Result decodeFrame(byte[] data) {
        int previewWidth = previewSize.width;
        int previewHeight = previewSize.height;
        int viewWidth = overlayView.getWidth();
        int viewHeight = overlayView.getHeight();
        if (viewWidth == 0 || viewHeight == 0) {
            return null;
        }

        RectF scanRect = overlayView.getScanRect();
        int cropLeft;
        int cropTop;
        int cropWidth;
        int cropHeight;

        if (cameraDisplayOrientation == 90 || cameraDisplayOrientation == 270) {
            float scaleX = (float) previewWidth / (float) viewHeight;
            float scaleY = (float) previewHeight / (float) viewWidth;
            cropLeft = clamp(Math.round(scanRect.top * scaleX), 0, previewWidth - 1);
            cropTop = clamp(Math.round((viewWidth - scanRect.right) * scaleY), 0, previewHeight - 1);
            cropWidth = clamp(Math.round(scanRect.height() * scaleX), 1, previewWidth - cropLeft);
            cropHeight = clamp(Math.round(scanRect.width() * scaleY), 1, previewHeight - cropTop);
        } else if (cameraDisplayOrientation == 180) {
            float scaleX = (float) previewWidth / (float) viewWidth;
            float scaleY = (float) previewHeight / (float) viewHeight;
            cropLeft = clamp(Math.round((viewWidth - scanRect.right) * scaleX), 0, previewWidth - 1);
            cropTop = clamp(Math.round((viewHeight - scanRect.bottom) * scaleY), 0, previewHeight - 1);
            cropWidth = clamp(Math.round(scanRect.width() * scaleX), 1, previewWidth - cropLeft);
            cropHeight = clamp(Math.round(scanRect.height() * scaleY), 1, previewHeight - cropTop);
        } else {
            float scaleX = (float) previewWidth / (float) viewWidth;
            float scaleY = (float) previewHeight / (float) viewHeight;
            cropLeft = clamp(Math.round(scanRect.left * scaleX), 0, previewWidth - 1);
            cropTop = clamp(Math.round(scanRect.top * scaleY), 0, previewHeight - 1);
            cropWidth = clamp(Math.round(scanRect.width() * scaleX), 1, previewWidth - cropLeft);
            cropHeight = clamp(Math.round(scanRect.height() * scaleY), 1, previewHeight - cropTop);
        }

        try {
            PlanarYUVLuminanceSource source = new PlanarYUVLuminanceSource(
                    data,
                    previewWidth,
                    previewHeight,
                    cropLeft,
                    cropTop,
                    cropWidth,
                    cropHeight,
                    false
            );
            BinaryBitmap bitmap = new BinaryBitmap(new HybridBinarizer(source));
            return reader.decodeWithState(bitmap);
        } catch (NotFoundException ignored) {
            reader.reset();
            return null;
        } catch (Exception ignored) {
            reader.reset();
            return null;
        }
    }

    private int clamp(int value, int min, int max) {
        if (value < min) {
            return min;
        }
        if (value > max) {
            return max;
        }
        return value;
    }

    private void finishWithResult(final String text) {
        if (finished) {
            return;
        }
        finished = true;
        mainHandler.post(new Runnable() {
            @Override
            public void run() {
                stopCamera();
                Intent intent = new Intent();
                intent.putExtra(EXTRA_SCAN_RESULT, text);
                setResult(RESULT_OK, intent);
                finish();
            }
        });
    }

    private void stopCamera() {
        if (camera != null) {
            try {
                camera.setPreviewCallback(null);
                camera.stopPreview();
                camera.release();
            } catch (Exception ignored) {
            }
            camera = null;
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            startCameraIfReady();
        } else {
            ensureCameraPermission();
        }
    }

    @Override
    protected void onPause() {
        stopCamera();
        super.onPause();
    }
}
