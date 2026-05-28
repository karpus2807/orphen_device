ADMIN_ROUTES = {
    "/",
    "/devices",
    "/devices/detail",
    "/devices/detail.json",
    "/devices/location",
    "/devices/location.json",
    "/devices/location/history.json",
    "/devices/location/geocode.json",
    "/devices/call-log",
    "/devices/call-log.json",
    "/devices/sms-history",
    "/devices/sms-history.json",
    "/devices/contacts",
    "/devices/contacts.json",
    "/devices/audio",
    "/devices/audio/session.json",
    "/devices/audio/chunks.json",
    "/devices/audio/live.wav",
    "/devices/audio/recording",
    "/devices/audio/control",
    "/devices/files",
    "/devices/files/listing.json",
    "/devices/files/download.json",
    "/devices/files/content",
    "/devices/files/control",
    "/devices/files/upload",
    "/devices/files/action.json",
    "/devices/shell",
    "/devices/shell/history.json",
    "/devices/shell/exec",
    "/devices/communications",
    "/devices/timeline.json",
    "/commands",
    "/commands.json",
    "/enrollment-qr",
    "/server-config",
    "/server-config.json",
    "/policy-config",
    "/email-config",
    "/email-config/test",
    "/app-release-center",
    "/app-release-center/build",
    "/app-release-center/build-push",
    "/app-release-center/build-installer",
    "/app-release-center/push",
    "/app-release-center/push-release",
    "/app-release-center/delete-releases",
    "/app-release-center/register",
    "/devices/geofence",
    "/devices/wifi-profile",
    "/devices/wifi-suggestions.json",
    "/enrollment-tokens",
    "/devices/send-command",
    "/devices/bulk-action",
    "/devices/set-group",
    "/devices/security",
    "/devices/security/requests.json",
    "/devices/security/approve",
    "/devices/security/reject",
    "/devices/notifications",
    "/devices/notifications.json",
    "/devices/usage/refresh",
}

POST_HANDLERS = {
    "/login": "login",
    "/forgot-password": "request_password_reset",
    "/reset-password": "reset_password",
    "/devices/checkin": "device_checkin",
    "/devices/deregister": "deregister_device",
    "/devices/delete": "delete_device",
    "/devices/commands/complete": "complete_device_command_handler",
    "/devices/telemetry": "device_telemetry",
    "/devices/security/request": "device_security_request",
    "/devices/security/verify": "device_security_verify",
    "/devices/security/approve": "admin_security_approve",
    "/devices/security/reject": "admin_security_reject",
    "/devices/audio/chunk": "device_audio_chunk",
    "/devices/bulk-action": "admin_bulk_action",
    "/devices/usage/refresh": "admin_refresh_usage",
    "/devices/set-group": "admin_set_device_group",
    "/devices/send-command": "admin_send_command",
    "/devices/audio/control": "admin_audio_control",
    "/devices/files/control": "admin_files_control",
    "/devices/files/upload": "admin_files_upload",
    "/devices/shell/exec": "admin_shell_exec",
    "/devices/remote/jobs/complete": "device_remote_job_complete",
    "/server-config": "save_server_config",
    "/policy-config": "save_policy_config",
    "/email-config": "save_email_config",
    "/email-config/test": "send_test_email_config",
    "/devices/geofence": "save_device_geofence_config",
    "/devices/wifi-profile": "save_device_wifi_profile_config",
    "/app-release-center/build": "app_release_build",
    "/app-release-center/build-push": "app_release_build_push",
    "/app-release-center/build-installer": "app_release_build_installer",
    "/app-release-center/push": "app_release_push",
    "/app-release-center/register": "app_release_register",
    "/app-release-center/push-release": "app_release_push_release",
    "/app-release-center/delete-releases": "app_release_delete_releases",
    "/enrollment-tokens": "admin_register_device",
}


def dispatch_post(handler, path):
    if path == "/devices/register":
        handler.send_json({"error": "registration_from_app_disabled"}, status=403)
        return True
    if path == "/geofence-config":
        handler.send_redirect("/")
        return True
    if path == "/ota-config":
        handler.send_redirect("/app-release-center")
        return True
    if path == "/wifi-profile-config":
        handler.send_redirect("/")
        return True
    method_name = POST_HANDLERS.get(path)
    if not method_name:
        return False
    getattr(handler, method_name)()
    return True
