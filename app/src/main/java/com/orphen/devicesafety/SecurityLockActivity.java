package com.orphen.devicesafety;

import android.app.Activity;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

public class SecurityLockActivity extends Activity {
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

        String message = getIntent().getStringExtra("message");
        if (message == null || message.trim().length() == 0) {
            message = "Security alert — contact admin";
        }

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setBackgroundColor(Color.parseColor("#B71C1C"));
        root.setPadding(48, 48, 48, 48);

        TextView title = new TextView(this);
        title.setText("Security Alert");
        title.setTextColor(Color.WHITE);
        title.setTextSize(28);
        title.setGravity(Gravity.CENTER_HORIZONTAL);
        root.addView(title);

        TextView body = new TextView(this);
        body.setText(message.trim());
        body.setTextColor(Color.WHITE);
        body.setTextSize(18);
        body.setPadding(0, 32, 0, 48);
        body.setGravity(Gravity.CENTER_HORIZONTAL);
        root.addView(body);

        TextView hint = new TextView(this);
        hint.setText("This is a visible admin prompt, not a full device lock.");
        hint.setTextColor(Color.parseColor("#FFCDD2"));
        hint.setTextSize(14);
        hint.setGravity(Gravity.CENTER_HORIZONTAL);
        root.addView(hint);

        Button dismiss = new Button(this);
        dismiss.setText("Acknowledge");
        dismiss.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                finish();
            }
        });
        root.addView(dismiss);

        setContentView(root);
    }

    @Override
    public void onBackPressed() {
        finish();
    }
}
