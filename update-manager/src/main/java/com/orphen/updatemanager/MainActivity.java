package com.orphen.updatemanager;

import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

public class MainActivity extends Activity {
    private TextView installedVersionView;
    private TextView serverVersionView;
    private TextView statusView;
    private Button updateButton;

    private final BroadcastReceiver stateReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            if (intent == null) {
                return;
            }
            String action = intent.getAction();
            if (UpdateEngine.ACTION_STATE_CHANGED.equals(action)) {
                String message = intent.getStringExtra("message");
                if (message != null && statusView != null) {
                    statusView.setText(message);
                }
                refreshVersionUi();
            } else if (UpdateEngine.ACTION_UPDATE_AVAILABLE.equals(action)) {
                refreshVersionUi();
            }
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        PrefsHelper.ensureDefaults(this);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(48, 48, 48, 48);
        root.setBackgroundColor(Color.WHITE);
        root.setGravity(Gravity.CENTER_HORIZONTAL);

        TextView title = new TextView(this);
        title.setText("Orphen APK Installer");
        title.setTextSize(22);
        title.setGravity(Gravity.CENTER);
        root.addView(title);

        installedVersionView = new TextView(this);
        installedVersionView.setTextSize(16);
        installedVersionView.setPadding(0, 32, 0, 8);
        root.addView(installedVersionView);

        serverVersionView = new TextView(this);
        serverVersionView.setTextSize(16);
        serverVersionView.setPadding(0, 0, 0, 8);
        root.addView(serverVersionView);

        statusView = new TextView(this);
        statusView.setTextSize(14);
        statusView.setTextColor(0xFF555555);
        statusView.setPadding(0, 0, 0, 24);
        root.addView(statusView);

        updateButton = new Button(this);
        updateButton.setText("Update");
        updateButton.setTextSize(18);
        LinearLayout.LayoutParams btnParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        );
        updateButton.setLayoutParams(btnParams);
        updateButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                updateButton.setEnabled(false);
                UpdateEngine.runUpdate(MainActivity.this, new Runnable() {
                    @Override
                    public void run() {
                        runOnUiThread(new Runnable() {
                            @Override
                            public void run() {
                                refreshVersionUi();
                                updateButton.setEnabled(PrefsHelper.prefs(MainActivity.this).getBoolean(PrefsHelper.KEY_UPDATE_AVAILABLE, false));
                            }
                        });
                    }
                });
            }
        });
        root.addView(updateButton);

        setContentView(root);
        refreshVersionUi();
        fetchCatalogAsync();
        UpdateSyncService.start(this);
    }

    @Override
    protected void onResume() {
        super.onResume();
        IntentFilter filter = new IntentFilter();
        filter.addAction(UpdateEngine.ACTION_STATE_CHANGED);
        filter.addAction(UpdateEngine.ACTION_UPDATE_AVAILABLE);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(stateReceiver, filter, Context.RECEIVER_NOT_EXPORTED);
        } else {
            registerReceiver(stateReceiver, filter);
        }
        refreshVersionUi();
        fetchCatalogAsync();
    }

    @Override
    protected void onPause() {
        super.onPause();
        try {
            unregisterReceiver(stateReceiver);
        } catch (Exception ignored) {
        }
    }

    private void fetchCatalogAsync() {
        statusView.setText("Checking server…");
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    CatalogInfo catalog = CatalogFetcher.fetchTargetRelease(MainActivity.this);
                    boolean needed = UpdateEngine.isUpdateNeeded(MainActivity.this, catalog);
                    UpdateEngine.saveCatalogSnapshot(MainActivity.this, catalog, needed);
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            refreshVersionUi();
                            statusView.setText(needed ? "Update available" : "Up to date");
                        }
                    });
                } catch (Exception exception) {
                    runOnUiThread(new Runnable() {
                        @Override
                        public void run() {
                            statusView.setText("Server: " + exception.getMessage());
                            refreshVersionUi();
                        }
                    });
                }
            }
        }).start();
    }

    private void refreshVersionUi() {
        UpdateEngine.InstalledVersion installed = UpdateEngine.getInstalledVersion(getApplicationContext());
        if (installed.installed) {
            installedVersionView.setText("Installed: " + installed.versionName + " (code " + installed.versionCode + ")");
        } else {
            installedVersionView.setText("Installed: Not installed");
        }

        String serverName = PrefsHelper.prefs(this).getString(PrefsHelper.KEY_SERVER_VERSION_NAME, "—");
        int serverCode = PrefsHelper.prefs(this).getInt(PrefsHelper.KEY_SERVER_VERSION_CODE, 0);
        if (serverCode > 0) {
            serverVersionView.setText("Server: " + serverName + " (code " + serverCode + ")");
        } else {
            serverVersionView.setText("Server: —");
        }

        boolean needed = PrefsHelper.prefs(this).getBoolean(PrefsHelper.KEY_UPDATE_AVAILABLE, false);
        if (UpdateEngine.isUpdateRunning()) {
            updateButton.setEnabled(false);
            updateButton.setText("Updating…");
        } else if (needed) {
            updateButton.setEnabled(true);
            updateButton.setText("Update");
        } else {
            updateButton.setEnabled(false);
            updateButton.setText("Up to date");
        }
    }
}
