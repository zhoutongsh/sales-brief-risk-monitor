/* 经营简报 MVP 前端。所有业务数据都来自本地 FastAPI；没有 data.js 假数据回退。 */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const loginScreen = $("#loginScreen");
  const appEl = $("#app");
  const content = $("#content");
  const drawer = $("#drawer");
  const drawerMask = $("#drawerMask");
  const modalRoot = $("#modalRoot");
  const toastWrap = $("#toastWrap");
  const roleMenu = $("#roleMenu");
  const notifyPop = $("#notifyPop");

  const state = {
    me: null,
    demoUsers: [],
    routePage: "brief",
    routeSeq: 0,
    riskFilters: { level: "all", status: "all", type: "all", sort: "priority", q: "", page: 1 },
    weeklyType: "this",
    currentBrief: null,
    drawerRiskId: null,
    drawerReq: 0,
    riskListReq: 0,
    notifyPage: 1,
    auditAction: "",
    loginBusy: false,
    shellBusy: false,
  };

  class ApiError extends Error {
    constructor(message, status = 0, data = null) {
      super(message);
      this.status = status;
      this.data = data;
    }
  }

  // ---------------------------------------------------------------- 基础工具

  function esc(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function icon(name, cls = "ic") {
    return `<svg class="${cls}" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
  }

  function num(value, digits = 1) {
    if (value === null || value === undefined || value === "") return "—";
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    return n.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  function intNum(value) {
    if (value === null || value === undefined || value === "") return "—";
    const n = Number(value);
    return Number.isFinite(n) ? n.toLocaleString("zh-CN") : "—";
  }

  function pct(value, digits = 1) {
    if (value === null || value === undefined || value === "") return "—";
    return `${num(value, digits)}%`;
  }

  function signedPct(value, digits = 1) {
    if (value === null || value === undefined || value === "") return "—";
    return `${value > 0 ? "+" : ""}${num(value, digits)}%`;
  }

  function shortTime(value) {
    if (!value) return "—";
    return String(value).replace("T", " ").slice(0, 16);
  }

  function dateCN(value) {
    if (!value) return "—";
    const parts = String(value).slice(0, 10).split("-");
    if (parts.length !== 3) return esc(value);
    return `${Number(parts[1])} 月 ${Number(parts[2])} 日`;
  }

  function levelTag(level, label) {
    return `<span class="tag ${esc(level)}">${esc(label || level)}</span>`;
  }

  function statusBadge(status, label) {
    const cls = { pending: "wait", processing: "doing", closed: "done", false_positive: "done", long_term: "done" }[status] || "done";
    return `<span class="status ${cls}">${esc(label || status)}</span>`;
  }

  function statusClass(status) {
    if (status === "pending") return "wait";
    if (status === "processing") return "doing";
    return "done";
  }

  function ownerOf(risk) {
    return (risk && risk.owner) || {};
  }

  function pageError(message, title = "数据读取失败") {
    return `<div class="page-error" role="alert"><b>${esc(title)}</b>${esc(message)}<br>
      <button class="btn sm" data-retry>${icon("refresh")}重新加载</button></div>`;
  }

  function emptyState(title, message) {
    return `<div class="empty-state"><b>${esc(title)}</b><p>${esc(message || "")}</p></div>`;
  }

  function sectionHead(title, sub, action = "") {
    return `<div class="card-h"><div><div class="t">${esc(title)}</div>${sub ? `<div class="s">${esc(sub)}</div>` : ""}</div>${action}</div>`;
  }

  function toast(message, type = "ok") {
    const el = document.createElement("div");
    el.className = `toast${type === "err" ? " err" : ""}`;
    el.innerHTML = `<span class="tic">${icon(type === "err" ? "risk" : "check")}</span><span>${esc(message)}</span>`;
    toastWrap.appendChild(el);
    setTimeout(() => {
      el.classList.add("out");
      setTimeout(() => el.remove(), 240);
    }, type === "err" ? 5200 : 3200);
  }

  function syncScrollLock() {
    const locked = modalRoot.classList.contains("open") || drawer.classList.contains("open");
    document.body.classList.toggle("no-scroll", locked);
  }

  function contentLoading(label = "正在加载业务数据…") {
    content.innerHTML = `<div class="loading-block">${esc(label)}</div>`;
  }

  // ---------------------------------------------------------------- API

  async function api(path, options = {}) {
    let response;
    try {
      response = await fetch(path, {
        credentials: "same-origin",
        headers: options.body ? { "Content-Type": "application/json" } : {},
        ...options,
      });
    } catch (err) {
      throw new ApiError("无法连接本地服务。请确认 uvicorn 已启动，并刷新页面。", 0);
    }
    const contentType = response.headers.get("content-type") || "";
    let data = null;
    if (contentType.includes("application/json")) {
      try { data = await response.json(); } catch (_) { data = null; }
    } else {
      const text = await response.text();
      data = text ? { detail: text.slice(0, 300) } : null;
    }
    if (!response.ok) {
      const message = (data && data.detail) || `请求失败（HTTP ${response.status}）`;
      if (response.status === 401 && state.me) showLogin("登录已过期，请重新选择演示账号。");
      throw new ApiError(message, response.status, data);
    }
    return data;
  }

  async function downloadFile(url, fallbackName = "export.xlsx") {
    let response;
    try {
      response = await fetch(url, { credentials: "same-origin" });
    } catch (_) {
      throw new ApiError("无法连接本地服务，下载失败。", 0);
    }
    if (!response.ok) {
      let detail = `下载失败（HTTP ${response.status}）`;
      try {
        const data = await response.json();
        detail = data.detail || detail;
      } catch (_) { /* 保留默认错误 */ }
      if (response.status === 401) showLogin("登录已过期，请重新登录。");
      throw new ApiError(detail, response.status);
    }
    const blob = await response.blob();
    const disposition = response.headers.get("content-disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match ? match[1] : fallbackName;
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = objectUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 2000);
    return filename;
  }

  // ---------------------------------------------------------------- 登录与会话

  function showLogin(message = "") {
    state.me = null;
    loginScreen.hidden = false;
    appEl.hidden = true;
    closeDrawer(false);
    closeModal();
    const err = $("#loginError");
    if (err) {
      err.textContent = message || "";
      err.classList.toggle("show", Boolean(message));
    }
  }

  async function loadDemoUsers() {
    const box = $("#loginUsers");
    try {
      const data = await api("/api/demo/users");
      state.demoUsers = data.items || [];
      renderLoginUsers();
      renderRoleOptions();
      return data;
    } catch (err) {
      state.demoUsers = [];
      box.innerHTML = pageError(err.message, "演示账号读取失败");
      return null;
    }
  }

  function renderLoginUsers() {
    const box = $("#loginUsers");
    if (!state.demoUsers.length) {
      box.innerHTML = emptyState("没有可用的演示账号", "请确认数据库已初始化。");
      return;
    }
    box.innerHTML = state.demoUsers.map((u) => `
      <button class="login-user" data-login-user="${esc(u.user_id)}" type="button">
        <span class="login-avatar">${esc((u.name || "?").slice(0, 1))}</span>
        <span><b>${esc(u.name)}</b><small>${esc(u.title)} · ${esc(u.scope_label)}</small></span>
        <span class="lu-go">进入工作台 →</span>
      </button>`).join("");
    $$("[data-login-user]", box).forEach((btn) => {
      btn.addEventListener("click", () => handleLogin(btn.dataset.loginUser, btn));
    });
  }

  async function handleLogin(userId, button) {
    if (state.loginBusy) return;
    state.loginBusy = true;
    const err = $("#loginError");
    err.classList.remove("show");
    if (button) button.disabled = true;
    try {
      const result = await api("/api/auth/login", { method: "POST", body: JSON.stringify({ user_id: userId }) });
      await enterApp(result.user);
    } catch (e) {
      err.textContent = e.message;
      err.classList.add("show");
    } finally {
      state.loginBusy = false;
      if (button) button.disabled = false;
    }
  }

  async function checkSession() {
    try {
      const me = await api("/api/me");
      await enterApp(me);
    } catch (err) {
      if (err.status !== 401) {
        showLogin(err.message);
      }
    }
  }

  async function enterApp(me) {
    state.me = me;
    loginScreen.hidden = true;
    appEl.hidden = false;
    state.riskFilters = { level: "all", status: "all", type: "all", sort: "priority", q: "", page: 1 };
    applyShell();
    if (!location.hash) {
      history.replaceState(null, "", "#/brief");
    }
    refreshShellData();
    await route(true);
  }

  function applyShell() {
    const me = state.me;
    if (!me) return;
    $("#roleAvatar").textContent = (me.name || "?").slice(0, 1);
    $("#roleName").textContent = me.name;
    $("#roleTitle").textContent = `${me.title} · ${me.scope ? me.scope.label : ""}`;
    $("#navAudit").hidden = me.role !== "gm";
    renderRoleOptions();
  }

  function renderRoleOptions() {
    const box = $("#roleOptions");
    if (!box) return;
    if (!state.demoUsers.length) {
      box.innerHTML = `<div class="pop-empty">演示角色读取失败</div>`;
      return;
    }
    box.innerHTML = state.demoUsers.map((u) => `
      <button class="role-option ${state.me && state.me.user_id === u.user_id ? "active" : ""}" data-switch-role="${esc(u.user_id)}" type="button">
        <span class="ro-avatar">${esc((u.name || "?").slice(0, 1))}</span>
        <span><b>${esc(u.name)}</b><small>${esc(u.title)} · ${esc(u.scope_label)}</small></span>
        <i class="ro-check">${icon("check")}</i>
      </button>`).join("");
    $$("[data-switch-role]", box).forEach((btn) => {
      btn.addEventListener("click", () => switchRole(btn.dataset.switchRole));
    });
  }

  async function switchRole(userId) {
    if (!state.me || userId === state.me.user_id) {
      roleMenu.classList.remove("open");
      return;
    }
    roleMenu.classList.remove("open");
    try {
      const result = await api("/api/auth/login", { method: "POST", body: JSON.stringify({ user_id: userId }) });
      state.me = result.user;
      state.currentBrief = null;
      state.riskFilters = { level: "all", status: "all", type: "all", sort: "priority", q: "", page: 1 };
      closeDrawer(false);
      applyShell();
      toast(`已切换为 ${result.user.name}，数据范围：${result.user.scope.label}`);
      refreshShellData();
      await route(true);
    } catch (err) {
      toast(err.message, "err");
    }
  }

  async function logout() {
    roleMenu.classList.remove("open");
    try { await api("/api/auth/logout", { method: "POST" }); } catch (_) { /* 即使接口失败也回到登录页 */ }
    showLogin("已退出演示登录。");
    await loadDemoUsers();
  }

  async function refreshShellData() {
    if (!state.me || state.shellBusy) return;
    state.shellBusy = true;
    try {
      const results = await Promise.allSettled([
        api("/api/notifications?page_size=3"),
        api("/api/risks?page_size=1"),
        api("/api/quality"),
      ]);
      if (results[0].status === "fulfilled") updateNotificationShell(results[0].value);
      if (results[1].status === "fulfilled") {
        const stats = results[1].value.stats || {};
        const badge = $("#navRiskBadge");
        badge.textContent = intNum(stats.active || 0);
        badge.hidden = !stats.active;
      }
      if (results[2].status === "fulfilled") updateBatchShell(results[2].value);
      if (results.some((r) => r.status === "rejected" && r.reason && r.reason.status === 401)) {
        showLogin("登录已过期，请重新登录。");
      }
    } finally {
      state.shellBusy = false;
    }
  }

  function updateNotificationShell(data) {
    const unread = data.unread || 0;
    const badge = $("#navMsgBadge");
    badge.textContent = intNum(unread);
    badge.hidden = !unread;
    $("#bellDot").hidden = !unread;
    $("#notifyUnread").textContent = unread ? `${unread} 条未读` : "全部已读";
    const items = data.items || [];
    const box = $("#notifyPreview");
    if (!items.length) {
      box.innerHTML = `<div class="pop-empty">暂无消息</div>`;
      return;
    }
    box.innerHTML = items.slice(0, 3).map((n) => `
      <button class="notify-item" data-notify-id="${Number(n.id)}" type="button">
        <span class="ni-ico ${n.kind === "risk" || n.kind === "escalation" ? "red" : (n.kind === "brief" ? "green" : "blue")}">${icon(n.kind === "risk" ? "risk" : "bell")}</span>
        <span><b>${esc(n.title)}</b><small>${shortTime(n.created_at)}${n.is_read ? "" : " · 未读"}</small></span>
      </button>`).join("");
    $$("[data-notify-id]", box).forEach((btn) => {
      btn.addEventListener("click", () => {
        const item = items.find((x) => String(x.id) === btn.dataset.notifyId);
        notifyPop.classList.remove("open");
        if (item) openNotification(item);
      });
    });
  }

  function updateBatchShell(report) {
    const batch = (report && report.batch) || {};
    const finished = batch.finished_at || (report && report.generated_at);
    const timeText = finished ? shortTime(finished) : "—";
    const failed = !!report && report.status === "fail";
    const failureText = (report && report.failure && report.failure.message)
      || (report && report.summary && report.summary.message)
      || "最近批次未通过数据质量检查，已停止发布。";
    $("#batchStatus").textContent = failed ? "批次失败" : (report && report.status === "pass" ? "演示批次已完成" : "批次有提示");
    $("#batchTime").textContent = finished ? `10-24 · ${timeText.slice(11)}` : "尚未跑批";
    $("#batchCard").classList.toggle("failed", failed);
    const pill = $("#dataPill");
    pill.querySelector("span").textContent = failed ? "批次失败" : (finished ? `10-24 批次 · ${timeText.slice(11)}` : "批次时间未知");
    pill.title = failed ? `最近批次失败：${failureText}` : (finished ? `批次完成时间 ${timeText}；业务日期 2026-10-24` : "未找到批次完成时间");
    const alert = $("#batchAlert");
    if (failed) {
      alert.hidden = false;
      alert.innerHTML = `<span class="ba-ico">${icon("risk")}</span><div class="ba-copy"><b>最近批次失败</b><span>${esc(failureText)}</span></div><button class="link" data-page="quality">查看数据质量 ${icon("arrow")}</button>`;
    } else {
      alert.hidden = true;
      alert.innerHTML = "";
    }
  }

  // ---------------------------------------------------------------- 路由

  const pageTitles = {
    brief: ["今日简报", "经营结论与风险入口"],
    risks: ["风险中心", "六类风险的证据、SLA 与闭环"],
    weekly: ["周报复盘", "本周对比上周的经营复盘"],
    metrics: ["指标中心", "12 项指标与下钻"],
    quality: ["数据质量", "源文件完整性与影响范围"],
    rules: ["预警规则", "阈值与启停"],
    notifications: ["消息中心", "风险、升级与简报通知"],
    exports: ["导出中心", "带演示水印的下载与打印"],
    audit: ["审计日志", "登录、查看、导出与处置记录"],
  };

  function parseRoute() {
    const raw = location.hash.replace(/^#\/?/, "");
    const parts = raw.split("/").filter(Boolean);
    let page = parts[0] || "brief";
    let riskId = null;
    if (page === "risks" && parts[1]) riskId = parts[1];
    if (!pageTitles[page]) page = "brief";
    return { page, riskId };
  }

  function navigate(page, riskId = null) {
    const target = riskId ? `#/${page}/${encodeURIComponent(riskId)}` : `#/${page}`;
    if (location.hash === target) {
      route(true);
    } else {
      location.hash = target;
    }
  }

  async function route(force = false) {
    if (!state.me) return;
    const { page, riskId } = parseRoute();
    state.routePage = page;
    const seq = ++state.routeSeq;
    closeDrawer(false);
    closeModal();
    roleMenu.classList.remove("open");
    notifyPop.classList.remove("open");
    $$(".nav-item").forEach((el) => el.classList.toggle("active", el.dataset.page === page));
    const meta = pageTitles[page] || pageTitles.brief;
    $("#crumbPage").textContent = meta[0];
    document.title = `${meta[0]}｜经营简报 MVP`;
    contentLoading(`正在加载${meta[0]}…`);
    if (!force) window.scrollTo({ top: 0, behavior: "instant" });

    if (page === "brief") await renderBrief(seq);
    else if (page === "risks") await renderRisks(seq, riskId);
    else if (page === "weekly") await renderWeekly(seq);
    else if (page === "metrics") await renderMetrics(seq);
    else if (page === "quality") await renderQuality(seq);
    else if (page === "rules") await renderRules(seq);
    else if (page === "notifications") await renderNotifications(seq);
    else if (page === "exports") await renderExports(seq);
    else if (page === "audit") await renderAudit(seq);
  }

  function bindRetry(root) {
    $$("[data-retry]", root).forEach((btn) => btn.addEventListener("click", () => route(true)));
  }

  // ---------------------------------------------------------------- 今日简报

  function kpiIcon(key) {
    const map = {
      contract_amount: "money", target_completion_rate: "target", new_leads: "leads",
      marketing_roi: "trend", opportunity_coverage: "chart", collection_completion_rate: "money",
    };
    return map[key] || "chart";
  }

  function deltaText(card) {
    if (card.delta === null || card.delta === undefined) return "环比 —";
    const label = card.key === "target_completion_rate" ? "较时间进度" : "环比";
    const unit = card.delta_unit || "%";
    const value = card.delta > 0 ? `+${num(card.delta, 1)}` : num(card.delta, 1);
    return `${label} ${value}${unit}`;
  }

  function kpiCard(card) {
    const tone = card.tone === "good" ? "good" : (card.tone === "bad" ? "bad" : "flat");
    return `
      <button class="kpi-card card" data-metric="${esc(card.key)}" title="点击查看指标下钻；口径：${esc(card.meaning || "")}">
        <span class="kpi-label">${icon(kpiIcon(card.key))}${esc(card.label)}</span>
        <span class="kpi-value">${esc(card.display)}</span>
        <span class="kpi-meta">
          <span class="kpi-sub" title="${esc(card.sub || "")}">${esc(card.sub || " ")}</span>
          <span class="delta ${tone}">${esc(deltaText(card))}</span>
        </span>
      </button>`;
  }

  function conclusionCard(c) {
    const toneClass = c.tone === "bad" ? "red" : (c.tone === "warning" ? "orange" : (c.tone === "good" ? "green" : ""));
    const action = c.risk_id ? `data-risk-link="${esc(c.risk_id)}"` : (c.metric_key ? `data-metric="${esc(c.metric_key)}"` : "");
    return `
      <article class="conclusion ${toneClass}" ${action} tabindex="0" role="button" data-tone="${esc(c.tone || "neutral")}"
        aria-label="结论 ${c.index}：${esc(c.title)}。点击查看相关数据">
        <span class="c-num">0${Number(c.index)}</span>
        <div class="c-body">
          <div class="c-top"><span class="c-tag">${esc(c.tag || c.title)}</span></div>
          <p><b>${esc(c.title)}：</b>${esc(c.text)}</p>
        </div>
        <span class="c-arrow">${icon("arrow")}</span>
      </article>`;
  }

  function riskMiniItem(risk) {
    const owner = ownerOf(risk);
    const sla = risk.sla || {};
    const urgent = sla.claim_state === "overdue" || sla.close_state === "overdue";
    const slaText = risk.status === "pending" ? sla.claim_text : (risk.status === "processing" ? sla.close_text : "已结束");
    return `
      <div class="rm-item" data-risk-link="${esc(risk.id)}" tabindex="0" role="button" aria-label="打开风险 ${esc(risk.id)}">
        <span class="rm-bar ${esc(risk.level)}"></span>
        <span class="rm-main">
          <span class="rm-title">${esc(risk.title)}</span>
          <span class="rm-meta">${levelTag(risk.level, risk.level_label)}<span>${esc(risk.type_label)}</span><span class="dot-sep"></span><span>${esc(owner.name || "—")}</span><span class="dot-sep"></span><span>${esc(risk.amount)} 万元</span></span>
          <span class="rm-sla ${urgent ? "urgent" : ""}">${icon("clock")}${esc(slaText)}</span>
        </span>
        <span class="rm-go">${icon("arrow")}</span>
      </div>`;
  }

  function trendSvg(trend) {
    const points = (trend && trend.points) || [];
    if (!points.length) return emptyState("暂无趋势数据", "服务端没有返回近 14 天签约趋势。");
    const w = 700, h = 230, left = 42, right = 16, top = 16, bottom = 30;
    const maxVal = Math.max(10, ...points.map((p) => Math.max(Number(p.sign_wan) || 0, Number(p.target_wan) || 0)));
    const maxY = Math.ceil(maxVal / 50) * 50;
    const x = (i) => left + (i * (w - left - right)) / Math.max(1, points.length - 1);
    const y = (v) => top + (h - top - bottom) * (1 - (Number(v) || 0) / maxY);
    const line = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.sign_wan).toFixed(1)}`).join(" ");
    const area = `${line} L${x(points.length - 1).toFixed(1)},${h - bottom} L${x(0).toFixed(1)},${h - bottom} Z`;
    const target = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.target_wan).toFixed(1)}`).join(" ");
    const grid = [0, 0.25, 0.5, 0.75, 1].map((r) => {
      const gy = top + (h - top - bottom) * r;
      const val = maxY * (1 - r);
      return `<line class="chart-grid" x1="${left}" y1="${gy.toFixed(1)}" x2="${w - right}" y2="${gy.toFixed(1)}"></line>
        <text class="chart-label" x="${left - 8}" y="${(gy + 3).toFixed(1)}" text-anchor="end">${num(val, 0)}</text>`;
    }).join("");
    const xLabels = points.map((p, i) => (i % 2 === 0 || i === points.length - 1)
      ? `<text class="chart-label" x="${x(i).toFixed(1)}" y="${h - 8}" text-anchor="middle">${esc(p.label)}</text>` : "").join("");
    const dots = points.map((p, i) => `<circle class="chart-dot" cx="${x(i).toFixed(1)}" cy="${y(p.sign_wan).toFixed(1)}" r="3.2"><title>${esc(p.date)} 签约 ${num(p.sign_wan)} 万元；目标 ${num(p.target_wan)} 万元；线索 ${intNum(p.leads)} 条</title></circle>`).join("");
    return `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="近 14 天每日签约与日目标折线图，数据可在表格视图查看">
      <defs><linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2F5597" stop-opacity=".18"></stop><stop offset="1" stop-color="#2F5597" stop-opacity="0"></stop></linearGradient></defs>
      ${grid}<path class="chart-area" d="${area}"></path><path class="chart-target" d="${target}"></path><path class="chart-line" d="${line}"></path>${dots}${xLabels}
      <text class="chart-label" x="${left}" y="${h - 8}" text-anchor="start">单位：万元</text>
    </svg>`;
  }

  function trendTable(trend) {
    const points = (trend && trend.points) || [];
    return `<div class="table-scroll no-min"><table class="chart-table"><thead><tr><th>日期</th><th>签约额（万元）</th><th>日目标（万元）</th><th>签约单数</th><th>线索</th></tr></thead><tbody>
      ${points.map((p) => `<tr><td>${esc(p.date)}</td><td>${num(p.sign_wan)}</td><td>${num(p.target_wan)}</td><td>${intNum(p.contracts)}</td><td>${intNum(p.leads)}</td></tr>`).join("")}
    </tbody></table></div>`;
  }

  function moverList(items, emptyText) {
    if (!items || !items.length) return `<div class="pop-empty">${esc(emptyText)}</div>`;
    return `<div class="mover-list">${items.map((m) => `
      <div class="mover-item">
        <span class="mv-name" title="${esc(m.name)}">${esc(m.name)}</span>
        <span class="mv-value ${m.change_pct >= 0 ? "trend-up" : "trend-down"}">${signedPct(m.change_pct)}</span>
        <span class="muted">${num(m.current_wan)} 万</span>
      </div>`).join("")}</div>`;
  }

  function channelTable(channels) {
    if (!channels || !channels.length) return emptyState("暂无渠道数据", "服务端没有返回渠道表现。");
    return `<div class="table-scroll"><table class="data-table"><thead><tr>
      <th>渠道</th><th class="r">线索</th><th class="r">有效线索</th><th class="r">转化率</th><th class="r">归因签约（万元）</th><th class="r">投放（万元）</th><th class="r">ROI（倍）</th><th class="r">线索周环比</th>
    </tr></thead><tbody>${channels.map((c) => `
      <tr><td class="name">${esc(c.channel)}</td><td class="r">${intNum(c.leads)}</td><td class="r">${intNum(c.valid_leads)}</td>
      <td class="r">${pct(c.conversion_rate)}</td><td class="r">${num(c.contract_amount_wan)}</td><td class="r">${num(c.spend_wan)}</td>
      <td class="r channel-roi">${num(c.roi, 1)}</td><td class="r ${c.leads_wow >= 0 ? "trend-up" : "trend-down"}">${signedPct(c.leads_wow)}</td></tr>`).join("")}
    </tbody></table></div>`;
  }

  async function renderBrief(seq) {
    let brief;
    try {
      brief = await api("/api/brief/daily");
    } catch (err) {
      if (seq !== state.routeSeq) return;
      if (err.status === 401) return;
      content.innerHTML = pageError(err.message);
      bindRetry(content);
      return;
    }
    if (seq !== state.routeSeq) return;
    state.currentBrief = brief;
    const channels = Array.isArray(brief.channels) ? brief.channels : ((brief.channels && brief.channels.items) || []);
    const actions = brief.actions || [];
    const topRisks = brief.top_risks || [];
    const riskStats = brief.risk_stats || { by_level: {} };
    document.getElementById("content").innerHTML = `
      <section class="page">
        <div class="page-head">
          <div>
            <div class="eyebrow">DAILY BRIEF · 演示环境</div>
            <h1>${esc(brief.greeting || "今日简报")}</h1>
            <p class="sub">${esc(brief.headline || "")}</p>
            <div class="meta-line">
              <span>业务日期 ${esc(brief.date)}（${esc(brief.weekday || "—")}）</span><span class="sep">·</span>
              <span>范围 ${esc(brief.scope && brief.scope.name)}</span><span class="sep">·</span>
              <span>发布 ${shortTime(brief.published_at)}</span><span class="sep">·</span>
              <span>${esc(brief.publish_schedule || "每日 08:30 推送")}</span>
            </div>
          </div>
          <div class="head-actions">
            <button class="btn sm" id="briefPrint">${icon("brief")}<span>打印日报</span></button>
            <button class="btn sm" id="briefExport">${icon("download")}<span>导出 Excel</span></button>
            <a class="btn sm" href="/docs" target="_blank" rel="noopener">${icon("info")}<span>接口文档</span></a>
          </div>
        </div>
        <div class="conclusions">${(brief.conclusions || []).map(conclusionCard).join("")}</div>
        <div class="kpi-grid">${(brief.kpis || []).map(kpiCard).join("")}</div>
        <div class="brief-grid">
          <div class="card">
            ${sectionHead("签约趋势（近 14 天）", "实线为每日签约额，虚线为按天折算的日目标", `<div class="head-actions"><div class="seg" id="trendToggle"><button class="on" data-trend-view="chart">${icon("chart")}图表</button><button data-trend-view="table">${icon("table")}表格</button></div></div>`)}
            <div class="card-b" style="padding-top:2px">
              <div class="legend" style="margin-bottom:4px"><span><i></i>签约额</span><span><i class="dash"></i>日目标</span><span>单位：万元</span></div>
              <div id="trendChart">${trendSvg(brief.trend)}</div>
              <div id="trendTable" hidden>${trendTable(brief.trend)}</div>
              <div class="chart-foot"><span>数据截至 ${esc(brief.date)}；日目标 = 月目标 ÷ 当月天数。</span><span>趋势口径：签约额按签约日期聚合。</span></div>
            </div>
          </div>
          <div class="card">
            ${sectionHead("风险 Top3", `当前未结束 ${riskStats.active ?? "—"} 条 · 红色未结束 ${riskStats.red_active ?? "—"} 条`, `<span class="tag red">优先处理</span>`)}
            <div class="card-b" style="padding-top:6px">
              <div class="risk-mini">${topRisks.length ? topRisks.map(riskMiniItem).join("") : `<div class="risk-zero">当前数据范围暂无未结束风险</div>`}</div>
              <div class="risk-mini-foot"><span class="muted" style="font-size:10px">按级别和认领时限排序</span><button class="link" data-page="risks">进入风险中心 ${icon("arrow")}</button></div>
            </div>
          </div>
        </div>
        <div class="card section-gap">
          ${sectionHead("渠道表现（近 30 天）", "线索、转化、归因签约、投放与 ROI；缺失值显示 —", `<div class="meta-line"><span>截至 ${esc(brief.channel_period && brief.channel_period.end)}</span></div>`)}
          <div class="card-b" style="padding-top:6px">${channelTable(channels)}</div>
        </div>
        <div class="brief-grid section-gap">
          <div class="card">
            ${sectionHead("增长与下滑", "近 7 天对比前 7 天签约额（按当前数据范围拆组织/人）", "")}
            <div class="card-b" style="padding-top:4px">
              <div class="mover-grid">
                <div><div class="eyebrow" style="margin-bottom:3px">增长</div>${moverList(brief.movers && brief.movers.growth, "暂无增长项")}</div>
                <div><div class="eyebrow" style="margin-bottom:3px">下滑</div>${moverList(brief.movers && brief.movers.decline, "暂无下滑项")}</div>
              </div>
            </div>
          </div>
          <div class="card">
            ${sectionHead("动作建议", "来自风险处置建议，服务端生成", "")}
            <div class="card-b" style="padding-top:4px">
              ${actions.length ? `<ol class="action-list">${actions.map((a) => `
                <li>${a.risk_id ? `<a href="#/risks/${esc(a.risk_id)}" class="action-link" data-risk-link="${esc(a.risk_id)}">${esc(a.title)}</a><div class="action-owner">责任人：${esc(a.owner_name || "—")}</div><div>${esc(a.text)}</div>` : `<b>${esc(a.title)}</b><div>${esc(a.text)}</div>`}</li>`).join("")}</ol>` : `<div class="pop-empty">暂无动作建议</div>`}
            </div>
          </div>
        </div>
        <div class="card section-gap">
          ${sectionHead("数据说明", "所有数字由服务端计算；缺失不用 0 代替", `<span class="tag gray">${esc(brief.data_quality && brief.data_quality.status === "pass" ? "质量通过" : "质量提示")}</span>`)}
          <div class="card-b" style="padding-top:6px">
            <ul class="data-note-list">${(brief.data_notes || []).map((n) => `<li>${esc(n)}</li>`).join("")}</ul>
            <div class="source-strip"><span>${icon("info")}${esc(brief.data_source || "")}</span><span>批次 ${esc(brief.batch_id || "—")}</span></div>
          </div>
        </div>
      </section>`;
    bindBriefEvents(seq, brief);
  }

  function bindBriefEvents(seq, brief) {
    $$("[data-metric]", content).forEach((el) => {
      el.addEventListener("click", (event) => {
        if (event.target.closest("[data-risk-link]")) return;
        openDrill(el.dataset.metric, brief.date);
      });
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDrill(el.dataset.metric, brief.date); }
      });
    });
    $$("[data-risk-link]", content).forEach((el) => {
      el.addEventListener("click", (event) => {
        event.preventDefault();
        openRiskRoute(el.dataset.riskLink);
      });
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openRiskRoute(el.dataset.riskLink); }
      });
    });
    $$("[data-page]", content).forEach((el) => el.addEventListener("click", () => navigate(el.dataset.page)));
    const toggle = $("#trendToggle");
    if (toggle) {
      $$("button", toggle).forEach((btn) => btn.addEventListener("click", () => {
        $$("button", toggle).forEach((b) => b.classList.toggle("on", b === btn));
        $("#trendChart").hidden = btn.dataset.trendView !== "chart";
        $("#trendTable").hidden = btn.dataset.trendView !== "table";
      }));
    }
    const exportBtn = $("#briefExport");
    if (exportBtn) exportBtn.addEventListener("click", () => {
      confirmDialog({
        title: "导出日报 Excel",
        body: `<div class="confirm-copy">即将下载 ${esc(brief.date)} 的日报 Excel。<ul>
          <li>文件会写入「演示数据·禁止外传」水印。</li>
          <li>只包含当前账号有权查看的数据范围。</li>
          <li>导出动作会写入审计日志。</li></ul></div>`,
        confirmLabel: "确认下载",
        onConfirm: async () => {
          const name = await downloadFile(`/api/export/brief.xlsx?date=${encodeURIComponent(brief.date)}`, `brief_${brief.date}.xlsx`);
          toast(`已开始下载：${name}`);
        },
      });
    });
    const printBtn = $("#briefPrint");
    if (printBtn) printBtn.addEventListener("click", () => {
      confirmDialog({
        title: "打开打印版日报",
        body: `<div class="confirm-copy">打印版为服务端生成的 HTML，带「演示数据·禁止外传」水印，可在浏览器中打印或另存为 PDF。</div>`,
        confirmLabel: "打开打印页",
        onConfirm: async () => {
          window.open(`/api/print/brief?date=${encodeURIComponent(brief.date)}`, "_blank", "noopener");
          toast("已打开打印页");
        },
      });
    });
  }

  // ---------------------------------------------------------------- 风险中心

  function riskStatCard(label, value, sub, cls = "") {
    return `<div class="stat-card card ${cls}"><div class="stat-label">${esc(label)}</div><div class="stat-value" id="${cls ? "" : ""}">${esc(value)}</div><div class="stat-sub">${esc(sub)}</div></div>`;
  }

  async function renderRisks(seq, deepRiskId) {
    content.innerHTML = `
      <section class="page">
        <div class="page-head">
          <div>
            <div class="eyebrow">RISK CENTER · 服务端行级过滤</div>
            <h1>风险中心</h1>
            <p class="sub">六类风险按级别、状态和认领时限排序；证据链、时间线与处置动作都在详情抽屉中。已结束风险自动置底。</p>
            <div class="meta-line"><span>范围 ${esc(state.me.scope.label)}</span><span class="sep">·</span><span>角色 ${esc(state.me.title)}</span><span class="sep">·</span><span>红色 4 小时认领 / 橙色 8 小时 / 黄色 1 个工作日</span></div>
          </div>
          <div class="head-actions">
            <button class="btn sm" id="riskExport">${icon("download")}<span>导出当前筛选</span></button>
          </div>
        </div>
        <div class="stat-grid">
          <div class="stat-card card"><div class="stat-label">未结束风险</div><div class="stat-value" id="riskStatActive">—</div><div class="stat-sub" id="riskStatTotal">读取中</div></div>
          <div class="stat-card card"><div class="stat-label">红色未结束</div><div class="stat-value" id="riskStatRed">—</div><div class="stat-sub">最高优先级</div></div>
          <div class="stat-card card late"><div class="stat-label">认领超时</div><div class="stat-value" id="riskStatClaimLate">—</div><div class="stat-sub">超过认领 SLA</div></div>
          <div class="stat-card card late"><div class="stat-label">关闭超时</div><div class="stat-value" id="riskStatCloseLate">—</div><div class="stat-sub">超过关闭 SLA</div></div>
        </div>
        <div class="filter-bar card">
          <div class="chips" id="riskLevelChips">
            <button class="chip on" data-level="all">全部 <span class="cnt"></span></button>
            <button class="chip" data-level="red"><span class="cdot red"></span>红色 <span class="cnt"></span></button>
            <button class="chip" data-level="orange"><span class="cdot orange"></span>橙色 <span class="cnt"></span></button>
            <button class="chip" data-level="yellow"><span class="cdot yellow"></span>黄色 <span class="cnt"></span></button>
          </div>
          <div class="select-wrap"><select class="select" id="riskStatusFilter" aria-label="状态筛选">
            <option value="all">全部状态</option><option value="active">未结束</option><option value="pending">待认领</option>
            <option value="processing">处理中</option><option value="closed">已关闭</option><option value="false_positive">误报</option><option value="long_term">长期跟踪</option>
          </select></div>
          <div class="select-wrap"><select class="select" id="riskTypeFilter" aria-label="类型筛选">
            <option value="all">全部类型</option><option value="target_gap">目标缺口</option><option value="decline">业绩下滑</option>
            <option value="leads">线索异常</option><option value="coverage">商机覆盖</option><option value="churn">大客户流失</option><option value="payment">订单/回款</option>
          </select></div>
          <div class="select-wrap"><select class="select" id="riskSort" aria-label="排序">
            <option value="priority">默认排序（未结束优先）</option><option value="due">认领时限</option><option value="level">级别</option>
            <option value="amount">金额</option><option value="created">生成时间</option>
          </select></div>
          <div class="search-box">${icon("search")}<input id="riskSearch" type="search" placeholder="搜索编号、标题、客户、责任人" aria-label="搜索风险" value="${esc(state.riskFilters.q)}"></div>
          <button class="filter-reset" id="riskReset">重置</button>
        </div>
        <div class="card table-card">
          <div class="table-top"><div class="t">风险清单 <span id="riskCount">读取中…</span></div><div class="sla-strip"><span class="tag gray">${icon("clock")}红色认领 4h</span><span class="tag gray">橙色 8h</span><span class="tag gray">黄色 1 个工作日</span></div></div>
          <div class="table-scroll">
            <table class="risk-table"><thead><tr>
              <th>级别</th><th>风险 / 对象</th><th>类型</th><th class="r">金额(万元)</th><th>责任人</th><th>SLA</th><th>状态</th><th class="r">处理</th>
            </tr></thead><tbody id="riskTableBody"><tr><td colspan="8"><div class="loading-block">正在读取风险…</div></td></tr></tbody></table>
          </div>
          <div class="pager" id="riskPager"></div>
        </div>
      </section>`;
    bindRiskPageEvents();
    await loadRiskList();
    if (deepRiskId) openRisk(deepRiskId, true);
  }

  function bindRiskPageEvents() {
    const chips = $("#riskLevelChips");
    $$("[data-level]", chips).forEach((btn) => btn.addEventListener("click", () => {
      state.riskFilters.level = btn.dataset.level;
      state.riskFilters.page = 1;
      $$("[data-level]", chips).forEach((b) => b.classList.toggle("on", b === btn));
      loadRiskList();
    }));
    const status = $("#riskStatusFilter");
    status.value = state.riskFilters.status;
    status.addEventListener("change", () => { state.riskFilters.status = status.value; state.riskFilters.page = 1; loadRiskList(); });
    const type = $("#riskTypeFilter");
    type.value = state.riskFilters.type;
    type.addEventListener("change", () => { state.riskFilters.type = type.value; state.riskFilters.page = 1; loadRiskList(); });
    const sort = $("#riskSort");
    sort.value = state.riskFilters.sort;
    sort.addEventListener("change", () => { state.riskFilters.sort = sort.value; state.riskFilters.page = 1; loadRiskList(); });
    let timer = null;
    const search = $("#riskSearch");
    search.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => { state.riskFilters.q = search.value.trim(); state.riskFilters.page = 1; loadRiskList(); }, 320);
    });
    $("#riskReset").addEventListener("click", () => {
      state.riskFilters = { level: "all", status: "all", type: "all", sort: "priority", q: "", page: 1 };
      route(true);
    });
    $("#riskExport").addEventListener("click", () => {
      const params = new URLSearchParams();
      if (state.riskFilters.level !== "all") params.set("level", state.riskFilters.level);
      if (state.riskFilters.status !== "all") params.set("status", state.riskFilters.status);
      if (state.riskFilters.type !== "all") params.set("type", state.riskFilters.type);
      if (state.riskFilters.q) params.set("q", state.riskFilters.q);
      params.set("sort", state.riskFilters.sort);
      confirmDialog({
        title: "导出风险清单 Excel",
        body: `<div class="confirm-copy">导出当前筛选结果，最多 1,000 条。文件带「演示数据·禁止外传」水印；手机号、邮箱保持脱敏。<ul><li>筛选：级别 ${esc(state.riskFilters.level === "all" ? "全部" : state.riskFilters.level)}，状态 ${esc(state.riskFilters.status)}，类型 ${esc(state.riskFilters.type)}。</li><li>导出会写审计日志。</li></ul></div>`,
        confirmLabel: "确认下载",
        onConfirm: async () => {
          const name = await downloadFile(`/api/export/risks.xlsx?${params.toString()}`, "risks.xlsx");
          toast(`已开始下载：${name}`);
        },
      });
    });
    const body = $("#riskTableBody");
    const openFromRow = (target) => {
      const row = target.closest("[data-risk-id]");
      if (row) openRisk(row.dataset.riskId);
    };
    body.addEventListener("click", (e) => { if (!e.target.closest("button")) openFromRow(e.target); });
    body.addEventListener("keydown", (e) => {
      if ((e.key === "Enter" || e.key === " ") && e.target.closest("[data-risk-id]")) {
        e.preventDefault(); openFromRow(e.target);
      }
    });
    const pager = $("#riskPager");
    pager.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-page-num]");
      if (!btn) return;
      const page = Number(btn.dataset.pageNum);
      if (!page || page === state.riskFilters.page) return;
      state.riskFilters.page = page;
      loadRiskList();
    });
  }

  function riskRow(risk) {
    const sla = risk.sla || {};
    const owner = ownerOf(risk);
    const status = risk.status;
    const slaText = status === "pending" ? sla.claim_text : (status === "processing" ? sla.close_text : "已结束");
    const urgent = (status === "pending" && sla.claim_state === "overdue") || (status === "processing" && sla.close_state === "overdue");
    return `<tr data-risk-id="${esc(risk.id)}" tabindex="0" class="${["closed", "false_positive", "long_term"].includes(status) ? "closed" : ""}" aria-label="打开风险 ${esc(risk.id)}">
      <td>${levelTag(risk.level, risk.level_label)}</td>
      <td><div class="risk-name">${esc(risk.title)}</div><div class="risk-obj">${esc(risk.id)} · ${esc(risk.object.type_label)}：${esc(risk.object.name)}</div></td>
      <td>${esc(risk.type_label)}</td>
      <td class="r risk-amount">${esc(risk.amount)}</td>
      <td><div class="risk-owner"><span class="mini-avatar">${esc((owner.name || "?").slice(0, 1))}</span><span>${esc(owner.name || "—")}<div class="risk-obj">${esc(owner.phone || "")}</div></span></div></td>
      <td class="sla-cell ${urgent ? "urgent" : ""}">${icon("clock", "ic")} ${esc(slaText)}</td>
      <td>${statusBadge(status, risk.status_label)}</td>
      <td class="r"><div class="row-actions"><button class="mini-btn pri" data-row-open="${esc(risk.id)}">查看/处理</button></div></td>
    </tr>`;
  }

  async function loadRiskList() {
    if (state.routePage !== "risks") return;
    const body = $("#riskTableBody");
    if (!body) return;
    const req = ++state.riskListReq;
    body.innerHTML = `<tr><td colspan="8"><div class="loading-block">正在读取风险…</div></td></tr>`;
    const params = new URLSearchParams();
    if (state.riskFilters.level !== "all") params.set("level", state.riskFilters.level);
    if (state.riskFilters.status !== "all") params.set("status", state.riskFilters.status);
    if (state.riskFilters.type !== "all") params.set("type", state.riskFilters.type);
    if (state.riskFilters.q) params.set("q", state.riskFilters.q);
    params.set("sort", state.riskFilters.sort);
    params.set("page", String(state.riskFilters.page));
    params.set("page_size", "20");
    try {
      const data = await api(`/api/risks?${params.toString()}`);
      if (req !== state.riskListReq || state.routePage !== "risks") return;
      const stats = data.stats || {};
      $("#riskStatActive").textContent = intNum(stats.active);
      $("#riskStatTotal").textContent = `全部 ${intNum(stats.total)} 条 · 已结束 ${intNum((stats.by_status && Object.values(stats.by_status).reduce((a, b) => a + b, 0)) - (stats.active || 0))} 条`;
      $("#riskStatRed").textContent = intNum(stats.red_active);
      $("#riskStatClaimLate").textContent = intNum(stats.claim_overdue);
      $("#riskStatCloseLate").textContent = intNum(stats.close_overdue);
      $("#riskCount").textContent = `共 ${intNum(data.total)} 条 · 第 ${data.page} 页`;
      const allChip = $('#riskLevelChips [data-level="all"] .cnt');
      if (allChip) allChip.textContent = intNum(stats.total);
      ["red", "orange", "yellow"].forEach((lv) => {
        const el = $(`#riskLevelChips [data-level="${lv}"] .cnt`);
        if (el) el.textContent = intNum((stats.by_level || {})[lv] || 0);
      });
      body.innerHTML = (data.items || []).length
        ? data.items.map(riskRow).join("")
        : `<tr><td colspan="8">${emptyState("没有符合条件的风险", "可以调整级别、状态或搜索条件。")}</td></tr>`;
      $$("[data-row-open]", body).forEach((btn) => btn.addEventListener("click", (e) => {
        e.stopPropagation(); openRisk(btn.dataset.rowOpen);
      }));
      renderRiskPager(data);
    } catch (err) {
      if (req !== state.riskListReq) return;
      if (err.status === 401) return;
      body.innerHTML = `<tr><td colspan="8"><div class="page-error list-error"><b>风险列表读取失败</b>${esc(err.message)}<br><button class="btn sm" data-retry-risk>重新加载</button></div></td></tr>`;
      const retry = $("[data-retry-risk]", body);
      if (retry) retry.addEventListener("click", () => loadRiskList());
    }
  }

  function renderRiskPager(data) {
    const pager = $("#riskPager");
    if (!pager) return;
    const pages = Math.max(1, Math.ceil((data.total || 0) / (data.page_size || 20)));
    const current = data.page || 1;
    const nums = [];
    const start = Math.max(1, current - 2), end = Math.min(pages, current + 2);
    for (let i = start; i <= end; i += 1) nums.push(i);
    pager.innerHTML = `<span>每页 ${data.page_size || 20} 条 · 共 ${pages} 页</span><div class="pager-btns">
      <button class="mini-btn" data-page-num="${current - 1}" ${current <= 1 ? "disabled" : ""}>上一页</button>
      ${nums.map((n) => `<button class="mini-btn ${n === current ? "on" : ""}" data-page-num="${n}">${n}</button>`).join("")}
      <button class="mini-btn" data-page-num="${current + 1}" ${current >= pages ? "disabled" : ""}>下一页</button>
    </div>`;
  }

  // ---------------------------------------------------------------- 风险抽屉

  async function openRisk(riskId, fromRoute = false) {
    if (!riskId) return;
    state.drawerRiskId = riskId;
    const req = ++state.drawerReq;
    drawer.innerHTML = `<div class="dw-head"><div class="dw-tags"><span class="tag gray">加载中</span></div><div class="dw-title">正在读取风险详情…</div></div><div class="dw-body"><div class="loading-block">正在读取证据链与时间线…</div></div>`;
    drawer.classList.add("open");
    drawer.removeAttribute("aria-hidden");
    drawerMask.classList.add("open");
    syncScrollLock();
    try {
      const risk = await api(`/api/risks/${encodeURIComponent(riskId)}`);
      if (req !== state.drawerReq) return;
      renderRiskDrawer(risk);
    } catch (err) {
      if (req !== state.drawerReq) return;
      if (err.status === 401) return;
      drawer.innerHTML = `<div class="dw-head"><div class="dw-title">风险详情</div><button class="icon-btn dw-close" data-drawer-close aria-label="关闭">${icon("close")}</button></div>
        <div class="dw-body"><div class="page-error dw-error"><b>读取失败</b>${esc(err.message)}<br><button class="btn sm" data-drawer-retry>重试</button></div></div>`;
      bindDrawerCommon();
      const retry = $("[data-drawer-retry]", drawer);
      if (retry) retry.addEventListener("click", () => openRisk(riskId, fromRoute));
    }
  }

  function openRiskRoute(riskId) {
    if (state.routePage === "risks" && location.hash === `#/risks/${encodeURIComponent(riskId)}`) {
      openRisk(riskId, true);
    } else {
      navigate("risks", riskId);
    }
  }

  function closeDrawer(updateHash = true) {
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    drawerMask.classList.remove("open");
    state.drawerRiskId = null;
    state.drawerReq += 1;
    syncScrollLock();
    if (updateHash && location.hash.startsWith("#/risks/")) {
      history.replaceState(null, "", "#/risks");
    }
  }

  function bindDrawerCommon() {
    $$("[data-drawer-close]", drawer).forEach((btn) => btn.addEventListener("click", () => closeDrawer(true)));
  }

  function evidenceRows(evidence) {
    if (!evidence || !evidence.length) return `<div class="pop-empty">暂无证据链</div>`;
    return `<div class="table-scroll no-min"><table class="evidence-table"><thead><tr><th>判定项</th><th>当前值</th><th>阈值</th><th>基期/基准</th><th>来源</th></tr></thead><tbody>
      ${evidence.map((e) => `<tr><td>${esc(e.label)}</td><td><b>${esc(e.current_value)}</b></td><td>${esc(e.threshold)}</td><td>${esc(e.baseline)}</td><td>${esc(e.source)}<div class="why-note">${shortTime(e.triggered_at)}</div></td></tr>`).join("")}
    </tbody></table></div>`;
  }

  function relatedHtml(risk) {
    const rows = [];
    (risk.related || []).forEach((r) => rows.push({
      label: r.label || r.customer || r.id, id: r.id, type: r.type,
      amount: r.amount, extra: r.stage || r.status || r.due_date || "",
    }));
    (risk.related_opportunities || []).forEach((o) => {
      if (!rows.some((x) => x.id === o.id)) rows.push({ label: o.customer, id: o.id, type: "opportunity", amount: o.amount, extra: o.stage || "" });
    });
    if (!rows.length) return `<div class="pop-empty">暂无关联商机/订单</div>`;
    return `<div class="related-list">${rows.map((r) => `
      <div class="related-row"><span>${esc(r.label)} <small class="muted">${esc(r.id)}</small></span><span>${r.amount !== undefined && r.amount !== null ? `${num(r.amount)} 万元` : ""} ${esc(r.extra || "")}</span></div>`).join("")}</div>`;
  }

  function timelineHtml(timeline) {
    if (!timeline || !timeline.length) return `<div class="pop-empty">暂无时间线</div>`;
    return `<div class="timeline">${timeline.slice().reverse().map((t, i) => `
      <div class="tl-item ${i === 0 ? "now" : ""}">
        <div class="tl-time">${shortTime(t.created_at)} · ${esc(t.event_label)}</div>
        <div class="tl-text"><b>${esc(t.actor && t.actor.name || "系统")}</b>${t.from_status ? ` · ${esc(t.from_status_label || t.from_status)} → ${esc(t.to_status_label || t.to_status)}` : ""}${t.note ? `<div>${esc(t.note)}</div>` : ""}</div>
      </div>`).join("")}</div>`;
  }

  function renderRiskDrawer(risk) {
    const owner = ownerOf(risk);
    const sla = risk.sla || {};
    const actions = risk.allowed_actions || {};
    const terminal = ["closed", "false_positive", "long_term"].includes(risk.status);
    const slaClaimUrgent = sla.claim_state === "overdue" || sla.claim_state === "due_soon";
    const slaCloseUrgent = sla.close_state === "overdue" || sla.close_state === "due_soon";
    const footButtons = [];
    if (actions.claim) footButtons.push(`<button class="btn primary" data-risk-act="claim">${icon("check")}认领风险</button>`);
    if (actions.close) footButtons.push(`<button class="btn primary" data-risk-act="close">${icon("check")}关闭风险</button>`);
    if (actions.transfer) footButtons.push(`<button class="btn" data-risk-act="transfer">${icon("arrow")}转派</button>`);
    if (actions.escalate) footButtons.push(`<button class="btn" data-risk-act="escalate">${icon("trend")}升级</button>`);
    drawer.innerHTML = `
      <div class="dw-head">
        <div class="dw-tags">${levelTag(risk.level, risk.level_label)}<span class="tag gray">${esc(risk.type_label)}</span>${statusBadge(risk.status, risk.status_label)}${risk.escalation && risk.escalation.level ? `<span class="tag orange">已升级 ${risk.escalation.level} 级</span>` : ""}</div>
        <div class="dw-title">${esc(risk.title)}</div>
        <div class="dw-id">${esc(risk.id)} · 对象：${esc(risk.object.type_label)} ${esc(risk.object.name)} · 生成于 ${shortTime(risk.created_at)}</div>
        <button class="icon-btn dw-close" data-drawer-close aria-label="关闭详情">${icon("close")}</button>
      </div>
      <div class="dw-body">
        ${terminal ? `<div class="closed-banner">${icon("check")}该风险已结束：${esc(risk.status_label)}${risk.closed_at ? ` · ${shortTime(risk.closed_at)}` : ""}</div>` : ""}
        <div class="dw-section">
          <h4>关键事实 <span class="side">金额单位：万元</span></h4>
          <div class="facts">
            <div class="fact"><div class="k">责任人 / 联系方式</div><div class="v">${esc(owner.name || "—")}<small>${esc(owner.title || "")}</small></div><div class="why-note">${esc(owner.phone || "—")} · ${esc(owner.email || "—")}</div></div>
            <div class="fact"><div class="k">所属组织</div><div class="v">${esc(risk.dept)}</div><div class="why-note">${esc(risk.org && risk.org.path)}</div></div>
            <div class="fact"><div class="k">风险金额</div><div class="v">${num(risk.amount)} <small>万元</small></div></div>
            <div class="fact"><div class="k">触发次数 / 合并</div><div class="v">${intNum(risk.trigger_count)} 次 <small>合并 ${intNum(risk.merged_count)} 次</small></div></div>
            <div class="fact"><div class="k">状态</div><div class="v">${esc(risk.status_label)}</div><div class="why-note">${risk.claimed_at ? `认领于 ${shortTime(risk.claimed_at)}` : "尚未认领"}</div></div>
            <div class="fact"><div class="k">最近更新</div><div class="v">${shortTime(risk.updated_at)}</div><div class="why-note">证据 ${risk.evidence_count || 0} 条 · 事件 ${risk.event_count || 0} 条</div></div>
          </div>
        </div>
        <div class="dw-section">
          <h4>SLA 时限 <span class="side">超时会自动升级，最多 2 级</span></h4>
          <div class="sla-grid">
            <div class="sla-box ${slaClaimUrgent || sla.claim_state === "overdue" ? "urgent" : ""}"><div class="k">认领时限</div><div class="v">${esc(sla.claim_text || "—")}</div><div class="why-note">${shortTime(sla.claim_due_at)}</div></div>
            <div class="sla-box ${slaCloseUrgent || sla.close_state === "overdue" ? "urgent" : ""}"><div class="k">关闭时限</div><div class="v">${esc(sla.close_text || "—")}</div><div class="why-note">${shortTime(sla.close_due_at)}</div></div>
          </div>
          ${risk.escalation && risk.escalation.escalated_to ? `<div class="transfer-current">当前升级对象：${esc(risk.escalation.escalated_to.name)}${risk.escalation.in_general_manager_pool ? "（总经理池）" : ""}</div>` : ""}
        </div>
        <div class="dw-section"><h4>判定依据 <span class="side">当前值 / 阈值 / 基期</span></h4>${evidenceRows(risk.evidence)}</div>
        <div class="dw-section"><h4>处置建议</h4>${(risk.actions || []).length ? `<ol class="action-list">${risk.actions.map((a) => `<li>${esc(a)}</li>`).join("")}</ol>` : `<div class="pop-empty">暂无处置建议</div>`}</div>
        <div class="dw-section"><h4>关联对象</h4>${relatedHtml(risk)}</div>
        <div class="dw-section"><h4>时间线 <span class="side">最新在前</span></h4>${timelineHtml(risk.timeline)}</div>
        ${(risk.watchers || []).length ? `<div class="dw-section"><h4>关注人 <span class="side">保留可见权</span></h4><div class="related-list">${risk.watchers.map((w) => `<div class="related-row"><span>${esc(w.name || w.user_id)} <small class="muted">${esc(w.title || "")}</small></span><span>${esc(w.reason || "")}</span></div>`).join("")}</div></div>` : ""}
        ${risk.close ? `<div class="dw-section"><h4>关闭记录</h4><div class="facts"><div class="fact"><div class="k">结果</div><div class="v">${esc(risk.close.result_status_label || risk.close.result_status)}</div></div><div class="fact"><div class="k">原因</div><div class="v">${esc(risk.close.reason)}</div></div><div class="fact"><div class="k">动作</div><div class="v">${esc(risk.close.action)}</div></div><div class="fact"><div class="k">结果说明</div><div class="v">${esc(risk.close.result)}</div></div></div></div>` : ""}
      </div>
      <div class="dw-foot">
        ${footButtons.join("")}
        ${footButtons.length ? "" : `<div class="action-disabled-note">当前状态下没有可执行动作${terminal ? "；风险已结束。" : "，或你的角色没有转派/升级权限。"}</div>`}
      </div>`;
    bindDrawerCommon();
    $$("[data-risk-act]", drawer).forEach((btn) => btn.addEventListener("click", () => {
      const act = btn.dataset.riskAct;
      if (act === "claim") openClaimDialog(risk);
      if (act === "close") openCloseDialog(risk);
      if (act === "transfer") openTransferDialog(risk);
      if (act === "escalate") openEscalateDialog(risk);
    }));
  }

  async function afterRiskChange(riskId) {
    await refreshShellData();
    if (state.routePage === "risks") await loadRiskList();
    await openRisk(riskId);
  }

  function formModal({ title, subtitle, body, submitLabel, submitClass = "primary", onSubmit }) {
    const formId = `modalForm${Date.now()}`;
    openModal(`
      <div class="modal-head"><h3>${esc(title)}</h3><p>${esc(subtitle || "")}</p><button class="icon-btn modal-close" data-close-modal aria-label="关闭">${icon("close")}</button></div>
      <form id="${formId}" novalidate>
        <div class="modal-body">${body}<div class="form-error modal-error" role="alert"></div></div>
        <div class="modal-foot"><div class="spacer"></div><button class="btn" type="button" data-close-modal>取消</button><button class="btn ${submitClass}" type="submit">${esc(submitLabel || "确认")}</button></div>
      </form>`, (root) => {
      const form = $(`#${formId}`, root);
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const btn = form.querySelector('[type="submit"]');
        const errBox = form.querySelector(".modal-error");
        errBox.classList.remove("show");
        btn.disabled = true;
        const original = btn.textContent;
        btn.textContent = "处理中…";
        try {
          await onSubmit(new FormData(form));
          closeModal();
        } catch (err) {
          errBox.textContent = err.message;
          errBox.classList.add("show");
        } finally {
          btn.disabled = false;
          btn.textContent = original;
        }
      });
    });
  }

  function riskSummary(risk) {
    return `<div class="risk-summary"><span class="rs-bar ${esc(risk.level)}"></span><div><b>${esc(risk.title)}</b><small>${esc(risk.id)} · 责任人 ${esc(ownerOf(risk).name || "—")}</small></div><span class="rs-sla">${esc((risk.sla && risk.sla.claim_text) || "")}</span></div>`;
  }

  function openClaimDialog(risk) {
    formModal({
      title: "认领风险",
      subtitle: "认领后状态变为「处理中」，认领动作与说明会写入审计。",
      body: `${riskSummary(risk)}
        <div class="form-row"><label>处理计划 <small>可选，建议写清下一步</small></label><textarea name="plan" placeholder="例如：今天 18:00 前拉通重点商机清单，确认 3 个可签约客户。"></textarea></div>
        <div class="form-grid"><div class="form-row"><label>计划完成节点</label><input type="text" name="due" placeholder="例如：2026-10-26 18:00"></div>
        <div class="form-row"><label>同步动作</label><label class="check-line"><input type="checkbox" name="sync" value="1">同步到站内消息</label></div></div>
        <div class="modal-note">状态机：待认领 → 处理中。风险关闭需到「处理中」状态后再填写原因、动作与结果。</div>`,
      submitLabel: "确认认领",
      onSubmit: async (fd) => {
        const payload = { plan: String(fd.get("plan") || ""), due: String(fd.get("due") || "") || null, sync: Boolean(fd.get("sync")) };
        await api(`/api/risks/${encodeURIComponent(risk.id)}/claim`, { method: "POST", body: JSON.stringify(payload) });
        toast("风险已认领");
        afterRiskChange(risk.id);
      },
    });
  }

  function openCloseDialog(risk) {
    formModal({
      title: "关闭风险",
      subtitle: "原因、动作、结果每项至少 5 个字；关闭后风险会置底并保留事件链。",
      body: `${riskSummary(risk)}
        <div class="form-row"><label>关闭结果</label><div class="radio-row">
          <label class="radio-pill"><input type="radio" name="result_status" value="closed" checked><span>已解决</span></label>
          <label class="radio-pill"><input type="radio" name="result_status" value="false_positive"><span>误报</span></label>
          <label class="radio-pill"><input type="radio" name="result_status" value="long_term"><span>长期跟踪</span></label>
        </div></div>
        <div class="form-row"><label>原因 <small>至少 5 个字</small></label><textarea name="reason" minlength="5" required placeholder="为什么会触发这条风险？"></textarea></div>
        <div class="form-row"><label>采取动作 <small>至少 5 个字</small></label><textarea name="action" minlength="5" required placeholder="已经做了什么？"></textarea></div>
        <div class="form-row"><label>结果 <small>至少 5 个字</small></label><textarea name="result" minlength="5" required placeholder="当前结果如何？"></textarea></div>`,
      submitLabel: "确认关闭",
      onSubmit: async (fd) => {
        const payload = {
          result_status: String(fd.get("result_status")),
          reason: String(fd.get("reason") || "").trim(),
          action: String(fd.get("action") || "").trim(),
          result: String(fd.get("result") || "").trim(),
        };
        if ([payload.reason, payload.action, payload.result].some((v) => v.length < 5)) {
          throw new Error("原因、动作、结果每项至少填写 5 个字");
        }
        await api(`/api/risks/${encodeURIComponent(risk.id)}/close`, { method: "POST", body: JSON.stringify(payload) });
        toast("风险已关闭");
        afterRiskChange(risk.id);
      },
    });
  }

  function openTransferDialog(risk) {
    const candidates = risk.transfer_candidates || [];
    if (!risk.transfer_allowed) {
      toast("当前角色无权转派风险", "err");
      return;
    }
    if (!candidates.length) {
      toast("没有可用的转派对象", "err");
      return;
    }
    formModal({
      title: "转派风险",
      subtitle: "转派后原负责人保留可见权；新责任人重新计算认领 SLA。",
      body: `${riskSummary(risk)}
        <div class="form-row"><label>转派给 <small>仅显示你有权转派的人员</small></label><select name="to_user_id">
          ${candidates.map((u) => `<option value="${esc(u.user_id)}" ${u.is_current_owner ? "disabled" : ""}>${esc(u.name)} · ${esc(u.title)} · ${esc(u.org_name)}${u.is_current_owner ? "（当前责任人）" : ""}</option>`).join("")}
        </select></div>
        <div class="form-row"><label>转派说明 <small>必填</small></label><textarea name="note" required placeholder="说明转派原因和对方需要跟进的动作。"></textarea></div>
        <div class="modal-note">转派会写站内通知；原负责人进入关注人列表，仍可查看完整时间线。</div>`,
      submitLabel: "确认转派",
      onSubmit: async (fd) => {
        const payload = { to_user_id: String(fd.get("to_user_id") || ""), note: String(fd.get("note") || "").trim() };
        if (!payload.note) throw new Error("请填写转派说明");
        await api(`/api/risks/${encodeURIComponent(risk.id)}/transfer`, { method: "POST", body: JSON.stringify(payload) });
        toast("风险已转派");
        afterRiskChange(risk.id);
      },
    });
  }

  function openEscalateDialog(risk) {
    formModal({
      title: "手动升级风险",
      subtitle: "升级会通知升级对象和责任人；最多升到第 2 级（总经理池）。",
      body: `${riskSummary(risk)}
        <div class="form-row"><label>升级原因 <small>可选</small></label><textarea name="note" placeholder="例如：需要跨部门协调资源，申请升级至销售总监。"></textarea></div>
        <div class="modal-note">当前升级级别：${Number((risk.escalation && risk.escalation.level) || 0)} / 2。升级动作会写入审计日志。</div>`,
      submitLabel: "确认升级",
      onSubmit: async (fd) => {
        await api(`/api/risks/${encodeURIComponent(risk.id)}/escalate`, { method: "POST", body: JSON.stringify({ note: String(fd.get("note") || "") }) });
        toast("风险已升级");
        afterRiskChange(risk.id);
      },
    });
  }

  // ---------------------------------------------------------------- 周报

  async function renderWeekly(seq) {
    contentLoading("正在加载周报…");
    let report;
    try {
      report = await api(`/api/brief/weekly?week=${encodeURIComponent(state.weeklyType)}`);
    } catch (err) {
      if (seq !== state.routeSeq) return;
      if (err.status === 401) return;
      content.innerHTML = pageError(err.message);
      bindRetry(content);
      return;
    }
    if (seq !== state.routeSeq) return;
    const closure = report.risk_closure || {};
    const ranking = report.ranking || [];
    const types = report.risk_types || [];
    const daily = report.daily || [];
    const maxSign = Math.max(1, ...daily.map((d) => Number(d.sign_wan) || 0));
    const typeMax = Math.max(1, ...types.map((t) => t.count || 0));
    const maxRank = Math.max(1, ...ranking.map((r) => Number(r.sign_wan) || 0));
    const closedPct = closure.new_count ? Math.min(100, (closure.closed_count / closure.new_count) * 100) : 0;
    content.innerHTML = `
      <section class="page">
        <div class="page-head">
          <div>
            <div class="eyebrow">WEEKLY REVIEW · ${esc(report.edition || "周报")}</div>
            <h1>周报复盘</h1>
            <p class="sub">${esc(report.week_label)}；数据截至 ${esc(report.data_through)}。本周与上周同期同跨度比较，风险闭环状态随处理进展实时更新。</p>
            <div class="meta-line"><span>范围 ${esc(report.scope && report.scope.name)}</span><span class="sep">·</span><span>${esc(report.publish_schedule || "")}</span><span class="sep">·</span><span>发布 ${shortTime(report.published_at)}</span></div>
          </div>
          <div class="head-actions"><div class="week-bar"><div class="seg" id="weekToggle">
            <button class="${state.weeklyType === "this" ? "on" : ""}" data-week="this">本周</button>
            <button class="${state.weeklyType === "last" ? "on" : ""}" data-week="last">上周</button>
          </div></div></div>
        </div>
        <div class="week-top">${(report.kpis || []).map((k) => `
          <div class="week-stat card"><div class="k">${esc(k.label)}</div><div class="v">${esc(k.display)}</div>
          <div class="wow ${k.wow && k.wow.value > 0 ? "good" : (k.wow && k.wow.value < 0 ? "bad" : "")}">${esc(k.wow ? (k.wow.text === "—" ? "环比 —" : `环比 ${k.wow.text}`) : "—")}</div>
          <div class="d">${esc(k.sub || "")}</div></div>`).join("")}
        </div>
        <div class="weekly-grid">
          <div class="card">${sectionHead("三条结论", "服务端按本周数据计算")}<div class="weekly-concl">${(report.conclusions || []).map((c) => `<div class="wc-item"><span class="wc-num">${c.index}</span><p><b>${esc(c.title)}：</b>${esc(c.text)}</p></div>`).join("")}</div></div>
          <div class="card">${sectionHead("风险闭环", "本周新增、已闭环与存量")}
            <div class="closure-hero"><div class="closure-num">${num(closure.closure_rate)}<small>%</small></div><div class="closure-meta"><b>闭环率</b><span>新增 ${intNum(closure.new_count)} · 已闭环 ${intNum(closure.closed_count)} · 存量 ${intNum(closure.open_count)}</span></div></div>
            <div class="stack-bar"><i class="closed" style="width:${closedPct}%"></i><i class="open" style="width:${100 - closedPct}%"></i></div>
            <div class="stack-legend"><span><i style="background:#4E7CB8"></i>已闭环</span><span><i style="background:#D9E1EE"></i>未结束</span></div>
            <div class="type-bars">${types.map((t) => `<div class="type-row"><span class="tn">${esc(t.label)}</span><span class="tb"><i style="width:${Math.max(3, (t.count / typeMax) * 100)}%"></i></span><span class="tv">${intNum(t.count)}</span></div>`).join("")}</div>
          </div>
        </div>
        <div class="weekly-grid">
          <div class="card">${sectionHead("团队排行", "按本周签约额，范围仅限当前账号可见组织")}
            <div class="rank-chart">${ranking.length ? ranking.slice(0, 8).map((r) => `<div class="rank-row"><span class="rn" title="${esc(r.name)}">${r.rank}. ${esc(r.name)}</span><span class="rb"><i style="width:${Math.max(3, (r.sign_wan / maxRank) * 100)}%"></i></span><span class="rv">${num(r.sign_wan)}</span></div>`).join("") : `<div class="pop-empty">暂无排行数据</div>`}</div>
            <div class="rank-note">数值为周签约额（万元）；完成率按按天折算周目标计算。点击排行行不跳转，避免暴露未授权范围。</div>
          </div>
          <div class="card">${sectionHead("本周 vs 上周", "按当前数据范围与同跨度基期")}
            <div class="card-b" style="padding-top:4px"><div class="table-scroll no-min"><table class="data-table"><thead><tr><th>口径</th><th class="r">本周</th><th class="r">上周同期</th><th class="r">变化</th></tr></thead><tbody>
              <tr><td>签约额（万元）</td><td class="r">${num(report.comparison && report.comparison.current && report.comparison.current.sign_wan)}</td><td class="r">${num(report.comparison && report.comparison.previous && report.comparison.previous.sign_wan)}</td><td class="r ${report.comparison && report.comparison.contract_wow >= 0 ? "trend-up" : "trend-down"}">${signedPct(report.comparison && report.comparison.contract_wow)}</td></tr>
              <tr><td>新增线索</td><td class="r">${intNum(report.comparison && report.comparison.current && report.comparison.current.leads)}</td><td class="r">${intNum(report.comparison && report.comparison.previous && report.comparison.previous.leads)}</td><td class="r ${report.comparison && report.comparison.leads_wow >= 0 ? "trend-up" : "trend-down"}">${signedPct(report.comparison && report.comparison.leads_wow)}</td></tr>
              <tr><td>回款额（万元）</td><td class="r">${num(report.comparison && report.comparison.current && report.comparison.current.paid_wan)}</td><td class="r">${num(report.comparison && report.comparison.previous && report.comparison.previous.paid_wan)}</td><td class="r ${report.comparison && report.comparison.paid_wow >= 0 ? "trend-up" : "trend-down"}">${signedPct(report.comparison && report.comparison.paid_wow)}</td></tr>
            </tbody></table></div></div>
            <div class="rank-note">${esc((report.data_notes || [])[report.data_notes.length - 2] || "")}</div>
          </div>
        </div>
        <div class="card section-gap">${sectionHead("每日签约节奏", "柱高为签约额；括号为线索数")}
          <div class="card-b"><div class="day-bars-wrap" style="margin:0;padding:6px 0 0"><div class="day-bars">${daily.map((d) => `<div class="day-bar" title="${esc(d.date)} 签约 ${num(d.sign_wan)} 万元；目标 ${num(d.target_wan)} 万元；线索 ${intNum(d.leads)} 条"><b>${num(d.sign_wan, 0)}</b><i style="height:${Math.max(3, (Number(d.sign_wan) / maxSign) * 100)}%"></i><span>${esc(d.label)}</span></div>`).join("")}</div></div></div>
          <div class="rank-note">日目标为月目标按天折算；缺失数据不会以 0 代替。</div>
        </div>
        <div class="weekly-grid section-gap">
          <div class="card">${sectionHead("风险 Top3", "按级别与认领时限排序")} <div class="card-b" style="padding-top:4px"><div class="risk-mini">${(report.top_risks || []).length ? report.top_risks.map(riskMiniItem).join("") : `<div class="risk-zero">暂无未结束风险</div>`}</div></div></div>
          <div class="card">${sectionHead("动作建议", "来自风险处置或经营缺口")}<div class="card-b" style="padding-top:4px">${(report.actions || []).length ? `<ol class="action-list">${report.actions.map((a) => `<li>${a.risk_id ? `<a href="#/risks/${esc(a.risk_id)}" class="action-link" data-risk-link="${esc(a.risk_id)}">${esc(a.title)}</a>` : `<b>${esc(a.title)}</b>`}<div>${esc(a.text)}</div></li>`).join("")}</ol>` : `<div class="pop-empty">暂无动作建议</div>`}</div></div>
        </div>
        <div class="card section-gap">${sectionHead("数据说明", "周报口径与数据质量")}
          <div class="card-b"><ul class="data-note-list">${(report.data_notes || []).map((n) => `<li>${esc(n)}</li>`).join("")}</ul>
          <div class="source-strip"><span>${icon("info")}${esc(report.data_source || "")}</span><span>批次 ${esc(report.batch_id || "—")}</span></div></div>
        </div>
      </section>`;
    $$("[data-week]", content).forEach((btn) => btn.addEventListener("click", () => {
      state.weeklyType = btn.dataset.week;
      route(true);
    }));
    $$("[data-risk-link]", content).forEach((el) => el.addEventListener("click", (event) => {
      event.preventDefault(); openRiskRoute(el.dataset.riskLink);
    }));
  }

  // ---------------------------------------------------------------- 指标中心与下钻

  function metricCard(m, extraClass = "") {
    return `<button class="metric-card card ${extraClass}" data-metric="${esc(m.key)}" title="${esc(m.formula || "")}">
      <div class="m-label"><span>${esc(m.label)}</span><span>${esc(m.unit)}</span></div>
      <div class="m-value">${esc(m.display)}</div>
      <div class="m-formula">${esc(m.formula || "")}</div>
      <span class="m-link">查看下钻 →</span>
    </button>`;
  }

  async function renderMetrics(seq) {
    let data;
    try {
      data = await api("/api/metrics");
    } catch (err) {
      if (seq !== state.routeSeq) return;
      if (err.status === 401) return;
      content.innerHTML = pageError(err.message);
      bindRetry(content);
      return;
    }
    if (seq !== state.routeSeq) return;
    content.innerHTML = `
      <section class="page">
        <div class="page-head"><div><div class="eyebrow">METRICS · 服务端计算</div><h1>指标中心</h1>
          <p class="sub">12 项核心指标 + 辅助指标。金额万元保留 1 位小数，比率保留 1 位小数；目标缺失或无可计算分母时显示「—」。点击任一指标查看按组织或人员的下钻。</p>
          <div class="meta-line"><span>业务日期 ${esc(data.date)}</span><span class="sep">·</span><span>范围 ${esc(data.scope && data.scope.name)}</span><span class="sep">·</span><span>批次 ${esc(data.batch_id || "—")}</span><span class="sep">·</span><span>生成 ${shortTime(data.generated_at)}</span></div></div>
          <div class="head-actions"><span class="tag ${data.data_available ? "green" : "orange"}">${data.data_available ? "数据可用" : "当天无快照"}</span></div>
        </div>
        ${data.data_available ? "" : `<div class="page-error"><b>当天没有已发布的指标快照</b>${esc(data.message || "")}</div>`}
        <div class="metric-page-grid">${(data.metrics || []).map((m) => metricCard(m)).join("")}</div>
        <div class="card section-gap">${sectionHead("辅助指标", "用于解释核心指标，不替代 12 项主指标")}<div class="card-b"><div class="metric-page-grid">${(data.auxiliary || []).map((m) => metricCard(m, "aux-card")).join("")}</div></div></div>
        <div class="metric-note">口径提示：营销 ROI 的分子是当前范围的归因签约，分母是公司当月投放费用（投放源未按组织拆分）；线索/签约周环比为本周一至 D 对比上周同期。这些说明同时出现在日报的「数据说明」中。</div>
      </section>`;
    $$("[data-metric]", content).forEach((el) => el.addEventListener("click", () => openDrill(el.dataset.metric, data.date)));
  }

  async function openDrill(metricKey, dateValue) {
    openModal(`<div class="modal-head"><h3>指标下钻</h3><p>正在读取 ${esc(metricKey)} 的组织/人员明细…</p><button class="icon-btn modal-close" data-close-modal aria-label="关闭">${icon("close")}</button></div><div class="modal-body"><div class="loading-block">读取中…</div></div>`, null, true);
    try {
      const data = await api(`/api/metrics/${encodeURIComponent(metricKey)}/drill?date=${encodeURIComponent(dateValue)}`);
      const total = data.total || {};
      const items = data.items || [];
      const maxShare = Math.max(1, ...items.map((i) => Number(i.share) || 0));
      const modal = $(".modal", modalRoot);
      if (!modal) return;
      modal.querySelector(".modal-head p").textContent = `${data.metric.label} · ${data.date} · 范围 ${data.scope.name}`;
      modal.querySelector(".modal-body").innerHTML = `
        <div class="drill-top"><div class="drill-value">${esc(total.display)}</div><div class="drill-note"><span>${esc(total.label)} · ${esc(total.unit)}</span><span>按${data.drill_type === "org" ? "下级组织" : "人员"}拆分</span></div></div>
        <div class="drill-formula">${icon("info")}<span><b>口径：</b>${esc(total.formula || "—")}<br><b>来源：</b>${esc(total.source || "—")}</span></div>
        <div class="table-scroll no-min" style="margin-top:12px"><table class="drill-table"><thead><tr><th>${data.drill_type === "org" ? "组织" : "人员"}</th><th class="r">数值</th><th class="r">占比</th></tr></thead><tbody>
          ${items.length ? items.map((i) => `<tr><td>${esc(i.name)}${i.title ? `<div class="why-note">${esc(i.title)}</div>` : ""}</td><td>${esc(i.display)}</td><td><span class="rate">${i.share === null ? "—" : `<i><b style="width:${Math.max(2, (i.share / maxShare) * 100)}%"></b></i>${num(i.share)}%`}</span></td></tr>`).join("") : `<tr><td colspan="3">${emptyState("没有可下钻的数据", "当前范围内不满足下钻条件。")}</td></tr>`}
        </tbody></table></div>
        <div class="modal-note" style="margin-top:12px">${data.data_available ? "数据来自服务端指标计算，不在浏览器本地推算。" : "当天没有可用快照。"}</div>`;
      const closeBtn = modal.querySelector(".modal-close");
      if (closeBtn) closeBtn.addEventListener("click", closeModal);
    } catch (err) {
      if (err.status === 401) return;
      const modal = $(".modal", modalRoot);
      if (modal) modal.querySelector(".modal-body").innerHTML = `<div class="page-error"><b>下钻读取失败</b>${esc(err.message)}</div>`;
    }
  }

  // ---------------------------------------------------------------- 数据质量

  function checkIcon(status) {
    return status === "pass" ? "check" : (status === "warn" ? "info" : "risk");
  }

  function affectedMetricLabel(item) {
    if (item && item.label) return item.label;
    if (item && Array.isArray(item.metrics) && item.metrics.length) return item.metrics.join("、");
    return (item && item.key) || "受影响指标";
  }

  function batchStepSummary(step) {
    if (step.status === "failed") return step.error || "步骤失败";
    const s = step.stats || {};
    const map = {
      extract: () => `源数据 ${Object.keys(s.row_counts || {}).length} 个文件，已校验入库`,
      metrics: () => `${intNum(s.snapshots)} 条指标快照`,
      quality: () => `得分 ${num(s.score)}，异常指标 ${intNum(s.affected_metrics)} 个`,
      risks: () => `新建 ${intNum(s.created)} 条，合并 ${intNum(s.merged)} 条，触发 ${intNum(s.triggered)} 条`,
      daily: () => `${intNum(s.briefs)} 份日报`,
      weekly: () => `${intNum(s.reports)} 份周报`,
      publish: () => `${intNum(s.daily_briefs)} 份日报、${intNum(s.weekly_reports)} 份周报已发布`,
      notify: () => `风险通知 ${intNum(s.risk_notifications)} 条，简报通知 ${intNum(s.brief_notifications)} 条`,
      escalation: () => `自动升级 ${intNum(s.escalated)} 条`,
    };
    return map[step.step] ? map[step.step]() : (step.error || "—");
  }

  async function renderQuality(seq) {
    let report;
    try {
      report = await api("/api/quality");
    } catch (err) {
      if (seq !== state.routeSeq) return;
      if (err.status === 401) return;
      content.innerHTML = pageError(err.message);
      bindRetry(content);
      return;
    }
    if (seq !== state.routeSeq) return;
    const checks = report.checks || [];
    const completeness = report.completeness || {};
    const sources = completeness.by_source || [];
    const batch = report.batch || {};
    const statusText = { pass: "全部检查通过", warn: "存在提示", fail: "存在阻断问题" }[report.status] || report.status;
    content.innerHTML = `
      <section class="page">
        <div class="page-head"><div><div class="eyebrow">DATA QUALITY · 批处理检查</div><h1>数据质量</h1>
          <p class="sub">每次批处理都会检查字段完整性、主键重复、目标覆盖、组织/负责人映射与源文件完整性。检查不通过时批处理停止发布，保留上一份可用快照。</p>
          <div class="meta-line"><span>业务日期 ${esc(report.as_of)}</span><span class="sep">·</span><span>批次 ${esc(report.batch_id || "—")}</span><span class="sep">·</span><span>完成 ${shortTime(batch.finished_at || report.generated_at)}</span><span class="sep">·</span><span>耗时 ${batch.duration_seconds !== null && batch.duration_seconds !== undefined ? `${num(batch.duration_seconds, 2)} 秒` : "—"}</span></div></div>
          <div class="head-actions"><span class="tag ${report.status === "pass" ? "green" : (report.status === "warn" ? "orange" : "red")}">${esc(statusText)}</span></div>
        </div>
        <div class="quality-hero">
          <div class="card quality-score"><div class="q-status">质量得分</div><div class="q-num">${report.score === null || report.score === undefined ? "未评分" : `${num(report.score)}<small> / 100</small>`}</div><div class="q-note">${esc(report.summary && report.summary.message || statusText)}</div>
            <div class="meta-line" style="margin-top:10px"><span class="tag ${report.status === "pass" ? "green" : "orange"}">${esc(statusText)}</span></div></div>
          <div class="card">${sectionHead("五项检查", `错误 ${report.summary && report.summary.errors || 0} 项 · 提示 ${report.summary && report.summary.warnings || 0} 项`)}
            <div class="quality-checks">${checks.map((c) => `<div class="q-check ${esc(c.status)}"><span class="qi">${icon(checkIcon(c.status))}</span><div><b>${esc(c.label)}：${esc(c.value)}</b><p>${esc(c.detail)}</p></div></div>`).join("")}</div>
          </div>
        </div>
        <div class="weekly-grid">
          <div class="card">${sectionHead("完整性明细", `检查 ${intNum(completeness.checked_cells)} 个必填单元格，缺失 ${intNum(completeness.missing_cells)} 个`)}
            <div class="card-b" style="padding-top:4px">${sources.map((s) => `<div class="completeness-row"><span style="width:120px">${esc(s.source)}</span><span class="muted" style="width:64px">${intNum(s.rows)} 行</span><span class="cb"><i style="width:${Math.max(0, Math.min(100, Number(s.score) || 0))}%"></i></span><span style="width:66px;text-align:right">${num(s.score)}%</span></div>`).join("")}</div>
          </div>
          <div class="card">${sectionHead("影响范围", "质量异常会标注相关指标；不会用 0 补齐")}
            <div class="card-b" style="padding-top:4px">
              ${(report.affected_metrics || []).length ? `<ul class="impact-list">${report.affected_metrics.map((m) => `<li><b>${esc(affectedMetricLabel(m))}</b>：${esc(m.reason || "受影响，展示需谨慎")}</li>`).join("")}</ul>` : `<div class="pop-empty">没有指标受影响</div>`}
              <div class="source-batch" style="margin-top:10px">${(report.missing_sources || []).length ? `缺失源文件：${report.missing_sources.map(esc).join("、")}` : `${intNum((sources || []).length)} 个源文件齐全。`}<br>目标覆盖：组织 ${intNum(report.targets && report.targets.orgs_with_target)} / ${intNum(report.targets && report.targets.orgs_total)}；销售个人 ${intNum(report.targets && report.targets.sales_users_with_target)} / ${intNum(report.targets && report.targets.sales_users_total)}。<br>映射失败：${intNum(report.mapping && report.mapping.count)} 条。</div>
            </div>
          </div>
        </div>
        <div class="card section-gap">${sectionHead("批次步骤", "批处理按真实依赖顺序执行；同日重跑幂等")}
          <div class="card-b" style="padding-top:4px"><div class="table-scroll"><table class="data-table batch-steps"><thead><tr><th>步骤</th><th>状态</th><th class="r">耗时(ms)</th><th>说明</th></tr></thead><tbody>
            ${(batch.steps || []).map((s) => `<tr><td class="name">${esc(s.label || s.step)}</td><td><span class="tag ${s.status === "success" ? "green" : "red"}">${esc(s.status)}</span></td><td class="r">${intNum(s.duration_ms)}</td><td>${esc(batchStepSummary(s))}</td></tr>`).join("") || `<tr><td colspan="4">${emptyState("暂无步骤记录", "批次信息尚未回写。")}</td></tr>`}
          </tbody></table></div></div>
        </div>
      </section>`;
  }

  // ---------------------------------------------------------------- 预警规则

  const PARAM_LABELS = {
    yellow_gap_pp: "黄色缺口阈值（百分点）", orange_gap_pp: "橙色缺口阈值（百分点）", red_gap_pp: "红色缺口阈值（百分点）",
    orange_drop_pct: "橙色下降阈值（%）", red_drop_pct: "红色下降阈值（%）", workdays: "观察工作日数",
    volume_drop_pct: "线索量下降阈值（%）", conversion_drop_pct: "转化率相对下降阈值（%）",
    min_coverage: "最低覆盖率（倍）", min_amount: "最低开放商机金额（元）", days_no_followup: "未跟进天数",
    min_cancel_amount: "最低取消金额（元）", overdue_days: "逾期天数",
  };

  function ruleThresholdText(rule) {
    const p = rule.params || {};
    if (rule.rule_id === "target_gap") return `缺口 ≥ ${p.yellow_gap_pp}pp 黄色 / ≥ ${p.orange_gap_pp}pp 橙色 / ≥ ${p.red_gap_pp}pp 红色`;
    if (rule.rule_id === "decline") return `连续 ${p.workdays} 个工作日；两段均 ≥ ${p.orange_drop_pct}% 橙色，均 ≥ ${p.red_drop_pct}% 红色`;
    if (rule.rule_id === "leads") return `线索量下降 ≥ ${p.volume_drop_pct}% 橙色；转化率相对下降 ≥ ${p.conversion_drop_pct}% 黄色`;
    if (rule.rule_id === "coverage") return `开放管道 ÷ 剩余目标 < ${p.min_coverage} 倍 橙色`;
    if (rule.rule_id === "churn") return `开放商机 ≥ ${intNum(p.min_amount)} 元且 ${p.days_no_followup} 天未跟进 红色`;
    if (rule.rule_id === "payment") return `取消 ≥ ${intNum(p.min_cancel_amount)} 元 或 应收逾期 ≥ ${p.overdue_days} 天 红色`;
    return JSON.stringify(p);
  }

  function ruleParamDisplay(key, value) {
    if (key === "min_amount" || key === "min_cancel_amount") return `${num(Number(value) / 10000)} 万元`;
    return value;
  }

  function ruleLevelValue(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    return n.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  }

  function ruleLevels(rule) {
    const p = rule.params || {};
    const v = ruleLevelValue;
    if (rule.rule_id === "target_gap") {
      return `<span class="rl yellow"><b>黄</b> ≥${v(p.yellow_gap_pp)}pp</span><span class="rl orange"><b>橙</b> ≥${v(p.orange_gap_pp)}pp</span><span class="rl red"><b>红</b> ≥${v(p.red_gap_pp)}pp</span>`;
    }
    if (rule.rule_id === "decline") {
      return `<span class="rl orange"><b>橙</b> ≥${v(p.orange_drop_pct)}%</span><span class="rl red"><b>红</b> ≥${v(p.red_drop_pct)}%</span>`;
    }
    if (rule.rule_id === "leads") {
      return `<span class="rl yellow"><b>黄</b> 转化率↓≥${v(p.conversion_drop_pct)}%</span><span class="rl orange"><b>橙</b> 线索量↓≥${v(p.volume_drop_pct)}%</span>`;
    }
    if (rule.rule_id === "coverage") {
      return `<span class="rl orange"><b>橙</b> 覆盖率 &lt;${v(p.min_coverage)} 倍</span>`;
    }
    if (rule.rule_id === "churn") {
      return `<span class="rl red"><b>红</b> ≥${ruleLevelValue(Number(p.min_amount) / 10000)} 万元 / ${v(p.days_no_followup)} 天</span>`;
    }
    if (rule.rule_id === "payment") {
      return `<span class="rl red"><b>红</b> 取消≥${ruleLevelValue(Number(p.min_cancel_amount) / 10000)} 万元 / 逾期≥${v(p.overdue_days)} 天</span>`;
    }
    return `<span class="rl red"><b>红</b> 高优先级</span>`;
  }

  async function renderRules(seq) {
    let data;
    try {
      data = await api("/api/rules");
    } catch (err) {
      if (seq !== state.routeSeq) return;
      if (err.status === 401) return;
      content.innerHTML = pageError(err.message);
      bindRetry(content);
      return;
    }
    if (seq !== state.routeSeq) return;
    const editable = data.can_edit;
    content.innerHTML = `
      <section class="page">
        <div class="page-head"><div><div class="eyebrow">ALERT RULES · 六类规则</div><h1>预警规则</h1>
          <p class="sub">规则阈值与启停只影响下一次批处理，历史风险不会被改写。仅公司总经理可以修改；其他角色只读。每次修改都会写审计日志。</p>
          <div class="meta-line"><span>${editable ? "你是总经理，可编辑" : "当前角色只读"}</span><span class="sep">·</span><span>规则 ${data.total} 条</span><span class="sep">·</span><span>修改后需重跑批处理才会影响风险识别</span></div></div>
          <div class="head-actions"><span class="tag ${editable ? "green" : "gray"}">${editable ? "可编辑" : "只读"}</span></div>
        </div>
        <div class="rules-grid">
          <div class="rule-list">${(data.items || []).map((rule) => `
            <div class="rule-card ${rule.enabled ? "" : "off"}" data-rule="${esc(rule.rule_id)}">
              <span class="rule-ico">${icon(rule.rule_id === "payment" ? "money" : (rule.rule_id === "churn" ? "user" : (rule.rule_id === "leads" ? "leads" : "risk")))}</span>
              <div class="rule-main"><div class="rule-title">${esc(rule.name)} <span class="tag ${rule.enabled ? "green" : "gray"}">${rule.enabled ? "启用" : "停用"}</span></div>
                <div class="rule-desc">${esc(rule.description)}</div>
                <div class="rule-threshold">${icon("filter")}${esc(ruleThresholdText(rule))}</div>
                <div class="rule-levels">${ruleLevels(rule)}</div>
                <div class="rule-params">${Object.entries(rule.params || {}).map(([k, v]) => `<span class="rule-param">${esc(PARAM_LABELS[k] || k)}：${esc(ruleParamDisplay(k, v))}</span>`).join("")}</div>
              </div>
              <div class="rule-actions">
                <button class="switch ${rule.enabled ? "on" : ""}" data-rule-toggle="${esc(rule.rule_id)}" role="switch" aria-checked="${rule.enabled}" aria-label="启用或停用 ${esc(rule.name)}" ${editable ? "" : "disabled"}></button>
                ${editable ? `<button class="link rule-edit" data-rule-edit="${esc(rule.rule_id)}">调整阈值 →</button>` : `<span class="muted" style="font-size:9px">只读</span>`}
              </div>
            </div>`).join("")}
          </div>
          <div>
            <div class="card side-card"><h4>执行说明</h4><div class="sc-sub">批处理按目标缺口 → 业绩下滑 → 线索异常 → 商机覆盖 → 大客户流失 → 订单/回款的顺序执行；同一对象 + 同一规则 24 小时内合并，同日重跑不新建、不重复事件。</div>
              <div class="sc-row"><span>阈值生效时点</span><b>下一次批处理</b></div>
              <div class="sc-row"><span>历史风险</span><b>保持原样</b></div>
              <div class="sc-row"><span>修改权限</span><b>仅总经理</b></div>
              <div class="sc-row"><span>审计</span><b>自动记录</b></div>
            </div>
            <div class="card side-card"><h4>角色权限</h4><div class="sc-sub">所有列表、详情、导出都在服务端按组织子树过滤。</div>
              <div class="perm-list"><div class="perm-item"><i class="perm-dot"></i>总经理 <small>全公司 · 可改规则</small></div><div class="perm-item"><i class="perm-dot"></i>销售总监 <small>全公司 · 只读规则</small></div><div class="perm-item"><i class="perm-dot"></i>事业部总经理 <small>本事业部及下级</small></div><div class="perm-item"><i class="perm-dot"></i>部门销售经理 <small>本部门及本人</small></div></div>
            </div>
            ${editable ? "" : `<div class="card side-card"><div class="rule-readonly-note">切换按钮和调参入口对当前角色隐藏/禁用；如果直接调用接口，服务端会返回 403 并写入越权审计。</div></div>`}
          </div>
        </div>
      </section>`;
    $$("[data-rule-toggle]", content).forEach((btn) => btn.addEventListener("click", () => toggleRule(btn)));
    $$("[data-rule-edit]", content).forEach((btn) => btn.addEventListener("click", () => {
      const rule = (data.items || []).find((x) => x.rule_id === btn.dataset.ruleEdit);
      if (rule) openRuleEditor(rule);
    }));
  }

  async function toggleRule(btn) {
    const ruleId = btn.dataset.ruleToggle;
    const next = !btn.classList.contains("on");
    btn.disabled = true;
    try {
      await api(`/api/rules/${encodeURIComponent(ruleId)}`, { method: "PATCH", body: JSON.stringify({ enabled: next }) });
      toast(next ? "规则已启用，下次批处理生效" : "规则已停用，下次批处理生效");
      route(true);
    } catch (err) {
      btn.disabled = false;
      toast(err.message, "err");
    }
  }

  function openRuleEditor(rule) {
    const fields = Object.entries(rule.params || {}).map(([key, value]) => `
      <div class="form-row"><label>${esc(PARAM_LABELS[key] || key)}</label><input type="number" step="any" min="0.01" name="${esc(key)}" value="${esc(value)}" required></div>`).join("");
    formModal({
      title: `调整规则阈值：${rule.name}`,
      subtitle: "参数修改只影响下一次批处理。请确认阈值口径后再保存。",
      body: `<div class="rule-edit-grid">${fields}</div><div class="modal-note">${esc(rule.description)}<br>修改后历史风险不会被追溯改写；保存会写审计日志。</div>`,
      submitLabel: "保存阈值",
      onSubmit: async (fd) => {
        const params = {};
        for (const key of Object.keys(rule.params || {})) {
          const raw = fd.get(key);
          const value = Number(raw);
          if (!Number.isFinite(value) || value <= 0) throw new Error(`${PARAM_LABELS[key] || key} 必须是大于 0 的数字`);
          params[key] = value;
        }
        await api(`/api/rules/${encodeURIComponent(rule.rule_id)}`, { method: "PATCH", body: JSON.stringify({ params }) });
        toast("规则阈值已保存，下次批处理生效");
        route(true);
      },
    });
  }

  // ---------------------------------------------------------------- 消息中心

  function notifyIcon(kind) {
    if (kind === "risk") return "risk";
    if (kind === "escalation") return "trend";
    if (kind === "assignment") return "user";
    return "bell";
  }

  async function renderNotifications(seq) {
    let data;
    try {
      data = await api(`/api/notifications?page=${state.notifyPage}&page_size=50`);
    } catch (err) {
      if (seq !== state.routeSeq) return;
      if (err.status === 401) return;
      content.innerHTML = pageError(err.message);
      bindRetry(content);
      return;
    }
    if (seq !== state.routeSeq) return;
    content.innerHTML = `
      <section class="page">
        <div class="page-head"><div><div class="eyebrow">INBOX · 站内消息</div><h1>消息中心</h1>
          <p class="sub">风险生成、转派、升级与今日简报发布都会写入当前账号的站内消息。消息按当前登录人过滤，不能查看他人消息。</p>
          <div class="meta-line"><span>共 ${intNum(data.total)} 条</span><span class="sep">·</span><span>未读 ${intNum(data.unread)} 条</span><span class="sep">·</span><span>消息只保留在本地 SQLite</span></div></div>
          <div class="head-actions"><button class="btn sm" id="markAllRead" ${data.unread ? "" : "disabled"}>${icon("check")}<span>全部标为已读</span></button></div>
        </div>
        <div class="card table-card">
          <div class="msg-toolbar"><span>${data.unread ? `你有 ${data.unread} 条未读消息` : "所有消息已读"}</span><span>点击消息查看关联对象</span></div>
          <div class="msg-list" id="msgList">${(data.items || []).length ? data.items.map((n) => `
            <div class="msg-item ${n.is_read ? "" : "unread"}" data-notification="${Number(n.id)}" tabindex="0" role="button">
              <span class="msg-ico ${esc(n.kind)}">${icon(notifyIcon(n.kind))}</span>
              <span class="msg-main"><b>${esc(n.title)}</b><p>${esc(n.body)}</p></span>
              <span class="msg-time">${shortTime(n.created_at)}</span>
              ${n.is_read ? "" : `<span class="msg-unread-dot" aria-label="未读"></span>`}
            </div>`).join("") : emptyState("暂无消息", "新的风险、升级或简报会出现在这里。")}</div>
          ${data.total > 50 ? `<div class="pager"><span>共 ${data.total} 条，仅显示最近 50 条</span></div>` : ""}
        </div>
      </section>`;
    const items = data.items || [];
    $$("[data-notification]", content).forEach((el) => {
      const item = items.find((x) => String(x.id) === el.dataset.notification);
      if (!item) return;
      const open = () => openNotification(item);
      el.addEventListener("click", open);
      el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
    });
    const markAll = $("#markAllRead");
    if (markAll) markAll.addEventListener("click", async () => {
      markAll.disabled = true;
      try {
        await api("/api/notifications/read-all", { method: "POST" });
        toast("所有消息已标为已读");
        refreshShellData();
        route(true);
      } catch (err) { markAll.disabled = false; toast(err.message, "err"); }
    });
  }

  async function openNotification(item) {
    try {
      if (!item.is_read) {
        await api(`/api/notifications/${encodeURIComponent(item.id)}/read`, { method: "POST" });
        item.is_read = true;
        refreshShellData();
      }
    } catch (err) {
      toast(err.message, "err");
      return;
    }
    if (item.related_risk_id) {
      openRiskRoute(item.related_risk_id);
      return;
    }
    if (item.link && item.link.startsWith("#/brief")) {
      navigate("brief");
      return;
    }
    if (state.routePage === "notifications") route(true);
  }

  // ---------------------------------------------------------------- 导出中心

  async function renderExports(seq) {
    const date = (state.currentBrief && state.currentBrief.date) || "2026-10-24";
    content.innerHTML = `
      <section class="page">
        <div class="page-head"><div><div class="eyebrow">EXPORT · 演示水印</div><h1>导出中心</h1>
          <p class="sub">所有导出由服务端生成，并按当前登录角色做行级过滤。Excel 与打印页均带「演示数据·禁止外传」水印；每次导出和打印都会写审计日志。</p>
          <div class="meta-line"><span>业务日期 ${esc(date)}</span><span class="sep">·</span><span>范围 ${esc(state.me.scope.label)}</span><span class="sep">·</span><span>文件格式：xlsx / 可打印 HTML</span></div></div>
        </div>
        <div class="export-grid">
          <div class="card export-card"><span class="export-ico">${icon("brief")}</span><h3>日报 Excel</h3>
            <p>包含 6 张指标卡、3 条结论、风险 Top3、渠道表现和数据说明。金额单位为万元、比率 1 位小数。</p>
            <div class="watermark-note">导出文件带「演示数据·禁止外传」水印；不包含未授权组织的数据。</div>
            <div class="head-actions"><button class="btn sm primary" id="exportBriefBtn">${icon("download")}<span>下载日报</span></button></div>
          </div>
          <div class="card export-card"><span class="export-ico">${icon("risk")}</span><h3>风险清单 Excel</h3>
            <p>导出当前账号可见的风险，含编号、级别、类型、责任人（脱敏）、金额、状态与 SLA。默认导出未结束风险，可在风险中心按筛选导出。</p>
            <div class="watermark-note">最多 1,000 条；手机号与邮箱保持脱敏。</div>
            <div class="head-actions"><button class="btn sm" id="exportRiskBtn">${icon("download")}<span>下载未结束风险</span></button>
              <button class="btn sm" id="exportRiskAllBtn">${icon("download")}<span>下载全部</span></button></div>
          </div>
          <div class="card export-card"><span class="export-ico">${icon("brief")}</span><h3>打印版日报</h3>
            <p>服务端生成适合 A4 的 HTML，浏览器可直接打印或另存为 PDF。打印页有固定水印和演示提示。</p>
            <div class="watermark-note">打印动作会写审计日志；页面不包含手机端布局。</div>
            <div class="head-actions"><button class="btn sm" id="printBriefBtn">${icon("brief")}<span>打开打印页</span></button></div>
          </div>
          <div class="card export-card"><span class="export-ico">${icon("shield")}</span><h3>使用边界</h3>
            <p>本 MVP 使用本地演示数据，不是生产报表，不连接真实 CRM/ERP。导出仅用于评审演示，请勿外传。</p>
            <div class="watermark-note">演示登录不是生产认证；切换账号即可查看不同数据范围。</div>
            <div class="head-actions"><a class="btn sm" href="/docs" target="_blank" rel="noopener">${icon("info")}<span>查看接口文档</span></a></div>
          </div>
        </div>
      </section>`;
    const doDownload = (url, name) => confirmDialog({
      title: "确认导出",
      body: `<div class="confirm-copy">即将从服务端生成并下载文件。<ul><li>文件带「演示数据·禁止外传」水印。</li><li>仅包含当前账号有权查看的数据。</li><li>本次导出会写审计日志。</li></ul></div>`,
      confirmLabel: "确认下载",
      onConfirm: async () => { const filename = await downloadFile(url, name); toast(`已开始下载：${filename}`); },
    });
    $("#exportBriefBtn").addEventListener("click", () => doDownload(`/api/export/brief.xlsx?date=${encodeURIComponent(date)}`, `brief_${date}.xlsx`));
    $("#exportRiskBtn").addEventListener("click", () => doDownload("/api/export/risks.xlsx?status=active", "risks_active.xlsx"));
    $("#exportRiskAllBtn").addEventListener("click", () => doDownload("/api/export/risks.xlsx", "risks_all.xlsx"));
    $("#printBriefBtn").addEventListener("click", () => confirmDialog({
      title: "打开打印版日报",
      body: `<div class="confirm-copy">打印页由服务端生成，带水印，可直接打印或另存为 PDF。</div>`,
      confirmLabel: "打开打印页",
      onConfirm: async () => { window.open(`/api/print/brief?date=${encodeURIComponent(date)}`, "_blank", "noopener"); toast("已打开打印页"); },
    }));
  }

  // ---------------------------------------------------------------- 审计

  async function renderAudit(seq) {
    if (state.me.role !== "gm") {
      content.innerHTML = `<div class="page-error"><b>无权查看审计</b>审计日志只对总经理开放。服务端会再校验一次角色；越权请求会返回 403 并记录。</div>`;
      return;
    }
    contentLoading("正在加载审计日志…");
    let data;
    try {
      const params = new URLSearchParams({ limit: "100" });
      if (state.auditAction) params.set("action", state.auditAction);
      data = await api(`/api/audit?${params.toString()}`);
    } catch (err) {
      if (seq !== state.routeSeq) return;
      if (err.status === 401) return;
      content.innerHTML = pageError(err.message);
      bindRetry(content);
      return;
    }
    if (seq !== state.routeSeq) return;
    content.innerHTML = `
      <section class="page">
        <div class="page-head"><div><div class="eyebrow">AUDIT · 仅总经理可见</div><h1>审计日志</h1>
          <p class="sub">登录、查看日报、查看风险、导出、打印、认领、转派、关闭、规则修改和越权 403 都会写审计。按时间倒序显示最近 100 条。</p>
          <div class="meta-line"><span>共 ${intNum(data.total)} 条</span><span class="sep">·</span><span>当前筛选 ${esc(state.auditAction || "全部")}</span><span class="sep">·</span><span>仅显示最近 100 条</span></div></div>
        </div>
        <div class="card table-card">
          <div class="audit-filter"><input id="auditAction" type="search" placeholder="按动作筛选，例如 risk.claim" value="${esc(state.auditAction)}"><button class="btn sm" id="auditApply">${icon("filter")}筛选</button><button class="filter-reset" id="auditReset">清除</button></div>
          <div class="table-scroll"><table class="data-table audit-table"><thead><tr><th>时间</th><th>操作人</th><th>动作</th><th>对象</th><th>详情</th><th>IP</th></tr></thead><tbody>
            ${(data.items || []).length ? data.items.map((a) => `<tr><td class="time">${shortTime(a.created_at)}</td><td>${esc(a.user_name || a.user_id || "系统")}</td><td><code style="font-size:10px">${esc(a.action)}</code></td><td>${esc(a.resource_type)}${a.resource_id ? ` · ${esc(a.resource_id)}` : ""}</td><td class="audit-detail">${esc(a.detail)}</td><td>${esc(a.ip || "—")}</td></tr>`).join("") : `<tr><td colspan="6">${emptyState("暂无审计记录", "执行登录、查看、导出或处置后会生成记录。")}</td></tr>`}
          </tbody></table></div>
        </div>
      </section>`;
    $("#auditApply").addEventListener("click", () => { state.auditAction = $("#auditAction").value.trim(); route(true); });
    $("#auditAction").addEventListener("keydown", (e) => { if (e.key === "Enter") { state.auditAction = e.target.value.trim(); route(true); } });
    $("#auditReset").addEventListener("click", () => { state.auditAction = ""; route(true); });
  }

  // ---------------------------------------------------------------- 弹窗

  function openModal(html, onMount = null, wide = false) {
    modalRoot.innerHTML = `<div class="modal ${wide ? "wide" : ""}" role="dialog" aria-modal="true" tabindex="-1">${html}</div>`;
    modalRoot.classList.add("open");
    syncScrollLock();
    const modal = $(".modal", modalRoot);
    $$("[data-close-modal]", modalRoot).forEach((btn) => btn.addEventListener("click", closeModal));
    modalRoot.onclick = (event) => { if (event.target === modalRoot) closeModal(); };
    if (onMount) onMount(modalRoot);
    setTimeout(() => { const focusable = $("textarea, input, select, button", modal); if (focusable) focusable.focus(); }, 30);
  }

  function closeModal() {
    modalRoot.classList.remove("open");
    modalRoot.innerHTML = "";
    syncScrollLock();
  }

  function confirmDialog({ title, body, confirmLabel = "确认", onConfirm }) {
    openModal(`
      <div class="modal-head"><h3>${esc(title)}</h3><button class="icon-btn modal-close" data-close-modal aria-label="关闭">${icon("close")}</button></div>
      <div class="modal-body">${body}<div class="form-error modal-error" role="alert"></div></div>
      <div class="modal-foot"><div class="spacer"></div><button class="btn" type="button" data-close-modal>取消</button><button class="btn primary" type="button" id="confirmAction">${esc(confirmLabel)}</button></div>`, (root) => {
      const btn = $("#confirmAction", root);
      btn.addEventListener("click", async () => {
        const errBox = $(".modal-error", root);
        errBox.classList.remove("show");
        btn.disabled = true;
        const original = btn.textContent;
        btn.textContent = "处理中…";
        try {
          await onConfirm();
          closeModal();
        } catch (err) {
          errBox.textContent = err.message;
          errBox.classList.add("show");
        } finally {
          btn.disabled = false;
          btn.textContent = original;
        }
      });
    });
  }

  // ---------------------------------------------------------------- 全局事件

  function bindGlobalEvents() {
    document.addEventListener("click", (event) => {
      const pageBtn = event.target.closest("[data-page]");
      if (pageBtn) {
        event.preventDefault();
        navigate(pageBtn.dataset.page);
        return;
      }
      const retry = event.target.closest("[data-retry]");
      if (retry) route(true);
      if (!event.target.closest(".role-wrap")) roleMenu.classList.remove("open");
      if (!event.target.closest(".pop-wrap")) notifyPop.classList.remove("open");
    });

    $("#roleBtn").addEventListener("click", (event) => {
      event.stopPropagation();
      const open = roleMenu.classList.toggle("open");
      $("#roleBtn").setAttribute("aria-expanded", String(open));
      notifyPop.classList.remove("open");
      $("#bellBtn").setAttribute("aria-expanded", "false");
    });
    $("#bellBtn").addEventListener("click", async (event) => {
      event.stopPropagation();
      const open = notifyPop.classList.toggle("open");
      $("#bellBtn").setAttribute("aria-expanded", String(open));
      roleMenu.classList.remove("open");
      if (open) await refreshShellData();
    });
    $("#logoutBtn").addEventListener("click", logout);
    $("#refreshBtn").addEventListener("click", async () => {
      await refreshShellData();
      await route(true);
      toast("已刷新当前页面数据");
    });
    drawerMask.addEventListener("click", () => closeDrawer(true));
    $("#loginUsers").addEventListener("click", (event) => {
      const retry = event.target.closest("[data-retry]");
      if (retry) loadDemoUsers();
    });
    window.addEventListener("hashchange", () => route(true));
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      if (modalRoot.classList.contains("open")) { closeModal(); return; }
      if (drawer.classList.contains("open")) { closeDrawer(true); return; }
      roleMenu.classList.remove("open");
      notifyPop.classList.remove("open");
    });
  }

  async function init() {
    bindGlobalEvents();
    showLogin("");
    await Promise.all([loadDemoUsers(), checkSession()]);
  }

  init();
})();
