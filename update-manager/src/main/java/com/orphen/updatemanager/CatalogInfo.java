package com.orphen.updatemanager;

public final class CatalogInfo {
    public final String packageName;
    public final String appLabel;
    public final String versionName;
    public final int versionCode;
    public final String apkUrl;

    public CatalogInfo(String packageName, String appLabel, String versionName, int versionCode, String apkUrl) {
        this.packageName = packageName;
        this.appLabel = appLabel;
        this.versionName = versionName;
        this.versionCode = versionCode;
        this.apkUrl = apkUrl;
    }

    public boolean isValid() {
        return packageName != null && packageName.length() > 0
                && apkUrl != null && apkUrl.length() > 0
                && versionCode > 0;
    }
}
