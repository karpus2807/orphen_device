package com.orphen.updatemanager;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(48, 48, 48, 48);
        root.setBackgroundColor(Color.WHITE);

        TextView title = new TextView(this);
        title.setText("Orphen APK Installer");
        title.setTextSize(22);
        root.addView(title);

        TextView hint = new TextView(this);
        hint.setText(
                "Install once on the phone. It checks your server for new APKs, installs updates automatically, "
                        + "then deletes the downloaded APK file. Allow \"Install unknown apps\" when Android asks."
        );
        hint.setTextSize(14);
        root.addView(hint);

        EditText host = new EditText(this);
        host.setHint("Server host (e.g. ipserver.in)");
        host.setText(PrefsHelper.prefs(this).getString("serverHost", "ipserver.in"));
        root.addView(host);

        EditText port = new EditText(this);
        port.setHint("Port (9030)");
        port.setText(PrefsHelper.prefs(this).getString("serverPort", "9030"));
        root.addView(port);

        Button save = new Button(this);
        save.setText("Save & start auto-install");
        save.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                PrefsHelper.prefs(MainActivity.this).edit()
                        .putString("serverHost", host.getText().toString().trim())
                        .putString("serverPort", port.getText().toString().trim())
                        .apply();
                UpdateSyncService.start(MainActivity.this);
                Toast.makeText(MainActivity.this, "APK installer service started", Toast.LENGTH_LONG).show();
            }
        });
        root.addView(save);

        Button syncNow = new Button(this);
        syncNow.setText("Check for updates now");
        syncNow.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                PrefsHelper.prefs(MainActivity.this).edit()
                        .putString("serverHost", host.getText().toString().trim())
                        .putString("serverPort", port.getText().toString().trim())
                        .apply();
                UpdateSyncService.start(MainActivity.this);
                Toast.makeText(MainActivity.this, "Checking server…", Toast.LENGTH_SHORT).show();
            }
        });
        root.addView(syncNow);

        setContentView(root);
        if (PrefsHelper.prefs(this).getString("serverHost", "").length() > 0) {
            UpdateSyncService.start(this);
        }
    }
}
