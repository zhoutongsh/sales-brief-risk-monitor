/* 演示数据：全部为模拟数据，仅用于产品原型展示 */
window.DEMO = (function () {
  'use strict';

  var KPI_META = [
    {
      key: 'sign', label: '今日签约额', unit: '万', decimals: 1,
      sub: '日目标 442 万', formula: 'CRM 合同审批通过金额，按签约日期归集；退款、作废合同不计入。',
      source: 'CRM · 合同表'
    },
    {
      key: 'rate', label: '本月目标完成率', unit: '%', decimals: 1,
      sub: '时间进度 80.0%', formula: '本月累计签约额 ÷ 本月目标；时间进度 = 已过工作日 ÷ 本月工作日。',
      source: 'CRM + 目标表'
    },
    {
      key: 'leads', label: '今日新增线索', unit: '条', decimals: 0,
      sub: '有效线索 214 条', formula: 'CRM 新建线索去重后按创建日期归集；标记无效的线索不计入有效数。',
      source: 'CRM · 线索表'
    },
    {
      key: 'roi', label: '营销 ROI', unit: 'x', decimals: 1,
      sub: '营销费用 89.3 万', formula: '营销归因签约额 ÷ 营销费用；归因窗口 90 天，跨渠道按最后触点归因。',
      source: 'CRM + 投放平台'
    },
    {
      key: 'cover', label: '商机覆盖率', unit: 'x', decimals: 1,
      sub: '健康线 ≥ 3.0 倍', formula: '在谈商机金额 ÷ 剩余目标；健康线 3 倍，低于 2 倍为红色。',
      source: 'CRM · 商机表'
    },
    {
      key: 'collect', label: '回款完成率', unit: '%', decimals: 1,
      sub: '逾期应收 1,240 万', formula: '本月累计回款 ÷ 本月回款目标；逾期应收按合同约定日期计算。',
      source: 'ERP · 应收表'
    }
  ];

  var ROLES = {
    gm: {
      key: 'gm', name: '张建国', honorific: '张总', title: '公司总经理', scope: '全公司', avatar: '张',
      kpi: {
        sign: [428.6, '+12.4%', 'up', 'good'],
        rate: [78.2, '-1.8pp', 'down', 'bad'],
        leads: [326, '+18.6%', 'up', 'good'],
        roi: [4.8, '+0.3', 'up', 'good'],
        cover: [2.7, '-0.3', 'down', 'bad'],
        collect: [71.5, '-6.2pp', 'down', 'bad']
      },
      conclusions: [
        { level: 'orange', tag: '目标缺口', text: '华东事业部本月签约缺口 186 万，完成率 78.0%，月底前需日均多签 18 万。' },
        { level: 'yellow', tag: '线索异常', text: '信息流线索有效率降至 41%，环比 -12pp，预计影响下周约 60 条有效线索。' },
        { level: 'red', tag: '大客户流失', text: '恒远科技 320 万商机 32 天未跟进，已触发红色预警，SLA 仅剩 2 小时 18 分。' }
      ],
      weekly: { sign: 3186, wow: 8.4, leads: 2214, closure: 86, newRisks: 68, closedRisks: 61, avgDays: 1.8 },
      ranking: [
        { name: '华东一部', rate: 104 }, { name: '华东二部', rate: 96 }, { name: '华南大区', rate: 91 },
        { name: '华北大区', rate: 84 }, { name: '西部大区', rate: 76 }
      ],
      priorities: ['补齐华东事业部 186 万缺口，周五前看到日进度', '压降信息流无效线索，把有效率拉回 50% 以上', '盯紧 3 个百万级商机，红色风险当日清零']
    },
    sd: {
      key: 'sd', name: '李敏', honorific: '李总', title: '销售总监', scope: '全公司销售', avatar: '李',
      kpi: {
        sign: [392.4, '+9.8%', 'up', 'good'],
        rate: [76.5, '-3.5pp', 'down', 'bad'],
        leads: [301, '+14.2%', 'up', 'good'],
        roi: [4.6, '+0.2', 'up', 'good'],
        cover: [2.6, '-0.4', 'down', 'bad'],
        collect: [69.8, '-7.1pp', 'down', 'bad']
      },
      conclusions: [
        { level: 'red', tag: '大客户流失', text: '恒远科技与宏达集团两条红色风险将在 4 小时内到期，需今天上午完成认领。' },
        { level: 'orange', tag: '业绩下滑', text: '华南、华北今日签约均低于日目标，合计缺口 63 万，周达成率 91%。' },
        { level: 'green', tag: '渠道机会', text: '渠道伙伴 ROI 6.8 居首，建议下周追加 15% 预算，重点复制华东金伙伴计划。' }
      ],
      weekly: { sign: 2912, wow: 6.2, leads: 1986, closure: 84, newRisks: 61, closedRisks: 52, avgDays: 1.9 },
      ranking: [
        { name: '华东一部', rate: 104 }, { name: '华东二部', rate: 96 }, { name: '华南大区', rate: 91 },
        { name: '华北大区', rate: 84 }, { name: '西部大区', rate: 76 }
      ],
      priorities: ['两条红色风险今天 12:00 前完成认领并给出方案', '华南、华北逐日复盘，追回 63 万缺口', '渠道预算追加方案周四前报总经理']
    },
    bu: {
      key: 'bu', name: '王强', honorific: '王总', title: '华东事业部总经理', scope: '华东事业部', avatar: '王',
      kpi: {
        sign: [156.8, '+6.2%', 'up', 'good'],
        rate: [78.0, '-2.0pp', 'down', 'bad'],
        leads: [118, '+11.5%', 'up', 'good'],
        roi: [4.4, '+0.1', 'up', 'good'],
        cover: [2.4, '-0.6', 'down', 'bad'],
        collect: [66.2, '-4.8pp', 'down', 'bad']
      },
      conclusions: [
        { level: 'orange', tag: '目标缺口', text: '事业部本月缺口 186 万，华东三部完成率 71.2%，是主要拖累项。' },
        { level: 'red', tag: '大客户流失', text: '恒远科技 320 万商机 32 天未跟进，负责人李娜，SLA 剩 2 小时 18 分。' },
        { level: 'yellow', tag: '商机覆盖', text: '华东一部商机覆盖仅 2.3 倍，低于 3 倍红线，本周需新增 6 条有效商机。' }
      ],
      weekly: { sign: 1156, wow: 4.1, leads: 784, closure: 88, newRisks: 24, closedRisks: 21, avgDays: 1.7 },
      ranking: [
        { name: '华东一部', rate: 104 }, { name: '华东二部', rate: 96 }, { name: '华东三部', rate: 88 },
        { name: '华东四部', rate: 81 }
      ],
      priorities: ['恒远科技今天安排拜访，红色风险当日闭环', '华东三部逐单过商机，周五前补齐 48 万', '华东一部本周新增 6 条有效商机']
    },
    sm: {
      key: 'sm', name: '李娜', honorific: '李娜', title: '华东一部销售经理', scope: '华东一部', avatar: '李',
      kpi: {
        sign: [42.6, '+8.4%', 'up', 'good'],
        rate: [82.4, '+2.4pp', 'up', 'good'],
        leads: [36, '+22.0%', 'up', 'good'],
        roi: [5.1, '+0.4', 'up', 'good'],
        cover: [2.3, '-0.7', 'down', 'bad'],
        collect: [74.0, '-3.6pp', 'down', 'bad']
      },
      conclusions: [
        { level: 'green', tag: '达成情况', text: '一部今日签约 42.6 万，环比 +8.4%，日目标完成 96.8%；本月完成率 82.4%，高于时间进度。' },
        { level: 'red', tag: '大客户流失', text: '恒远科技 320 万商机 32 天未跟进，红色预警，需今天 12:00 前联系。' },
        { level: 'yellow', tag: '商机覆盖', text: '组内商机覆盖 2.3 倍，低于 3 倍红线，本周还需补 6 条有效商机。' }
      ],
      weekly: { sign: 318, wow: 11.2, leads: 226, closure: 92, newRisks: 7, closedRisks: 6, avgDays: 1.2 },
      ranking: [
        { name: '李娜', rate: 112 }, { name: '周涛', rate: 98 }, { name: '陈晨', rate: 91 },
        { name: '孙浩', rate: 84 }, { name: '王芳', rate: 72 }
      ],
      priorities: ['恒远科技今天 12:00 前电话 + 48 小时内拜访', '本周新增 6 条有效商机，补到 3 倍覆盖', '组内 5 条未联系线索今天清零']
    }
  };

  var RISKS = [
    {
      id: 'R-20261024-018', level: 'red', type: '大客户流失', title: '恒远科技 30 天未跟进',
      object: '恒远科技', amount: 320, owner: '李娜', org: '华东事业部', dept: '华东一部',
      status: '待认领', created: '08:30', sla: '2h18m', remain: 138, overdue: false,
      visibleTo: ['gm', 'sd', 'bu', 'sm'],
      why: [['最后跟进距今天数', '32 天（阈值 ≥30 天）'], ['商机阶段停留', '方案确认 · 18 天未推进'], ['客户活跃度', '低于同组 72%']],
      actions: ['今天 12:00 前电话确认预算与决策人', '48 小时内安排现场拜访', '无进展则转交事业部总经理介入'],
      related: [['恒远科技 · 智能仓储', '320 万 / 方案确认'], ['恒远科技 · 二期扩容', '80 万 / 初步接触']]
    },
    {
      id: 'R-20261024-017', level: 'red', type: '订单 / 回款', title: '宏达集团回款逾期 18 天',
      object: '宏达集团', amount: 320, owner: '赵磊', org: '华南大区', dept: '华南一部',
      status: '待认领', created: '08:31', sla: '3h05m', remain: 185, overdue: false,
      visibleTo: ['gm', 'sd'],
      why: [['应收逾期天数', '18 天（阈值 >15 天）'], ['逾期金额', '320 万，占客户应收 64%'], ['最近承诺回款日', '10 月 6 日，已违约 2 次']],
      actions: ['今天联系对方财务确认付款排期', '发出书面催收函并抄送销售总监', '本周内给出分期回款计划'],
      related: [['合同 HT-2025-118', '320 万 / 已验收'], ['历史回款准时率', '近 12 个月 58%']]
    },
    {
      id: 'R-20261024-016', level: 'orange', type: '目标缺口', title: '华东事业部签约缺口 186 万',
      object: '华东事业部', amount: 186, owner: '王强', org: '华东事业部', dept: '事业部',
      status: '处理中', created: '08:30', sla: '5h42m', remain: 342, overdue: false,
      visibleTo: ['gm', 'sd', 'bu'],
      why: [['本月完成率', '78.0%（时间进度 80.0%）'], ['缺口金额', '186 万，需日均多签 18 万'], ['下属组织', '华东三部完成率 71.2%，拖累最大']],
      actions: ['今天拆解到 3 个部门，明确每日补口目标', '盘点 9 个 B 类商机，挑 3 个提前签约', '周五前申请一次专项促销资源'],
      related: [['华东事业部月目标', '846 万'], ['在谈商机', '2,140 万 / 覆盖率 2.5 倍']]
    },
    {
      id: 'R-20261024-015', level: 'orange', type: '商机覆盖', title: '华南大区商机覆盖不足 2.1 倍',
      object: '华南大区', amount: 0, owner: '周敏', org: '华南大区', dept: '大区',
      status: '待认领', created: '08:32', sla: '6h20m', remain: 380, overdue: false,
      visibleTo: ['gm', 'sd'],
      why: [['商机覆盖率', '2.1 倍（健康线 ≥3 倍）'], ['在谈商机', '1,260 万，剩余目标 600 万'], ['新增商机', '本周仅 8 条，环比 -38%']],
      actions: ['下周新增 20 条有效商机', '启动 3 场行业沙龙补量', '把覆盖率纳入周会固定议题'],
      related: [['华南大区月目标', '600 万'], ['本周新增商机', '8 条']]
    },
    {
      id: 'R-20261024-014', level: 'yellow', type: '线索异常', title: '信息流线索有效率跌至 41%',
      object: '信息流渠道', amount: 0, owner: '陈晨', org: '市场部', dept: '数字营销',
      status: '处理中', created: '08:33', sla: '18h', remain: 1080, overdue: false,
      visibleTo: ['gm', 'sd', 'bu', 'sm'],
      why: [['线索有效率', '41%（阈值 ≥50%）'], ['环比变化', '-12pp，连续 3 天下降'], ['无效原因', '重复提交 38%、空号 27%']],
      actions: ['今天暂停 2 个低质投放计划', '加严表单必填与手机号校验', '把有效率纳入投放日报'],
      related: [['信息流本月线索', '1,286 条'], ['信息流签约', '1,260 万 / ROI 3.9']]
    },
    {
      id: 'R-20261024-013', level: 'yellow', type: '业绩下滑', title: '华东三部周签约环比 -21%',
      object: '华东三部', amount: 78, owner: '孙浩', org: '华东事业部', dept: '华东三部',
      status: '待认领', created: '08:34', sla: '20h', remain: 1200, overdue: false,
      visibleTo: ['gm', 'sd', 'bu'],
      why: [['本周签约', '78 万，环比 -21%'], ['周目标完成率', '62%，低于 80% 红线'], ['连续下滑', '已连续 2 周下降']],
      actions: ['逐个过 5 个重点商机，找出卡点', '安排一次老客复购专项', '周五前提交追赶计划'],
      related: [['华东三部周目标', '126 万'], ['负责人', '孙浩']]
    },
    {
      id: 'R-20261024-012', level: 'orange', type: '目标缺口', title: '华北大区完成率仅 68.9%',
      object: '华北大区', amount: 142, owner: '刘洋', org: '华北大区', dept: '大区',
      status: '已超时', created: '08:30', sla: '超时 3h', remain: -180, overdue: true,
      visibleTo: ['gm', 'sd'],
      why: [['本月完成率', '68.9%（时间进度 80.0%）'], ['缺口金额', '142 万'], ['红色客户', '2 个百万级商机停滞']],
      actions: ['今天组织华北周中复盘', '两个红区商机由大区总直接跟', '申请总部方案专家支持'],
      related: [['华北大区月目标', '457 万'], ['在谈商机', '980 万 / 覆盖率 2.1 倍']]
    },
    {
      id: 'R-20261024-011', level: 'yellow', type: '商机覆盖', title: '华东一部商机覆盖 2.3 倍',
      object: '华东一部', amount: 0, owner: '李娜', org: '华东事业部', dept: '华东一部',
      status: '待认领', created: '08:35', sla: '22h', remain: 1320, overdue: false,
      visibleTo: ['gm', 'sd', 'bu', 'sm'],
      why: [['商机覆盖率', '2.3 倍（健康线 ≥3 倍）'], ['在谈商机', '410 万，剩余目标 178 万'], ['本周新增', '仅 2 条有效商机']],
      actions: ['本周新增 6 条有效商机', '从 32 家老客户中筛 5 家复购', '把商机补量拆到每人每天'],
      related: [['华东一部月目标', '244 万'], ['组内人数', '5 人']]
    },
    {
      id: 'R-20261024-010', level: 'yellow', type: '线索异常', title: '华东一部线索有效率 38%',
      object: '华东一部线索池', amount: 0, owner: '李娜', org: '华东事业部', dept: '华东一部',
      status: '处理中', created: '08:36', sla: '1d 2h', remain: 1560, overdue: false,
      visibleTo: ['gm', 'sd', 'bu', 'sm'],
      why: [['线索有效率', '38%（阈值 ≥50%）'], ['环比变化', '-9pp'], ['主要来源', '官网表单重复提交 31%']],
      actions: ['上线表单去重规则', '今天回访 20 条未联系线索', '把无效原因同步市场部'],
      related: [['本周线索', '86 条'], ['有效线索', '33 条']]
    },
    {
      id: 'R-20261024-009', level: 'yellow', type: '业绩下滑', title: '华南二部周签约环比 -15%',
      object: '华南二部', amount: 56, owner: '赵磊', org: '华南大区', dept: '华南二部',
      status: '已关闭', created: '08:30', sla: '—', remain: 0, overdue: false,
      visibleTo: ['gm', 'sd'], closeNote: '已补齐 2 个商机，周目标回到 92%',
      why: [['本周签约', '56 万，环比 -15%'], ['周目标完成率', '71%'], ['连续下滑', '1 周']],
      actions: ['复盘 3 个丢单原因', '补充 5 条 A 类商机', '跟催 2 笔应收'], related: []
    },
    {
      id: 'R-20261024-008', level: 'orange', type: '订单 / 回款', title: '西部大区应收逾期率 12.4%',
      object: '西部大区', amount: 210, owner: '陈刚', org: '西部大区', dept: '大区',
      status: '已关闭', created: '08:30', sla: '—', remain: 0, overdue: false,
      visibleTo: ['gm', 'sd'], closeNote: '完成 3 笔逾期回款，逾期率降至 8.1%',
      why: [['应收逾期率', '12.4%（阈值 >10%）'], ['逾期金额', '210 万'], ['涉及客户', '6 家，最长逾期 41 天']],
      actions: ['逐户确认付款计划', '对 2 家高风险客户暂停发货', '把回款纳入销售周会'], related: []
    },
    {
      id: 'R-20261024-007', level: 'yellow', type: '大客户流失', title: '华北重点客户 21 天未联系',
      object: '中科智造', amount: 96, owner: '刘洋', org: '华北大区', dept: '华北一部',
      status: '处理中', created: '08:37', sla: '16h', remain: 960, overdue: false,
      visibleTo: ['gm', 'sd'],
      why: [['最后联系距今天数', '21 天（阈值 ≥14 天）'], ['客户等级', 'A 级 / 年签约 96 万'], ['商机阶段', '商务谈判 · 停滞']],
      actions: ['今天电话联系客户副总', '本周安排一次现场拜访', '同步更新商机阶段'],
      related: [['中科智造 · 产线改造', '96 万 / 商务谈判']]
    }
  ];

  var CHANNELS = [
    { name: '渠道伙伴', leads: 318, valid: 74, conv: 9.1, sign: 1420, roi: 6.8, wow: 18.2, color: '合作' },
    { name: '老客转介绍', leads: 208, valid: 82, conv: 12.6, sign: 860, roi: 9.2, wow: 6.4, color: '老客' },
    { name: '信息流', leads: 1286, valid: 41, conv: 3.2, sign: 1260, roi: 3.9, wow: -12.0, color: '投放' },
    { name: '自然搜索', leads: 642, valid: 68, conv: 6.8, sign: 980, roi: 5.6, wow: 4.1, color: '搜索' },
    { name: '内容营销', leads: 486, valid: 57, conv: 4.4, sign: 620, roi: 4.1, wow: -2.3, color: '内容' }
  ];

  var RULES = [
    { id: 'target', name: '目标缺口', desc: '完成率明显落后时间进度', threshold: '完成率 < 时间进度 - 5pp', on: true,
      levels: [['黄', '5-10pp'], ['橙', '10-15pp'], ['红', '>15pp']], icon: 'target' },
    { id: 'decline', name: '业绩下滑', desc: '周签约环比出现明显下滑', threshold: '周签约环比 < -15%', on: true,
      levels: [['黄', '-15~-25%'], ['橙', '-25~-35%'], ['红', '<-35%']], icon: 'trend' },
    { id: 'leads', name: '线索异常', desc: '有效率或线索量异常波动', threshold: '有效率 < 50% 或环比 -10pp', on: true,
      levels: [['黄', '单日触发'], ['橙', '连续 2 天'], ['红', '连续 3 天']], icon: 'leads' },
    { id: 'cover', name: '商机覆盖', desc: '在谈商机不足以支撑剩余目标', threshold: '商机覆盖率 < 3.0 倍', on: true,
      levels: [['黄', '2.5-3.0x'], ['橙', '2.0-2.5x'], ['红', '<2.0x']], icon: 'cover' },
    { id: 'churn', name: '大客户流失', desc: '重点客户长时间未跟进', threshold: '≥30 天未跟进且金额 ≥100 万', on: true,
      levels: [['黄', '14-21 天'], ['橙', '22-30 天'], ['红', '>30 天']], icon: 'user' },
    { id: 'payment', name: '订单 / 回款', desc: '应收逾期或回款进度异常', threshold: '逾期 >15 天或逾期率 >10%', on: true,
      levels: [['黄', '15-30 天'], ['橙', '31-60 天'], ['红', '>60 天']], icon: 'money' }
  ];

  var WEEK_META = {
    this: { label: '本周', range: '10/19 - 10/25', factor: 1, wowShift: 0 },
    last: { label: '上周', range: '10/12 - 10/18', factor: 0.92, wowShift: -10.5 }
  };

  return {
    TODAY: '2026-10-24', WEEKDAY: '星期六', CUTOFF: '08:00',
    KPI_META: KPI_META, ROLES: ROLES, RISKS: RISKS, CHANNELS: CHANNELS,
    RULES: RULES, WEEK_META: WEEK_META
  };
})();
