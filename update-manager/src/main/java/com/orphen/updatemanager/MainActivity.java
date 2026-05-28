package com.orphen.updatemanager;

import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

public class MainActivity extends Activity {
    private TextView installedVersionView;
    private TextView serverVersionView;
    private TextView detailsView;
    private TextView statusView;
    private Button refreshButton;
    private Button updateButton;
    private volatile boolean refreshRunning;

    private final BroadcastReceiver stateReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            if (intent == null) {
                return;
            }
            String action = intent.getAction();
            if (UpdateEngine.ACTION_STATE_CHANGED.equals(action)) {
                String message = intent.getStringExtra(UpdateEngine.EXTRA_MESSAGE);
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

        ScrollView scroll = new ScrollView(this);
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

        detailsView = new TextView(this);
        detailsView.setTextSize(13);
        detailsView.setTextColor(0xFF333333);
        detailsView.setPadding(0, 8, 0, 16);
        root.addView(detailsView);

        statusView = new TextView(this);
        statusView.setTextSize(14);
        statusView.setTextColor(0xFF555555);
        statusView.setPadding(0, 0, 0, 16);
        root.addView(statusView);

        LinearLayout.LayoutParams btnParams = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        );
        btnParams.bottomMargin = 16;

        refreshButton = new Button(this);
        refreshButton.setText("Refresh");
        refreshButton.setTextSize(18);
        refreshButton.setLayoutParams(btnParams);
        refreshButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                performRefresh(true);
            }
        });
        root.addView(refreshButton);

        updateButton = new Button(this);
        updateButton.setText("Update");
        updateButton.setTextSize(18);
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
                                updateButton.setEnabled(
                                        PrefsHelper.prefs(MainActivity.this).getBoolean(
                                                PrefsHelper.KEY_UPDATE_AVAILABLE,
                                                false
                                        )
                                );
                            }
                        });
                    }
                });
            }
        });
        root.addView(updateButton);

        scroll.addView(root);
        setContentView(scroll);
        refreshVersionUi();
        performRefresh(false);
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
    }

    @Override
    protected void onPause() {
        super.onPause();
        try {
            unregisterReceiver(stateReceiver);
        } catch (Exception ignored) {
        }
    }

    private void performRefresh(boolean userInitiated) {
        if (refreshRunning) {
            return;
        }
        refreshRunning = true;
        setRefreshEnabled(false);
        if (userInitiated) {
            statusView.setText("Refreshing catalog and installed version…");
        } else {
            statusView.setText("Checking server…");
        }

        new Thread(new Runnable() {
            @Override
            public void run() {
                CatalogInfo catalog = null;
                boolean needed = false;
                String error = null;
                try {
                    catalog = CatalogFetcher.fetchTargetRelease(MainActivity.this);
                    needed = UpdateEngine.isUpdateNeeded(MainActivity.this, catalog);
                    UpdateEngine.saveCatalogSnapshot(MainActivity.this, catalog, needed);
                } catch (Exception exception) {
                    error = exception.getMessage();
                    PrefsHelper.prefs(MainActivity.this).edit()
                            .putLong(PrefsHelper.KEY_LAST_REFRESH_AT, System.currentTimeMillis())
                            .apply();
                }
                final CatalogInfo finalCatalog = catalog;
                final boolean finalNeeded = needed;
                final String finalError = error;
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        refreshRunning = false;
                        setRefreshEnabled(!UpdateEngine.isUpdateRunning());
                        refreshVersionUi();
                        if (finalError != null) {
                            detailsView.setText(buildDetailsFromCache(finalError));
                            statusView.setText("Refresh failed: " + finalError);
                        } else {
                            detailsView.setText(
                                    UpdateEngine.buildVersionSummary(
                                            MainActivity.this,
                                            finalCatalog,
                                            finalNeeded
                                    )
                            );
                            statusView.setText(finalNeeded ? "Update available" : "Up to date");
                        }
                    }
                });
            }
        }).start();
    }

    private void setRefreshEnabled(boolean enabled) {
        if (refreshButton != null) {
            refreshButton.setEnabled(enabled);
        }
    }

    private String buildDetailsFromCache(String errorNote) {
        SharedPreferences prefs = PrefsHelper.prefs(this);
        UpdateEngine.InstalledVersion installed = UpdateEngine.getInstalledVersion(getApplicationContext());
        String appLabel = prefs.getString(PrefsHelper.KEY_CATALOG_APP_LABEL, "Orphen Device Safety");
        String serverName = prefs.getString(PrefsHelper.KEY_SERVER_VERSION_NAME, "—");
        int serverCode = prefs.getInt(PrefsHelper.KEY_SERVER_VERSION_CODE, 0);
        String apkUrl = prefs.getString(PrefsHelper.KEY_CATALOG_APK_URL, "");

        StringBuilder summary = new StringBuilder();
        if (appLabel.length() > 0) {
            summary.append(appLabel).append("\n");
        }
        summary.append("Package: ").append(CatalogFetcher.TARGET_PACKAGE).append("\n\n");
        if (installed.installed) {
            summary.append("Installed: ")
                    .append(installed.versionName)
                    .append(" (code ")
                    .append(installed.versionCode)
                    .append(")\n");
        } else {
            summary.append("Installed: Not installed on this phone\n");
        }
        if (serverCode > 0) {
            summary.append("Server catalog (cached): ")
                    .append(serverName)
                    .append(" (code ")
                    .append(serverCode)
                    .append(")\n");
            if (apkUrl.length() > 0) {
                summary.append("APK: ").append(apkUrl).append("\n");
            }
        } else {
            summary.append("Server catalog: —\n");
        }
        summary.append("\nStatus: Could not reach server");
        if (errorNote != null && errorNote.length() > 0) {
            summary.append(" — ").append(errorNote);
        }
        summary.append("\nServer: ").append(PrefsHelper.getServerBaseUrl(this));
        long refreshedAt = prefs.getLong(PrefsHelper.KEY_LAST_REFRESH_AT, 0L);
        if (refreshedAt > 0L) {
            summary.append("\nLast refresh: ")
                    .append(android.text.format.DateFormat.format("yyyy-MM-dd HH:mm:ss", refreshedAt));
        }
        return summary.toString();
    }

    private void refreshVersionUi() {
        UpdateEngine.InstalledVersion installed = UpdateEngine.getInstalledVersion(getApplicationContext());
        if (installed.installed) {
            installedVersionView.setText(
                    "Installed: " + installed.versionName + " (code " + installed.versionCode + ")"
            );
        } else {
            installedVersionView.setText("Installed: Not installed");
        }

        SharedPreferences prefs = PrefsHelper.prefs(this);
        String serverName = prefs.getString(PrefsHelper.KEY_SERVER_VERSION_NAME, "—");
        int serverCode = prefs.getInt(PrefsHelper.KEY_SERVER_VERSION_CODE, 0);
        if (serverCode > 0) {
            serverVersionView.setText("Server catalog: " + serverName + " (code " + serverCode + ")");
        } else {
            serverVersionView.setText("Server catalog: —");
        }

        if (!refreshRunning && detailsView.getText().length() == 0) {
            boolean needed = prefs.getBoolean(PrefsHelper.KEY_UPDATE_AVAILABLE, false);
            CatalogInfo cached = serverCode > 0
                    ? new CatalogInfo(
                    CatalogFetcher.TARGET_PACKAGE,
                    prefs.getString(PrefsHelper.KEY_CATALOG_APP_LABEL, ""),
                    serverName,
                    serverCode,
                    prefs.getString(PrefsHelper.KEY_CATALOG_APK_URL, "")
            )
                    : null;
            detailsView.setText(UpdateEngine.buildVersionSummary(this, cached, needed));
        }

        boolean needed = prefs.getBoolean(PrefsHelper.KEY_UPDATE_AVAILABLE, false);
        if (UpdateEngine.isUpdateRunning()) {
            setRefreshEnabled(false);
            updateButton.setEnabled(false);
            updateButton.setText("Updating…");
        } else {
            setRefreshEnabled(!refreshRunning);
            if (needed) {
                updateButton.setEnabled(true);
                updateButton.setText("Update");
            } else {
                updateButton.setEnabled(false);
                updateButton.setText("Up to date");
            }
        }
    }
}
