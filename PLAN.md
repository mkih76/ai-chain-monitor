# AI产业链先行信号雷达 — 重构方案

> 核心理念：在新闻出来之前，从原始数据中嗅到信号。
> 新闻是验证手段，不是信息来源。

---

## 一、设计理念

### 1.1 信号流水线模型

```
原始数据 ──→ 异常检测 ──→ 多源关联 ──→ AI研判 ──→ 推送/展示
 (采集)       (检测)       (交叉验证)    (综合判断)   (行动建议)
```

所有模块围绕一个核心对象运转：**Signal（信号）**。

### 1.2 信号对象（Signal）

```python
Signal = {
    "id": str,                    # UUID
    "timestamp": datetime,        # 检测时间
    "source": str,                # 来源模块: inventory/capital/commodity/announcement/overseas
    "type": str,                  # 信号类型（见下方分类）
    "target_stocks": list[str],   # 受影响股票代码
    "target_sectors": list[str],  # 受影响板块
    "direction": str,             # bullish/bearish
    "severity": str,              # S1(临界)/S2(高)/S3(中)/S4(观察)
    "lead_time_days": int,        # 历史领先天数（距价格反应）
    "confidence": float,          # 0-1 综合置信度
    "strength": float,            # 0-100 信号强度
    "raw_data": dict,             # 原始数据（可审计）
    "description": str,           # 人类可读描述
    "corroboration": list[str],   # 关联信号ID（互相印证的信号）
    "status": str,                # active/confirmed/expired/invalidated
    "ai_verdict": dict|None,      # AI研判结果（后填）
}
```

### 1.3 信号分级标准

| 级别 | 条件 | 示例 |
|------|------|------|
| **S1 临界** | 多源共振(≥3) + 置信度>0.8 | 库存暴降 + 北向连续买入 + 铜期货异动，同时指向铜板块 |
| **S2 高** | 单源强信号 + 1个佐证 | 机构席位净买入>1亿 + 融资余额增加 |
| **S3 中** | 单源中等信号 | 北向连续3天买入某标的 |
| **S4 观察** | 弱信号/待确认 | 股吧热度上升（情绪指标，领先但不可靠） |

### 1.4 信号生命周期

```
创建(active) → 被佐证(confirmed) → 价格验证(verified)
      ↓              ↓                    ↓
    过期(expired)  被否定(invalidated)   归档(archived)
```

信号默认存活72小时。若期间有佐证信号，延长至120小时。
价格按预期方向移动≥2%，标记verified（用于回测准确率计算）。

---

## 二、模块详细设计

### 模块依赖关系

```
                        ┌──────────────────────────────────────┐
                        │           Web 展示层                  │
                        │   信号雷达 / 市场全景 / 分析报告      │
                        └──────────┬───────────────────────────┘
                                   │
                        ┌──────────▼───────────────────────────┐
                        │        M5 · AI 研判引擎               │
                        │   综合所有信号 → 输出结论和建议         │
                        └──────────┬───────────────────────────┘
                                   │
                        ┌──────────▼───────────────────────────┐
                        │        M4 · 关联分析引擎               │
                        │   多源信号交叉验证 → 置信度评分          │
                        └──────────┬───────────────────────────┘
                                   │
           ┌───────────┬───────────┼───────────┬───────────┐
           ▼           ▼           ▼           ▼           ▼
    ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
    │ M1 库存  │ │ M2 资金  │ │ M3 商品  │ │ M6 公告  │ │ M7 海外  │
    │ 监控     │ │ 异动     │ │ 期货     │ │ 雷达     │ │ 映射     │
    └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘
         ↑           ↑           ↑           ↑           ↑
    ┌──────────────────────────────────────────────────────────────┐
    │                    原始数据源                                 │
    │  SHFE/LME | 东方财富datacenter | 新浪期货 | 巨潮资讯 | Yahoo  │
    └──────────────────────────────────────────────────────────────┘
```

---

### M1 · 库存监控模块（最高优先级）

