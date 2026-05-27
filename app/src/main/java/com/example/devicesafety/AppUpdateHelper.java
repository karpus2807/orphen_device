package com.example.devicesafety;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.DownloadManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Environment;

public final class AppUpdateHelper {
    private AppUpdateHelper() {
    }

    public static String handleUpdateCommand(final Context context, String payload) throws Exception {
        String version = BackendClient.extractJsonValue(payload, "version").trim();
        String apkUrl = BackendClient.extractJsonValue(payload, "apkUrl").trim();
        String releaseNotes = BackendClient.extractJsonValue(payload, "releaseNotes").trim();
        if (apkUrl.length() == 0) {
            throw new Exception("APK URL is missing");
        }

        String currentVersion = readAppVersion(context);
        if (version.length() > 0 && version.equals(currentVersion)) {
            return "Device already has version " + version;
        }

        final String notes = releaseNotes.length() > 0 ? releaseNotes : "A new app version is available.";
        final String targetVersion = version.length() > 0 ? version : "latest";

        if (context instanceof Activity) {
            final Activity activity = (Activity) context;
            activity.runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    new AlertDialog.Builder(activity)
                            .setTitle("App Update Available")
                            .setMessage("Version " + targetVersion + "\n\n" + notes)
                            .setPositiveButton("Download Update", new android.content.DialogInterface.OnClickListener() {
                                @Override
                                public void onClick(android.content.DialogInterface dialog, int which) {
                                    try {
                                        queueDownload(context, apkUrl, targetVersion);
                                    } catch (Exception exception) {
                                        openApkUrl(context, apkUrl);
                                    }
                                }
                            })
                            .setNegativeButton("Later", null)
                            .show();
                }
            });
            return "Update prompt shown for version " + targetVersion;
        }

        queueDownload(context, apkUrl, targetVersion);
        return "Update download queued for version " + targetVersion;
    }

    private static void queueDownload(Context context, String apkUrl, String versionLabel) {
        DownloadManager.Request request = new DownloadManager.Request(Uri.parse(apkUrl));
        request.setTitle("Device Safety Manager update");
        request.setDescription("Downloading version " + versionLabel);
        request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
        request.setMimeType("application/vnd.android.package-archive");
        request.setDestinationInExternalPublicDir(
                Environment.DIRECTORY_DOWNLOADS,
                "device-safety-" + versionLabel.replaceAll("[^a-zA-Z0-9._-]", "_") + ".apk"
        );
        DownloadManager manager = (DownloadManager) context.getSystemService(Context.DOWNLOAD_SERVICE);
        if (manager != null) {
            manager.enqueue(request);
        }
    }

    private static void openApkUrl(Context context, String apkUrl) {
        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(apkUrl));
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        context.startActivity(intent);
    }

    private static String readAppVersion(Context context) {
        try {
            PackageInfo info = context.getPackageManager().getPackageInfo(context.getPackageName(), 0);
            return info.versionName == null ? "" : info.versionName;
        } catch (PackageManager.NameNotFoundException exception) {
            return "";
        }
    }
}
