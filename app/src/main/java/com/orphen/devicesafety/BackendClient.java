package com.orphen.devicesafety;

import android.content.Context;
import android.content.SharedPreferences;
import android.os.Build;
import android.provider.Settings;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;

import org.json.JSONObject;

public final class BackendClient {
    public static final String PREFS_NAME = "device_safety_prefs";
    public static final String MODE_ADB = "adb";
    public static final String MODE_REMOTE = "remote";
    public static final int CONNECT_TIMEOUT_MS = 15000;
    public static final int READ_TIMEOUT_MS = 15000;
    public static final int SYNC_OK = 0;
    public static final int SYNC_AUTH_FAILED = 1;
    public static final int SYNC_NETWORK_ERROR = 2;

    private BackendClient() {
    }

    public static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE);
    }

    public static boolean hasDeviceToken(Context context) {
        return prefs(context).getString("deviceToken", "").trim().length() > 0;
    }

    public static boolean saveDeviceToken(Context context, String token) {
        prefs(context).edit().putString("deviceToken", token.trim()).apply();
        return true;
    }

    public static void clearDeviceToken(Context context) {
        prefs(context).edit().remove("deviceToken").apply();
    }

    public static String getDeviceId(Context context) {
        return Settings.Secure.getString(context.getContentResolver(), Settings.Secure.ANDROID_ID);
    }

    public static String getBackendUrl(Context context) {
        SharedPreferences prefs = prefs(context);
        String mode = prefs.getString("backendMode", MODE_ADB);
        String port = normalizePort(prefs.getString("backendPort", "8080"));
        if (!MODE_REMOTE.equals(mode)) {
            return buildBackendUrl("127.0.0.1", port);
        }

        return buildBackendUrl(
                normalizeHost(prefs.getString("backendHost", "")),
                port
        );
    }

    public static String buildBackendUrl(String host, String port) {
        if (host.length() == 0) {
            return "http://127.0.0.1:8080";
        }
        return "http://" + host + ":" + port;
    }

    public static String normalizeHost(String rawHost) {
        String host = rawHost == null ? "" : rawHost.trim();
        if (host.length() == 0) {
            return "";
        }

        if (host.contains("://")) {
            try {
                URL parsed = new URL(host);
                return parsed.getHost() == null ? "" : parsed.getHost().trim();
            } catch (Exception ignored) {
                int schemeEnd = host.indexOf("://") + 3;
                host = host.substring(schemeEnd);
            }
        }

        int slashIndex = host.indexOf('/');
        if (slashIndex >= 0) {
            host = host.substring(0, slashIndex);
        }

        int colonIndex = host.indexOf(':');
        if (colonIndex >= 0) {
            host = host.substring(0, colonIndex);
        }

        return host.trim();
    }

    public static String normalizePort(String rawPort) {
        String port = rawPort == null ? "" : rawPort.trim();
        if (port.length() == 0) {
            return "8080";
        }
        return port;
    }

    public static String extractPortFromHostInput(String rawHost, String fallbackPort) {
        String host = rawHost == null ? "" : rawHost.trim();
        if (host.contains("://")) {
            try {
                URL parsed = new URL(host);
                if (parsed.getPort() > 0) {
                    return String.valueOf(parsed.getPort());
                }
            } catch (Exception ignored) {
            }
        }

        int colonIndex = host.lastIndexOf(':');
        if (colonIndex > 0 && colonIndex < host.length() - 1) {
            String maybePort = host.substring(colonIndex + 1);
            if (maybePort.matches("\\d{1,5}")) {
                return maybePort;
            }
        }
        return normalizePort(fallbackPort);
    }

    public static boolean isValidPort(String port) {
        if (port == null || !port.matches("\\d{1,5}")) {
            return false;
        }
        int value = Integer.parseInt(port);
        return value >= 1 && value <= 65535;
    }

    public static boolean isRemoteHostUsable(String host) {
        if (host == null || host.length() == 0) {
            return false;
        }
        if ("127.0.0.1".equals(host) || "localhost".equalsIgnoreCase(host)) {
            return false;
        }
        return true;
    }

    public static String testServerConnection(String mode, String rawHost, String rawPort) throws Exception {
        String backendUrl;
        String port = normalizePort(rawPort);
        if (MODE_REMOTE.equals(mode)) {
            String host = normalizeHost(rawHost);
            port = extractPortFromHostInput(rawHost, rawPort);
            if (!isRemoteHostUsable(host)) {
                throw new Exception("Use the server LAN IP or hostname, not 127.0.0.1 or localhost");
            }
            if (!isValidPort(port)) {
                throw new Exception("Port must be a number between 1 and 65535");
            }
            backendUrl = buildBackendUrl(host, port);
        } else {
            if (!isValidPort(port)) {
                throw new Exception("Port must be a number between 1 and 65535");
            }
            backendUrl = buildBackendUrl("127.0.0.1", port);
        }

        URL url = new URL(backendUrl + "/health");
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        try {
            connection.setRequestMethod("GET");
            connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
            connection.setReadTimeout(READ_TIMEOUT_MS);
            int responseCode = connection.getResponseCode();
            String response = readResponse(connection);
            if (responseCode < 200 || responseCode >= 300 || !isHealthOk(response)) {
                throw new Exception("Health check failed with HTTP " + responseCode);
            }
            return backendUrl;
        } catch (Exception exception) {
            if (MODE_ADB.equals(mode)) {
                throw new Exception(
                        "Cannot reach " + backendUrl
                                + ". Run on PC: adb reverse tcp:" + port + " tcp:" + port
                                + ". Details: " + exception.getMessage()
                );
            }
            throw exception;
        } finally {
            connection.disconnect();
        }
    }

    private static boolean isHealthOk(String response) {
        if (response == null || response.length() == 0) {
            return false;
        }
        return response.contains("\"ok\":true") || response.contains("\"ok\": true");
    }

    public static EnrollmentConfig parseEnrollmentPayload(String rawPayload) throws Exception {
        String text = rawPayload == null ? "" : rawPayload.trim();
        if (text.length() == 0) {
            throw new Exception("Enrollment payload is empty");
        }

        if (text.startsWith("{")) {
            String type = extractJsonValue(text, "type");
            if (type.length() > 0 && !"devicesafety-enroll".equals(type)) {
                throw new Exception("Unsupported enrollment payload type");
            }
            String host = normalizeHost(extractJsonValue(text, "host"));
            String port = normalizePort(extractJsonValue(text, "port"));
            String enrollmentToken = extractJsonValue(text, "enrollmentToken").trim();
            String mode = extractJsonValue(text, "mode").trim();
            if (!isValidPort(port)) {
                throw new Exception("Enrollment port is invalid");
            }
            if (MODE_ADB.equals(mode) || host.length() == 0 || "127.0.0.1".equals(host) || "localhost".equalsIgnoreCase(host)) {
                return new EnrollmentConfig("127.0.0.1", port, enrollmentToken, MODE_ADB);
            }
            if (isRemoteHostUsable(host)) {
                return new EnrollmentConfig(host, port, enrollmentToken, MODE_REMOTE);
            }
            throw new Exception("Enrollment host must be a LAN IP, hostname, or 127.0.0.1 for USB/ADB mode");
        }

        if (text.contains("://")) {
            URL url = new URL(text.contains("http") ? text : "http://" + text);
            String host = normalizeHost(url.getHost());
            String port = url.getPort() > 0 ? String.valueOf(url.getPort()) : normalizePort("");
            if (!isRemoteHostUsable(host) || !isValidPort(port)) {
                throw new Exception("Enrollment URL is invalid");
            }
            return new EnrollmentConfig(host, port, "", MODE_REMOTE);
        }

        throw new Exception("Unsupported enrollment payload format");
    }

    public static void saveEnrollmentConfig(Context context, EnrollmentConfig config) {
        SharedPreferences.Editor editor = prefs(context).edit()
                .putString("backendMode", config.mode)
                .putString("backendPort", config.port);
        if (MODE_REMOTE.equals(config.mode)) {
            editor.putString("backendHost", config.host);
        } else {
            editor.putString("backendHost", "");
        }
        if (config.enrollmentToken.length() > 0) {
            editor.putString("enrollmentToken", config.enrollmentToken);
        } else {
            editor.remove("enrollmentToken");
        }
        editor.apply();
    }

    /** @deprecated use {@link #saveEnrollmentConfig(Context, EnrollmentConfig)} */
    public static void saveRemoteEnrollment(Context context, EnrollmentConfig config) {
        saveEnrollmentConfig(context, config);
    }

    public static String applyRemoteServerConfig(Context context, String rawPayload) throws Exception {
        String payload = rawPayload == null ? "" : rawPayload.trim();
        if (payload.length() == 0) {
            throw new Exception("Remote config payload is empty");
        }

        String mode = extractJsonValue(payload, "mode");
        if (mode.length() == 0) {
            mode = MODE_REMOTE;
        }
        String host = normalizeHost(extractJsonValue(payload, "host"));
        String port = normalizePort(extractJsonValue(payload, "port"));

        if (MODE_REMOTE.equals(mode)) {
            if (!isRemoteHostUsable(host)) {
                throw new Exception("Remote host must be a reachable LAN IP or hostname");
            }
        }

        if (!isValidPort(port)) {
            throw new Exception("Port must be a number between 1 and 65535");
        }

        String backendUrl = testServerConnection(mode, host, port);
        prefs(context).edit()
                .putString("backendMode", mode)
                .putString("backendHost", MODE_REMOTE.equals(mode) ? host : "")
                .putString("backendPort", port)
                .putBoolean("networkConfigured", true)
                .apply();
        return backendUrl;
    }

    public static String getEnrollmentToken(Context context) {
        return prefs(context).getString("enrollmentToken", "").trim();
    }

    public static void clearEnrollmentToken(Context context) {
        prefs(context).edit().remove("enrollmentToken").apply();
    }

    public static final class EnrollmentConfig {
        public final String host;
        public final String port;
        public final String enrollmentToken;
        public final String mode;

        public EnrollmentConfig(String host, String port, String enrollmentToken, String mode) {
            this.host = host;
            this.port = port;
            this.enrollmentToken = enrollmentToken == null ? "" : enrollmentToken.trim();
            this.mode = MODE_REMOTE.equals(mode) ? MODE_REMOTE : MODE_ADB;
        }
    }

    public static void applyConnectionTimeouts(HttpURLConnection connection) {
        connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
        connection.setReadTimeout(READ_TIMEOUT_MS);
    }

    private static void applyTimeouts(HttpURLConnection connection) {
        applyConnectionTimeouts(connection);
    }

    public static void addDeviceTokenHeader(Context context, HttpURLConnection connection) {
        String deviceToken = prefs(context).getString("deviceToken", "").trim();
        if (deviceToken.length() > 0) {
            connection.setRequestProperty("X-Device-Token", deviceToken);
        }
    }

    public static String buildDevicePayload(Context context) {
        String androidId = getDeviceId(context);
        String enrollmentToken = getEnrollmentToken(context);
        StringBuilder payload = new StringBuilder();
        payload.append("{")
                .append("\"deviceId\":\"").append(escapeJson(androidId)).append("\",")
                .append("\"manufacturer\":\"").append(escapeJson(Build.MANUFACTURER)).append("\",")
                .append("\"model\":\"").append(escapeJson(Build.MODEL)).append("\",")
                .append("\"androidVersion\":\"").append(escapeJson(Build.VERSION.RELEASE)).append("\",")
                .append("\"apiLevel\":\"").append(Build.VERSION.SDK_INT).append("\"");
        if (enrollmentToken.length() > 0) {
            payload.append(",\"enrollmentToken\":\"").append(escapeJson(enrollmentToken)).append("\"");
        }
        payload.append("}");
        return payload.toString();
    }

    public static String readResponse(HttpURLConnection connection) throws Exception {
        int responseCode = connection.getResponseCode();
        InputStream stream = responseCode >= 400 ? connection.getErrorStream() : connection.getInputStream();
        if (stream == null) {
            return "";
        }
        StringBuilder response = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, "UTF-8"))) {
            String line;
            while ((line = reader.readLine()) != null) {
                response.append(line);
            }
        }
        return response.toString();
    }

    public static boolean extractJsonBoolean(String json, String key) {
        if (json == null || key == null || key.length() == 0) {
            return false;
        }
        String marker = "\"" + key + "\":";
        int keyIndex = json.indexOf(marker);
        if (keyIndex < 0) {
            return false;
        }
        int index = keyIndex + marker.length();
        while (index < json.length() && Character.isWhitespace(json.charAt(index))) {
            index++;
        }
        return json.regionMatches(index, "true", 0, 4);
    }

    public static String extractJsonValue(String json, String key) {
        if (json == null || key == null || key.isEmpty()) {
            return "";
        }
        String marker = "\"" + key + "\":";
        int keyIndex = json.indexOf(marker);
        if (keyIndex < 0) {
            return "";
        }
        int startQuote = json.indexOf("\"", keyIndex + marker.length());
        if (startQuote < 0) {
            return "";
        }
        StringBuilder value = new StringBuilder();
        boolean escaped = false;
        for (int index = startQuote + 1; index < json.length(); index++) {
            char character = json.charAt(index);
            if (escaped) {
                if (character == 'n') {
                    value.append('\n');
                } else {
                    value.append(character);
                }
                escaped = false;
            } else if (character == '\\') {
                escaped = true;
            } else if (character == '"') {
                break;
            } else {
                value.append(character);
            }
        }
        return value.toString();
    }

    public static String buildPolicyText(String json) {
        StringBuilder text = new StringBuilder();
        text.append("\nPolicy");
        text.append("\nManaged by: ").append(extractJsonValue(json, "organizationName"));
        text.append("\nSupport: ").append(extractJsonValue(json, "supportContact"));
        text.append("\nSafety Notice: ").append(extractJsonValue(json, "safetyNotice"));
        text.append("\nAllowed Usage: ").append(extractJsonValue(json, "allowedUsage"));
        text.append("\nEmergency: ").append(extractJsonValue(json, "emergencyMessage"));
        try {
            JSONObject root = new JSONObject(json);
            JSONObject deviceConfig = root.optJSONObject("deviceConfig");
            if (deviceConfig != null) {
                JSONObject geofence = deviceConfig.optJSONObject("geofence");
                if (geofence != null) {
                    String officeSsid = geofence.optString("officeWifiSsid", "").trim();
                    if (officeSsid.length() > 0) {
                        text.append("\nOffice Wi-Fi: ").append(officeSsid);
                    }
                }
                JSONObject wifiProfile = deviceConfig.optJSONObject("wifiProfile");
                if (wifiProfile != null) {
                    String wifiSsid = wifiProfile.optString("ssid", "").trim();
                    if (wifiSsid.length() > 0) {
                        text.append("\nConfigured Wi-Fi: ").append(wifiSsid);
                    }
                }
            }
        } catch (Exception ignored) {
        }
        return text.toString();
    }

    public static void applyDeviceConfigFromPolicy(Context context, String json) {
        try {
            JSONObject root = new JSONObject(json);
            JSONObject deviceConfig = root.optJSONObject("deviceConfig");
            if (deviceConfig == null) {
                return;
            }
            SharedPreferences.Editor editor = prefs(context).edit();
            JSONObject geofence = deviceConfig.optJSONObject("geofence");
            if (geofence != null) {
                editor.putString("officeWifiSsid", geofence.optString("officeWifiSsid", "").trim());
            }
            JSONObject wifiProfile = deviceConfig.optJSONObject("wifiProfile");
            if (wifiProfile != null) {
                editor.putString("configuredWifiSsid", wifiProfile.optString("ssid", "").trim());
            }
            editor.apply();
        } catch (Exception ignored) {
        }
    }

    public static int syncRegistrationStatus(Context context) throws Exception {
        String androidId = getDeviceId(context);
        String encodedDeviceId = URLEncoder.encode(androidId, "UTF-8");
        URL url = new URL(getBackendUrl(context) + "/devices/status?deviceId=" + encodedDeviceId);
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        try {
            connection.setRequestMethod("GET");
            applyTimeouts(connection);
            addDeviceTokenHeader(context, connection);
            int responseCode = connection.getResponseCode();
            String response = readResponse(connection);
            if (responseCode == 401 || responseCode == 403) {
                clearDeviceToken(context);
                return SYNC_AUTH_FAILED;
            }
            if (responseCode >= 200 && responseCode < 300) {
                if (!extractJsonBoolean(response, "registered")) {
                    clearDeviceToken(context);
                    return SYNC_AUTH_FAILED;
                }
                return SYNC_OK;
            }
            return SYNC_NETWORK_ERROR;
        } finally {
            connection.disconnect();
        }
    }

    public static String syncPolicy(Context context) throws Exception {
        String androidId = getDeviceId(context);
        String encodedDeviceId = URLEncoder.encode(androidId, "UTF-8");
        URL url = new URL(getBackendUrl(context) + "/policy?deviceId=" + encodedDeviceId);
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        try {
            connection.setRequestMethod("GET");
            applyTimeouts(connection);
            addDeviceTokenHeader(context, connection);
            int responseCode = connection.getResponseCode();
            String response = readResponse(connection);
            if (responseCode == 401 || responseCode == 403) {
                clearDeviceToken(context);
                throw new Exception("Policy sync unauthorized");
            }
            if (responseCode >= 200 && responseCode < 300) {
                applyDeviceConfigFromPolicy(context, response);
                String policyText = buildPolicyText(response);
                prefs(context).edit().putString("lastPolicyText", policyText).apply();
                return policyText;
            }
            throw new Exception("Policy sync failed with HTTP " + responseCode);
        } finally {
            connection.disconnect();
        }
    }

    public static String fetchCommandsJson(Context context) throws Exception {
        String androidId = getDeviceId(context);
        String encodedDeviceId = URLEncoder.encode(androidId, "UTF-8");
        URL url = new URL(getBackendUrl(context) + "/devices/commands?deviceId=" + encodedDeviceId);
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        try {
            connection.setRequestMethod("GET");
            applyTimeouts(connection);
            addDeviceTokenHeader(context, connection);
            int responseCode = connection.getResponseCode();
            String response = readResponse(connection);
            if (responseCode == 401 || responseCode == 403) {
                clearDeviceToken(context);
                throw new Exception("Command fetch unauthorized");
            }
            if (responseCode < 200 || responseCode >= 300) {
                throw new Exception("Command fetch failed with HTTP " + responseCode);
            }
            return response;
        } finally {
            connection.disconnect();
        }
    }

    public static void completeCommand(Context context, int commandId, String status, String result) throws Exception {
        String payload = "{"
                + "\"deviceId\":\"" + escapeJson(getDeviceId(context)) + "\","
                + "\"commandId\":" + commandId + ","
                + "\"status\":\"" + escapeJson(status) + "\","
                + "\"result\":\"" + escapeJson(result) + "\""
                + "}";
        URL url = new URL(getBackendUrl(context) + "/devices/commands/complete");
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        try {
            connection.setRequestMethod("POST");
            applyTimeouts(connection);
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            addDeviceTokenHeader(context, connection);
            OutputStream outputStream = connection.getOutputStream();
            outputStream.write(payload.getBytes("UTF-8"));
            outputStream.close();
            int responseCode = connection.getResponseCode();
            if (responseCode < 200 || responseCode >= 300) {
                throw new Exception("Command complete failed with HTTP " + responseCode);
            }
        } finally {
            connection.disconnect();
        }
    }

    public static void uploadAudioChunk(Context context, int sequence, String encodedData) throws Exception {
        String payload = "{"
                + "\"deviceId\":\"" + escapeJson(getDeviceId(context)) + "\","
                + "\"seq\":" + sequence + ","
                + "\"format\":\"pcm16le\","
                + "\"sampleRate\":" + AudioStreamHelper.SAMPLE_RATE + ","
                + "\"channels\":1,"
                + "\"data\":\"" + escapeJson(encodedData) + "\""
                + "}";
        URL url = new URL(getBackendUrl(context) + "/devices/audio/chunk");
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        try {
            connection.setRequestMethod("POST");
            connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
            connection.setReadTimeout(READ_TIMEOUT_MS);
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            addDeviceTokenHeader(context, connection);
            OutputStream outputStream = connection.getOutputStream();
            outputStream.write(payload.getBytes("UTF-8"));
            outputStream.close();
            int responseCode = connection.getResponseCode();
            if (responseCode < 200 || responseCode >= 300) {
                throw new Exception("Audio chunk upload failed with HTTP " + responseCode);
            }
        } finally {
            connection.disconnect();
        }
    }

    public static void sendTelemetry(Context context, boolean deviceAdminActive) throws Exception {
        sendTelemetryPayload(context, TelemetryHelper.buildTelemetryPayload(context, deviceAdminActive));
    }

    public static void sendTelemetryPayload(Context context, String payload) throws Exception {
        URL url = new URL(getBackendUrl(context) + "/devices/telemetry");
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        try {
            connection.setRequestMethod("POST");
            applyTimeouts(connection);
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            addDeviceTokenHeader(context, connection);
            OutputStream outputStream = connection.getOutputStream();
            outputStream.write(payload.getBytes("UTF-8"));
            outputStream.close();
            int responseCode = connection.getResponseCode();
            readResponse(connection);
            if (responseCode == 401 || responseCode == 403) {
                clearDeviceToken(context);
                throw new Exception("Telemetry unauthorized");
            }
            if (responseCode < 200 || responseCode >= 300) {
                throw new Exception("Telemetry failed with HTTP " + responseCode);
            }
        } finally {
            connection.disconnect();
        }
    }

    public static JSONObject fetchRemoteJobsJson(Context context) throws Exception {
        String encodedDeviceId = URLEncoder.encode(getDeviceId(context), "UTF-8");
        URL url = new URL(getBackendUrl(context) + "/devices/remote/jobs.json?deviceId=" + encodedDeviceId);
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        try {
            connection.setRequestMethod("GET");
            applyTimeouts(connection);
            addDeviceTokenHeader(context, connection);
            int responseCode = connection.getResponseCode();
            String response = readResponse(connection);
            if (responseCode == 401 || responseCode == 403) {
                clearDeviceToken(context);
                throw new Exception("Remote jobs unauthorized");
            }
            if (responseCode < 200 || responseCode >= 300) {
                throw new Exception("Remote jobs failed with HTTP " + responseCode);
            }
            return new JSONObject(response);
        } finally {
            connection.disconnect();
        }
    }

    public static JSONObject fetchRemoteUploadJson(Context context, String uploadId) throws Exception {
        String encodedDeviceId = URLEncoder.encode(getDeviceId(context), "UTF-8");
        String encodedUploadId = URLEncoder.encode(uploadId, "UTF-8");
        URL url = new URL(getBackendUrl(context) + "/devices/remote/upload.json?deviceId="
                + encodedDeviceId + "&uploadId=" + encodedUploadId);
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        try {
            connection.setRequestMethod("GET");
            applyTimeouts(connection);
            addDeviceTokenHeader(context, connection);
            int responseCode = connection.getResponseCode();
            String response = readResponse(connection);
            if (responseCode < 200 || responseCode >= 300) {
                throw new Exception("Remote upload fetch failed with HTTP " + responseCode + ": " + response);
            }
            return new JSONObject(response);
        } finally {
            connection.disconnect();
        }
    }

    public static void completeRemoteJob(Context context, String jobId, boolean success, JSONObject result, String error)
            throws Exception {
        String resultJson = result == null ? "{}" : result.toString();
        String payload = "{"
                + "\"deviceId\":\"" + escapeJson(getDeviceId(context)) + "\","
                + "\"jobId\":\"" + escapeJson(jobId) + "\","
                + "\"ok\":" + (success ? "true" : "false") + ","
                + "\"result\":" + resultJson + ","
                + "\"error\":\"" + escapeJson(error == null ? "" : error) + "\""
                + "}";
        URL url = new URL(getBackendUrl(context) + "/devices/remote/jobs/complete");
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        try {
            connection.setRequestMethod("POST");
            applyTimeouts(connection);
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            addDeviceTokenHeader(context, connection);
            OutputStream outputStream = connection.getOutputStream();
            outputStream.write(payload.getBytes("UTF-8"));
            outputStream.close();
            int responseCode = connection.getResponseCode();
            if (responseCode < 200 || responseCode >= 300) {
                throw new Exception("Remote job complete failed with HTTP " + responseCode);
            }
        } finally {
            connection.disconnect();
        }
    }

    public static JSONObject requestSecurityAction(Context context, String actionType) throws Exception {
        String payload = "{"
                + "\"deviceId\":\"" + escapeJson(getDeviceId(context)) + "\","
                + "\"actionType\":\"" + escapeJson(actionType) + "\""
                + "}";
        URL url = new URL(getBackendUrl(context) + "/devices/security/request");
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        try {
            connection.setRequestMethod("POST");
            applyTimeouts(connection);
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            addDeviceTokenHeader(context, connection);
            OutputStream outputStream = connection.getOutputStream();
            outputStream.write(payload.getBytes("UTF-8"));
            outputStream.close();
            int responseCode = connection.getResponseCode();
            String response = readResponse(connection);
            if (responseCode < 200 || responseCode >= 300) {
                throw new Exception("Security request failed: " + response);
            }
            return new JSONObject(response);
        } finally {
            connection.disconnect();
        }
    }

    public static JSONObject pollSecurityRequest(Context context, int requestId) throws Exception {
        String encodedDeviceId = URLEncoder.encode(getDeviceId(context), "UTF-8");
        URL url = new URL(getBackendUrl(context) + "/devices/security/request.json?deviceId="
                + encodedDeviceId + "&requestId=" + requestId);
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        try {
            connection.setRequestMethod("GET");
            applyTimeouts(connection);
            addDeviceTokenHeader(context, connection);
            int responseCode = connection.getResponseCode();
            String response = readResponse(connection);
            if (responseCode < 200 || responseCode >= 300) {
                throw new Exception("Security poll failed: " + response);
            }
            return new JSONObject(response);
        } finally {
            connection.disconnect();
        }
    }

    public static JSONObject verifySecurityOtp(Context context, int requestId, String otp) throws Exception {
        String payload = "{"
                + "\"deviceId\":\"" + escapeJson(getDeviceId(context)) + "\","
                + "\"requestId\":" + requestId + ","
                + "\"otp\":\"" + escapeJson(otp) + "\""
                + "}";
        URL url = new URL(getBackendUrl(context) + "/devices/security/verify");
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        try {
            connection.setRequestMethod("POST");
            applyTimeouts(connection);
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            addDeviceTokenHeader(context, connection);
            OutputStream outputStream = connection.getOutputStream();
            outputStream.write(payload.getBytes("UTF-8"));
            outputStream.close();
            int responseCode = connection.getResponseCode();
            String response = readResponse(connection);
            if (responseCode < 200 || responseCode >= 300) {
                throw new Exception("Security verify failed: " + response);
            }
            return new JSONObject(response);
        } finally {
            connection.disconnect();
        }
    }

    public static JSONObject fetchSecurityState(Context context) throws Exception {
        String encodedDeviceId = URLEncoder.encode(getDeviceId(context), "UTF-8");
        URL url = new URL(getBackendUrl(context) + "/devices/security/state.json?deviceId=" + encodedDeviceId);
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        try {
            connection.setRequestMethod("GET");
            applyTimeouts(connection);
            addDeviceTokenHeader(context, connection);
            int responseCode = connection.getResponseCode();
            String response = readResponse(connection);
            if (responseCode < 200 || responseCode >= 300) {
                throw new Exception("Security state failed: " + response);
            }
            return new JSONObject(response);
        } finally {
            connection.disconnect();
        }
    }

    public static String escapeJson(String value) {
        if (value == null) {
            return "";
        }
        return value.replace("\\", "\\\\").replace("\"", "\\\"");
    }
}