**为什么最重要**：库存是最"硬"的先行指标。供需基本面决定价格，库存数据直接反映供需。
历史上SHFE锡库存连续下降3周后，锡价平均在5-8个交易日内上涨。

**数据源**：
- SHFE上期所仓单日报（铜/锡/镍/铝）— 每日
- LME伦敦金属交易所库存 — 每日
- 注册仓单变化（可选）

**检测逻辑**：
```python
# 信号类型1: 连续下降
if 连续N周下降(周均下降>2%):
    → Signal(type="inventory_decline", severity=S3 if N>=3 else S4)

# 信号类型2: 库存突破阈值
if 当前库存 < 历史20%分位:
    → Signal(type="inventory_critical", severity=S2)

# 信号类型3: 库存加速下降
if 本周下降幅度 > 前4周均值的2倍:
    → Signal(type="inventory_acceleration", severity=S2)
```

**关联传导**：
```
锡库存下降 → 锡价上涨压力 → 封装焊接成本上升 → 长电/通富成本端承压
铜库存下降 → 铜价上涨压力 → PCB成本上升 → 深南/兴森成本端承压
                 → 铜缆受益 → 沃尔核材/紫金矿业
```

**输出**：Signal对象 → 发送至M4关联分析

---

### M2 · 资金异动模块

**为什么重要**：机构和外资有信息优势，他们的买卖行为领先于公开信息。

**数据源**（全部来自东方财富datacenter API，已验证可用）：

| 子模块 | 数据 | API | 领先性 |
|--------|------|-----|--------|
| 北向资金 | 每日个股净买卖 | `datacenter-web.eastmoney.com` | 连续3天买入=信号 |
| 龙虎榜 | 机构席位/游资席位净买入 | 同上 | 机构专用>5000万=信号 |
| 融资融券 | 融资余额变化率 | 同上 | 周增幅>10%=信号 |
| 大宗交易 | 溢价/折价率 | 同上 | 溢价>5%=信号 |
| 机构调研 | 调研频次突增 | 同上 | 3天内5家以上机构=信号 |

**检测逻辑**：
```python
# 北向资金
if 连续3天净买入同一标的:
    → Signal(type="northbound_consecutive", severity=S3)
if 连续5天:
    → Signal(type="northbound_consecutive", severity=S2)
if 单日净买入>1亿:
    → Signal(type="northbound_surge", severity=S2)

# 龙虎榜
if 机构专用席位净买入>5000万:
    → Signal(type="institutional_buy", severity=S2)
if 3家以上机构同日买入同一标的:
    → Signal(type="institutional_cluster", severity=S1)

# 融资融券
if 融资余额周增幅>10%:
    → Signal(type="margin_surge", severity=S3)

# 机构调研
if 7天内>5家机构调研同一标的:
    → Signal(type="research_cluster", severity=S3)
```

**输出**：Signal对象 → 发送至M4关联分析

---

### M3 · 商品期货联动模块

**为什么重要**：商品价格变化传导到A股有1-3天时滞，这是最确定的时间窗口。

**数据源**：
- 新浪期货API（沪铜/沪锡/沪镍/沪铝主力合约）— 实时
- COMEX/LME外盘（可选）

**检测逻辑**：
```python
# 单日异动
if 商品单日涨幅>3%:
    → Signal(type="commodity_surge", severity=S3)
    → 自动计算传导标的: 沪锡→锡业股份, 长电, 通富

# 趋势突破
if 商品突破20日均线且连续3日站上:
    → Signal(type="commodity_breakout", severity=S2)

# 期现背离
if 期货价格上涨但库存也在上涨:
    → Signal(type="divergence_warning", severity=S4)
    → description: "期货涨但库存涨，可能是投机驱动，持续性存疑"
```

**传导链**（写入signal.description）：
```
沪锡+3.5% → 【传导】锡业股份(直接受益) > 长电/通富(成本端承压) > 深南/兴森(PCB锡焊)
沪铜+4.0% → 【传导】紫金矿业(直接受益) > 沃尔核材(铜缆) > 深南/兴森(PCB铜箔)
```

