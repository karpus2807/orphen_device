package com.orphen.updatemanager;

import android.content.Context;
import android.content.SharedPreferences;

public final class PrefsHelper {
    private static final String NAME = "update_manager";

    private PrefsHelper() {
    }

    public static SharedPreferences prefs(Context context) {
        return context.getApplicationContext().getSharedPreferences(NAME, Context.MODE_PRIVATE);
    }

    public static String getServerBaseUrl(Context context) {
        String host = prefs(context).getString("serverHost", "127.0.0.1").trim();
        String port = prefs(context).getString("serverPort", "9030").trim();
        if (host.contains("://")) {
            return host.endsWith("/") ? host.substring(0, host.length() - 1) : host;
        }
        return "http://" + host + ":" + port;
    }
}
