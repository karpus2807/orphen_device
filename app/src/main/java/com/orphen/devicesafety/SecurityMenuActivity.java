package com.orphen.devicesafety;

import android.app.Activity;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;

public class SecurityMenuActivity extends Activity {
    private static final long POLL_INTERVAL_MS = 3000L;

    private TextView statusView;
    private TextView otpDisplayView;
    private EditText otpInput;
    private LinearLayout actionsLayout;
    private Handler handler;
    private Runnable pollRunnable;
    private int activeRequestId;
    private String activeAction = "";
    private boolean otpAutoVerifyInProgress = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        handler = new Handler(Looper.getMainLooper());
        activeAction = getIntent().getStringExtra(SecurityHelper.EXTRA_ACTION);
        if (activeAction == null) {
            activeAction = "";
        }

        int horizontal = dp(20);
        int top = dp(16);
        int bottom = dp(24);

        ScrollView scrollView = new ScrollView(this);
        scrollView.setFillViewport(true);
        scrollView.setVerticalScrollBarEnabled(true);
        scrollView.setScrollbarFadingEnabled(false);
        scrollView.setScrollBarStyle(View.SCROLLBARS_OUTSIDE_OVERLAY);
        scrollView.setClipToPadding(false);
        scrollView.setPadding(horizontal, top, horizontal, bottom);
        scrollView.setLayoutParams(new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
        ));
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            scrollView.setVerticalScrollbarTrackDrawable(null);
        }

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setLayoutParams(new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        ));

        TextView appTitle = new TextView(this);
        appTitle.setText("Device Safety Manager");
        appTitle.setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
        appTitle.setTypeface(Typeface.DEFAULT_BOLD);
        appTitle.setTextColor(Color.parseColor("#0F172A"));
        appTitle.setGravity(Gravity.START);
        appTitle.setLayoutParams(fullWidthParams(0, 0, 0, dp(6)));
        root.addView(appTitle);

        TextView screenTitle = new TextView(this);
        screenTitle.setText("Security Control Menu");
        screenTitle.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        screenTitle.setTextColor(Color.parseColor("#1565C0"));
        screenTitle.setTypeface(Typeface.DEFAULT_BOLD);
        screenTitle.setLayoutParams(fullWidthParams(0, 0, 0, dp(10)));
        root.addView(screenTitle);

        TextView subtitle = new TextView(this);
        subtitle.setText(
                "Protected actions require admin approval. After approval, OTP appears here and auto-fills below."
        );
        subtitle.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        subtitle.setTextColor(Color.parseColor("#546E7A"));
        subtitle.setLineSpacing(dp(2), 1.15f);
        subtitle.setLayoutParams(fullWidthParams(0, 0, 0, dp(16)));
        root.addView(subtitle);

        View divider = new View(this);
        divider.setBackgroundColor(Color.parseColor("#E0E7EF"));
        LinearLayout.LayoutParams dividerParams = fullWidthParams(0, 0, 0, dp(16));
        dividerParams.height = dp(1);
        divider.setLayoutParams(dividerParams);
        root.addView(divider);

        statusView = new TextView(this);
        statusView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        statusView.setTextColor(Color.parseColor("#37474F"));
        statusView.setLineSpacing(dp(2), 1.12f);
        statusView.setLayoutParams(fullWidthParams(0, 0, 0, dp(14)));
        root.addView(statusView);

        TextView actionsLabel = new TextView(this);
        actionsLabel.setText("Protected Actions");
        actionsLabel.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        actionsLabel.setTypeface(Typeface.DEFAULT_BOLD);
        actionsLabel.setTextColor(Color.parseColor("#172033"));
        actionsLabel.setLayoutParams(fullWidthParams(0, 0, 0, dp(8)));
        root.addView(actionsLabel);

        actionsLayout = new LinearLayout(this);
        actionsLayout.setOrientation(LinearLayout.VERTICAL);
        actionsLayout.setLayoutParams(fullWidthParams(0, 0, 0, dp(16)));
        root.addView(actionsLayout);
        buildActionButtons();

        TextView otpLabel = new TextView(this);
        otpLabel.setText("OTP Verification");
        otpLabel.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        otpLabel.setTypeface(Typeface.DEFAULT_BOLD);
        otpLabel.setTextColor(Color.parseColor("#172033"));
        otpLabel.setLayoutParams(fullWidthParams(0, 0, 0, dp(8)));
        root.addView(otpLabel);

        otpDisplayView = new TextView(this);
        otpDisplayView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 32);
        otpDisplayView.setTypeface(Typeface.DEFAULT_BOLD);
        otpDisplayView.setTextColor(Color.parseColor("#1565C0"));
        otpDisplayView.setGravity(Gravity.CENTER_HORIZONTAL);
        otpDisplayView.setVisibility(View.GONE);
        otpDisplayView.setLayoutParams(fullWidthParams(0, 0, 0, dp(8)));
        root.addView(otpDisplayView);

        otpInput = new EditText(this);
        otpInput.setHint("OTP auto-fills here, or enter manually");
        otpInput.setInputType(InputType.TYPE_CLASS_NUMBER);
        otpInput.setMaxLines(1);
        otpInput.setGravity(Gravity.CENTER_HORIZONTAL);
        otpInput.setLayoutParams(fullWidthParams(0, 0, 0, dp(10)));
        root.addView(otpInput);

        Button verify = new Button(this);
        verify.setText("Verify OTP");
        verify.setAllCaps(false);
        verify.setLayoutParams(fullWidthParams(0, 0, 0, dp(8)));
        verify.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                verifyOtp();
            }
        });
        root.addView(verify);

        Button close = new Button(this);
        close.setText("Close");
        close.setAllCaps(false);
        close.setLayoutParams(fullWidthParams(0, 0, 0, dp(8)));
        close.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                finish();
            }
        });
        root.addView(close);

        scrollView.addView(root);
        setContentView(scrollView);
        updateStatus("Locked: " + (SecurityHelper.isLocked(this) ? "Yes" : "No")
                + " · Hidden: " + (SecurityHelper.isHidden(this) ? "Yes" : "No"));

        if (activeAction.length() > 0) {
            requestAction(activeAction);
        }
    }

    @Override
    protected void onDestroy() {
        stopPolling();
        super.onDestroy();
    }

    private int dp(int value) {
        return Math.round(TypedValue.applyDimension(
                TypedValue.COMPLEX_UNIT_DIP,
                value,
                getResources().getDisplayMetrics()
        ));
    }

    private LinearLayout.LayoutParams fullWidthParams(int left, int top, int right, int bottom) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        );
        params.setMargins(left, top, right, bottom);
        return params;
    }

    private void buildActionButtons() {
        addActionButton("Unlock App", "unlock");
        addActionButton("Unhide App", "unhide");
        addActionButton("Hide App", "hide");
        addActionButton("Lock App", "lock");
        addActionButton("Enable Device Admin", "enable_device_admin");
        addActionButton("Disable Device Admin", "disable_device_admin");
        addActionButton("Allow Uninstall / Deregister", "allow_uninstall");
    }

    private void addActionButton(String label, final String actionType) {
        Button button = new Button(this);
        button.setText(label);
        button.setAllCaps(false);
        button.setLayoutParams(fullWidthParams(0, 0, 0, dp(8)));
        button.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                requestAction(actionType);
            }
        });
        actionsLayout.addView(button);
    }

    private void requestAction(final String actionType) {
        activeAction = actionType;
        clearOtpDisplay();
        updateStatus("Sending request for " + actionType.replace('_', ' ') + "...");
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    JSONObject response = BackendClient.requestSecurityAction(SecurityMenuActivity.this, actionType);
                    final JSONObject request = response.getJSONObject("request");
                    activeRequestId = request.getInt("id");
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            updateStatus("Request #" + activeRequestId + " pending admin approval.");
                            startPolling();
                        }
                    });
                } catch (final Exception exception) {
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            updateStatus("Request failed: " + exception.getMessage());
                        }
                    });
                }
            }
        }).start();
    }

    private void startPolling() {
        stopPolling();
        pollRunnable = new Runnable() {
            @Override
            public void run() {
                pollRequestStatus();
                handler.postDelayed(this, POLL_INTERVAL_MS);
            }
        };
        handler.post(pollRunnable);
    }

    private void stopPolling() {
        if (pollRunnable != null) {
            handler.removeCallbacks(pollRunnable);
            pollRunnable = null;
        }
    }

    private void pollRequestStatus() {
        if (activeRequestId <= 0) {
            return;
        }
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    JSONObject response = BackendClient.pollSecurityRequest(SecurityMenuActivity.this, activeRequestId);
                    final JSONObject request = response.getJSONObject("request");
                    final String status = request.optString("status", "");
                    final String otpCode = request.optString("otpCode", "");
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            if ("approved".equals(status)) {
                                if (otpCode.length() == 4) {
                                    stopPolling();
                                    showOtpCode(otpCode);
                                    updateStatus("Approved. OTP shown above. Auto-verifying in 2 seconds...");
                                    handler.postDelayed(new Runnable() {
                                        @Override
                                        public void run() {
                                            if (activeRequestId > 0 && !otpAutoVerifyInProgress) {
                                                verifyOtpWithCode(otpCode);
                                            }
                                        }
                                    }, 2000L);
                                } else {
                                    updateStatus("Request #" + activeRequestId + " approved. Waiting for OTP...");
                                }
                            } else if ("rejected".equals(status)) {
                                stopPolling();
                                updateStatus("Request rejected by admin.");
                            } else if ("used".equals(status)) {
                                stopPolling();
                                updateStatus("OTP already used.");
                            } else {
                                updateStatus("Request #" + activeRequestId + " waiting for admin approval...");
                            }
                        }
                    });
                } catch (Exception ignored) {
                }
            }
        }).start();
    }

    private void showOtpCode(String otpCode) {
        if (otpCode == null || otpCode.length() != 4) {
            return;
        }
        if (otpDisplayView != null) {
            otpDisplayView.setText("OTP: " + otpCode);
            otpDisplayView.setVisibility(View.VISIBLE);
        }
        if (otpInput != null) {
            otpInput.setText(otpCode);
        }
    }

    private void clearOtpDisplay() {
        if (otpDisplayView != null) {
            otpDisplayView.setText("");
            otpDisplayView.setVisibility(View.GONE);
        }
        if (otpInput != null) {
            otpInput.setText("");
        }
    }

    private void verifyOtp() {
        verifyOtpWithCode(otpInput.getText().toString().trim());
    }

    private void verifyOtpWithCode(final String otp) {
        if (otp.length() != 4) {
            Toast.makeText(this, "Enter a 4-digit OTP", Toast.LENGTH_SHORT).show();
            return;
        }
        if (activeRequestId <= 0) {
            Toast.makeText(this, "Request an action first", Toast.LENGTH_SHORT).show();
            return;
        }
        if (otpAutoVerifyInProgress) {
            return;
        }
        otpAutoVerifyInProgress = true;
        updateStatus("Verifying OTP...");
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    JSONObject response = BackendClient.verifySecurityOtp(
                            SecurityMenuActivity.this,
                            activeRequestId,
                            otp
                    );
                    final JSONObject verified = response.getJSONObject("verified");
                    final String actionType = verified.getString("actionType");
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            otpAutoVerifyInProgress = false;
                            SecurityHelper.performVerifiedAction(SecurityMenuActivity.this, actionType);
                            updateStatus("OTP verified. Action applied: " + actionType.replace('_', ' '));
                            clearOtpDisplay();
                            activeRequestId = 0;
                            Toast.makeText(SecurityMenuActivity.this, "Security action completed", Toast.LENGTH_SHORT).show();
                            if ("hide".equals(actionType)) {
                                finish();
                                return;
                            }
                            if ("unlock".equals(actionType) && !SecurityHelper.isLocked(SecurityMenuActivity.this)) {
                                finish();
                            }
                        }
                    });
                } catch (final Exception exception) {
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            otpAutoVerifyInProgress = false;
                            updateStatus("OTP verification failed: " + exception.getMessage());
                        }
                    });
                }
            }
        }).start();
    }

    private void updateStatus(String message) {
        if (statusView != null) {
            statusView.setText(message);
        }
    }
}