**输出**：Signal对象 → 发送至M4关联分析

---

### M4 · 关联分析引擎（中枢）

**核心职责**：接收所有模块的Signal，做交叉验证，计算综合置信度。

**输入**：所有M1/M2/M3/M6/M7产生的Signal

**分析逻辑**：

```python
def correlate_signals(signals: list[Signal]) -> list[CorrelatedSignal]:
    """
    1. 按target_sectors分组
    2. 同一板块内，不同来源的信号互相印证
    3. 计算综合置信度
    """
    # 示例: 3个信号同时指向"铜"板块
    # M1: SHFE铜库存连续3周下降 (confidence=0.7)
    # M2: 北向资金连续3天买入紫金矿业 (confidence=0.65)
    # M3: 沪铜突破20日均线 (confidence=0.6)
    #
    # 综合置信度 = 1 - (1-0.7)*(1-0.65)*(1-0.6) = 0.958
    # → 升级为S1临界信号
```

**置信度计算**：
```python
def combined_confidence(source_confs: list[float]) -> float:
    """多源独立信号的置信度合并（假设独立）"""
    return 1 - prod(1 - c for c in source_confs)

def boost_for_corroboration(n_sources: int) -> float:
    """来源数量加成"""
    if n_sources >= 3: return 1.2  # 3源共振，置信度*1.2
    if n_sources >= 2: return 1.1  # 2源佐证
    return 1.0
```

**信号TTL管理**：
```python
def manage_signal_lifecycle():
    """定时任务: 每小时检查一次"""
    for signal in get_active_signals():
        age_hours = (now - signal.timestamp).total_seconds() / 3600
        if signal.corroboration and age_hours > 120:
            signal.status = "expired"
        elif not signal.corroboration and age_hours > 72:
            signal.status = "expired"
```

**输出**：CorrelatedSignal → 发送至M5 AI研判

---

### M5 · AI研判引擎

**核心职责**：综合所有信号 + 市场环境，输出人类可读的结论。

**与旧版的区别**：
- 旧版：分析新闻标题 → 输出"利好/利空"（事后诸葛亮）
- 新版：分析原始信号组合 → 输出"建议关注/建议回避/无明确方向"（事前研判）

**输入**：
- M4输出的CorrelatedSignal列表
- 当前持仓信息（可选）
- 市场整体环境（大盘趋势）

**输出格式**：
```python
AIReport = {
    "timestamp": datetime,
    "summary": "一句话总结",
    "action": "watch/act/hold/avoid",  # 建议动作
    "signals_reviewed": int,            # 分析了多少个信号
    "top_calls": [                      # 最值得关注的
        {
            "sector": "铜",
            "direction": "bullish",
            "confidence": 0.85,
            "reasoning": "SHFE库存3周连降+北向资金连续买入紫金矿业+沪铜突破均线",
            "key_levels": "紫金矿业压力位31.2",
            "risk": "全球经济放缓可能抑制需求",
        }
    ],
    "risk_alerts": [...],    # 风险提示
    "data_gaps": [...],      # 数据缺失说明
}
```

**调用方式**：MiMo LLM Proxy（VPS上可用，本地可选）

---

### M6 · 公告雷达模块（新增）

**为什么新增**：原始公告比新闻早1-3天。巨潮资讯的公告是第一手信息源。

**数据源**：巨潮资讯网API（已有采集器，但之前只做了新闻类）

**重点监控公告类型**：
```python
ANNOUNCEMENT_KEYWORDS = {
    "中标/合同": ["中标", "合同", "订单", "框架协议"],
    "增持/回购": ["增持", "回购", "举牌"],
    "产能扩张": ["投产", "扩产", "新建产能", "生产线"],
    "战略合作": ["战略合作", "合资", "投资设立"],
    "业绩预告": ["预增", "预减", "扭亏", "业绩快报"],
}
```

