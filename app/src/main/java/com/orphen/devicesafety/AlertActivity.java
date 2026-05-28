package com.orphen.devicesafety;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;

public class AlertActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        String message = getIntent().getStringExtra("message");
        if (message == null || message.trim().length() == 0) {
            message = "Message from admin.";
        }

        final String alertMessage = message;
        new AlertDialog.Builder(this)
                .setTitle("Admin Alert")
                .setMessage(alertMessage)
                .setCancelable(false)
                .setPositiveButton("OK", new android.content.DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(android.content.DialogInterface dialog, int which) {
                        finish();
                    }
                })
                .show();
    }
}
