#!/usr/bin/env python3
"""Minimal GitHub webhook listener: pull + restart backend on push to main."""

import hashlib
import hmac
import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def env(name, default=""):
    return os.environ.get(name, default).strip()


SECRET = env("WEBHOOK_SECRET")
PORT = int(env("WEBHOOK_PORT", "9001") or "9001")
BRANCH = env("WEBHOOK_BRANCH", "main")
APP_DIR = env("APP_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
DEPLOY_SCRIPT = os.path.join(APP_DIR, "deploy", "deploy.sh")


def verify_signature(body, signature_header):
    if not SECRET:
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
    received = signature_header.split("=", 1)[1]
    return hmac.compare_digest(expected, received)


def should_deploy(payload):
    if payload.get("zen") is not None:
        return False
    ref = str(payload.get("ref") or "")
    return ref == f"refs/heads/{BRANCH}"


def run_deploy():
    env = os.environ.copy()
    env["APP_DIR"] = APP_DIR
    env["DEPLOY_BRANCH"] = BRANCH
    log_path = os.environ.get("DEPLOY_LOG", "/var/log/device-safety-deploy.log")
    with open(log_path, "a", encoding="utf-8") as log_f:
        log_f.write(f"\n[{__import__('datetime').datetime.now().isoformat()}] webhook triggered deploy\n")
        subprocess.Popen(
            ["/bin/bash", DEPLOY_SCRIPT],
            cwd=APP_DIR,
            env=env,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


class WebhookHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stdout.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self):
        if self.path in {"/", "/health"}:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path != "/webhook":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length)
        event = self.headers.get("X-GitHub-Event", "")
        signature = self.headers.get("X-Hub-Signature-256", "")

        if not verify_signature(body, signature):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"invalid signature")
            return

        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"invalid json")
            return

        if event == "ping":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"pong")
            return

        if event == "push" and should_deploy(payload):
            run_deploy()
            self.send_response(202)
            self.end_headers()
            self.wfile.write(b"deploy queued")
            return

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ignored")


def main():
    if not SECRET:
        print("Set WEBHOOK_SECRET in deploy/webhook.env", file=sys.stderr)
        sys.exit(1)
    if not os.path.isfile(DEPLOY_SCRIPT):
        print(f"Missing deploy script: {DEPLOY_SCRIPT}", file=sys.stderr)
        sys.exit(1)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), WebhookHandler)
    print(f"Webhook listening on http://0.0.0.0:{PORT}/webhook (branch={BRANCH})")
    server.serve_forever()


if __name__ == "__main__":
    main()