**检测逻辑**：
```python
# 中标公告 → 直接利好
if 公告类型 == "中标" and 金额 > 1亿:
    → Signal(type="contract_win", severity=S2)

# 高管增持 → 内部人看好
if 公告类型 == "增持" and 增持比例 > 0.5%:
    → Signal(type="insider_buy", severity=S2)

# 产能扩张 → 中长期利好
if 公告类型 == "投产/扩产":
    → Signal(type="capacity_expansion", severity=S3)
```

**输出**：Signal对象 → 发送至M4关联分析

---

### M7 · 海外映射模块

**为什么重要**：A股AI板块跟随美股科技巨头。NVDA盘后异动 → 次日A股开盘前就能预判。

**数据源**：Yahoo Finance（已有采集器）

**检测逻辑**：
```python
# 海外龙头单日大跌 → A股次日大概率跟跌
if NVDA日跌幅 > 5%:
    → Signal(type="overseas_drag", severity=S2, direction="bearish")
    → targets: 光模块, 服务器, PCB, 封装

# 海外龙头创新高 → A股滞后跟涨
if NVDA创60日新高:
    → Signal(type="overseas_momentum", severity=S3, direction="bullish")

# 海外财报超预期（需手动或API接入）
if NVDA营收超预期>10%:
    → Signal(type="earnings_beat", severity=S1)
```

**时区优势**：美股收盘→次日A股开盘有12小时窗口，是天然的预警时间。

**输出**：Signal对象 → 发送至M4关联分析

---

### M8 · 消息验证模块（降级为辅助）

**旧角色**：主力信息源（新闻聚合）
**新角色**：信号印证 + 市场情绪参考

**保留功能**：
1. 新闻作为信号的"验证"：如果M1-M7的信号被新闻报道，标记confirmed
2. 舆情热度：股吧/论坛情绪指标（已有先行指标引擎）
3. 券商研报：仅作为参考，不产生信号

**不再做的事**：
- ❌ 把新闻标题当信号源
- ❌ AI分析新闻方向（事后诸葛亮）
- ❌ 新闻推送到主界面

---

## 三、数据源优先级

| 优先级 | 数据源 | 更新频率 | 领先性 | 可靠性 | 模块 |
|--------|--------|----------|--------|--------|------|
| P0 | SHFE/LME库存 | 每日 | ★★★★★ | ★★★★★ | M1 |
| P0 | 北向资金个股明细 | 每日 | ★★★★ | ★★★★★ | M2 |
| P0 | 龙虎榜机构席位 | 每日 | ★★★★ | ★★★★★ | M2 |
| P1 | 商品期货价格 | 实时 | ★★★ | ★★★★★ | M3 |
| P1 | 融资融券 | 每日 | ★★★ | ★★★★★ | M2 |
| P1 | 巨潮公告(中标/增持) | 实时 | ★★★★ | ★★★★★ | M6 |
| P2 | Yahoo Finance海外 | 每日 | ★★★ | ★★★★ | M7 |
| P2 | 大宗交易 | 每日 | ★★★ | ★★★★ | M2 |
| P3 | 股吧情绪 | 每日 | ★★ | ★★ | M8 |
| P3 | 新闻/研报 | 实时 | ★ | ★★★ | M8 |

---

## 四、Web界面重构

### 4.1 导航结构

```
信号雷达（默认页）  市场全景  分析报告  进化系统
```

### 4.2 信号雷达页（核心）

