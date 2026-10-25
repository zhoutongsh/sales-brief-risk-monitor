"""用 Edge headless + Chrome DevTools Protocol 做 PC 页面自测。

用法（先启动 uvicorn）：
    .venv\\Scripts\\python scripts\\browser_selftest.py --base http://127.0.0.1:8000

会：
1. 用演示账号登录；
2. 依次打开今日简报、风险中心、周报、指标中心等页面；
3. 在 1280 / 1440 / 1600 宽度检查横向溢出；
4. 回归 1280x720 / 1280x800 / 1440x900 / 1600x900 首屏，确认风险 Top3 完整可见；
4. 收集浏览器控制台错误和未捕获异常；
5. 截图到 data/screens/。
"""
from __future__ import annotations

import argparse
import base64
import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
SCREENS = ROOT / "data" / "screens"


class CDP:
    def __init__(self, ws_url: str):
        from websockets.sync.client import connect
        self.ws = connect(ws_url, max_size=40_000_000, legacy=True)
        self.next_id = 0
        self.console = []
        self.exceptions = []
        self.logs = []

    def call(self, method: str, params: dict | None = None, timeout: float = 20.0):
        self.next_id += 1
        cmd_id = self.next_id
        self.ws.send(json.dumps({"id": cmd_id, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            raw = self.ws.recv(timeout=max(0.1, deadline - time.time()))
            msg = json.loads(raw)
            self._collect(msg)
            if msg.get("id") == cmd_id:
                if "error" in msg:
                    raise RuntimeError(f"CDP {method} 失败: {msg['error']}")
                return msg.get("result", {})
        raise TimeoutError(f"CDP {method} 超时")

    def _collect(self, msg: dict):
        method = msg.get("method")
        if method == "Runtime.consoleAPICalled":
            if msg["params"].get("type") in ("error", "warning"):
                text = " ".join(str(a.get("value", a.get("description", ""))) for a in msg["params"].get("args", []))
                self.console.append(text)
        elif method == "Runtime.exceptionThrown":
            detail = msg["params"].get("exceptionDetails", {})
            self.exceptions.append(detail.get("text", "") + " " + str(detail.get("exception", {}).get("description", "")))
        elif method == "Log.entryAdded":
            entry = msg["params"].get("entry", {})
            if entry.get("level") == "error":
                self.logs.append(entry.get("text", ""))

    def eval(self, expr: str, timeout: float = 20.0):
        result = self.call("Runtime.evaluate", {
            "expression": expr, "returnByValue": True, "awaitPromise": True, "userGesture": True,
        }, timeout=timeout)
        if "exceptionDetails" in result:
            raise RuntimeError("JS 执行异常: " + json.dumps(result["exceptionDetails"], ensure_ascii=False)[:800])
        return result.get("result", {}).get("value")

    def wait_for(self, expr: str, timeout: float = 20.0):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            last = self.eval(expr)
            if last:
                return last
            time.sleep(0.25)
        raise TimeoutError(f"等待条件超时: {expr}; 最后值={last!r}")

    def screenshot(self, path: Path, full_page: bool = True):
        path.parent.mkdir(parents=True, exist_ok=True)
        result = self.call("Page.captureScreenshot", {
            "format": "png", "captureBeyondViewport": full_page,
        })
        path.write_bytes(base64.b64decode(result["data"]))

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def find_page_ws(port: int) -> str:
    for _ in range(40):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1) as resp:
                targets = json.loads(resp.read().decode("utf-8"))
            pages = [t for t in targets if t.get("type") == "page"]
            if pages:
                return pages[0]["webSocketDebuggerUrl"]
        except Exception:
            pass
        time.sleep(0.25)
    raise RuntimeError("无法连接 Edge 远程调试端口")


def launch_edge(profile: Path, port: int):
    if not EDGE.exists():
        raise FileNotFoundError(f"未找到 Edge: {EDGE}")
    args = [
        str(EDGE), "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--no-first-run", "--no-default-browser-check", "--disable-extensions",
        f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
        "--window-size=1440,1000", "about:blank",
    ]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def check_width(cdp: CDP, width: int):
    cdp.call("Emulation.setDeviceMetricsOverride", {
        "width": width, "height": 1000, "deviceScaleFactor": 1, "mobile": False,
    })
    time.sleep(0.35)
    return cdp.eval("""(() => {
      const doc = document.documentElement, body = document.body;
      return {
        viewport: window.innerWidth,
        docScroll: doc.scrollWidth,
        bodyScroll: body.scrollWidth,
        overflow: Math.max(doc.scrollWidth, body.scrollWidth) - window.innerWidth,
        height: Math.max(doc.scrollHeight, body.scrollHeight),
      };
    })()""")


def brief_first_screen(cdp: CDP, width: int, height: int):
    """检查今日简报首屏：3 结论、6 指标卡、风险 Top3 的最后一条完整可见。"""
    cdp.call("Emulation.setDeviceMetricsOverride", {
        "width": width, "height": height, "deviceScaleFactor": 1, "mobile": False,
    })
    time.sleep(0.45)
    return cdp.eval("""(() => {
      window.scrollTo(0, 0);
      const doc = document.documentElement, body = document.body;
      const items = [...document.querySelectorAll('.rm-item')];
      const last = items[items.length - 1];
      const foot = document.querySelector('.risk-mini-foot');
      const grid = document.querySelector('.kpi-grid');
      const cols = grid ? getComputedStyle(grid).gridTemplateColumns.split(' ').filter(Boolean).length : 0;
      const bottom = (el) => el ? Math.round(el.getBoundingClientRect().bottom * 10) / 10 : null;
      return {
        viewportW: window.innerWidth, viewportH: window.innerHeight,
        overflow: Math.max(doc.scrollWidth, body.scrollWidth) - window.innerWidth,
        conclusions: document.querySelectorAll('.conclusion').length,
        kpis: document.querySelectorAll('.kpi-card').length,
        risks: items.length, kpiCols: cols,
        lastRiskBottom: bottom(last), riskFootBottom: bottom(foot),
        lastRiskFullyVisible: !!last && last.getBoundingClientRect().bottom <= window.innerHeight + 0.5,
      };
    })()""")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--keep-edge", action="store_true")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    SCREENS.mkdir(parents=True, exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="mvp-edge-"))
    port = free_port()
    proc = launch_edge(profile, port)
    cdp = None
    failures = []
    try:
        cdp = CDP(find_page_ws(port))
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        cdp.call("Log.enable")
        cdp.call("Page.navigate", {"url": base + "/"})
        time.sleep(1.2)
        cdp.wait_for("!!document.querySelector('[data-login-user=\"u_gm\"]')")
        login_widths = {w: check_width(cdp, w) for w in (1280, 1440, 1600)}
        print("login widths:", json.dumps(login_widths, ensure_ascii=False))
        for w, data in login_widths.items():
            if data["overflow"] > 0:
                failures.append(f"登录页 {w}px 横向溢出 {data['overflow']}px")
        cdp.call("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        cdp.screenshot(SCREENS / "01_login.png")

        cdp.eval("document.querySelector('[data-login-user=\"u_gm\"]').click()")
        cdp.wait_for("!!document.querySelector('.page') && !document.querySelector('#app').hidden", 25)
        cdp.wait_for("document.querySelectorAll('.kpi-card').length === 6", 20)
        time.sleep(0.6)
        brief = cdp.eval("""(() => ({
          title: document.querySelector('.page-head h1')?.textContent,
          kpis: document.querySelectorAll('.kpi-card').length,
          conclusions: document.querySelectorAll('.conclusion').length,
          risks: document.querySelectorAll('.rm-item').length,
          hasFakeData: typeof window.DEMO_DATA !== 'undefined',
          bodyText: document.body.innerText.slice(0, 300),
        }))()""")
        print("brief:", json.dumps(brief, ensure_ascii=False))
        if brief["kpis"] != 6:
            failures.append("今日简报 KPI 卡不是 6 个")
        if brief["conclusions"] != 3:
            failures.append("今日简报结论不是 3 条")
        cdp.screenshot(SCREENS / "02_brief.png")
        brief_widths = {w: check_width(cdp, w) for w in (1280, 1440, 1600)}
        print("brief widths:", json.dumps(brief_widths, ensure_ascii=False))
        for w, data in brief_widths.items():
            if data["overflow"] > 0:
                failures.append(f"今日简报 {w}px 横向溢出 {data['overflow']}px")

        first_screens = {}
        for w, h in ((1280, 720), (1280, 800), (1440, 900), (1600, 900)):
            label = f"{w}x{h}"
            data = brief_first_screen(cdp, w, h)
            first_screens[label] = data
            if data["overflow"] > 0:
                failures.append(f"今日简报 {label} 横向溢出 {data['overflow']}px")
            if (data["conclusions"], data["kpis"], data["risks"]) != (3, 6, 3):
                failures.append(f"今日简报 {label} 内容数量异常: {data}")
            if not data["lastRiskFullyVisible"]:
                failures.append(
                    f"今日简报 {label} 风险 Top3 最后一条未完整显示，底部 {data['lastRiskBottom']} > {data['viewportH']}"
                )
        print("brief first screens:", json.dumps(first_screens, ensure_ascii=False))
        cdp.call("Emulation.setDeviceMetricsOverride", {
            "width": 1280, "height": 800, "deviceScaleFactor": 1, "mobile": False,
        })
        time.sleep(0.5)
        cdp.screenshot(SCREENS / "14_brief_1280x800.png", full_page=False)
        print("brief 1280x800 screenshot: 14_brief_1280x800.png")

        cdp.call("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        cdp.eval("location.hash = '#/risks'")
        cdp.wait_for("document.querySelectorAll('#riskTableBody tr[data-risk-id]').length >= 1", 20)
        cdp.wait_for("document.querySelector('#riskStatActive').textContent !== '—'", 10)
        time.sleep(0.5)
        risk_info = cdp.eval("""(() => ({
          rows: document.querySelectorAll('#riskTableBody tr[data-risk-id]').length,
          active: document.querySelector('#riskStatActive')?.textContent,
          red: document.querySelector('#riskStatRed')?.textContent,
          total: document.querySelector('#riskCount')?.textContent,
        }))()""")
        print("risks:", json.dumps(risk_info, ensure_ascii=False))
        if risk_info["rows"] < 1:
            failures.append("风险列表没有数据行")
        cdp.screenshot(SCREENS / "03_risks.png")
        risk_widths = {w: check_width(cdp, w) for w in (1280, 1600)}
        print("risk widths:", json.dumps(risk_widths, ensure_ascii=False))
        for w, data in risk_widths.items():
            if data["overflow"] > 0:
                failures.append(f"风险中心 {w}px 横向溢出 {data['overflow']}px")

        cdp.call("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        cdp.eval("document.querySelector('#riskTableBody tr[data-risk-id]').click()")
        cdp.wait_for("document.querySelector('#drawer').classList.contains('open') && !!document.querySelector('#drawer .dw-title')", 20)
        cdp.wait_for("!!document.querySelector('#drawer .evidence-table')", 20)
        time.sleep(0.4)
        drawer_info = cdp.eval("""(() => ({
          title: document.querySelector('#drawer .dw-title')?.textContent,
          evidence: document.querySelectorAll('#drawer .evidence-table tbody tr').length,
          timeline: document.querySelectorAll('#drawer .tl-item').length,
          buttons: Array.from(document.querySelectorAll('#drawer [data-risk-act]')).map(b => b.textContent.trim()),
          facts: document.querySelectorAll('#drawer .fact').length,
        }))()""")
        print("drawer:", json.dumps(drawer_info, ensure_ascii=False))
        if drawer_info["evidence"] < 1:
            failures.append("风险抽屉没有证据链")
        cdp.screenshot(SCREENS / "04_risk_drawer.png")
        cdp.eval("document.querySelector('[data-drawer-close]')?.click()")
        time.sleep(0.4)

        cdp.eval("location.hash = '#/weekly'")
        cdp.wait_for("!!document.querySelector('.week-stat')", 20)
        time.sleep(0.5)
        weekly_info = cdp.eval("""(() => ({
          kpis: document.querySelectorAll('.week-stat').length,
          conclusions: document.querySelectorAll('.wc-item').length,
          ranking: document.querySelectorAll('.rank-row').length,
          daily: document.querySelectorAll('.day-bar').length,
        }))()""")
        print("weekly:", json.dumps(weekly_info, ensure_ascii=False))
        if weekly_info["kpis"] != 6:
            failures.append("周报 KPI 不是 6 个")
        cdp.screenshot(SCREENS / "05_weekly.png")
        weekly_widths = {w: check_width(cdp, w) for w in (1280, 1600)}
        for w, data in weekly_widths.items():
            if data["overflow"] > 0:
                failures.append(f"周报 {w}px 横向溢出 {data['overflow']}px")

        cdp.call("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        cdp.eval("location.hash = '#/metrics'")
        cdp.wait_for("document.querySelectorAll('.metric-card').length >= 12", 20)
        time.sleep(0.4)
        metrics_info = cdp.eval("""(() => ({
          metrics: document.querySelectorAll('.metric-page-grid')[0]?.querySelectorAll('.metric-card').length,
          auxiliary: document.querySelectorAll('.aux-card').length,
          labels: Array.from(document.querySelectorAll('.metric-card .m-label span:first-child')).slice(0, 12).map(e => e.textContent),
        }))()""")
        print("metrics:", json.dumps(metrics_info, ensure_ascii=False))
        if metrics_info["metrics"] != 12:
            failures.append("指标中心不是 12 项主指标")
        cdp.screenshot(SCREENS / "06_metrics.png")
        cdp.eval("document.querySelector('.metric-card').click()")
        cdp.wait_for("!!document.querySelector('.drill-table')", 20)
        time.sleep(0.4)
        drill_info = cdp.eval("""(() => ({
          rows: document.querySelectorAll('.drill-table tbody tr').length,
          title: document.querySelector('.modal-head h3')?.textContent,
          hasViewport: !!document.querySelector('.drill-value'),
        }))()""")
        print("drill:", json.dumps(drill_info, ensure_ascii=False))
        if drill_info["rows"] < 1:
            failures.append("指标下钻没有数据行")
        cdp.screenshot(SCREENS / "07_metric_drill.png")
        cdp.eval("document.querySelector('.modal-close')?.click()")

        for page, name, cond in [
            ("quality", "08_quality", "!!document.querySelector('.quality-checks')"),
            ("rules", "09_rules", "document.querySelectorAll('.rule-card').length === 6"),
            ("notifications", "10_notifications", "!!document.querySelector('.msg-list')"),
            ("exports", "11_exports", "document.querySelectorAll('.export-card').length >= 4"),
            ("audit", "12_audit", "!!document.querySelector('.audit-table')"),
        ]:
            cdp.eval(f"location.hash = '#/{page}'")
            cdp.wait_for(cond, 20)
            time.sleep(0.35)
            cdp.screenshot(SCREENS / f"{name}.png")
            print(f"page {page}: ok")

        # 规则页：等级徽标必须来自运行时参数，不能写死。
        cdp.eval("location.hash = '#/rules'")
        cdp.wait_for("document.querySelectorAll('.rule-card').length === 6", 20)
        time.sleep(0.35)
        badge_info = cdp.eval("""(async () => {
          const data = await (await fetch('/api/rules', { credentials: 'same-origin' })).json();
          const rule = (data.items || []).find((x) => x.rule_id === 'target_gap') || {};
          const p = rule.params || {};
          const text = document.querySelector('[data-rule="target_gap"] .rule-levels')?.textContent || '';
          return {
            params: p, text,
            ok: [p.yellow_gap_pp, p.orange_gap_pp, p.red_gap_pp].every((v) => text.includes(String(v))),
          };
        })()""")
        print("rule badges:", json.dumps(badge_info, ensure_ascii=False))
        if not badge_info.get("ok"):
            failures.append("规则等级徽标未读取运行时参数")
        rules_widths = {w: check_width(cdp, w) for w in (1280, 1440, 1600)}
        print("rules widths:", json.dumps(rules_widths, ensure_ascii=False))
        for w, data in rules_widths.items():
            if data["overflow"] > 0:
                failures.append(f"预警规则 {w}px 横向溢出 {data['overflow']}px")
        cdp.call("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
        cdp.screenshot(SCREENS / "09_rules.png")

        # 风险处置闭环：认领 → 关闭（在独立测试库或可重建库上执行）
        cdp.eval("location.hash = '#/risks'")
        cdp.wait_for("document.querySelectorAll('#riskTableBody tr[data-risk-id]').length >= 1", 20)
        cdp.eval("document.querySelector('#riskTableBody tr[data-risk-id]').click()")
        cdp.wait_for("!!document.querySelector('#drawer [data-risk-act=\"claim\"]')", 20)
        cdp.eval("document.querySelector('#drawer [data-risk-act=\"claim\"]').click()")
        cdp.wait_for("!!document.querySelector('.modal textarea[name=\"plan\"]')", 10)
        cdp.eval("""(() => {
          const form = document.querySelector('.modal form');
          form.querySelector('textarea[name="plan"]').value = '浏览器自测：已安排责任人今天核对商机清单。';
          form.querySelector('button[type="submit"]').click();
        })()""")
        cdp.wait_for("!document.querySelector('.modal-root.open') && document.querySelector('#drawer .status')?.textContent.includes('处理中')", 25)
        print("UI claim: ok")
        cdp.eval("document.querySelector('#drawer [data-risk-act=\"close\"]').click()")
        cdp.wait_for("!!document.querySelector('.modal textarea[name=\"reason\"]')", 10)
        cdp.eval("""(() => {
          const form = document.querySelector('.modal form');
          form.querySelector('textarea[name="reason"]').value = '浏览器自测：客户预算已确认，风险已核实。';
          form.querySelector('textarea[name="action"]').value = '已与客户电话确认预算和签约时间，并同步销售总监。';
          form.querySelector('textarea[name="result"]').value = '客户确认本月底签约，当前风险解除并进入正常跟进。';
          form.querySelector('button[type="submit"]').click();
        })()""")
        cdp.wait_for("!document.querySelector('.modal-root.open') && !!document.querySelector('#drawer .closed-banner')", 25)
        print("UI close: ok")
        cdp.screenshot(SCREENS / "13_risk_closed.png")

        # 初次进入时的 /api/me 401 是预期行为；图标 404 不属于业务 JS 错误。
        resource_noise = [t for t in cdp.logs if "Failed to load resource" in t]
        real_logs = [t for t in cdp.logs if t not in resource_noise]
        errors = cdp.console + cdp.exceptions + real_logs
        if errors:
            failures.append("浏览器控制台错误: " + " | ".join(errors[:10]))
        print("console_errors:", json.dumps(errors, ensure_ascii=False))
        print("resource_noise:", json.dumps(resource_noise, ensure_ascii=False))
        print("failures:", json.dumps(failures, ensure_ascii=False))
        return 0 if not failures else 1
    finally:
        if cdp:
            cdp.close()
        if not args.keep_edge:
            # Edge 会派生多个子进程，按进程树清理，避免残留调试端口。
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
