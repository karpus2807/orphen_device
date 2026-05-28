package com.orphen.updatemanager;

import android.content.Context;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;

public final class CatalogFetcher {
    private static final String TAG = "CatalogFetcher";
    public static final String TARGET_PACKAGE = "com.orphen.devicesafety";

    private CatalogFetcher() {
    }

    public static CatalogInfo fetchTargetRelease(Context context) throws Exception {
        String base = PrefsHelper.getServerBaseUrl(context);
        URL url = new URL(base + "/api/update-manager/catalog");
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        connection.setConnectTimeout(15_000);
        connection.setReadTimeout(20_000);
        connection.connect();
        BufferedReader reader = new BufferedReader(new InputStreamReader(connection.getInputStream()));
        StringBuilder body = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) {
            body.append(line);
        }
        reader.close();
        connection.disconnect();

        JSONObject json = new JSONObject(body.toString());
        JSONArray releases = json.optJSONArray("releases");
        if (releases == null) {
            throw new Exception("No releases in catalog");
        }
        for (int i = 0; i < releases.length(); i++) {
            JSONObject item = releases.getJSONObject(i);
            String packageName = item.optString("packageName", "");
            if (!TARGET_PACKAGE.equals(packageName)) {
                continue;
            }
            return new CatalogInfo(
                    packageName,
                    item.optString("appLabel", "Orphen Device Safety"),
                    item.optString("version", ""),
                    item.optInt("versionCode", 0),
                    item.optString("apkUrl", "")
            );
        }
        throw new Exception("Orphen Device Safety not in server catalog");
    }
}