```
┌─────────────────────────────────────────────────────────────┐
│  AI产业链先行信号雷达                    最后更新: 10:30      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─ 信号流水线 ──────────────────────────────────────────┐  │
│  │                                                       │  │
│  │  [库存] ──┐                                           │  │
│  │  [资金] ──┤                                           │  │
│  │  [商品] ──┼──→ [关联分析] ──→ [AI研判] ──→ 行动建议   │  │
│  │  [公告] ──┤      3源共振      置信度85%               │  │
│  │  [海外] ──┘      S1级信号      "铜板块偏多"            │  │
│  │                                                       │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌─ 活跃信号（按置信度排序）──────────────────────────────┐  │
│  │                                                       │  │
│  │  S1 ██████████████████████████████████████████  95.8%  │  │
│  │  铜板块多源共振 · 库存降+北向买+期货涨                   │  │
│  │  来源: M1库存 ✓ M2资金 ✓ M3商品 ✓                       │  │
│  │  领先: ~5天  创建: 06-04 14:00                          │  │
│  │  [查看详情] [标记已验证]                                 │  │
│  │                                                       │  │
│  │  S2 ██████████████████████████████████  78.2%          │  │
│  │  NVDA大跌-6.2% · A股光模块/服务器次日承压                 │  │
│  │  来源: M7海外                                          │  │
│  │  领先: ~1天  创建: 06-06 04:00                          │  │
│  │                                                       │  │
│  │  S3 ██████████████████████  62.0%                      │  │
│  │  中际旭创股吧热度飙升 · 情绪领先1-3天                    │  │
│  │  来源: M8舆情                                          │  │
│  │  领先: ~2天  创建: 06-06 09:00                          │  │
│  │                                                       │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌─ 信号统计 ────────────────────────────────────────────┐  │
│  │  活跃: 8  已确认: 3  已验证(正确): 12  过期: 5         │  │
│  │  历史准确率: 72.3% (验证/总验证)                        │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 4.3 市场全景页

```
┌─────────────────────────────────────────────────────────────┐
│  市场全景                                                    │
├──────────┬──────────────────────────────────────────────────┤
│          │                                                  │
│  原材料   │  ┌─ 商品期货联动 ────────────────────────────┐  │
│  ┌──────┐│  │  沪铜  ████████░░  +1.8%  传导→ 紫金矿业   │  │
│  │ 锡   ││  │  沪锡  ████████████ +3.5%  传导→ 锡业股份   │  │
│  │ 供需  ││  │  沪镍  ██████░░░░  +0.9%                   │  │
│  │ 紧张  ││  │  沪铝  ████░░░░░░  +0.5%                   │  │
│  └──────┘│  └────────────────────────────────────────────┘  │
│  ┌──────┐│                                                  │
│  │ 铜   ││  ┌─ 资金流向 ────────────────────────────────┐  │
│  │ 库存  ││  │  北向净流入: +12.5亿                       │  │
│  │ 下降  ││  │  个股: 紫金矿业+0.8亿(连续3天)             │  │
│  └──────┘│  │  个股: 寒武纪+0.5亿                        │  │
│          │  │  融资余额变化: +2.3%                       │  │
│  产业链   │  └────────────────────────────────────────────┘  │
│  ┌──────┐│                                                  │
│  │光模块 ││  ┌─ 库存监控 ────────────────────────────────┐  │
│  │ 跟随  ││  │  SHFE铜: 28,500吨 ↓↓ (3周连降)            │  │
│  │ NVDA  ││  │  SHFE锡: 5,100吨 ↓↓↓ (5周连降，警戒)      │  │
│  │ -6.2% ││  │  LME铜: 125,000吨 → (平稳)                │  │
│  └──────┘│  └────────────────────────────────────────────┘  │
│          │                                                  │
│  （点击板块查看详情）                                         │
└──────────┴──────────────────────────────────────────────────┘
```

### 4.4 分析报告页

AI研判的详细报告，包含：
- 当日综合研判（AI生成）
- 活跃信号的详细分析
- 历史相似场景匹配
- 风险提示

---

## 五、文件结构

```
ai-chain-monitor/
├── config.py                     # 配置（标的/阈值/API）
├── db.py                         # 数据库（信号表+历史表）
├── main.py                       # 主入口
├── scheduler.py                  # 定时调度
│
├── collectors/                   # 数据采集层
│   ├── inventory_collector.py    # [M1] SHFE/LME库存
│   ├── capital_collector.py      # [M2] 北向/龙虎/融资/大宗/调研（重命名）
│   ├── commodity_collector.py    # [M3] 商品期货价格（新增）
│   ├── announcement_collector.py # [M6] 巨潮公告雷达（新增）
│   ├── overseas_collector.py     # [M7] 海外标的
│   └── news_collector.py         # [M8] 新闻（降级为验证用）
│
├── detectors/                    # 信号检测层（新增目录）
│   ├── inventory_detector.py     # 库存信号检测
│   ├── capital_detector.py       # 资金信号检测
│   ├── commodity_detector.py     # 商品信号检测
│   ├── announcement_detector.py  # 公告信号检测
│   └── overseas_detector.py      # 海外信号检测
│
├── analyzers/                    # 分析层
│   ├── correlator.py             # [M4] 关联分析引擎（新增，核心）
│   └── ai_engine.py              # [M5] AI研判引擎（重构）
│
├── web/                          # 展示层
│   ├── app.py                    # Flask路由
│   ├── templates/
│   │   ├── base.html
│   │   ├── radar.html            # 信号雷达（新增，核心页面）
│   │   ├── market.html           # 市场全景（新增）
│   │   ├── report.html           # 分析报告（重构）
│   │   └── evolution.html        # 进化系统（保留）
│   └── static/
│
└── data/
    └── monitor.db
