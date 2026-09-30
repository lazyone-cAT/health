"""Browser smoke test: login via API, then drive headless Chrome through the SPA."""
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

import requests
from websockets.sync.client import connect

BASE = "http://localhost:5000"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# 1. login via API to obtain session cookie
s = requests.Session()
r = s.post(f"{BASE}/api/login", json={"username": "district1", "password": "district123"})
assert r.status_code == 200, r.text
cookies = {c.name: c.value for c in s.cookies}
print("session cookie acquired:", list(cookies))

profile = tempfile.mkdtemp(prefix="smokechrome-")
proc = subprocess.Popen(
    [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
     "--remote-debugging-port=9333", f"--user-data-dir={profile}", "about:blank"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)

ws_url = None
for _ in range(40):
    try:
        req = urllib.request.Request("http://127.0.0.1:9333/json/new?about:blank", method="PUT")
        with urllib.request.urlopen(req, timeout=2) as v:
            ws_url = json.load(v)["webSocketDebuggerUrl"]
        break
    except Exception:
        try:
            with urllib.request.urlopen("http://127.0.0.1:9333/json/list", timeout=1) as v:
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

def run_page(path):
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
        time.sleep(3)
        res = wait_for(send("Runtime.evaluate",
                            {"expression": "document.body.innerText", "returnByValue": True}), 10)
        text = ""
        if res and res.get("result", {}).get("result", {}).get("value"):
            text = res["result"]["result"]["value"]
        return text


for path in ("/", "/inventory", "/medicines", "/alerts", "/redistribution", "/federated", "/audit", "/upload"):
    text = run_page(path)
    head = " / ".join([ln.strip() for ln in text.splitlines() if ln.strip()][:4])
    print(f"{path:18} -> {head[:150]}")

proc.kill()
print("\nJS exceptions:", len(errors))
for p, e in errors[:6]:
    print(" ", p, e[:200])
