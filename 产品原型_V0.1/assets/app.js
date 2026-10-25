/* 经营简报 · 交互原型逻辑（无后端，全部为模拟数据） */
(function () {
  'use strict';

  var D = window.DEMO;
  var content = document.getElementById('content');
  var drawer = document.getElementById('drawer');
  var drawerMask = document.getElementById('drawerMask');
  var modalRoot = document.getElementById('modalRoot');
  var phoneOverlay = document.getElementById('phoneOverlay');
  var toastWrap = document.getElementById('toastWrap');
  var navBadge = document.getElementById('navRiskBadge');

  var state = {
    role: 'gm',
    page: 'brief',
    level: 'all',
    status: 'all',
    type: 'all',
    owner: 'all',
    q: '',
    sortKey: 'level',
    sortDir: 'desc',
    week: 'this',
    trendView: 'chart',
    phoneTab: 'brief'
  };

  var RISKS = JSON.parse(JSON.stringify(D.RISKS));
  RISKS.forEach(function (r) { r.events = []; });
  var currentRiskId = null;
  var chartSeq = 0;

  var LEVELS = {
    red: { label: '红色', cls: 'red', weight: 3 },
    orange: { label: '橙色', cls: 'orange', weight: 2 },
    yellow: { label: '黄色', cls: 'yellow', weight: 1 }
  };
  var PAGE_NAMES = { brief: '今日简报', risks: '风险中心', weekly: '周报复盘', rules: '预警规则' };
  var PAGE_ICONS = { brief: 'brief', risks: 'risk', weekly: 'weekly', rules: 'rules' };
  var TREND_LABELS = ['10/11', '10/12', '10/13', '10/14', '10/15', '10/16', '10/17', '10/18', '10/19', '10/20', '10/21', '10/22', '10/23', '10/24'];

  var RULE_ICONS = { target: 'target', trend: 'trend', leads: 'leads', cover: 'cover', user: 'user', money: 'money' };
  var stateRules = D.RULES.map(function (r) { return Object.assign({}, r); });

  /* ---------------- 基础工具 ---------------- */
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function fmt(n, d) {
    d = d == null ? 0 : d;
    return Number(n).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function icon(name, cls) {
    return '<svg class="ic ' + (cls || '') + '" aria-hidden="true"><use href="#i-' + name + '"></use></svg>';
  }
  function curRole() { return D.ROLES[state.role]; }
  function roleFactor() { return curRole().kpi.sign[0] / 428.6; }
  function money(v) { return v ? fmt(v, 0) + ' 万' : '—'; }
  function kpiSub(key) {
    var v = curRole().kpi[key][0];
    if (key === 'sign') return '日目标 ' + fmt(trendTarget()) + ' 万';
    if (key === 'rate') return '时间进度 80.0%';
    if (key === 'leads') return '有效线索 ' + fmt(Math.round(v * 0.66)) + ' 条';
    if (key === 'roi') return '近 90 天归因口径';
    if (key === 'cover') return '健康线 ≥ 3.0 倍';
    return '逾期应收 ' + fmt(Math.round(1240 * roleFactor())) + ' 万';
  }
  function levelOf(r) { return LEVELS[r.level] || LEVELS.yellow; }
  function statusCls(s) {
    return s === '待认领' ? 'wait' : s === '处理中' ? 'doing' : s === '已超时' ? 'late' : 'done';
  }
  var DELTA_BASE = { sign: '较昨日', rate: '较进度', leads: '较昨日', roi: '较上周', cover: '较红线', collect: '较上周' };
  function deltaHTML(arr, key) {
    var dir = arr[2] === 'up' ? '↑' : '↓';
    var base = key && DELTA_BASE[key] ? '<em>' + DELTA_BASE[key] + '</em>' : '';
    return '<span class="delta ' + arr[3] + '">' + base + dir + ' ' + esc(arr[1]) + '</span>';
  }
  function todayLine() { return '2026 年 10 月 24 日 · 星期六'; }

  function visibleRisks() {
    return RISKS.filter(function (r) { return r.visibleTo.indexOf(state.role) > -1; });
  }
  function openRisks() {
    return visibleRisks().filter(function (r) { return r.status !== '已关闭'; });
  }
  function riskById(id) {
    for (var i = 0; i < RISKS.length; i++) { if (RISKS[i].id === id) return RISKS[i]; }
    return null;
  }

  function filteredRisks() {
    var arr = visibleRisks();
    if (state.level !== 'all') arr = arr.filter(function (r) { return r.level === state.level; });
    if (state.status !== 'all') arr = arr.filter(function (r) { return r.status === state.status; });
    if (state.type !== 'all') arr = arr.filter(function (r) { return r.type === state.type; });
    if (state.owner !== 'all') arr = arr.filter(function (r) { return r.owner === state.owner; });
    var q = state.q.trim().toLowerCase();
    if (q) {
      arr = arr.filter(function (r) {
        return (r.title + r.object + r.owner + r.id + r.type).toLowerCase().indexOf(q) > -1;
      });
    }
    var key = state.sortKey;
    var dir = state.sortDir === 'asc' ? 1 : -1;
    arr.sort(function (a, b) {
      var ac = a.status === '已关闭' ? 1 : 0, bc = b.status === '已关闭' ? 1 : 0;
      if (ac !== bc) return ac - bc;
      var va, vb;
      if (key === 'level') { va = LEVELS[a.level].weight; vb = LEVELS[b.level].weight; }
      else if (key === 'amount') { va = a.amount; vb = b.amount; }
      else if (key === 'remain') {
        va = a.status === '已关闭' ? 999999 : a.remain;
        vb = b.status === '已关闭' ? 999999 : b.remain;
      } else { va = a.created; vb = b.created; }
      if (va === vb) return a.id < b.id ? 1 : -1;
      return (va - vb) * dir;
    });
    return arr;
  }

  /* ---------------- 指标数据 ---------------- */
  function trendActual() {
    var base = [398, 376, 426, 412, 468, 441, 420, 459, 432, 487, 451, 502, 438, 428.6];
    var f = roleFactor();
    return base.map(function (v, i) {
      return i === base.length - 1 ? curRole().kpi.sign[0] : Math.round(v * f * 10) / 10;
    });
  }
  function trendTarget() { return Math.round(curRole().kpi.sign[0] / 0.97); }

  function shapeSeries(value, shape) {
    var last = shape[shape.length - 1];
    return shape.map(function (k) { return value * k / last; });
  }
  function kpiSeries(key) {
    var v = curRole().kpi[key][0];
    if (key === 'sign') return trendActual().slice(-7);
    if (key === 'rate') return shapeSeries(v, [0.925, 0.935, 0.952, 0.961, 0.982, 0.991, 1]);
    if (key === 'leads') return shapeSeries(v, [0.74, 0.82, 0.78, 0.92, 0.88, 0.96, 1]);
    if (key === 'roi') return shapeSeries(v, [0.875, 0.917, 0.896, 0.958, 0.938, 0.979, 1]);
    if (key === 'cover') return shapeSeries(v, [1.148, 1.111, 1.074, 1.074, 1.037, 1.037, 1]);
    return shapeSeries(v, [1.09, 1.074, 1.055, 1.036, 1.024, 1.007, 1]);
  }

  function channels() {
    var f = roleFactor();
    return D.CHANNELS.map(function (c) {
      return Object.assign({}, c, { leads: Math.round(c.leads * f), sign: Math.round(c.sign * f) });
    }).sort(function (a, b) { return b.sign - a.sign; });
  }

  function weeklyData() {
    var w = curRole().weekly;
    var m = D.WEEK_META[state.week];
    var f = m.factor;
    var last = state.week === 'last';
    var sign = Math.round(w.sign * f);
    var leads = Math.round(w.leads * f);
    var newRisks = Math.max(1, Math.round(w.newRisks * (last ? 1.06 : 1)));
    var closed = Math.max(1, Math.round(w.closedRisks * (last ? 0.97 : 1)));
    if (closed > newRisks) closed = newRisks;
    var closure = Math.max(1, Math.round(closed / newRisks * 100));
    var ranking = curRole().ranking.map(function (x) {
      return { name: x.name, rate: Math.max(40, Math.round(x.rate + (last ? -5 : 0))) };
    }).sort(function (a, b) { return b.rate - a.rate; });
    var types = ['目标缺口', '业绩下滑', '线索异常', '商机覆盖', '大客户流失', '订单 / 回款'];
    var weights = [0.27, 0.21, 0.18, 0.14, 0.12, 0.08];
    var counts = weights.map(function (x) { return Math.max(1, Math.round(newRisks * x)); });
    var sum = counts.reduce(function (a, b) { return a + b; }, 0);
    counts[counts.length - 1] += newRisks - sum;
    if (counts[counts.length - 1] < 0) counts[counts.length - 1] = 0;
    return {
      sign: sign, wow: Number((w.wow + m.wowShift).toFixed(1)), leads: leads,
      closure: closure, newRisks: newRisks, closed: closed,
      open: Math.max(0, newRisks - closed), avg: (w.avgDays + (last ? 0.2 : 0)).toFixed(1),
      ranking: ranking, types: types, counts: counts,
      range: m.range
    };
  }

  var GROUPS = {
    gm: [
      { name: '华东一部', w: 0.22, perf: 104, pct: 96 },
      { name: '华东二部', w: 0.18, perf: 96, pct: 88 },
      { name: '华东三部', w: 0.14, perf: 88, pct: 70 },
      { name: '华南大区', w: 0.19, perf: 91, pct: 75 },
      { name: '华北大区', w: 0.15, perf: 84, pct: 66 },
      { name: '西部大区', w: 0.12, perf: 76, pct: 60 }
    ],
    sd: [
      { name: '华东一部', w: 0.22, perf: 104, pct: 96 },
      { name: '华东二部', w: 0.18, perf: 96, pct: 88 },
      { name: '华东三部', w: 0.14, perf: 88, pct: 70 },
      { name: '华南大区', w: 0.19, perf: 91, pct: 75 },
      { name: '华北大区', w: 0.15, perf: 84, pct: 66 },
      { name: '西部大区', w: 0.12, perf: 76, pct: 60 }
    ],
    bu: [
      { name: '华东一部', w: 0.46, perf: 104, pct: 82 },
      { name: '华东二部', w: 0.32, perf: 96, pct: 78 },
      { name: '华东三部', w: 0.22, perf: 88, pct: 70 }
    ],
    sm: [
      { name: '李娜', w: 0.28, perf: 112, pct: 88 },
      { name: '周涛', w: 0.24, perf: 98, pct: 84 },
      { name: '陈晨', w: 0.20, perf: 91, pct: 79 },
      { name: '孙浩', w: 0.16, perf: 84, pct: 74 },
      { name: '王芳', w: 0.12, perf: 72, pct: 68 }
    ]
  };
  var GROUP_MOM = [-1.8, 2.4, 0.9, -2.2, 1.1, -0.6];

  function drillRows(key) {
    var groups = GROUPS[state.role] || GROUPS.gm;
    var total = curRole().kpi[key][0];
    var pctBase = key === 'rate' ? curRole().kpi.rate[0] : key === 'collect' ? curRole().kpi.collect[0] : null;
    var pctValues = groups.map(function (g) { return g.pct; });
    if (pctBase) {
      var avg = groups.reduce(function (s, g) { return s + g.w * g.pct; }, 0);
      pctValues = pctValues.map(function (v) { return v * (pctBase + 0.0) / avg; });
    }
    return groups.map(function (g, i) {
      var text, share = Math.round(g.w * 100) + '%';
      if (key === 'sign') text = fmt(total * g.w, 1) + ' 万';
      else if (key === 'leads') text = fmt(Math.round(total * g.w), 0) + ' 条';
      else if (key === 'rate') text = pctValues[i].toFixed(1) + ' %';
      else if (key === 'collect') text = pctValues[i].toFixed(1) + ' %';
      else if (key === 'roi') text = (curRole().kpi.roi[0] * (0.94 + i * 0.035)).toFixed(1) + ' x';
      else text = (curRole().kpi.cover[0] * (1.08 - i * 0.05)).toFixed(1) + ' x';
      return { name: g.name, value: text, share: share, mom: GROUP_MOM[i] };
    });
  }

  /* ---------------- 图表 ---------------- */
  function sparkSVG(values, color) {
    var w = 120, h = 30, p = 2;
    var min = Math.min.apply(null, values), max = Math.max.apply(null, values);
    var span = max - min || 1;
    var pts = values.map(function (v, i) {
      return [p + (w - p * 2) * i / (values.length - 1), h - p - (h - p * 2) * (v - min) / span];
    });
    var line = pts.map(function (pt, i) { return (i ? 'L' : 'M') + pt[0].toFixed(1) + ',' + pt[1].toFixed(1); }).join(' ');
    var area = line + ' L' + (w - p) + ',' + (h - p) + ' L' + p + ',' + (h - p) + ' Z';
    return '<svg viewBox="0 0 120 30" preserveAspectRatio="none" aria-hidden="true">' +
      '<path d="' + area + '" fill="' + color + '" opacity=".08"></path>' +
      '<path d="' + line + '" fill="none" stroke="' + color + '" stroke-width="1.6" vector-effect="non-scaling-stroke" stroke-linejoin="round" stroke-linecap="round"></path></svg>';
  }

  function drawLine(box, cfg) {
    if (!box) return;
    box.innerHTML = '';
    var W = Math.max(box.clientWidth - 2, 300);
    var H = cfg.height || 250;
    var m = { l: 40, r: cfg.endLabels ? 54 : 16, t: 18, b: 26 };
    var all = [];
    cfg.series.forEach(function (s) { all = all.concat(s.values); });
    var min = Math.min.apply(null, all), max = Math.max.apply(null, all);
    var span = max - min || 1;
    var step = span <= 5 ? 1 : span <= 30 ? 5 : span <= 150 ? 20 : 50;
    min = Math.floor((min - span * 0.14) / step) * step;
    max = Math.ceil((max + span * 0.16) / step) * step;
    if (min < 0) min = 0;
    if (max <= min) max = min + step;
    var n = cfg.labels.length;
    var x = function (i) { return m.l + (W - m.l - m.r) * (i / (n - 1)); };
    var y = function (v) { return m.t + (H - m.t - m.b) * (1 - (v - min) / (max - min)); };
    var gid = 'g' + (++chartSeq);
    var svg = '<svg width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(cfg.aria || '趋势图') + '">';
    svg += '<defs>';
    cfg.series.forEach(function (s, si) {
      if (!s.fill) return;
      svg += '<linearGradient id="' + gid + '-' + si + '" x1="0" y1="0" x2="0" y2="1">' +
        '<stop offset="0%" stop-color="' + s.color + '" stop-opacity=".16"></stop>' +
        '<stop offset="100%" stop-color="' + s.color + '" stop-opacity="0"></stop></linearGradient>';
    });
    svg += '</defs>';
    for (var g = 0; g <= 4; g++) {
      var gv = min + (max - min) * g / 4;
      var gy = y(gv);
      svg += '<line x1="' + m.l + '" y1="' + gy.toFixed(1) + '" x2="' + (W - m.r) + '" y2="' + gy.toFixed(1) + '" stroke="#EDF0F5" stroke-width="1"></line>';
      svg += '<text x="' + (m.l - 7) + '" y="' + (gy + 3.5).toFixed(1) + '" text-anchor="end" font-size="9" fill="#98A2B3" font-family="Microsoft YaHei,sans-serif">' + (max <= 10 ? gv.toFixed(1) : Math.round(gv)) + '</text>';
    }
    cfg.series.forEach(function (s, si) {
      var pts = s.values.map(function (v, i) { return [x(i), y(v)]; });
      var d = pts.map(function (pt, i) { return (i ? 'L' : 'M') + pt[0].toFixed(1) + ',' + pt[1].toFixed(1); }).join(' ');
      if (s.fill) {
        svg += '<path d="' + d + ' L' + x(n - 1).toFixed(1) + ',' + (H - m.b) + ' L' + x(0).toFixed(1) + ',' + (H - m.b) + ' Z" fill="url(#' + gid + '-' + si + ')"></path>';
      }
      svg += '<path d="' + d + '" fill="none" stroke="' + s.color + '" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"' + (s.dashed ? ' stroke-dasharray="5 4"' : '') + '></path>';
    });
    cfg.labels.forEach(function (lb, i) {
      if (n > 8 && i % 2 !== 0 && i !== n - 1) return;
      svg += '<text x="' + x(i).toFixed(1) + '" y="' + (H - 7) + '" text-anchor="middle" font-size="9" fill="#98A2B3" font-family="Microsoft YaHei,sans-serif">' + lb + '</text>';
    });
    var main = cfg.series[0];
    var lastX = x(n - 1), lastY = y(main.values[n - 1]);
    svg += '<circle cx="' + lastX.toFixed(1) + '" cy="' + lastY.toFixed(1) + '" r="4" fill="' + main.color + '" stroke="#fff" stroke-width="2"></circle>';
    if (cfg.endLabels) {
      svg += '<text x="' + (lastX + 7) + '" y="' + (lastY + 3.5).toFixed(1) + '" font-size="9.5" font-weight="700" fill="' + main.color + '" font-family="Microsoft YaHei,sans-serif">' + cfg.formatValue(main.values[n - 1]) + '</text>';
      if (cfg.series[1]) {
        var ty = y(cfg.series[1].values[n - 1]);
        svg += '<text x="' + (lastX + 7) + '" y="' + (ty + 3.5).toFixed(1) + '" font-size="9.5" font-weight="700" fill="' + cfg.series[1].color + '" font-family="Microsoft YaHei,sans-serif">' + cfg.formatValue(cfg.series[1].values[n - 1]) + '</text>';
      }
    }
    svg += '<line id="hLine" x1="0" y1="' + m.t + '" x2="0" y2="' + (H - m.b) + '" stroke="#A9B6C9" stroke-width="1" stroke-dasharray="3 3" opacity="0"></line>';
    cfg.series.forEach(function (s, si) {
      svg += '<circle id="hDot' + si + '" r="4" fill="#fff" stroke="' + s.color + '" stroke-width="2" opacity="0"></circle>';
    });
    svg += '<rect id="hitArea" x="' + m.l + '" y="' + m.t + '" width="' + (W - m.l - m.r) + '" height="' + (H - m.t - m.b) + '" fill="transparent"></rect>';
    svg += '</svg>';
    box.innerHTML = svg + '<div class="chart-tip" id="chartTip"></div>';

    var svgEl = box.querySelector('svg');
    var hit = box.querySelector('#hitArea');
    var tip = box.querySelector('#chartTip');
    var hLine = box.querySelector('#hLine');
    var dots = cfg.series.map(function (s, i) { return box.querySelector('#hDot' + i); });

    function move(ev) {
      var rect = svgEl.getBoundingClientRect();
      var px = ev.clientX - rect.left;
      var ratio = (px - m.l) / (W - m.l - m.r);
      var idx = Math.round(ratio * (n - 1));
      idx = Math.max(0, Math.min(n - 1, idx));
      var cx = x(idx);
      hLine.setAttribute('x1', cx); hLine.setAttribute('x2', cx); hLine.setAttribute('opacity', '1');
      cfg.series.forEach(function (s, si) {
        dots[si].setAttribute('cx', cx);
        dots[si].setAttribute('cy', y(s.values[idx]));
        dots[si].setAttribute('opacity', '1');
      });
      var rows = cfg.series.map(function (s) {
        return '<div class="tt-row"><i><span class="tt-dot" style="background:' + s.color + '"></span>' + s.label + '</i><b>' + cfg.formatValue(s.values[idx]) + '</b></div>';
      }).join('');
      if (cfg.showRate && cfg.series.length > 1) {
        var rate = cfg.series[0].values[idx] / cfg.series[1].values[idx] * 100;
        rows += '<div class="tt-row"><i>完成率</i><b>' + rate.toFixed(1) + '%</b></div>';
      }
      tip.innerHTML = '<div style="margin-bottom:3px;font-weight:700">' + cfg.labels[idx] + '</div>' + rows;
      tip.classList.add('on');
      var left = svgEl.offsetLeft + cx;
      left = Math.max(70, Math.min(box.clientWidth - 70, left));
      tip.style.left = left + 'px';
      tip.style.top = (svgEl.offsetTop + Math.min.apply(null, cfg.series.map(function (s) { return y(s.values[idx]); })) - 8) + 'px';
    }
    function leave() {
      tip.classList.remove('on');
      hLine.setAttribute('opacity', '0');
      dots.forEach(function (d) { d.setAttribute('opacity', '0'); });
    }
    hit.addEventListener('mousemove', move);
    hit.addEventListener('mouseleave', leave);
  }

  function drawTrend() {
    var box = document.getElementById('trendBox');
    if (!box) return;
    var actual = trendActual();
    var target = trendTarget();
    drawLine(box, {
      labels: TREND_LABELS,
      height: 246,
      endLabels: true,
      showRate: true,
      aria: '近 14 天签约趋势',
      formatValue: function (v) { return fmt(v, 1) + ' 万'; },
      series: [
        { label: '实际签约', color: '#2F5597', values: actual, fill: true },
        { label: '日目标', color: '#BF9000', values: TREND_LABELS.map(function () { return target; }), dashed: true }
      ]
    });
  }

  function drawSingle(box, values, labels, unit, color, title) {
    drawLine(box, {
      labels: labels,
      height: 146,
      endLabels: true,
      aria: title,
      formatValue: function (v) { return fmt(v, unit === '%' ? 1 : 1) + ' ' + unit; },
      series: [{ label: title, color: color || '#2F5597', values: values, fill: true }]
    });
  }

  function drawRanking() {
    var box = document.getElementById('rankChart');
    if (!box) return;
    var data = weeklyData().ranking;
    var W = Math.max(box.clientWidth - 2, 300);
    var rowH = 34, top = 8, left = 68, right = 46, bottom = 22;
    var H = top + data.length * rowH + bottom;
    var max = Math.max(110, Math.max.apply(null, data.map(function (d) { return d.rate; })) + 6);
    var bw = W - left - right;
    var x = function (v) { return left + bw * v / max; };
    var svg = '<svg width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="组织达成率排行">';
    [0, 50, 100].forEach(function (v) {
      svg += '<line x1="' + x(v).toFixed(1) + '" y1="' + (top - 2) + '" x2="' + x(v).toFixed(1) + '" y2="' + (H - bottom) + '" stroke="#EDF0F5" stroke-width="1"></line>';
      svg += '<text x="' + x(v).toFixed(1) + '" y="' + (H - 6) + '" text-anchor="middle" font-size="8.5" fill="#A3ACBA" font-family="Microsoft YaHei,sans-serif">' + v + '%</text>';
    });
    svg += '<line x1="' + x(100).toFixed(1) + '" y1="' + (top - 4) + '" x2="' + x(100).toFixed(1) + '" y2="' + (H - bottom) + '" stroke="#BF9000" stroke-width="1.2" stroke-dasharray="4 3"></line>';
    data.forEach(function (d, i) {
      var yy = top + i * rowH + 6;
      var bh = 18;
      svg += '<text x="' + (left - 9) + '" y="' + (yy + 13) + '" text-anchor="end" font-size="10" fill="#495568" font-family="Microsoft YaHei,sans-serif">' + esc(d.name) + '</text>';
      svg += '<rect x="' + left + '" y="' + yy + '" width="' + Math.max(2, x(d.rate) - left).toFixed(1) + '" height="' + bh + '" rx="4" fill="#4E7CB8"><title>' + esc(d.name) + '：' + d.rate + '%</title></rect>';
      svg += '<text x="' + (x(d.rate) + 6).toFixed(1) + '" y="' + (yy + 13) + '" font-size="10" font-weight="700" fill="#2F4E77" font-family="Microsoft YaHei,sans-serif">' + d.rate + '%</text>';
    });
    svg += '</svg>';
    box.innerHTML = svg;
  }

  /* ---------------- 页面：今日简报 ---------------- */
  function briefHTML() {
    var r = curRole();
    var openCount = openRisks().length;
    var html = '<div class="page">';
    html += '<div class="page-head"><div><h1>上午好，' + esc(r.honorific) + '</h1>' +
      '<div class="sub">' + todayLine() + ' · ' + esc(r.scope) + ' · 先看 3 条判断，再看指标与明细。</div></div>' +
      '<div class="head-actions">' +
      '<button class="btn" data-act="export">' + icon('download') + '<span>导出简报</span></button>' +
      '<button class="btn primary" data-act="phone">' + icon('phone') + '<span>手机预览</span></button>' +
      '</div></div>';

    html += '<div class="conclusions">';
    r.conclusions.forEach(function (c, i) {
      html += '<button class="conclusion ' + c.level + '" data-act="conclusion" data-level="' + c.level + '">' +
        '<span class="c-num">' + (i + 1) + '</span>' +
        '<span class="c-body"><span class="c-top"><span class="c-tag">' + esc(c.tag) + '</span></span>' +
        '<p>' + esc(c.text) + '</p></span>' +
        '<span class="c-arrow">' + icon('arrow') + '</span></button>';
    });
    html += '</div>';

    html += '<div class="kpi-grid">';
    D.KPI_META.forEach(function (k) {
      var arr = r.kpi[k.key];
      html += '<button class="kpi-card" data-act="kpi" data-kpi="' + k.key + '">' +
        '<span class="kpi-label">' + esc(k.label) + icon('info') + '</span>' +
        '<span class="kpi-value num">' + fmt(arr[0], k.decimals) + '<small>' + esc(k.unit) + '</small></span>' +
        '<span class="kpi-meta">' + deltaHTML(arr, k.key) + '<span class="kpi-sub">' + esc(kpiSub(k.key)) + '</span></span>' +
        '<span class="kpi-spark">' + sparkSVG(kpiSeries(k.key), '#3E6CB8') + '</span>' +
        '</button>';
    });
    html += '</div>';

    html += '<div class="brief-grid">';
    html += '<section class="card trend-card">' +
      '<div class="card-h"><div><div class="t">近 14 天签约趋势</div><div class="s">日签约额与日目标对比 · 单位：万元</div></div>' +
      '<div class="seg"><button class="' + (state.trendView === 'chart' ? 'on' : '') + '" data-act="trend-view" data-view="chart">' + icon('trend') + '图表</button>' +
      '<button class="' + (state.trendView === 'table' ? 'on' : '') + '" data-act="trend-view" data-view="table">' + icon('table') + '表格</button></div></div>';
    html += '<div class="chart-legend" style="padding:12px 18px 2px">' +
      '<span class="lg-item"><i class="lg-line"></i>实际签约</span>' +
      '<span class="lg-item"><i class="lg-line dash"></i>日目标 ' + trendTarget() + ' 万</span>' +
      '<span class="lg-item" style="margin-left:auto;color:#5F6B7D">14 天累计 ' + fmt(trendActual().reduce(function (a, b) { return a + b; }, 0), 1) + ' 万</span></div>';
    if (state.trendView === 'chart') {
      html += '<div class="chart-box" id="trendBox"></div>';
    } else {
      html += trendTableHTML();
    }
    html += '<div class="chart-foot"><span>10/11 — 10/24 · 每日 08:00 更新</span><span>数据来源：CRM 合同表</span></div></section>';

    var top = openRisks().slice().sort(function (a, b) {
      return LEVELS[b.level].weight - LEVELS[a.level].weight || a.remain - b.remain;
    }).slice(0, 3);
    html += '<section class="card"><div class="card-h"><div><div class="t">今日 Top3 风险</div><div class="s">按级别与 SLA 剩余时间排序</div></div>' +
      '<span class="tag red">' + openCount + ' 条待处理</span></div><div class="card-b">';
    html += '<div class="risk-mini">';
    if (!top.length) {
      html += '<div class="risk-zero">当前范围内没有待处理风险<br><span style="font-size:10px">演示数据可在「预警规则」中调整</span></div>';
    } else {
      top.forEach(function (risk) {
        var lv = levelOf(risk);
        var urgent = risk.remain > 0 && risk.remain < 240;
        html += '<button class="rm-item" data-act="risk" data-id="' + risk.id + '">' +
          '<span class="rm-bar ' + lv.cls + '"></span>' +
          '<span class="rm-main"><span class="rm-title">' + esc(risk.title) + '</span>' +
          '<span class="rm-meta"><span class="lvl ' + lv.cls + '"><i></i>' + lv.label + '</span><span class="dot-sep"></span>' + esc(risk.type) +
          '<span class="dot-sep"></span>' + esc(risk.owner) + '</span>' +
          '<span class="rm-sla ' + (urgent ? 'urgent' : '') + '">' + icon('clock') + (risk.overdue ? '已超时 ' + esc(risk.sla.replace('超时 ', '')) : '剩 ' + esc(risk.sla)) + '</span></span>' +
          '<span class="rm-go">' + icon('arrow') + '</span></button>';
      });
    }
    html += '</div>';
    html += '<div class="risk-mini-foot"><span style="font-size:9.5px;color:#8A94A4">红色 4 小时内认领 · 橙色 8 小时</span>' +
      '<button class="link" data-act="goto-risks">查看全部 ' + openCount + ' 条 ' + icon('arrow') + '</button></div>';
    html += '</div></section>';
    html += '</div>';

    var chs = channels();
    var totalSign = chs.reduce(function (a, c) { return a + c.sign; }, 0);
    var maxSign = Math.max.apply(null, chs.map(function (c) { return c.sign; }));
    html += '<section class="card table-card"><div class="table-top"><div class="t">近 14 天渠道表现<span>按签约额排序 · 单位：万元</span></div>' +
      '<button class="link" data-act="channel-more">查看渠道分析 ' + icon('arrow') + '</button></div>';
    html += '<table class="data-table"><thead><tr><th>渠道</th><th class="r">线索量</th><th class="r">有效率</th><th class="r">转化率</th><th class="r">签约额</th><th class="r">ROI</th><th class="r">环比</th></tr></thead><tbody>';
    chs.forEach(function (c) {
      var share = totalSign ? Math.round(c.sign / totalSign * 100) : 0;
      html += '<tr data-act="channel" data-name="' + esc(c.name) + '">' +
        '<td><div class="name">' + esc(c.name) + '</div><div style="font-size:9px;color:#8A94A4;margin-top:2px">占签约 ' + share + '%</div></td>' +
        '<td class="r num">' + fmt(c.leads) + '</td>' +
        '<td class="r num">' + c.valid + '%</td>' +
        '<td class="r num">' + c.conv + '%</td>' +
        '<td class="r"><div class="amount"><b>' + fmt(c.sign) + '</b><span class="mbar"><i style="width:' + Math.round(c.sign / maxSign * 100) + '%"></i></span></div></td>' +
        '<td class="r num">' + c.roi.toFixed(1) + 'x</td>' +
        '<td class="r"><span class="' + (c.wow >= 0 ? 'trend-up' : 'trend-down') + '">' + (c.wow >= 0 ? '↑' : '↓') + ' ' + Math.abs(c.wow).toFixed(1) + '%</span></td>' +
        '</tr>';
    });
    html += '</tbody></table></section>';
    html += '<div class="source-note">' + icon('info') + '数据来源：CRM / ERP / 投放平台 · 今日 06:00 抽取，07:15 质量校验通过 · 点击任意指标可查看口径与下钻</div>';
    html += '</div>';
    return html;
  }

  function trendTableHTML() {
    var actual = trendActual(), target = trendTarget();
    var rows = actual.map(function (v, i) {
      return '<tr><td>' + TREND_LABELS[i] + '</td><td>' + fmt(v, 1) + '</td><td>' + fmt(target, 0) + '</td><td>' + (v / target * 100).toFixed(1) + '%</td></tr>';
    }).reverse().join('');
    return '<div class="chart-table-wrap"><table class="chart-table"><thead><tr><th>日期</th><th>实际（万）</th><th>目标（万）</th><th>完成率</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
  }

  /* ---------------- 页面：风险中心 ---------------- */
  function riskPageHTML() {
    var vis = visibleRisks();
    var counts = {
      all: vis.length,
      wait: vis.filter(function (r) { return r.status === '待认领'; }).length,
      doing: vis.filter(function (r) { return r.status === '处理中'; }).length,
      late: vis.filter(function (r) { return r.status === '已超时'; }).length
    };
    var lvCount = { red: 0, orange: 0, yellow: 0 };
    vis.forEach(function (r) { lvCount[r.level]++; });
    var types = Array.from(new Set(vis.map(function (r) { return r.type; })));
    var owners = Array.from(new Set(vis.map(function (r) { return r.owner; })));

    var html = '<div class="page">';
    html += '<div class="page-head"><div><h1>风险中心</h1><div class="sub">' + esc(curRole().scope) + ' · 共 ' + vis.length + ' 条风险，待处理 ' + openRisks().length + ' 条 · 红色 4 小时内认领，超时自动升级（最多两级）。</div></div>' +
      '<div class="head-actions"><button class="btn" data-act="refresh">' + icon('update') + '<span>刷新</span></button>' +
      '<button class="btn" data-act="export">' + icon('download') + '<span>导出清单</span></button></div></div>';

    html += '<div class="stat-grid">' +
      statCard('今日新增', counts.all, '条', '红色 ' + lvCount.red + ' · 橙色 ' + lvCount.orange + ' · 黄色 ' + lvCount.yellow, 'all', 'brief', state.status === 'all') +
      statCard('待认领', counts.wait, '条', '需在 SLA 内点击认领', '待认领', 'clock', state.status === '待认领') +
      statCard('处理中', counts.doing, '条', '已认领，等待处置结果', '处理中', 'user', state.status === '处理中') +
      statCard('已超时', counts.late, '条', '建议今天上午完成升级', '已超时', 'risk', state.status === '已超时', true) +
      '</div>';

    html += '<div class="card filter-bar">';
    html += '<div class="chips">' + levelChip('all', '全部', counts.all) + levelChip('red', '红色', lvCount.red) +
      levelChip('orange', '橙色', lvCount.orange) + levelChip('yellow', '黄色', lvCount.yellow) + '</div>';
    html += '<div class="select-wrap"><select class="select" id="fType" aria-label="按类型筛选"><option value="all">全部类型</option>' +
      types.map(function (t) { return '<option value="' + esc(t) + '"' + (state.type === t ? ' selected' : '') + '>' + esc(t) + '</option>'; }).join('') + '</select></div>';
    html += '<div class="select-wrap"><select class="select" id="fOwner" aria-label="按负责人筛选"><option value="all">全部负责人</option>' +
      owners.map(function (o) { return '<option value="' + esc(o) + '"' + (state.owner === o ? ' selected' : '') + '>' + esc(o) + '</option>'; }).join('') + '</select></div>';
    html += '<div class="select-wrap"><select class="select" id="fStatus" aria-label="按状态筛选">' +
      ['all', '待认领', '处理中', '已超时', '已关闭'].map(function (s) {
        return '<option value="' + s + '"' + (state.status === s ? ' selected' : '') + '>' + (s === 'all' ? '全部状态' : s) + '</option>';
      }).join('') + '</select></div>';
    html += '<div class="search-box">' + icon('search') + '<input id="fSearch" type="text" placeholder="搜索客户 / 编号 / 负责人" value="' + esc(state.q) + '"></div>';
    html += '<button class="filter-reset" data-act="reset">重置</button>';
    html += '</div>';

    html += riskTableHTML();
    html += '<div class="source-note">' + icon('info') + '风险由规则库每日 07:50 自动识别；认领、转派、关闭都会写入处理时间线，可在详情中查看。</div>';
    html += '</div>';
    return html;
  }

  function statCard(label, value, unit, sub, status, icoName, active, late) {
    return '<button class="stat-card' + (active ? ' active' : '') + (late ? ' late' : '') + '" data-act="stat" data-status="' + status + '">' +
      '<div><div class="stat-label">' + label + '</div><div class="stat-value num">' + value + '<small>' + unit + '</small></div>' +
      '<div class="stat-sub">' + sub + '</div></div>' +
      '<span class="stat-ico">' + icon(icoName) + '</span></button>';
  }

  function levelChip(level, label, count) {
    var dot = level === 'all' ? '' : '<i class="cdot ' + level + '"></i>';
    return '<button class="chip' + (state.level === level ? ' on' : '') + '" data-act="level" data-level="' + level + '">' +
      dot + label + ' <span class="cnt">' + count + '</span></button>';
  }

  function riskTableHTML() {
    var arr = filteredRisks();
    var html = '<section class="card table-card" id="riskTableCard"><div class="table-top"><div class="t">风险列表<span id="riskCount">' + arr.length + ' 条</span></div>' +
      '<span style="font-size:9.5px;color:#8A94A4">点击一行查看证据链与处理动作</span></div><div class="table-scroll">';
    html += '<table class="risk-table"><thead><tr>' +
      '<th>编号</th>' + sortTh('level', '级别') + '<th>类型</th><th>风险对象</th>' + sortTh('amount', '金额') +
      '<th>负责人</th><th>触发</th>' + sortTh('remain', 'SLA 剩余') + '<th>状态</th><th style="text-align:right">操作</th>' +
      '</tr></thead><tbody>';
    if (!arr.length) {
      html += '<tr><td colspan="10"><div class="empty"><div class="e-ico">' + icon('search') + '</div><b>没有符合条件的风险</b><p>试试切换级别、状态，或清空搜索关键词</p></div></td></tr>';
    } else {
      arr.forEach(function (r) { html += riskRowHTML(r); });
    }
    html += '</tbody></table></div></section>';
    return html;
  }

  function sortTh(key, label) {
    var on = state.sortKey === key;
    return '<th class="sortable' + (on ? ' on' : '') + '" data-act="sort" data-key="' + key + '">' + label +
      '<span class="sort">' + (on ? (state.sortDir === 'desc' ? '▼' : '▲') : '↕') + '</span></th>';
  }

  function riskRowHTML(r) {
    var lv = levelOf(r);
    var urg = r.remain > 0 && r.remain < 240;
    var sla = r.status === '已关闭' ? '—' : (r.overdue ? esc(r.sla) : '剩 ' + esc(r.sla));
    var actions = '<button class="mini-btn" data-act="risk" data-id="' + r.id + '">查看</button>';
    if (r.status === '待认领' || r.status === '已超时') actions += '<button class="mini-btn pri" data-act="claim" data-id="' + r.id + '">认领</button>';
    else if (r.status === '处理中') actions += '<button class="mini-btn pri" data-act="close-risk" data-id="' + r.id + '">关闭</button>';
    return '<tr class="' + (r.status === '已关闭' ? 'closed' : '') + '" data-act="risk" data-id="' + r.id + '">' +
      '<td><div class="risk-id">' + esc(r.id) + '</div></td>' +
      '<td><span class="lvl ' + lv.cls + '"><i></i>' + lv.label + '</span></td>' +
      '<td>' + esc(r.type) + '</td>' +
      '<td><div class="risk-name">' + esc(r.title) + '</div><div class="risk-obj">' + esc(r.object) + ' · ' + esc(r.dept) + '</div></td>' +
      '<td class="risk-amount">' + (r.amount ? fmt(r.amount) + ' 万' : '—') + '</td>' +
      '<td><div class="risk-owner"><span class="mini-avatar">' + esc(r.owner.slice(0, 1)) + '</span>' + esc(r.owner) + '</div></td>' +
      '<td class="risk-id">' + esc(r.created) + '</td>' +
      '<td class="sla-cell ' + (r.overdue ? 'overdue' : urg ? 'urgent' : '') + '">' + sla + '</td>' +
      '<td><span class="status ' + statusCls(r.status) + '">' + esc(r.status) + '</span></td>' +
      '<td><div class="row-actions">' + actions + '</div></td></tr>';
  }

  /* ---------------- 页面：周报 ---------------- */
  function weeklyHTML() {
    var w = weeklyData();
    var r = curRole();
    var wkLabel = state.week === 'last' ? '上周' : '本周';
    var html = '<div class="page">';
    html += '<div class="page-head"><div><h1>周报复盘</h1><div class="sub">' + esc(r.scope) + ' · ' + w.range + ' · 周一至周日，周六 08:00 生成周中版。</div></div>' +
      '<div class="head-actions"><div class="week-bar"><div class="seg">' +
      '<button class="' + (state.week === 'this' ? 'on' : '') + '" data-act="week" data-week="this">本周</button>' +
      '<button class="' + (state.week === 'last' ? 'on' : '') + '" data-act="week" data-week="last">上周</button>' +
      '</div><span class="week-range">' + w.range + '</span></div>' +
      '<button class="btn" data-act="export">' + icon('download') + '<span>导出周报</span></button></div></div>';

    html += '<div class="week-top">' +
      weekStat(wkLabel + '签约额', fmt(w.sign), '万', (w.wow >= 0 ? '↑ ' : '↓ ') + Math.abs(w.wow) + '% 环比', w.wow >= 0 ? 'good' : 'bad') +
      weekStat('新增线索', fmt(w.leads), '条', '有效线索约 ' + (w.leads ? Math.round(w.leads * 0.63) : 0) + ' 条', '') +
      weekStat('风险按期关闭率', w.closure, '%', '目标 ≥ 85%', w.closure >= 85 ? 'good' : 'bad') +
      weekStat('平均处理时长', w.avg, '天', '红色风险平均 ' + (Number(w.avg) * 0.6).toFixed(1) + ' 天', '') +
      '</div>';

    html += '<div class="weekly-grid">';
    html += '<section class="card"><div class="card-h"><div><div class="t">' + wkLabel + ' 3 条判断</div><div class="s">给管理者的复盘结论，不堆指标</div></div>' +
      '<span class="tag blue">' + D.WEEK_META[state.week].label + '</span></div><div class="weekly-concl">';
    var c1 = '<b>' + esc(r.scope) + '</b>' + wkLabel + '签约 <b>' + fmt(w.sign) + ' 万</b>，环比 <b>' + (w.wow >= 0 ? '+' : '') + w.wow + '%</b>，' + (w.wow >= 0 ? '保持增长。' : '出现回落。');
    var c2 = '风险按期关闭率 <b>' + w.closure + '%</b>，' + (w.closure >= 85 ? '处于健康区间' : '低于 85% 目标') + '；平均处理 <b>' + w.avg + ' 天</b>。';
    var c3 = '接下来优先：<b>' + esc(r.priorities[0]) + '</b>。';
    [c1, c2, c3].forEach(function (t, i) {
      html += '<div class="wc-item"><span class="wc-num">' + (i + 1) + '</span><p>' + t + '</p></div>';
    });
    html += '</div>';
    var dayWeights = [0.13, 0.15, 0.14, 0.16, 0.13, 0.15, 0.14];
    var dayNames = ['一', '二', '三', '四', '五', '六', '日'];
    var dayVals = dayWeights.map(function (x) { return Math.round(w.sign * x); });
    dayVals[6] += w.sign - dayVals.reduce(function (a, b) { return a + b; }, 0);
    var dayMax = Math.max.apply(null, dayVals);
    html += '<div class="day-bars-wrap"><div class="day-bars-head"><span>' + wkLabel + '每日签约</span><span>单位：万元</span></div><div class="day-bars">';
    dayVals.forEach(function (v, i) {
      html += '<div class="day-bar"><b>' + fmt(v) + '</b><i style="height:' + (10 + Math.round(v / dayMax * 34)) + 'px"></i><span>' + dayNames[i] + '</span></div>';
    });
    html += '</div></div></section>';

    html += '<section class="card"><div class="card-h"><div><div class="t">组织达成排行</div><div class="s">' + wkLabel + '签约完成率 · 金色虚线为 100% 达标线</div></div></div>' +
      '<div class="rank-chart" id="rankChart"></div></section>';
    html += '</div>';

    html += '<div class="weekly-grid">';
    html += '<section class="card"><div class="card-h"><div><div class="t">风险闭环</div><div class="s">新增 ' + w.newRisks + ' 条 · 关闭 ' + w.closed + ' 条 · 未闭环 ' + w.open + ' 条</div></div></div>' +
      '<div class="closure-hero"><div class="closure-num">' + w.closure + '<small>%</small></div>' +
      '<div class="closure-meta"><b>按期关闭率</b><span>' + (w.closure >= 85 ? '高于 85% 目标' : '低于 85% 目标') + ' · 平均 ' + w.avg + ' 天</span></div></div>' +
      '<div class="stack-bar"><i class="closed" style="width:' + Math.round(w.closed / w.newRisks * 100) + '%"></i><i class="open" style="width:' + Math.round(w.open / w.newRisks * 100) + '%"></i></div>' +
      '<div class="stack-legend"><span><i style="background:#4E7CB8"></i>已关闭 ' + w.closed + '</span><span><i style="background:#D9E1EE"></i>未闭环 ' + w.open + '</span></div>' +
      '<div style="border-top:1px solid #EFF2F6;margin:0 18px"></div>' +
      '<div class="card-h" style="padding:12px 18px 0"><div class="t" style="font-size:12px">风险类型分布</div></div>' +
      '<div class="type-bars" id="typeBars"></div></section>';

    html += '<section class="card"><div class="card-h"><div><div class="t">接下来 3 件重点</div><div class="s">只留 3 件，周会逐项过</div></div></div>' +
      '<div class="priority-card">';
    r.priorities.forEach(function (p, i) {
      html += '<div class="priority-item"><span class="pnum">' + (i + 1) + '</span><span>' + esc(p) + '</span></div>';
    });
    html += '</div><div style="margin:10px 18px 0;border-top:1px solid #EFF2F6;padding-top:6px">' +
      '<div class="sc-row"><span>周会时间</span><b>周一 09:30</b></div>' +
      '<div class="sc-row"><span>参会人</span><b>总经理 · 销售总监 · 事业部总</b></div>' +
      '<div class="sc-row"><span>会议输出</span><b>3 项动作 + 责任人 + 截止</b></div></div>' +
      '<div class="week-note" style="padding:8px 18px 14px">周报每周六 08:00 生成周中版，周一 08:00 更新正式版；如遇节假日顺延。</div></section>';
    html += '</div>';
    html += '<div class="source-note">' + icon('info') + '数据来源：CRM 合同 / 线索 / 商机表，ERP 回款表 · 口径与日报一致，避免“数出多门”。</div>';
    html += '</div>';
    return html;
  }

  function weekStat(label, value, unit, sub, tone) {
    return '<div class="card week-stat"><div class="k">' + label + '</div><div class="v num">' + value + '<small>' + unit + '</small></div>' +
      '<div class="d"><span class="delta ' + (tone || 'flat') + '">' + sub + '</span></div></div>';
  }

  function renderTypeBars() {
    var el = document.getElementById('typeBars');
    if (!el) return;
    var w = weeklyData();
    var max = Math.max.apply(null, w.counts) || 1;
    el.innerHTML = w.types.map(function (t, i) {
      return '<div class="type-row"><span class="tn">' + t + '</span><span class="tb"><i style="width:' + Math.round(w.counts[i] / max * 100) + '%"></i></span><span class="tv">' + w.counts[i] + '</span></div>';
    }).join('');
  }

  /* ---------------- 页面：规则 ---------------- */
  function rulesHTML() {
    var html = '<div class="page">';
    html += '<div class="page-head"><div><h1>预警规则</h1><div class="sub">规则在每天 07:50 的批次中执行；修改后次日 06:00 生效（演示环境不写入服务器）。</div></div>' +
      '<div class="head-actions"><button class="btn" data-act="add-rule">' + icon('rules') + '<span>新增规则</span></button>' +
      '<button class="btn primary" data-act="rules-save">' + icon('check') + '<span>保存配置</span></button></div></div>';
    html += '<div class="rules-grid"><div class="rule-list">';
    stateRules.forEach(function (rule) {
      html += '<div class="rule-card' + (rule.on ? '' : ' off') + '">' +
        '<div class="rule-ico">' + icon(RULE_ICONS[rule.icon] || 'target') + '</div>' +
        '<div class="rule-main"><div class="rule-title">' + esc(rule.name) + (rule.on ? '' : ' <span class="tag gray">已停用</span>') + '</div>' +
        '<div class="rule-desc">' + esc(rule.desc) + '</div>' +
        '<div class="rule-threshold">' + icon('filter') + '触发条件：' + esc(rule.threshold) + '</div>' +
        '<div class="rule-levels">' + rule.levels.map(function (l) {
          return '<span class="rl ' + levelClass(l[0]) + '"><b>' + l[0] + '</b>' + esc(l[1]) + '</span>';
        }).join('') + '</div></div>' +
        '<button class="switch' + (rule.on ? ' on' : '') + '" data-act="rule-toggle" data-id="' + rule.id + '" role="switch" aria-checked="' + rule.on + '" aria-label="启用或停用' + esc(rule.name) + '"></button>' +
        '</div>';
    });
    html += '</div><div>';

    html += '<div class="card side-card"><h4>推送设置</h4><div class="sc-sub">每日批次完成后，按角色模板推送到对应渠道。</div>' +
      '<div class="form-row" style="margin-bottom:10px"><label>推送时间</label><input type="time" value="08:30" id="pushTime" style="height:32px;padding:0 9px"></div>' +
      '<div class="sc-sub" style="margin-bottom:2px">推送渠道</div><div class="channel-checks">' +
      '<label class="ch-check"><input type="checkbox" checked>钉钉</label>' +
      '<label class="ch-check"><input type="checkbox" checked>企业微信</label>' +
      '<label class="ch-check"><input type="checkbox">邮件 PDF</label>' +
      '<label class="ch-check"><input type="checkbox" disabled>短信</label></div>' +
      '<button class="btn sm" data-act="rules-save" style="width:100%">保存推送设置</button></div>';

    html += '<div class="card side-card"><h4>角色与数据范围</h4><div class="sc-sub">同一份简报，按角色裁剪结论、指标与风险。</div><div class="perm-list">' +
      '<div class="perm-item"><i class="perm-dot"></i>公司总经理<small>全公司</small></div>' +
      '<div class="perm-item"><i class="perm-dot"></i>销售总监<small>全公司销售</small></div>' +
      '<div class="perm-item"><i class="perm-dot"></i>事业部总经理<small>本事业部</small></div>' +
      '<div class="perm-item"><i class="perm-dot"></i>部门销售经理<small>本部门</small></div>' +
      '</div></div>';

    html += '<div class="card side-card"><h4>规则执行说明</h4>' +
      '<div class="sc-row"><span>执行时间</span><b>每日 07:50</b></div>' +
      '<div class="sc-row"><span>升级层级</span><b>最多 2 级</b></div>' +
      '<div class="sc-row"><span>误报处理</span><b>可关闭并标记原因</b></div>' +
      '<div class="sc-row"><span>规则版本</span><b>V0.1 · 6 条</b></div></div>';
    html += '</div></div>';
    html += '<div class="source-note">' + icon('info') + '规则阈值建议先跑 30 天试点，再按误报率调整；不要让“预警”变成“狼来了”。</div>';
    html += '</div>';
    return html;
  }

  function levelClass(cn) {
    return cn === '红' ? 'red' : cn === '橙' ? 'orange' : 'yellow';
  }

  /* ---------------- 抽屉：风险详情 ---------------- */
  function buildTimeline(r) {
    var items = [
      { t: '08:30', text: '系统触发预警，推送钉钉 / 企微' },
      { t: '08:35', text: '已推送给 ' + r.owner + ' 及上级' }
    ];
    if (r.status === '已超时') items.push({ t: '08:40', text: r.owner + ' 未在时限内认领，已升级至销售总监' });
    if (r.status === '处理中' && !r.events.length) items.push({ t: '09:10', text: r.owner + ' 已认领，开始处置' });
    if (r.status === '已关闭' && !r.events.length) {
      items.push({ t: '09:10', text: r.owner + ' 已认领' });
      items.push({ t: '次日 17:20', text: '已关闭：' + (r.closeNote || '完成处置并留痕') });
    }
    r.events.forEach(function (e) { items.push(e); });
    items.push({ t: '现在', text: r.status === '已关闭' ? '已关闭，处理记录已归档' : 'SLA 计时中 · 剩余 ' + r.sla, now: true });
    return items.map(function (it, i) {
      return '<div class="tl-item' + (it.now || i === items.length - 1 ? ' now' : '') + '"><div class="tl-time">' + esc(it.t) + '</div><div class="tl-text">' + esc(it.text) + '</div></div>';
    }).join('');
  }

  function drawerHTML(r) {
    var lv = levelOf(r);
    var remainText = r.status === '已关闭' ? '已关闭' : (r.overdue ? r.sla : '剩 ' + r.sla);
    var html = '<div class="dw-head"><div class="dw-tags"><span class="tag ' + lv.cls + '">' + lv.label + '风险</span>' +
      '<span class="tag outline">' + esc(r.type) + '</span><span class="status ' + statusCls(r.status) + '">' + esc(r.status) + '</span></div>' +
      '<div class="dw-title">' + esc(r.title) + '</div>' +
      '<div class="dw-id">' + esc(r.id) + ' · ' + esc(r.org) + ' / ' + esc(r.dept) + ' · 触发于 ' + esc(r.created) + '</div>' +
      '<button class="icon-btn dw-close" data-act="drawer-close" aria-label="关闭详情">' + icon('close') + '</button></div>';
    html += '<div class="dw-body">';
    if (r.status === '已关闭') {
      html += '<div class="closed-banner">' + icon('check') + '<span>该风险已关闭：' + esc(r.closeNote || '处理完成，已留痕') + '</span></div>';
    }
    html += '<div class="facts">' +
      fact('风险对象', r.object) + fact('涉及金额', r.amount ? fmt(r.amount) + ' 万' : '不涉及金额') +
      fact('负责人', r.owner) + fact('SLA', remainText) +
      fact('所属组织', r.org + ' / ' + r.dept) + fact('触发时间', '今日 ' + r.created) + '</div>';

    html += '<div class="dw-section" style="margin-top:17px"><h4>为什么报<span class="side">每条都带阈值，减少误报争议</span></h4>';
    r.why.forEach(function (w) {
      html += '<div class="why-row"><span>' + esc(w[0]) + '</span><span>' + esc(w[1]) + '</span></div>';
    });
    html += '<div class="why-note">阈值来自预警规则库，可在「预警规则」中调整；系统按 T+1 数据计算，不读取实时手工改动。</div></div>';

    html += '<div class="dw-section"><h4>建议动作<span class="side">按优先级排序</span></h4><ol class="action-list">';
    r.actions.forEach(function (a) { html += '<li>' + esc(a) + '</li>'; });
    html += '</ol></div>';

    html += '<div class="dw-section"><h4>处理时间线</h4><div class="timeline">' + buildTimeline(r) + '</div></div>';

    if (r.related && r.related.length) {
      html += '<div class="dw-section"><h4>关联商机 / 指标<span class="side">' + r.related.length + ' 条</span></h4><div class="related-list">';
      r.related.forEach(function (x) {
        html += '<div class="related-row"><span>' + esc(x[0]) + '</span><span>' + esc(x[1]) + '</span></div>';
      });
      html += '</div></div>';
    }

    if (r.events.length) {
      html += '<div class="dw-section"><h4>我的处理记录</h4>';
      r.events.forEach(function (e) {
        html += '<div class="why-row"><span>' + esc(e.t) + '</span><span>' + esc(e.text) + '</span></div>';
      });
      html += '</div>';
    }
    html += '</div>';

    html += '<div class="dw-foot">';
    if (r.status === '待认领' || r.status === '已超时') {
      html += '<button class="btn primary" data-act="claim" data-id="' + r.id + '">认领并处理</button>' +
        '<button class="btn" data-act="transfer" data-id="' + r.id + '">转派</button>';
    } else if (r.status === '处理中') {
      html += '<button class="btn primary" data-act="close-risk" data-id="' + r.id + '">关闭风险</button>' +
        '<button class="btn" data-act="transfer" data-id="' + r.id + '">转派</button>';
    } else {
      html += '<button class="btn" disabled>' + icon('check') + ' 已关闭</button>' +
        '<button class="btn" data-act="view-log" data-id="' + r.id + '">查看处理记录</button>';
    }
    html += '</div>';
    return html;
  }

  function fact(k, v) {
    return '<div class="fact"><div class="k">' + esc(k) + '</div><div class="v">' + esc(v) + '</div></div>';
  }

  function openDrawer(id) {
    var r = riskById(id);
    if (!r || r.visibleTo.indexOf(state.role) === -1) return;
    currentRiskId = id;
    drawer.innerHTML = drawerHTML(r);
    drawer.classList.add('open');
    drawerMask.classList.add('open');
    drawer.setAttribute('aria-hidden', 'false');
    lockScroll();
  }
  function closeDrawer() {
    drawer.classList.remove('open');
    drawerMask.classList.remove('open');
    drawer.setAttribute('aria-hidden', 'true');
    currentRiskId = null;
    unlockScroll();
  }

  /* ---------------- 弹窗 ---------------- */
  function lockScroll() { document.body.style.overflow = 'hidden'; }
  function unlockScroll() {
    if (!drawer.classList.contains('open') && !modalRoot.classList.contains('open') && !phoneOverlay.classList.contains('open')) {
      document.body.style.overflow = '';
    }
  }
  function openModal(html, wide) {
    modalRoot.innerHTML = '<div class="modal' + (wide ? ' wide' : '') + '" role="dialog" aria-modal="true">' + html + '</div>';
    modalRoot.classList.add('open');
    lockScroll();
    modalRoot.querySelectorAll('[data-close]').forEach(function (b) {
      b.addEventListener('click', closeModal);
    });
    var box = modalRoot.querySelector('.modal');
    box.setAttribute('tabindex', '-1');
    box.focus();
    return box;
  }
  function closeModal() {
    modalRoot.classList.remove('open');
    modalRoot.innerHTML = '';
    unlockScroll();
  }

  function riskSummaryHTML(r) {
    var lv = levelOf(r);
    return '<div class="risk-summary"><span class="rs-bar ' + lv.cls + '"></span><div><b>' + esc(r.title) + '</b>' +
      '<small>' + esc(r.id) + ' · ' + esc(r.type) + ' · ' + esc(r.owner) + '</small></div>' +
      '<span class="rs-sla">' + (r.overdue ? esc(r.sla) : '剩 ' + esc(r.sla)) + '</span></div>';
  }

  function openClaim(id) {
    var r = riskById(id); if (!r) return;
    var m = openModal(
      '<div class="modal-head"><h3>认领风险</h3><p>认领后 SLA 继续计时，处理结果会记入时间线，作为周报复盘依据。</p>' +
      '<button class="icon-btn modal-close" data-close aria-label="关闭">' + icon('close') + '</button></div>' +
      '<div class="modal-body">' + riskSummaryHTML(r) +
      '<div class="form-row"><label>处理计划<small>必填，建议写清“找谁、做什么、何时完成”</small></label>' +
      '<textarea id="claimPlan">' + esc(r.actions[0]) + '</textarea><div class="form-error" id="claimErr">请填写至少 5 个字的处理计划</div></div>' +
      '<div class="form-grid"><div class="form-row"><label>预计完成</label><select id="claimDue"><option>今天 18:00 前</option><option>明天 12:00 前</option><option>3 个工作日内</option></select></div>' +
      '<div class="form-row"><label>同步给</label><select id="claimSync"><option>直属上级</option><option>仅自己</option><option>上级 + 销售总监</option></select></div></div>' +
      '<label class="check-line"><input type="checkbox" id="claimNotify" checked> 同步推送到钉钉，并在风险卡片中展示处理计划</label></div>' +
      '<div class="modal-foot"><button class="btn" data-close>取消</button><button class="btn primary" id="claimConfirm">确认认领</button></div>'
    );
    m.querySelector('#claimConfirm').addEventListener('click', function () {
      var plan = m.querySelector('#claimPlan').value.trim();
      if (plan.length < 5) { m.querySelector('#claimErr').classList.add('show'); return; }
      r.status = '处理中';
      r.events.push({ t: '09:12', text: curRole().name + ' 认领，计划：' + plan });
      refreshAll();
      closeModal();
      toast('已认领风险，SLA 计时中');
    });
  }

  function openClose(id) {
    var r = riskById(id); if (!r) return;
    var m = openModal(
      '<div class="modal-head"><h3>关闭风险</h3><p>关闭前请填写处理结果。系统会记录操作人与时间，避免“口头关闭”。</p>' +
      '<button class="icon-btn modal-close" data-close aria-label="关闭">' + icon('close') + '</button></div>' +
      '<div class="modal-body">' + riskSummaryHTML(r) +
      '<div class="form-row"><label>处理结果<small>必填</small></label><textarea id="closeNote" placeholder="例如：已电话确认预算，客户同意本周五签约"></textarea>' +
      '<div class="form-error" id="closeErr">请填写至少 5 个字的处理结果</div></div>' +
      '<div class="form-row"><label>关闭原因</label><div class="radio-row">' +
      '<label class="radio-pill"><input type="radio" name="closeReason" value="已解决" checked><span>已解决</span></label>' +
      '<label class="radio-pill"><input type="radio" name="closeReason" value="客户放弃"><span>客户放弃</span></label>' +
      '<label class="radio-pill"><input type="radio" name="closeReason" value="误报"><span>误报</span></label>' +
      '<label class="radio-pill"><input type="radio" name="closeReason" value="转长期跟踪"><span>转长期跟踪</span></label></div></div>' +
      '<label class="check-line"><input type="checkbox" checked> 关闭后同步到周报的“风险闭环”统计</label></div>' +
      '<div class="modal-foot"><button class="btn" data-close>取消</button><button class="btn primary" id="closeConfirm">确认关闭</button></div>'
    );
    m.querySelector('#closeConfirm').addEventListener('click', function () {
      var note = m.querySelector('#closeNote').value.trim();
      if (note.length < 5) { m.querySelector('#closeErr').classList.add('show'); return; }
      var reason = m.querySelector('input[name="closeReason"]:checked').value;
      r.status = '已关闭';
      r.closeNote = note + (reason && reason !== '已解决' ? '（' + reason + '）' : '');
      r.events.push({ t: '09:12', text: curRole().name + ' 关闭风险：' + note });
      refreshAll();
      closeModal();
      toast('风险已关闭，处理记录已留痕');
    });
  }

  function openTransfer(id) {
    var r = riskById(id); if (!r) return;
    var people = ['王强', '李敏', '赵磊', '周敏', '刘洋', '陈刚'].filter(function (p) { return p !== r.owner; });
    var m = openModal(
      '<div class="modal-head"><h3>转派风险</h3><p>转派后责任人和 SLA 重新计算，原负责人仍可在时间线中看到记录。</p>' +
      '<button class="icon-btn modal-close" data-close aria-label="关闭">' + icon('close') + '</button></div>' +
      '<div class="modal-body">' + riskSummaryHTML(r) +
      '<div class="form-row"><label>转派给</label><select id="transferTo">' + people.map(function (p) { return '<option>' + p + '</option>'; }).join('') + '</select></div>' +
      '<div class="form-row"><label>转派说明<small>可选</small></label><textarea id="transferNote" placeholder="说明转派原因，便于对方接手"></textarea></div></div>' +
      '<div class="modal-foot"><button class="btn" data-close>取消</button><button class="btn primary" id="transferConfirm">确认转派</button></div>'
    );
    m.querySelector('#transferConfirm').addEventListener('click', function () {
      var to = m.querySelector('#transferTo').value;
      var note = m.querySelector('#transferNote').value.trim();
      r.owner = to;
      r.status = '待认领';
      r.events.push({ t: '09:12', text: curRole().name + ' 转派给 ' + to + (note ? '：' + note : '') });
      refreshAll();
      closeModal();
      toast('已转派给 ' + to + '，等待对方认领');
    });
  }

  function openDrill(key) {
    var meta = D.KPI_META.filter(function (k) { return k.key === key; })[0];
    if (!meta) return;
    var arr = curRole().kpi[key];
    var rows = drillRows(key);
    var addType = key === 'sign' || key === 'leads';
    var tableHead = addType ? '<th>组织 / 团队</th><th>本期</th><th>占比</th><th>环比</th>' : '<th>组织 / 团队</th><th>本期</th><th>签约占比</th><th>环比</th>';
    var tableRows = rows.map(function (x) {
      return '<tr><td>' + esc(x.name) + '</td><td>' + esc(x.value) + '</td><td>' + x.share + '</td>' +
        '<td><span class="' + (x.mom >= 0 ? 'trend-up' : 'trend-down') + '">' + (x.mom >= 0 ? '+' : '') + x.mom.toFixed(1) + '%</span></td></tr>';
    }).join('');
    var m = openModal(
      '<div class="modal-head"><h3>' + esc(meta.label) + ' · 指标下钻</h3><p>' + esc(curRole().scope) + ' · 近 7 天走势与组织拆分</p>' +
      '<button class="icon-btn modal-close" data-close aria-label="关闭">' + icon('close') + '</button></div>' +
      '<div class="modal-body"><div class="drill-top"><div class="drill-value">' + fmt(arr[0], meta.decimals) + '<small>' + esc(meta.unit) + '</small></div>' +
      '<div class="drill-note">' + deltaHTML(arr, key) + '<span>' + esc(kpiSub(key)) + '</span></div></div>' +
      '<div class="drill-chart" id="drillChart"></div>' +
      '<div class="drill-formula">' + icon('info') + '<div><b>口径：</b>' + esc(meta.formula) + '<br><b>来源：</b>' + esc(meta.source) + '</div></div>' +
      '<div style="display:flex;justify-content:space-between;align-items:baseline;margin:14px 0 4px"><b style="font-size:11px">按' + (state.role === 'sm' ? '销售' : '组织') + '拆分</b><span style="font-size:9.5px;color:#8A94A4">按签约占比排序</span></div>' +
      '<table class="drill-table"><thead><tr>' + tableHead + '</tr></thead><tbody>' + tableRows + '</tbody></table></div>' +
      '<div class="modal-foot"><button class="btn primary" data-close>知道了</button></div>', true
    );
    drawSingle(m.querySelector('#drillChart'), kpiSeries(key).slice(-7), TREND_LABELS.slice(-7), meta.unit, '#2F5597', meta.label);
  }

  function openChannel(name) {
    var c = channels().filter(function (x) { return x.name === name; })[0];
    if (!c) return;
    var total = channels().reduce(function (a, x) { return a + x.sign; }, 0);
    var share = total ? Math.round(c.sign / total * 100) : 0;
    var tips = {
      '渠道伙伴': '伙伴带来的线索有效率与转化率都高，适合优先复制。建议把华东金伙伴计划做成标准包。',
      '老客转介绍': 'ROI 最高但规模有限，适合做存量客户激活，不建议作为唯一增长来源。',
      '信息流': '量最大但有效率最低，问题在表单质量而不是投放量。先修表单与去重，再加预算。',
      '自然搜索': '转化稳定，适合承接品牌词和行业词，建议保持现有预算。',
      '内容营销': '周期长、直接转化一般，但对商机覆盖有贡献，按季度看而不是按天看。'
    };
    openModal(
      '<div class="modal-head"><h3>' + esc(c.name) + ' · 渠道详情</h3><p>近 14 天 · 占全部签约 ' + share + '%</p>' +
      '<button class="icon-btn modal-close" data-close aria-label="关闭">' + icon('close') + '</button></div>' +
      '<div class="modal-body"><div class="facts">' +
      fact('线索量', fmt(c.leads) + ' 条') + fact('有效率', c.valid + '%') + fact('转化率', c.conv + '%') +
      fact('签约额', fmt(c.sign) + ' 万') + fact('营销 ROI', c.roi.toFixed(1) + 'x') + fact('环比', (c.wow >= 0 ? '+' : '') + c.wow.toFixed(1) + '%') +
      '</div><div class="drill-formula" style="margin-top:13px">' + icon('info') + '<div>' + esc(tips[c.name] || '建议结合线索质量与转化周期综合判断。') + '</div></div>' +
      '<div style="margin-top:14px"><div style="display:flex;justify-content:space-between;font-size:10px;color:#7B8698;margin-bottom:6px"><span>签约贡献</span><span>' + fmt(c.sign) + ' 万 / ' + fmt(total) + ' 万</span></div>' +
      '<div class="stack-bar" style="margin:0"><i class="closed" style="width:' + share + '%"></i><i class="open" style="width:' + (100 - share) + '%"></i></div></div></div>' +
      '<div class="modal-foot"><button class="btn" data-close>关闭</button></div>'
    );
  }

  function openQuality() {
    openModal(
      '<div class="modal-head"><h3>数据质量</h3><p>今日 07:15 校验 · 12 项指标全部可用，2 条口径提醒</p>' +
      '<button class="icon-btn modal-close" data-close aria-label="关闭">' + icon('close') + '</button></div>' +
      '<div class="modal-body"><div class="facts">' +
      fact('抽取完成', '06:00') + fact('清洗完成', '06:15') + fact('指标完成', '06:45') + fact('校验完成', '07:15') +
      '</div><table class="drill-table" style="margin-top:14px"><thead><tr><th>检查项</th><th>结果</th><th>说明</th></tr></thead><tbody>' +
      '<tr><td>指标完整性</td><td><span class="tag green">通过</span></td><td>12 / 12</td></tr>' +
      '<tr><td>线索去重</td><td><span class="tag green">通过</span></td><td>重复率 1.8%</td></tr>' +
      '<tr><td>目标表版本</td><td><span class="tag yellow">提醒</span></td><td>华东目标人工调整未备注</td></tr>' +
      '<tr><td>手机号校验</td><td><span class="tag yellow">提醒</span></td><td>3 条线索疑似重复</td></tr>' +
      '</tbody></table><div class="why-note">提醒项不影响日报生成，但建议在 12:00 前由数据管理员确认。</div></div>' +
      '<div class="modal-foot"><button class="btn primary" data-close>知道了</button></div>'
    );
  }

  function openSettings() {
    var m = openModal(
      '<div class="modal-head"><h3>简报设置</h3><p>仅影响当前账号的展示，不改变组织级规则。</p>' +
      '<button class="icon-btn modal-close" data-close aria-label="关闭">' + icon('close') + '</button></div>' +
      '<div class="modal-body">' +
      '<div class="form-row"><label>默认落地页</label><select id="setLanding"><option>今日简报</option><option>风险中心</option></select></div>' +
      '<div class="form-row"><label>简报推送时间</label><input type="time" value="08:30"></div>' +
      '<label class="check-line"><input type="checkbox" checked> 桌面通知：红色风险到期前 1 小时提醒</label>' +
      '<label class="check-line"><input type="checkbox" checked> 每周一 08:00 接收周报摘要</label>' +
      '<label class="check-line"><input type="checkbox"> 紧凑模式：隐藏 KPI 卡片说明</label></div>' +
      '<div class="modal-foot"><button class="btn" data-close>取消</button><button class="btn primary" id="setSave">保存设置</button></div>'
    );
    m.querySelector('#setSave').addEventListener('click', function () {
      closeModal();
      toast('设置已保存（演示环境不持久化）');
    });
  }

  function openTour() {
    var steps = [
      ['切换角色', '右上角切换 4 个角色，看结论、指标、风险范围如何随权限变化。'],
      ['点开指标', '点任意 KPI 卡片，查看口径、14 天走势和组织拆分。'],
      ['处理风险', '在风险中心筛选红色风险，认领后填写处理计划。'],
      ['看证据链', '打开风险详情，核对“为什么报”的阈值与建议动作。'],
      ['复盘与触达', '查看周报复盘，再打开手机预览，看钉钉 / 企微里的样子。']
    ];
    var body = steps.map(function (s, i) {
      return '<div class="priority-item" style="border-top:' + (i ? '1px dashed #E7EBF1' : '0') + '">' +
        '<span class="pnum">' + (i + 1) + '</span><span><b>' + s[0] + '</b><br><span style="color:#7B8698;font-size:10.5px">' + s[1] + '</span></span></div>';
    }).join('');
    openModal(
      '<div class="modal-head"><h3>5 分钟演示导览</h3><p>按这条路径，可以看完“简报 → 风险 → 认领 → 复盘”的完整闭环。</p>' +
      '<button class="icon-btn modal-close" data-close aria-label="关闭">' + icon('close') + '</button></div>' +
      '<div class="modal-body"><div class="priority-card" style="padding:0">' + body + '</div>' +
      '<div class="why-note">所有数据均为模拟数据，不连接真实系统。</div></div>' +
      '<div class="modal-foot"><button class="btn" data-close>稍后再看</button><button class="btn primary" data-close>开始体验</button></div>', true
    );
  }

  /* ---------------- 手机预览 ---------------- */
  function renderPhone() {
    var r = curRole();
    var tab = state.phoneTab;
    var title = tab === 'brief' ? '今日简报' : tab === 'risks' ? '风险中心' : '我的';
    var html = '<div class="ph-status"><span>9:41</span><span>●●●&nbsp;&nbsp;▮</span></div>' +
      '<div class="ph-head"><div><h3>' + title + '</h3><small>10/24 周六 · ' + esc(r.scope) + '</small></div>' +
      '<span class="ph-role">' + esc(r.title) + '</span></div><div class="ph-scroll">';

    if (tab === 'brief') {
      html += '<div class="ph-card ph-concl"><h4><i>1</i>今日 3 条结论</h4><ol>';
      r.conclusions.forEach(function (c) { html += '<li>' + esc(c.text) + '</li>'; });
      html += '</ol></div><div class="ph-kpis">';
      ['sign', 'rate', 'leads', 'roi'].forEach(function (key) {
        var meta = D.KPI_META.filter(function (k) { return k.key === key; })[0];
        var a = r.kpi[key];
        html += '<div class="ph-kpi"><div class="k">' + esc(meta.label) + '</div><div class="v">' + fmt(a[0], meta.decimals) + '<small>' + esc(meta.unit) + '</small></div>' +
          '<div class="d"><span class="delta ' + a[3] + '" style="font-size:7px">' + (a[2] === 'up' ? '↑' : '↓') + ' ' + esc(a[1]) + '</span></div></div>';
      });
      html += '</div><div class="ph-sec"><b>Top3 风险</b><span>按级别 · SLA</span></div>';
      var top = openRisks().slice().sort(function (a, b) { return LEVELS[b.level].weight - LEVELS[a.level].weight || a.remain - b.remain; }).slice(0, 3);
      top.forEach(function (risk) {
        var lv = levelOf(risk);
        html += '<div class="ph-risk"><span class="bar ' + lv.cls + '"></span><div class="rmain"><div class="rt">' + esc(risk.title) + '</div>' +
          '<div class="rm">' + lv.label + ' · ' + esc(risk.type) + ' · ' + esc(risk.owner) + '</div>' +
          '<div class="rf"><span class="rsla">' + (risk.overdue ? esc(risk.sla) : '剩 ' + esc(risk.sla)) + '</span>' +
          '<button data-act="phone-risk" data-id="' + risk.id + '">去处理</button></div></div></div>';
      });
      html += '<div style="text-align:center;font-size:7.5px;color:#98A2B3;padding:4px 0 8px">数据截至 08:00 · 点击数字可下钻</div>';
    } else if (tab === 'risks') {
      var vis = visibleRisks();
      html += '<div class="ph-kpis" style="grid-template-columns:repeat(3,1fr)">' +
        '<div class="ph-kpi"><div class="k">待认领</div><div class="v" style="font-size:16px">' + vis.filter(function (x) { return x.status === '待认领'; }).length + '</div></div>' +
        '<div class="ph-kpi"><div class="k">处理中</div><div class="v" style="font-size:16px">' + vis.filter(function (x) { return x.status === '处理中'; }).length + '</div></div>' +
        '<div class="ph-kpi"><div class="k">已超时</div><div class="v" style="font-size:16px;color:#C0392B">' + vis.filter(function (x) { return x.status === '已超时'; }).length + '</div></div></div>';
      html += '<div class="ph-sec"><b>全部风险</b><span>' + vis.length + ' 条</span></div>';
      vis.filter(function (x) { return x.status !== '已关闭'; }).forEach(function (risk) {
        var lv = levelOf(risk);
        html += '<div class="ph-risk"><span class="bar ' + lv.cls + '"></span><div class="rmain"><div class="rt">' + esc(risk.title) + '</div>' +
          '<div class="rm">' + esc(risk.type) + ' · ' + esc(risk.owner) + ' · ' + esc(risk.status) + '</div>' +
          '<div class="rf"><span class="rsla">' + (risk.overdue ? esc(risk.sla) : '剩 ' + esc(risk.sla)) + '</span>' +
          '<button data-act="phone-risk" data-id="' + risk.id + '">查看</button></div></div></div>';
      });
    } else {
      html += '<div class="ph-profile"><div class="pa">' + esc(r.avatar) + '</div><b>' + esc(r.name) + '</b><p>' + esc(r.title) + ' · ' + esc(r.scope) + '</p></div>' +
        '<div class="ph-card" style="margin-top:10px"><div class="ph-sec" style="margin:0 0 4px"><b>我的权限</b></div>' +
        '<div class="ph-perm"><div><span>数据范围</span><b>' + esc(r.scope) + '</b></div>' +
        '<div><span>可看风险</span><b>' + visibleRisks().length + ' 条</b></div>' +
        '<div><span>可处理</span><b>认领 / 转派 / 关闭</b></div>' +
        '<div><span>导出权限</span><b>PDF / Excel</b></div></div></div>' +
        '<div class="ph-card"><div class="ph-sec" style="margin:0 0 4px"><b>消息设置</b></div>' +
        '<div class="ph-perm"><div><span>晨间简报</span><b>08:30</b></div><div><span>风险提醒</span><b>已开启</b></div></div></div>';
    }
    html += '</div><div class="ph-tabbar">' +
      phTab('brief', '简报', 'brief') + phTab('risks', '风险', 'risk') + phTab('me', '我的', 'user') +
      '</div>';
    document.getElementById('phoneScreen').innerHTML = html;
  }
  function phTab(key, label, ico) {
    return '<button class="ph-tab' + (state.phoneTab === key ? ' on' : '') + '" data-act="phone-tab" data-tab="' + key + '">' + icon(ico) + label + '</button>';
  }
  function openPhone() {
    state.phoneTab = 'brief';
    renderPhone();
    phoneOverlay.classList.add('open');
    phoneOverlay.setAttribute('aria-hidden', 'false');
    lockScroll();
  }
  function closePhone() {
    phoneOverlay.classList.remove('open');
    phoneOverlay.setAttribute('aria-hidden', 'true');
    unlockScroll();
  }

  /* ---------------- 全局刷新 ---------------- */
  function syncRoleUI() {
    var r = curRole();
    document.getElementById('roleAvatar').textContent = r.avatar;
    document.getElementById('roleName').textContent = r.name;
    document.getElementById('roleTitle').textContent = r.title + ' · ' + r.scope;
    document.querySelectorAll('.role-option').forEach(function (b) {
      b.classList.toggle('active', b.dataset.role === state.role);
    });
    document.getElementById('crumbPage').textContent = PAGE_NAMES[state.page];
    document.querySelectorAll('.nav-item').forEach(function (b) {
      b.classList.toggle('active', b.dataset.page === state.page);
    });
    navBadge.textContent = openRisks().length;
    navBadge.style.display = openRisks().length ? '' : 'none';
  }

  function render() {
    syncRoleUI();
    if (state.page === 'brief') content.innerHTML = briefHTML();
    else if (state.page === 'risks') content.innerHTML = riskPageHTML();
    else if (state.page === 'weekly') content.innerHTML = weeklyHTML();
    else content.innerHTML = rulesHTML();

    bindPage();
    if (state.page === 'brief' && state.trendView === 'chart') drawTrend();
    if (state.page === 'weekly') { drawRanking(); renderTypeBars(); }
    if (location.hash !== '#' + state.page) history.replaceState(null, '', '#' + state.page);
  }

  function refreshAll() {
    render();
    if (currentRiskId) {
      var r = riskById(currentRiskId);
      if (r && r.visibleTo.indexOf(state.role) > -1) {
        drawer.innerHTML = drawerHTML(r);
      } else {
        closeDrawer();
      }
    }
  }

  function bindPage() {
    var search = document.getElementById('fSearch');
    if (search) {
      var timer = null;
      search.addEventListener('input', function () {
        clearTimeout(timer);
        var val = search.value;
        timer = setTimeout(function () {
          state.q = val;
          var card = document.getElementById('riskTableCard');
          if (card) card.outerHTML = riskTableHTML();
        }, 180);
      });
    }
    ['fType', 'fOwner', 'fStatus'].forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      el.addEventListener('change', function () {
        if (id === 'fType') state.type = el.value;
        if (id === 'fOwner') state.owner = el.value;
        if (id === 'fStatus') state.status = el.value;
        var card = document.getElementById('riskTableCard');
        if (card) card.outerHTML = riskTableHTML();
        document.querySelectorAll('.stat-card').forEach(function (c) {
          c.classList.toggle('active', c.dataset.status === state.status);
        });
      });
    });
  }

  /* ---------------- Toast ---------------- */
  function toast(msg) {
    var el = document.createElement('div');
    el.className = 'toast';
    el.innerHTML = '<span class="tic">' + icon('check') + '</span><span>' + esc(msg) + '</span>';
    toastWrap.appendChild(el);
    setTimeout(function () {
      el.classList.add('out');
      setTimeout(function () { el.remove(); }, 220);
    }, 2600);
  }

  /* ---------------- 菜单 ---------------- */
  function closeRoleMenu() {
    document.getElementById('roleMenu').classList.remove('open');
    var btn = document.querySelector('[data-act="role-menu"]');
    if (btn) btn.setAttribute('aria-expanded', 'false');
  }
  function closeNotify() {
    document.getElementById('notifyPop').classList.remove('open');
  }

  /* ---------------- 事件 ---------------- */
  document.getElementById('nav').addEventListener('click', function (e) {
    var btn = e.target.closest('.nav-item');
    if (!btn) return;
    state.page = btn.dataset.page;
    state.level = 'all';
    state.type = 'all';
    state.owner = 'all';
    state.q = '';
    if (location.hash !== '#' + state.page) history.replaceState(null, '', '#' + state.page);
    window.scrollTo(0, 0);
    render();
  });

  document.querySelector('[data-act="role-menu"]').addEventListener('click', function () {
    var menu = document.getElementById('roleMenu');
    menu.classList.toggle('open');
    this.setAttribute('aria-expanded', menu.classList.contains('open') ? 'true' : 'false');
    closeNotify();
  });

  document.querySelectorAll('.role-option').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var next = btn.dataset.role;
      if (next === state.role) { closeRoleMenu(); return; }
      state.role = next;
      state.level = 'all'; state.status = 'all'; state.type = 'all'; state.owner = 'all'; state.q = '';
      closeRoleMenu();
      closeDrawer();
      closeModal();
      render();
      window.scrollTo(0, 0);
      var r = curRole();
      toast('已切换到 ' + r.title + ' · ' + r.scope + '，数据范围已同步');
    });
  });

  drawerMask.addEventListener('click', closeDrawer);
  modalRoot.addEventListener('click', function (e) { if (e.target === modalRoot) closeModal(); });
  phoneOverlay.addEventListener('click', function (e) { if (e.target === phoneOverlay) closePhone(); });

  document.addEventListener('click', function (e) {
    if (!e.target.closest('.role-wrap')) closeRoleMenu();
    if (!e.target.closest('.pop-wrap')) closeNotify();
  });

  document.addEventListener('click', function (e) {
    var el = e.target.closest('[data-act]');
    if (!el) return;
    var act = el.dataset.act;
    var id = el.dataset.id;

    if (act === 'role-menu') return;
    if (act === 'export') {
      toast((state.page === 'weekly' ? '周报' : state.page === 'risks' ? '风险清单' : '今日简报') + '已生成 PDF（演示）');
      return;
    }
    if (act === 'phone') { openPhone(); return; }
    if (act === 'close-phone') { closePhone(); return; }
    if (act === 'phone-tab') { state.phoneTab = el.dataset.tab; renderPhone(); return; }
    if (act === 'phone-risk') {
      var pid = el.dataset.id;
      closePhone();
      state.page = 'risks'; state.level = 'all'; state.status = 'all'; state.type = 'all'; state.owner = 'all'; state.q = '';
      render();
      openDrawer(pid);
      return;
    }
    if (act === 'notify') { document.getElementById('notifyPop').classList.toggle('open'); closeRoleMenu(); return; }
    if (act === 'notify-risk') { closeNotify(); state.page = 'risks'; render(); openDrawer('R-20261024-018'); return; }
    if (act === 'notify-week') { closeNotify(); state.page = 'weekly'; render(); return; }
    if (act === 'notify-data') { closeNotify(); openQuality(); return; }
    if (act === 'settings') { openSettings(); return; }
    if (act === 'tour') { openTour(); return; }
    if (act === 'quality') { openQuality(); return; }
    if (act === 'goto-risks') { state.page = 'risks'; render(); window.scrollTo(0, 0); return; }
    if (act === 'goto-weekly') { state.page = 'weekly'; render(); window.scrollTo(0, 0); return; }
    if (act === 'conclusion') {
      var lv = el.dataset.level;
      if (lv === 'green') { state.page = 'weekly'; }
      else { state.page = 'risks'; state.level = lv; state.status = 'all'; }
      render(); window.scrollTo(0, 0);
      return;
    }
    if (act === 'kpi') { openDrill(el.dataset.kpi); return; }
    if (act === 'risk') { openDrawer(id); return; }
    if (act === 'claim') { openClaim(id); return; }
    if (act === 'close-risk') { openClose(id); return; }
    if (act === 'transfer') { openTransfer(id); return; }
    if (act === 'drawer-close') { closeDrawer(); return; }
    if (act === 'view-log') {
      var rr = riskById(id);
      toast(rr && rr.closeNote ? '处理记录：' + rr.closeNote : '暂无更多处理记录');
      return;
    }
    if (act === 'level') { state.level = el.dataset.level; state.status = 'all'; render(); return; }
    if (act === 'stat') { state.status = el.dataset.status; render(); return; }
    if (act === 'reset') { state.level = 'all'; state.status = 'all'; state.type = 'all'; state.owner = 'all'; state.q = ''; render(); return; }
    if (act === 'sort') {
      var key = el.dataset.key;
      if (state.sortKey === key) state.sortDir = state.sortDir === 'desc' ? 'asc' : 'desc';
      else { state.sortKey = key; state.sortDir = 'desc'; }
      render();
      return;
    }
    if (act === 'refresh') { render(); toast('已刷新，数据批次仍为 10-24 08:00'); return; }
    if (act === 'trend-view') { state.trendView = el.dataset.view; render(); return; }
    if (act === 'week') { state.week = el.dataset.week; render(); return; }
    if (act === 'channel') { openChannel(el.dataset.name); return; }
    if (act === 'channel-more') { state.page = 'weekly'; render(); toast('渠道明细已汇总到周报复盘（演示）'); return; }
    if (act === 'rule-toggle') {
      var rule = stateRules.filter(function (x) { return x.id === id; })[0];
      if (rule) { rule.on = !rule.on; render(); toast('规则「' + rule.name + '」已' + (rule.on ? '启用' : '停用') + '（演示）'); }
      return;
    }
    if (act === 'rules-save') { toast('配置已保存，次日 06:00 批次生效（演示）'); return; }
    if (act === 'add-rule') { toast('演示版仅展示已有 6 条规则，新增入口保留'); return; }
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      if (phoneOverlay.classList.contains('open')) { closePhone(); return; }
      if (modalRoot.classList.contains('open')) { closeModal(); return; }
      if (drawer.classList.contains('open')) { closeDrawer(); return; }
      closeRoleMenu(); closeNotify();
    }
  });

  var resizeTimer = null;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      if (state.page === 'brief' && state.trendView === 'chart') drawTrend();
      if (state.page === 'weekly') drawRanking();
    }, 120);
  });

  /* ---------------- 启动 ---------------- */
  var params = new URLSearchParams(location.search);
  var qRole = params.get('role');
  if (qRole && D.ROLES[qRole]) state.role = qRole;
  var qPage = params.get('page') || location.hash.replace('#', '');
  if (PAGE_NAMES[qPage]) state.page = qPage;
  if (params.get('week') === 'last') state.week = 'last';
  render();
  var qOpen = params.get('open');
  if (qOpen && riskById(qOpen) && riskById(qOpen).visibleTo.indexOf(state.role) > -1) {
    setTimeout(function () { openDrawer(qOpen); }, 60);
  }
  if (params.get('phone') === '1') setTimeout(openPhone, 80);
  if (params.get('tour') === '1') setTimeout(openTour, 120);
  setTimeout(function () { toast('演示数据已加载：右上角可切换角色，查看不同权限视图'); }, 700);
})();
