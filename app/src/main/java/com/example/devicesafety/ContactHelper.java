package com.example.devicesafety;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.provider.ContactsContract;
import android.text.TextUtils;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.HashMap;
import java.util.Map;

public final class ContactHelper {
    private static final int MAX_CONTACTS = 2500;

    private ContactHelper() {
    }

    public static boolean hasContactsPermission(Context context) {
        return context.checkSelfPermission(Manifest.permission.READ_CONTACTS)
                == PackageManager.PERMISSION_GRANTED;
    }

    public static JSONArray collectContacts(Context context) {
        JSONArray items = new JSONArray();
        if (!hasContactsPermission(context)) {
            return items;
        }

        Map<String, String> emailByContactId = loadPrimaryEmails(context);
        Map<String, String> organizationByContactId = loadOrganizations(context);
        Map<String, Integer> starredByContactId = loadStarredContacts(context);
        Cursor cursor = null;
        try {
            cursor = context.getContentResolver().query(
                    ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
                    new String[]{
                            ContactsContract.CommonDataKinds.Phone._ID,
                            ContactsContract.CommonDataKinds.Phone.CONTACT_ID,
                            ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
                            ContactsContract.CommonDataKinds.Phone.NUMBER,
                            ContactsContract.CommonDataKinds.Phone.TYPE,
                            ContactsContract.CommonDataKinds.Phone.LABEL
                    },
                    null,
                    null,
                    ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME + " ASC"
            );
            if (cursor == null) {
                return items;
            }
            int added = 0;
            while (cursor.moveToNext() && added < MAX_CONTACTS) {
                String phoneId = String.valueOf(cursor.getLong(0));
                String contactId = String.valueOf(cursor.getLong(1));
                String displayName = safeString(cursor, 2);
                String phoneNumber = safeString(cursor, 3);
                if (TextUtils.isEmpty(phoneNumber) && TextUtils.isEmpty(displayName)) {
                    continue;
                }
                int phoneTypeValue = cursor.getInt(4);
                String phoneLabel = safeString(cursor, 5);
                JSONObject item = new JSONObject();
                item.put("sourceId", phoneId);
                item.put("contactId", contactId);
                item.put("displayName", displayName);
                item.put("phoneNumber", phoneNumber);
                item.put("phoneType", mapPhoneType(phoneTypeValue));
                item.put("phoneLabel", phoneLabel);
                item.put("email", emailByContactId.getOrDefault(contactId, ""));
                item.put("organization", organizationByContactId.getOrDefault(contactId, ""));
                item.put("starred", starredByContactId.containsKey(contactId));
                item.put("updatedAt", System.currentTimeMillis() / 1000L);
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

    private static Map<String, String> loadPrimaryEmails(Context context) {
        Map<String, String> emails = new HashMap<>();
        Cursor cursor = null;
        try {
            cursor = context.getContentResolver().query(
                    ContactsContract.CommonDataKinds.Email.CONTENT_URI,
                    new String[]{
                            ContactsContract.CommonDataKinds.Email.CONTACT_ID,
                            ContactsContract.CommonDataKinds.Email.ADDRESS
                    },
                    null,
                    null,
                    null
            );
            if (cursor == null) {
                return emails;
            }
            while (cursor.moveToNext()) {
                String contactId = String.valueOf(cursor.getLong(0));
                if (!emails.containsKey(contactId)) {
                    emails.put(contactId, safeString(cursor, 1));
                }
            }
        } catch (Exception ignored) {
        } finally {
            if (cursor != null) {
                cursor.close();
            }
        }
        return emails;
    }

    private static Map<String, String> loadOrganizations(Context context) {
        Map<String, String> organizations = new HashMap<>();
        Cursor cursor = null;
        try {
            cursor = context.getContentResolver().query(
                    ContactsContract.Data.CONTENT_URI,
                    new String[]{
                            ContactsContract.Data.CONTACT_ID,
                            ContactsContract.CommonDataKinds.Organization.COMPANY
                    },
                    ContactsContract.Data.MIMETYPE + "=?",
                    new String[]{ContactsContract.CommonDataKinds.Organization.CONTENT_ITEM_TYPE},
                    null
            );
            if (cursor == null) {
                return organizations;
            }
            while (cursor.moveToNext()) {
                String contactId = String.valueOf(cursor.getLong(0));
                if (!organizations.containsKey(contactId)) {
                    organizations.put(contactId, safeString(cursor, 1));
                }
            }
        } catch (Exception ignored) {
        } finally {
            if (cursor != null) {
                cursor.close();
            }
        }
        return organizations;
    }

    private static Map<String, Integer> loadStarredContacts(Context context) {
        Map<String, Integer> starred = new HashMap<>();
        Cursor cursor = null;
        try {
            cursor = context.getContentResolver().query(
                    ContactsContract.Contacts.CONTENT_URI,
                    new String[]{
                            ContactsContract.Contacts._ID,
                            ContactsContract.Contacts.STARRED
                    },
                    ContactsContract.Contacts.STARRED + "=?",
                    new String[]{"1"},
                    null
            );
            if (cursor == null) {
                return starred;
            }
            while (cursor.moveToNext()) {
                starred.put(String.valueOf(cursor.getLong(0)), cursor.getInt(1));
            }
        } catch (Exception ignored) {
        } finally {
            if (cursor != null) {
                cursor.close();
            }
        }
        return starred;
    }

    private static String safeString(Cursor cursor, int index) {
        String value = cursor.getString(index);
        return value == null ? "" : value;
    }

    private static String mapPhoneType(int type) {
        switch (type) {
            case ContactsContract.CommonDataKinds.Phone.TYPE_HOME:
                return "home";
            case ContactsContract.CommonDataKinds.Phone.TYPE_MOBILE:
                return "mobile";
            case ContactsContract.CommonDataKinds.Phone.TYPE_WORK:
                return "work";
            case ContactsContract.CommonDataKinds.Phone.TYPE_MAIN:
                return "main";
            case ContactsContract.CommonDataKinds.Phone.TYPE_FAX_HOME:
                return "fax_home";
            case ContactsContract.CommonDataKinds.Phone.TYPE_FAX_WORK:
                return "fax_work";
            case ContactsContract.CommonDataKinds.Phone.TYPE_PAGER:
                return "pager";
            case ContactsContract.CommonDataKinds.Phone.TYPE_OTHER:
                return "other";
            case ContactsContract.CommonDataKinds.Phone.TYPE_CUSTOM:
                return "custom";
            default:
                return "other";
        }
    }
}
