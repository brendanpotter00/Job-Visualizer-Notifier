"""Host-pin evidence, against the REAL child subprocess and a REAL Chromium.

A. clean board harvests, and its third-party CDN sub-resource still loads
B. careers page 302s off-host  -> navigation pinned, private NEVER reached
C. recipe fetch 302s off-host  -> fetch pinned,      private NEVER reached
D. the child runs on the minimal allowlisted env (no secrets inherited)
"""
import http.server
import json
import os
import socketserver
import subprocess
import sys
import threading

ROOT = "/Users/bpotter/developer/personal/Job-Visualizer-Notifier/.claude/worktrees/2"
BACKEND = f"{ROOT}/src/backend"
sys.path.insert(0, BACKEND)
sys.path.insert(0, ROOT)

HITS = []


class Board(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    def log_message(self, *a): pass
    def do_GET(self):
        HITS.append(("BOARD", self.path))
        if self.path == "/careers-redirecting":
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{PRIVATE_PORT}/internal/secret")
            self.end_headers()
        elif self.path.startswith("/api/jobs-redirecting"):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{PRIVATE_PORT}/internal/api")
            self.end_headers()
        elif self.path.startswith("/api/jobs"):
            payload = json.dumps({"data": {"jobs": [{"id": str(i)} for i in range(3)]}})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload.encode())
        else:
            html = f'<html><body><img src="http://127.0.0.1:{CDN_PORT}/logo.png"></body></html>'.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)


class Private(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    def log_message(self, *a): pass
    def do_GET(self):
        HITS.append(("PRIVATE-REACHED", self.path))
        body = b'{"internal":"token"}'
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Cdn(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    def log_message(self, *a): pass
    def do_GET(self):
        HITS.append(("CDN-REACHED", self.path))
        self.send_response(200)
        self.send_header("Content-Length", "1")
        self.end_headers()
        self.wfile.write(b"x")


class T(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(h):
    s = T(("127.0.0.1", 0), h)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s.server_address[1]


PRIVATE_PORT = serve(Private)
CDN_PORT = serve(Cdn)
BOARD_PORT = serve(Board)

from api.services.browser_fetch import runner  # noqa: E402


def child(plan):
    env = runner._child_env()
    env["PYTHONPATH"] = os.pathsep.join([BACKEND, ROOT])
    return subprocess.run(
        [sys.executable, "-m", "api.services.browser_fetch._browser_fetch_main"],
        input=json.dumps(plan), cwd=BACKEND, env=env,
        capture_output=True, text=True, timeout=120,
    )


base = {"method": "GET", "headers": {}, "body": {}, "pagination": None,
        "records_path": "data.jobs", "allowed_hosts": ["localhost"]}
results = {}

print("== A. clean board (3rd-party CDN sub-resource must still load) ==")
HITS.clear()
p = child({**base, "origin_url": f"http://localhost:{BOARD_PORT}/careers",
           "url": f"http://localhost:{BOARD_PORT}/api/jobs"})
rep = runner._parse_report(p.stdout) if p.returncode == 0 else None
print("  rc =", p.returncode, "| report =", {k: v for k, v in (rep or {}).items() if k != "pages"})
if rep:
    print("  page status/body =", rep["pages"][0]["status"], rep["pages"][0]["text"][:44])
results["A_harvested"] = bool(rep) and rep["pages"][0]["status"] == 200
results["A_cdn_loaded"] = any(h[0] == "CDN-REACHED" for h in HITS)
results["A_private"] = any(h[0] == "PRIVATE-REACHED" for h in HITS)
print("  CDN loaded:", results["A_cdn_loaded"], "| private reached:", results["A_private"])

print("\n== B. careers page 302s to a NON-allowed host ==")
HITS.clear()
p = child({**base, "origin_url": f"http://localhost:{BOARD_PORT}/careers-redirecting",
           "url": f"http://localhost:{BOARD_PORT}/api/jobs"})
print("  rc =", p.returncode)
print("  pin stderr:", [l for l in p.stderr.splitlines() if "host-pin" in l][:2])
results["B_failed_run"] = p.returncode != 0
results["B_private"] = any(h[0] == "PRIVATE-REACHED" for h in HITS)
print("  private reached:", results["B_private"])

print("\n== C. recipe FETCH 302s to a NON-allowed host ==")
HITS.clear()
p = child({**base, "origin_url": f"http://localhost:{BOARD_PORT}/careers",
           "url": f"http://localhost:{BOARD_PORT}/api/jobs-redirecting"})
print("  rc =", p.returncode)
results["C_failed_run"] = p.returncode != 0
results["C_private"] = any(h[0] == "PRIVATE-REACHED" for h in HITS)
print("  private reached:", results["C_private"])

print("\n== D. child env is an allowlist (no secrets) ==")
keys = sorted(runner._child_env())
print("  child env keys:", keys)
results["D_no_secrets"] = not any(
    k in keys for k in ("DATABASE_URL", "ANTHROPIC_API_KEY", "BROWSERBASE_API_KEY", "INTERNAL_API_KEY"))

want = {"A_harvested": True, "A_cdn_loaded": True, "A_private": False,
        "B_failed_run": True, "B_private": False,
        "C_failed_run": True, "C_private": False,
        "D_no_secrets": True}
print("\n=== VERDICT ===")
bad = {k: (results[k], want[k]) for k in want if results[k] != want[k]}
for k in want:
    print(f"  {'OK  ' if results[k] == want[k] else 'FAIL'} {k}: got={results[k]} want={want[k]}")
print("ALL PASS" if not bad else f"FAILURES: {bad}")
sys.exit(0 if not bad else 1)
