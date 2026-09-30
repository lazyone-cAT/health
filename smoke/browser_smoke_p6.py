"""Browser smoke for P6: 30s auto-refresh line + stale banner wiring."""
import json
import subprocess
import sys
import tempfile
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests
from websockets.sync.client import connect

BASE = "http://localhost:5000"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

s = requests.Session()
r = s.post(f"{BASE}/api/login", json={"username": "district1", "password": "district123"})
assert r.status_code == 200, r.text
cookies = {c.name: c.value for c in s.cookies}

profile = tempfile.mkdtemp(prefix="smokechrome-")
proc = subprocess.Popen(
    [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
     "--remote-debugging-port=9336", f"--user-data-dir={profile}", "about:blank"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)

ws_url = None
for _ in range(40):
    try:
        req = urllib.request.Request("http://127.0.0.1:9336/json/new?about:blank", method="PUT")
        with urllib.request.urlopen(req, timeout=2) as v:
            ws_url = json.load(v)["webSocketDebuggerUrl"]
        break
    except Exception:
        try:
            with urllib.request.urlopen("http://127.0.0.1:9336/json/list", timeout=1) as v:
                targets = json.load(v)
            pages = [t for t in targets if t.get("type") == "page"]
            if pages:
                ws_url = pages[0]["webSocketDebuggerUrl"]
                break
        except Exception:
            pass
        time.sleep(0.5)
if not ws_url:
    proc.kill()
    sys.exit("chrome debugging did not start")

errors = []


def run_page(path, expr="document.body.innerText", wait=6):
    with connect(ws_url, open_timeout=10) as ws:
        mid = 0

        def send(method, params=None):
            nonlocal mid
            mid += 1
            ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
            return mid

        def wait_for(msg_id, timeout=15):
            end = time.time() + timeout
            while time.time() < end:
                try:
                    msg = json.loads(ws.recv(timeout=end - time.time()))
                except Exception:
                    break
                if msg.get("method") in ("Runtime.exceptionThrown", "Log.entryAdded"):
                    errors.append((path, json.dumps(msg.get("params"))[:400]))
                if msg.get("id") == msg_id:
                    return msg
            return None

        wait_for(send("Runtime.enable"))
        wait_for(send("Page.enable"))
        wait_for(send("Network.enable"))
        for name, value in cookies.items():
            wait_for(send("Network.setCookie", {"name": name, "value": value, "url": BASE}))
        wait_for(send("Page.navigate", {"url": BASE + path}))
        time.sleep(wait)
        res = wait_for(send("Runtime.evaluate", {"expression": expr, "returnByValue": True}), 10)
        if res and res.get("result", {}).get("result", {}).get("value") is not None:
            return res["result"]["result"]["value"]
        return ""


FRESHNESS_EXPR = ("(function(){var el=document.querySelector('.freshness');"
                  "return el?el.innerText:(document.querySelector('.stale-banner')||{}).innerText||''})()")

failed = []

for path in ("/", "/alerts", "/beds"):
    text = run_page(path, wait=6)
    hay = text.lower()
    print(f"{path:9} ({len(text)} chars)")
    for n in ["auto-refresh 30s", "updated", "· server 20"]:
        if n not in hay:
            failed.append((path, n))
    fresh = run_page(path, expr=FRESHNESS_EXPR, wait=1)
    print("   freshness:", fresh.replace("\n", " ")[:100])
    if "auto-refresh" not in fresh.lower() and "stale" not in fresh.lower():
        failed.append((path, "freshness line element"))

# --- wait one full poll cycle and confirm the timestamp advanced -------------
run_page("/", wait=6)  # navigate back to Overview
first = run_page("/", expr=FRESHNESS_EXPR, wait=1)
print("before poll:", first.replace("\n", " ")[:100])
time.sleep(33)
second = ""
with connect(ws_url, open_timeout=10) as ws:
    mid = 0

    def send(method, params=None):
        global mid
        mid += 1
        ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        return mid

    end = time.time() + 10
    wait_id = send("Runtime.evaluate", {"expression": FRESHNESS_EXPR, "returnByValue": True})
    while time.time() < end:
        try:
            msg = json.loads(ws.recv(timeout=end - time.time()))
        except Exception:
            break
        if msg.get("method") in ("Runtime.exceptionThrown", "Log.entryAdded"):
            errors.append(("/", json.dumps(msg.get("params"))[:400]))
        if msg.get("id") == wait_id:
            second = msg["result"]["result"].get("value") or ""
            break
print("after  poll:", second.replace("\n", " ")[:100])
if first and second and first == second:
    failed.append(("/poll", "freshness line did not update after 33s"))

# --- stale banner: block /api/overview, wait for a failed poll --------------
with connect(ws_url, open_timeout=10) as ws:
    mid = 0

    def send(method, params=None):
        global mid
        mid += 1
        ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        return mid

    def eval_expr(expr, timeout=10):
        wid = send("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        end = time.time() + timeout
        while time.time() < end:
            try:
                msg = json.loads(ws.recv(timeout=end - time.time()))
            except Exception:
                break
            if msg.get("method") in ("Runtime.exceptionThrown", "Log.entryAdded"):
                errors.append(("/stale", json.dumps(msg.get("params"))[:400]))
            if msg.get("id") == wid:
                return msg.get("result", {}).get("result", {}).get("value") or ""
        return ""

    BANNER = ("(function(){var b=document.querySelector('.stale-banner');"
              "return b?b.innerText:''})()")

    send("Network.enable")
    send("Network.setBlockedURLs", {"urls": ["*api/overview*"]})
    banner = ""
    deadline = time.time() + 40
    while time.time() < deadline:
        time.sleep(5)
        banner = eval_expr(BANNER)
        if banner:
            break
    print("stale banner:", banner.replace("\n", " ")[:160])
    if not banner or "stale" not in banner.lower():
        failed.append(("/stale", "stale banner did not appear while API blocked"))
    if "last successful refresh" not in banner.lower():
        failed.append(("/stale", "banner should show last good update time"))

    # recover: unblock, next poll must clear the banner
    send("Network.setBlockedURLs", {"urls": []})
    deadline = time.time() + 40
    cleared = ""
    while time.time() < deadline:
        time.sleep(5)
        cleared = eval_expr(BANNER)
        if not cleared:
            break
    print("after unblock, banner:", repr(cleared)[:80])
    if cleared:
        failed.append(("/stale", "banner did not clear after API recovered"))

proc.kill()
print("\nJS exceptions:", len(errors))
for p, e in errors[:6]:
    print("  ", p, e[:200])
if failed:
    print("MISSING:", failed)
    sys.exit(1)
print("ALL BROWSER P6 CHECKS PASSED")
