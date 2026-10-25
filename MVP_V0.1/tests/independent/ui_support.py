"""Edge headless + Chrome DevTools Protocol helpers for PC UI smoke."""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

from websockets.sync.client import connect

EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_http(url: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.2)
    raise TimeoutError(url)


class CDP:
    def __init__(self, ws):
        self.ws = ws
        self._id = 0
        self.events: list[dict] = []

    def _recv(self, timeout: float):
        try:
            return json.loads(self.ws.recv(timeout=timeout))
        except TimeoutError:
            return None

    def command(self, method: str, params: dict | None = None, timeout: float = 10.0):
        self._id += 1
        current = self._id
        self.ws.send(json.dumps({"id": current, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            message = self._recv(max(0.01, deadline - time.time()))
            if message is None:
                break
            if message.get("id") == current:
                if "error" in message:
                    raise RuntimeError(message["error"])
                return message.get("result", {})
            self.events.append(message)
        raise TimeoutError(method)

    def drain(self, seconds: float = 0.3) -> None:
        deadline = time.time() + seconds
        while time.time() < deadline:
            message = self._recv(max(0.01, deadline - time.time()))
            if message is None:
                break
            self.events.append(message)

    def eval(self, expression: str, timeout: float = 10.0):
        result = self.command(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
            timeout,
        )
        return result.get("result", {}).get("value")

    def console_errors(self) -> list[dict]:
        errors = []
        for event in self.events:
            method = event.get("method")
            if method == "Runtime.exceptionThrown":
                errors.append(event)
            elif method == "Log.entryAdded":
                entry = event.get("params", {}).get("entry", {})
                if entry.get("level") == "error":
                    errors.append(event)
            elif method == "Runtime.consoleAPICalled":
                if event.get("params", {}).get("type") in {"error", "assert"}:
                    errors.append(event)
        return errors


class EdgeSession:
    def __init__(self, cdp: CDP, process: subprocess.Popen, profile: Path):
        self.cdp = cdp
        self.process = process
        self.profile = profile

    def close(self) -> None:
        try:
            self.process.terminate()
            self.process.wait(timeout=5)
        except Exception:
            try:
                self.process.kill()
            except Exception:
                pass
        shutil.rmtree(self.profile, ignore_errors=True)


def open_edge(profile: Path, width: int = 1440, height: int = 900) -> EdgeSession:
    if not EDGE.exists():
        raise FileNotFoundError(EDGE)
    shutil.rmtree(profile, ignore_errors=True)
    profile.mkdir(parents=True, exist_ok=True)
    port = free_port()
    process = subprocess.Popen(
        [
            str(EDGE), "--headless=new", f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
            "--disable-gpu", "--remote-allow-origins=*",
            f"--window-size={width},{height}", "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        targets = None
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1) as response:
                    targets = json.load(response)
                break
            except Exception:
                time.sleep(0.2)
        if not targets:
            raise TimeoutError("Edge CDP did not start")
        page = next(item for item in targets if item["type"] == "page")
        ws = connect(
            page["webSocketDebuggerUrl"],
            max_size=None,
            origin="http://localhost",
            legacy=True,
        )
        cdp = CDP(ws)
        cdp.command("Page.enable")
        cdp.command("Runtime.enable")
        cdp.command("Log.enable")
        cdp.command("Network.enable")
        cdp.command("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height, "deviceScaleFactor": 1, "mobile": False,
        })
        return EdgeSession(cdp, process, profile)
    except Exception:
        process.terminate()
        raise


def _wait_content(cdp: CDP, timeout: float = 8.0) -> str:
    text = ""
    deadline = time.time() + timeout
    while time.time() < deadline:
        text = cdp.eval("document.querySelector('#content')?.innerText || ''") or ""
        if text and "正在加载" not in text and "进入工作台" not in text:
            return text
        time.sleep(0.15)
        cdp.drain(0.1)
    return text


def _login(cdp: CDP, base: str, user_id: str = "u_gm") -> int:
    return cdp.eval(
        "fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},"
        "body:JSON.stringify({user_id:'%s'}),credentials:'same-origin'}).then(r=>r.status)" % user_id
    )


def smoke_probe(base: str, profile: Path) -> dict:
    session = open_edge(profile)
    cdp = session.cdp
    result: dict = {"pages": {}, "widths": {}, "errors": {}}
    try:
        cdp.command("Page.navigate", {"url": base + "/"})
        time.sleep(1.5)
        cdp.drain(0.5)
        result["login_cards"] = cdp.eval("document.querySelectorAll('#loginUsers .login-user').length")
        result["login_errors"] = len(cdp.console_errors())
        cdp.events.clear()
        result["login_status"] = _login(cdp, base)
        cdp.command("Page.navigate", {"url": base + "/#/brief"})
        cdp.command("Page.reload", {"ignoreCache": True})
        time.sleep(2.0)
        cdp.drain(0.5)

        for page in ["brief", "risks", "weekly", "rules", "exports"]:
            cdp.events.clear()
            cdp.command("Page.navigate", {"url": f"{base}/#/{page}"})
            time.sleep(0.6)
            text = _wait_content(cdp)
            cdp.drain(0.2)
            result["pages"][page] = {
                "length": len(text),
                "first": text[:120].replace("\n", " | "),
                "errors": len(cdp.console_errors()),
                "hash": cdp.eval("location.hash"),
            }
            result["errors"][page] = cdp.console_errors()[:5]

        # Export button must open a second-confirmation dialog before download.
        cdp.events.clear()
        cdp.command("Page.navigate", {"url": f"{base}/#/exports"})
        time.sleep(0.8)
        _wait_content(cdp)
        cdp.eval("document.querySelector('#exportBriefBtn')?.click()")
        time.sleep(0.5)
        result["export_dialog"] = {
            "open": bool(cdp.eval("document.querySelector('#modalRoot')?.classList.contains('open')")),
            "text": (cdp.eval("document.querySelector('#modalRoot')?.innerText || ''") or "")[:160],
        }
        cdp.eval("document.querySelector('#modalRoot [data-close-modal]')?.click()")

        cdp.command("Page.navigate", {"url": f"{base}/#/brief"})
        time.sleep(1.0)
        for width in [1280, 1440, 1600]:
            cdp.command("Emulation.setDeviceMetricsOverride", {
                "width": width, "height": 900, "deviceScaleFactor": 1, "mobile": False,
            })
            time.sleep(0.4)
            cdp.drain(0.2)
            result["widths"][str(width)] = {
                "scroll_width": cdp.eval("document.documentElement.scrollWidth"),
                "client_width": cdp.eval("document.documentElement.clientWidth"),
                "inner_width": cdp.eval("window.innerWidth"),
                "horizontal": bool(cdp.eval(
                    "document.documentElement.scrollWidth > window.innerWidth"
                )),
            }
        return result
    finally:
        session.close()


def rules_threshold_probe(base: str, profile: Path) -> str:
    session = open_edge(profile)
    cdp = session.cdp
    try:
        cdp.command("Page.navigate", {"url": base + "/"})
        _wait_content(cdp, timeout=10.0)
        login_status = _login(cdp, base)
        if login_status != 200:
            raise AssertionError(f"login failed: {login_status}")
        me_status = cdp.eval("fetch('/api/me',{credentials:'same-origin'}).then(r=>r.status)")
        if me_status != 200:
            raise AssertionError(f"session cookie not usable: {me_status}")
        status = cdp.eval(
            "fetch('/api/rules/target_gap',{method:'PATCH',headers:{'Content-Type':'application/json'},"
            "body:JSON.stringify({params:{yellow_gap_pp:2}}),credentials:'same-origin'}).then(r=>r.status)"
        )
        if status != 200:
            raise AssertionError(f"rule patch failed: {status}")
        # A query change forces a real document load; navigating only by hash would
        # stay on the login screen because the probe logs in through fetch().
        cdp.command("Page.navigate", {"url": base + "/?probe=rules#/rules"})
        deadline = time.time() + 15
        text = ""
        while time.time() < deadline:
            _wait_content(cdp, timeout=2.0)
            text = cdp.eval(
                "(()=>{const c=[...document.querySelectorAll('.rule-card')]"
                ".find(x=>x.innerText.includes('目标缺口'));"
                "return c?c.innerText.split(String.fromCharCode(10)).join(' | '):''})()"
            ) or ""
            if "缺口 ≥" in text:
                return text
            time.sleep(0.3)
            cdp.drain(0.1)
        raise AssertionError(
            "rules card did not render: hash=%r content=%r errors=%r"
            % (
                cdp.eval("location.hash"),
                _wait_content(cdp, timeout=1.0)[:160],
                cdp.console_errors()[:3],
            )
        )
    finally:
        session.close()