```

---

## 六、数据库变更

### 新增 signals_v2 表

```sql
CREATE TABLE IF NOT EXISTS signals_v2 (
    id TEXT PRIMARY KEY,              -- UUID
    timestamp TEXT NOT NULL,
    source TEXT NOT NULL,             -- inventory/capital/commodity/announcement/overseas
    type TEXT NOT NULL,               -- 信号类型
    target_stocks TEXT,               -- JSON array of stock codes
    target_sectors TEXT,              -- JSON array of sector names
    direction TEXT,                   -- bullish/bearish
    severity TEXT NOT NULL,           -- S1/S2/S3/S4
    lead_time_days INTEGER,
    confidence REAL,
    strength REAL,
    raw_data TEXT,                    -- JSON
    description TEXT,
    corroboration TEXT,               -- JSON array of signal IDs
    status TEXT DEFAULT 'active',     -- active/confirmed/expired/invalidated/verified
    ai_verdict TEXT,                  -- JSON
    price_at_creation REAL,           -- 创建时的价格（用于验证）
    price_verified_at TEXT,           -- 验证时间
    price_change_pct REAL             -- 验证时的涨跌幅
);
```

---

## 七、实施计划

### Phase 1: 信号基础设施（Day 1）
- [ ] 新建 `detectors/` 目录 + 信号对象定义
- [ ] 创建 signals_v2 表
- [ ] 实现 M1 库存信号检测器
- [ ] 实现 M2 资金信号检测器
- [ ] 本地测试：手动触发采集+检测，输出Signal

### Phase 2: 关联引擎 + 更多数据源（Day 2）
- [ ] 实现 M4 关联分析引擎（核心）
- [ ] 实现 M3 商品期货联动检测
- [ ] 实现 M6 公告雷达检测
- [ ] 实现 M7 海外映射检测
- [ ] 本地测试：多信号关联验证

### Phase 3: Web前端重构（Day 3）
- [ ] 信号雷达页面（radar.html）
- [ ] 市场全景页面（market.html）
- [ ] 分析报告页面（report.html）
- [ ] API接口重构

### Phase 4: AI研判 + 进化系统（Day 4）
- [ ] AI研判引擎重构
- [ ] 信号验证/回测系统
- [ ] 准确率统计
- [ ] 推送到VPS部署

---

## 八、验收标准

1. `python main.py collect && python main.py detect` 能产生至少5个Signal
2. 同一板块的多源信号能自动关联，置信度正确计算
3. Web信号雷达页面能实时显示活跃信号
4. 信号从创建→过期的生命周期正确管理
5. 历史信号的验证准确率可统计
