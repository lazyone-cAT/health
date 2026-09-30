"""Browser smoke for P5: live Federated screen (district officer) + phc_manager gating."""
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

profile = tempfile.mkdtemp(prefix="smokechrome-")
proc = subprocess.Popen(
    [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
     "--remote-debugging-port=9335", f"--user-data-dir={profile}", "about:blank"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)

ws_url = None
for _ in range(40):
    try:
        req = urllib.request.Request("http://127.0.0.1:9335/json/new?about:blank", method="PUT")
        with urllib.request.urlopen(req, timeout=2) as v:
            ws_url = json.load(v)["webSocketDebuggerUrl"]
        break
    except Exception:
        try:
            with urllib.request.urlopen("http://127.0.0.1:9335/json/list", timeout=1) as v:
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


def make_cookies(user, password):
    s = requests.Session()
    r = s.post(f"{BASE}/api/login", json={"username": user, "password": password})
    assert r.status_code == 200, r.text
    return {c.name: c.value for c in s.cookies}


def run_page(path, cookies, expr="document.body.innerText", wait=6):
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


failed = []

officer = make_cookies("district1", "district123")

# --- Federated live screen (district officer -> only own state's node) ------
text = run_page("/federated", officer, wait=7)
hay = text.lower()
print("/federated  (%d chars): %s" % (
    len(text), " / ".join([ln.strip() for ln in text.splitlines() if ln.strip()][:3])[:140]))
needles = ["live ·", "fedavg", "node-od", "node_sync", "local_fit",
           "raw rows shared: no", "resync nodes", "state nodes",
           "holdout", "fedavg model r", "round log", "privacy model"]
for n in needles:
    if n not in hay:
        failed.append(("/federated", n))
# state scoping: other states' nodes must not appear
for n in ["node-cg", "node-ts", "chhattisgarh", "telangana"]:
    if n in hay:
        failed.append(("/federated", f"unexpected {n}"))
if failed and failed[-1][0] == "/federated":
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    print("   lines:", lines[:60])

# --- nav shows Federated for an officer ------------------------------------
links = run_page("/", officer, expr="Array.from(document.querySelectorAll('a')).map(a=>a.textContent).join('|')", wait=5)
if "federated" not in str(links).lower():
    failed.append(("/", "nav Federated link for officer"))

# --- phc_manager: no nav entry, direct URL blocked -------------------------
phc = make_cookies("khariar1", "phc123")
phc_links = run_page("/", phc, expr="Array.from(document.querySelectorAll('a')).map(a=>a.textContent).join('|')", wait=5)
if "federated" in str(phc_links).lower():
    failed.append(("/ (phc_manager)", "nav should NOT show Federated"))
blocked = run_page("/federated", phc, wait=5).lower()
print("/federated as phc_manager:", blocked[:120].replace("\n", " "))
if "forbidden" not in blocked and "403" not in blocked:
    failed.append(("/federated (phc_manager)", "expected Forbidden"))

proc.kill()
print("\nJS exceptions:", len(errors))
for p, e in errors[:6]:
    print("  ", p, e[:200])
if failed:
    print("MISSING:", failed)
    sys.exit(1)
print("ALL BROWSER P5 CHECKS PASSED")
