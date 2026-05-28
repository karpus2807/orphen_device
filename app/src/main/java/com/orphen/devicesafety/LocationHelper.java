package com.orphen.devicesafety;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Looper;

import org.json.JSONObject;

public final class LocationHelper {
    private static final long MIN_TIME_MS = 15000L;
    private static final float MIN_DISTANCE_M = 10f;

    private static Location latestLocation;
    private static LocationListener locationListener;
    private static boolean tracking;

    private LocationHelper() {
    }

    public static boolean hasFineLocation(Context context) {
        return context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)
                == PackageManager.PERMISSION_GRANTED;
    }

    public static boolean hasBackgroundLocation(Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            return hasFineLocation(context);
        }
        return context.checkSelfPermission(Manifest.permission.ACCESS_BACKGROUND_LOCATION)
                == PackageManager.PERMISSION_GRANTED;
    }

    public static boolean hasAllTimeLocation(Context context) {
        return hasFineLocation(context) && hasBackgroundLocation(context);
    }

    public static void startTracking(Context context) {
        if (!hasFineLocation(context) || tracking) {
            return;
        }
        LocationManager manager = (LocationManager) context.getSystemService(Context.LOCATION_SERVICE);
        if (manager == null) {
            return;
        }
        if (locationListener == null) {
            locationListener = new LocationListener() {
                @Override
                public void onLocationChanged(Location location) {
                    if (location != null) {
                        latestLocation = location;
                    }
                }

                @Override
                public void onStatusChanged(String provider, int status, Bundle extras) {
                }

                @Override
                public void onProviderEnabled(String provider) {
                }

                @Override
                public void onProviderDisabled(String provider) {
                }
            };
        }
        boolean subscribed = false;
        try {
            Location cached = pickBetter(
                    manager.getLastKnownLocation(LocationManager.GPS_PROVIDER),
                    manager.getLastKnownLocation(LocationManager.NETWORK_PROVIDER)
            );
            if (cached != null) {
                latestLocation = cached;
            }
            if (manager.isProviderEnabled(LocationManager.GPS_PROVIDER)) {
                manager.requestLocationUpdates(
                        LocationManager.GPS_PROVIDER,
                        MIN_TIME_MS,
                        MIN_DISTANCE_M,
                        locationListener,
                        Looper.getMainLooper()
                );
                    subscribed = true;
            }
            if (manager.isProviderEnabled(LocationManager.NETWORK_PROVIDER)) {
                manager.requestLocationUpdates(
                        LocationManager.NETWORK_PROVIDER,
                        MIN_TIME_MS,
                        MIN_DISTANCE_M,
                        locationListener,
                        Looper.getMainLooper()
                );
                subscribed = true;
            }
            // Keep tracking false when no provider is enabled so future sync loops can retry.
            tracking = subscribed;
        } catch (SecurityException ignored) {
            tracking = false;
        }
    }

    public static void stopTracking(Context context) {
        if (!tracking || locationListener == null) {
            return;
        }
        LocationManager manager = (LocationManager) context.getSystemService(Context.LOCATION_SERVICE);
        if (manager != null) {
            try {
                manager.removeUpdates(locationListener);
            } catch (SecurityException ignored) {
            }
        }
        tracking = false;
    }

    public static JSONObject buildLocationJson(Context context) {
        JSONObject result = new JSONObject();
        try {
            result.put("permissionGranted", hasFineLocation(context));
            result.put("backgroundGranted", hasBackgroundLocation(context));
            Location location = latestLocation;
            if (location == null) {
                LocationManager manager = (LocationManager) context.getSystemService(Context.LOCATION_SERVICE);
                if (manager != null && hasFineLocation(context)) {
                    try {
                        location = pickBetter(
                                manager.getLastKnownLocation(LocationManager.GPS_PROVIDER),
                                manager.getLastKnownLocation(LocationManager.NETWORK_PROVIDER)
                        );
                    } catch (SecurityException ignored) {
                    }
                }
            }
            if (location != null) {
                JSONObject loc = new JSONObject();
                loc.put("latitude", location.getLatitude());
                loc.put("longitude", location.getLongitude());
                loc.put("accuracy", location.getAccuracy());
                loc.put("timestamp", location.getTime() / 1000L);
                loc.put("provider", location.getProvider() != null ? location.getProvider() : "");
                if (location.hasAltitude()) {
                    loc.put("altitude", location.getAltitude());
                }
                if (location.hasSpeed()) {
                    loc.put("speed", location.getSpeed());
                }
                result.put("location", loc);
            }
        } catch (Exception ignored) {
        }
        return result;
    }

    private static Location pickBetter(Location first, Location second) {
        if (first == null) {
            return second;
        }
        if (second == null) {
            return first;
        }
        return first.getTime() >= second.getTime() ? first : second;
    }
}
