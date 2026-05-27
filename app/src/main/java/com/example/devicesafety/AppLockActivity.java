package com.example.devicesafety;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

public class AppLockActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true);
            setTurnScreenOn(true);
        } else {
            getWindow().addFlags(
                    WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                            | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
                            | WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON
            );
        }

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setBackgroundColor(Color.parseColor("#1A237E"));
        root.setPadding(48, 48, 48, 48);

        TextView title = new TextView(this);
        title.setText("App Locked");
        title.setTextColor(Color.WHITE);
        title.setTextSize(28);
        title.setGravity(Gravity.CENTER_HORIZONTAL);
        root.addView(title);

        TextView body = new TextView(this);
        body.setText("This app is locked by your administrator.\nUse the secret menu to request an unlock OTP.");
        body.setTextColor(Color.WHITE);
        body.setTextSize(16);
        body.setPadding(0, 32, 0, 32);
        body.setGravity(Gravity.CENTER_HORIZONTAL);
        root.addView(body);

        TextView hint = new TextView(this);
        hint.setText("Dial *#*#15072377#*#* from the phone dialer");
        hint.setTextColor(Color.parseColor("#C5CAE9"));
        hint.setTextSize(14);
        hint.setGravity(Gravity.CENTER_HORIZONTAL);
        root.addView(hint);

        Button unlock = new Button(this);
        unlock.setText("Open Security Menu");
        unlock.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                Intent menuIntent = new Intent(AppLockActivity.this, SecurityMenuActivity.class);
                menuIntent.putExtra(SecurityHelper.EXTRA_ACTION, "unlock");
                startActivity(menuIntent);
            }
        });
        root.addView(unlock);

        setContentView(root);
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (!SecurityHelper.isLocked(this)) {
            finish();
        }
    }

    @Override
    public void onBackPressed() {
    }
}
