package com.example.devicesafety;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.util.AttributeSet;
import android.view.View;

public class ScanOverlayView extends View {
    private static final float SCAN_RATIO = 0.72f;
    private static final float CORNER_LENGTH_RATIO = 0.16f;
    private static final float STROKE_DP = 3f;

    private final Paint dimPaint = new Paint();
    private final Paint borderPaint = new Paint();
    private final Paint cornerPaint = new Paint();
    private final RectF scanRect = new RectF();

    public ScanOverlayView(Context context) {
        super(context);
        init();
    }

    public ScanOverlayView(Context context, AttributeSet attrs) {
        super(context, attrs);
        init();
    }

    private void init() {
        setWillNotDraw(false);
        dimPaint.setColor(0x99000000);
        borderPaint.setColor(0xFFFFFFFF);
        borderPaint.setStyle(Paint.Style.STROKE);
        borderPaint.setStrokeWidth(dp(STROKE_DP));
        cornerPaint.setColor(0xFF4FC3F7);
        cornerPaint.setStyle(Paint.Style.STROKE);
        cornerPaint.setStrokeWidth(dp(STROKE_DP + 1f));
        cornerPaint.setStrokeCap(Paint.Cap.ROUND);
    }

    public RectF getScanRect() {
        return new RectF(scanRect);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        int width = getWidth();
        int height = getHeight();
        if (width == 0 || height == 0) {
            return;
        }

        float boxSize = Math.min(width, height) * SCAN_RATIO;
        float left = (width - boxSize) / 2f;
        float top = (height - boxSize) / 2f;
        scanRect.set(left, top, left + boxSize, top + boxSize);

        canvas.drawRect(0, 0, width, scanRect.top, dimPaint);
        canvas.drawRect(0, scanRect.top, scanRect.left, scanRect.bottom, dimPaint);
        canvas.drawRect(scanRect.right, scanRect.top, width, scanRect.bottom, dimPaint);
        canvas.drawRect(0, scanRect.bottom, width, height, dimPaint);

        canvas.drawRect(scanRect, borderPaint);
        drawCorners(canvas);
    }

    private void drawCorners(Canvas canvas) {
        float corner = scanRect.width() * CORNER_LENGTH_RATIO;
        float l = scanRect.left;
        float t = scanRect.top;
        float r = scanRect.right;
        float b = scanRect.bottom;

        canvas.drawLine(l, t, l + corner, t, cornerPaint);
        canvas.drawLine(l, t, l, t + corner, cornerPaint);

        canvas.drawLine(r, t, r - corner, t, cornerPaint);
        canvas.drawLine(r, t, r, t + corner, cornerPaint);

        canvas.drawLine(l, b, l + corner, b, cornerPaint);
        canvas.drawLine(l, b, l, b - corner, cornerPaint);

        canvas.drawLine(r, b, r - corner, b, cornerPaint);
        canvas.drawLine(r, b, r, b - corner, cornerPaint);
    }

    private float dp(float value) {
        return value * getResources().getDisplayMetrics().density;
    }
}
