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

    public static void recordSuccessfulInstall(Context context, String packageName, int versionCode) {
        prefs(context).edit()
                .putInt(installKey(packageName), versionCode)
                .putLong(installTimeKey(packageName), System.currentTimeMillis())
                .apply();
    }

    public static int getRecordedInstallCode(Context context, String packageName) {
        return prefs(context).getInt(installKey(packageName), 0);
    }

    private static String installKey(String packageName) {
        return "installed_code_" + packageName;
    }

    private static String installTimeKey(String packageName) {
        return "installed_time_" + packageName;
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
