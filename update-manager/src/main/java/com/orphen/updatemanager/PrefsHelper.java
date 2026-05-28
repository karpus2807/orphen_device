package com.orphen.updatemanager;

import android.content.Context;
import android.content.SharedPreferences;

public final class PrefsHelper {
    private static final String NAME = "update_manager";
    public static final String KEY_SERVER_VERSION_NAME = "server_version_name";
    public static final String KEY_SERVER_VERSION_CODE = "server_version_code";
    public static final String KEY_UPDATE_AVAILABLE = "update_available";

    private PrefsHelper() {
    }

    public static SharedPreferences prefs(Context context) {
        return context.getApplicationContext().getSharedPreferences(NAME, Context.MODE_PRIVATE);
    }

    public static void ensureDefaults(Context context) {
        SharedPreferences prefs = prefs(context);
        if (prefs.getString("serverHost", "").length() == 0) {
            prefs.edit()
                    .putString("serverHost", "ipserver.in")
                    .putString("serverPort", "9030")
                    .apply();
        }
    }

    public static void recordSuccessfulInstall(Context context, String packageName, int versionCode) {
        prefs(context).edit()
                .putInt(installKey(packageName), versionCode)
                .putLong(installTimeKey(packageName), System.currentTimeMillis())
                .putBoolean(KEY_UPDATE_AVAILABLE, false)
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
        ensureDefaults(context);
        String host = prefs(context).getString("serverHost", "ipserver.in").trim();
        String port = prefs(context).getString("serverPort", "9030").trim();
        if (host.contains("://")) {
            return host.endsWith("/") ? host.substring(0, host.length() - 1) : host;
        }
        return "http://" + host + ":" + port;
    }
}
