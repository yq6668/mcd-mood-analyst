# 🍔 麦当劳情绪食鉴官（McDonald's Mood Analyst）

> 用一张真实账单，反推你今天的心情。

一个基于**麦当劳 MCP Server** 的开源 Skill。它读取你的真实订单记录，结合下单时间、餐品构成和消费金额，推断你下单时的心情，同时给出账单统计、营养画像与每日/每月开支分析。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Skill](https://img.shields.io/badge/Skill-WorkBuddy-blue.svg)](./SKILL.md)
[![MCP](https://img.shields.io/badge/MCP-McDonald's%20Server-red.svg)](./MCP_INTEGRATION.md)

---

## 📌 它解决什么问题

我们都有过这样的时刻：晚上十一点，点了一份巨无霸加派加鸡翅加甜品。

事后回想，那一刻点单的自己，其实是在找安慰。

**麦当劳情绪食鉴官**不评判你该不该吃麦当劳，它做的是另一件事：**把你的订单翻译成情绪语言**，让你看见自己的消费习惯背后的状态。

| 维度 | 你能得到什么 |
|---|---|
| 💰 **账单统计** | 笔数、总支出、客单价、最高单笔、门店榜、时段分布 |
| 💗 **情绪解读** | 情绪标签 + 强度分数 + 具体触发因子（点名是哪些餐品） |
| 🥗 **营养画像** | 能量/脂肪/钠/蛋白质/钙五项评级 + 可追溯的改进建议 |
| 📅 **开支账本** | 日均/月均开支、环比变化、下月预测、建议预算 |
| 📈 **趋势洞察** | 消费周期规律、高频单品、情绪-时间关联模式 |

---

## ✨ 示例输出

```
## 🍔 麦当劳情绪食鉴报告

> 2026-10-11 —— 情绪性进食（71.2 分）

### 💗 情绪解读

**情绪标签：情绪性进食（71.2 分）**

| 因子 | 强度 |
|---|---|
| 深夜因子 | 100/100 |
| 高糖高脂因子 | 77.3/100 |
| 金额冲动因子 | 72.0/100 |
| 频次因子 | 0.0/100 |

**触发因子：**
- 🕐 **深夜下单** — 23:30 下单 巨无霸套餐×1、麦辣鸡翅-2块×1、香芋派×2（麦当劳陆家嘴中心店）
- 🍟 **高糖高脂组合** — 甜品占当日热量 39%：香芋派

> 💬 建议先歇十分钟，再决定要不要点。
> *以上为基于订单数据的推测，不构成心理诊断。*

### 🥗 营养画像

| 营养素 | 摄入 | 参考 | 评级 |
|---|---|---|---|
| 能量 | 1201 kcal | ≤2000 kcal | 🔴 >50% |
| 脂肪供能比 | 49% | 20%-30% | 🔴 >40% 偏高 |
| 钠 | 2176 mg | ≤2000 mg | 🔴 >80% 上限 |
```

> 以上为演示样例数据，实际报告基于你的真实订单生成。

---

## 🚀 安装方法

### 前置条件

1. **WorkBuddy** 智能体客户端
2. 已完成**麦当劳 MCP Server** 授权（连接器面板中完成麦当劳账号授权）
3. Python 3.8+（仅使用标准库，无需 pip 安装任何依赖）

### 步骤

**1. 克隆仓库**

```bash
git clone https://github.com/<your-username>/mcd-mood-analyst.git
cd mcd-mood-analyst
```

**2. 配置 MCP**

将 `mcp-config.example.json` 中的配置合并到你的 MCP 配置文件，敏感信息用环境变量占位符替换（详见 [`MCP_INTEGRATION.md`](./MCP_INTEGRATION.md)）。

**3. 安装 Skill**

把整个项目目录放入 WorkBuddy 技能目录：

```bash
cp -r mcd-mood-analyst ~/.workbuddy/skills/
```

Windows 用户可手动将目录复制到 `%USERPROFILE%\.workbuddy\skills\mcd-mood-analyst\`。

**4. 验证**

```bash
python3 scripts/mood_analyzer.py --demo
```

看到完整报告即安装成功。

---

## 💡 使用示例

安装后在 WorkBuddy 中直接对话即可：

**菜单一 · 账单统计**

> 🗣️ "看看我的麦当劳账单"

**菜单二 · 情绪解读**

> 🗣️ "我今天是什么心情？"

**菜单三 · 营养画像**

> 🗣️ "我今天的营养够吗？"

**菜单四 · 开支账本**

> 🗣️ "我这个月在麦当劳花了多少钱？"

**菜单五 · 趋势洞察**

> 🗣️ "预判一下我下个月的消费"

**组合查询**

> 🗣️ "帮我看看 10 月 11 日那单我当时什么状态"

**命令行调用**

```bash
# 完整报告
python3 scripts/mood_analyzer.py --orders mcd_data/orders_raw.json --mode all

# 指定日期的情绪分析
python3 scripts/mood_analyzer.py --orders mcd_data/orders_raw.json --mode mood --date 2026-10-11

# 自定义月度预算
python3 scripts/mood_analyzer.py --orders mcd_data/orders_raw.json --mode spend --budget 500

# 结构化输出，便于二次处理
python3 scripts/mood_analyzer.py --orders mcd_data/orders_raw.json --mode nutrition --json
```

---

## 🎯 目标用户

| 用户类型 | 典型场景 |
|---|---|
| 🧑‍💻 **程序员/学生** | 工作日深夜加班后的例行下单，想了解自己的压力曲线 |
| 🧠 **情绪管理需求者** | 通过饮食记录观察自己的情绪触发点 |
| 🏃 **健身/控卡人群** | 需要精确的能量与钠摄入参考，辅助日常决策 |
| 💰 **记账习惯者** | 希望把餐饮消费纳入月度预算管理 |
| 🍔 **麦当劳重度用户** | 好奇自己的口味画像和消费规律 |

---

## 🧠 情绪模型是怎么算的

情绪分（0-100，**分数越高代表情绪性越强，不是"心情越好"**）由四个维度加权：

| 因子 | 权重 | 逻辑 |
|---|---|---|
| 🕐 深夜因子 | 30% | 22:00 后下单为满分，20:00-22:00 线性衰减 |
| 🍟 高糖高脂因子 | 30% | 甜品占当日热量比，50% 记满分 |
| 💸 金额冲动因子 | 25% | 当日总额 / 客单价，2 倍记满分 |
| 🔁 频次因子 | 15% | 单日订单数，≥3 笔记满分 |

营养评级依据《中国居民膳食指南（2022）》成年人日参考值。完整定义见 [`references/mood_model.md`](./references/mood_model.md) 与 [`references/nutrition_reference.md`](./references/nutrition_reference.md)。

---

## 📁 项目结构

```
mcd-mood-analyst/
├── SKILL.md                        # Skill 核心指令（WorkBuddy 加载入口）
├── README.md                       # 本文件
├── CONTEST_DECLARATION.md          # 参赛声明
├── MCP_INTEGRATION.md              # MCP 集成说明
├── mcp-config.example.json         # 脱敏 MCP 配置示例
├── workbuddy.md                    # WorkBuddy 对话上下文
├── LICENSE
├── scripts/
│   └── mood_analyzer.py            # 分析引擎（账单/情绪/营养/开支）
└── references/
    ├── mood_model.md               # 情绪模型数学定义
    ├── nutrition_reference.md      # 营养参考值与评级标准
    └── nutrition_db.json           # MCP 营养库离线快照（158 项）
```

---

## 🔐 隐私与合规

- 订单数据**仅保存在用户本地** `mcd_data/` 目录，不上传任何第三方服务器
- 不收集手机号、地址、会员卡号等个人敏感信息
- 报告输出前自动检查敏感信息泄露
- 随时说"删掉我的数据"即可清除本地记录
- 营养建议为一般性参考，**不构成医疗建议**
- 情绪分析为基于订单的推测，**不构成心理诊断**

---

## 📄 许可证

[MIT](./LICENSE)

---

## 🤝 参与麦当劳程序员创意开发大赛

本项目为「麦当劳程序员创意开发大赛」参赛作品，真实使用麦当劳 MCP Server 能力开发。

- 参赛声明：[`CONTEST_DECLARATION.md`](./CONTEST_DECLARATION.md)
- MCP 集成说明：[`MCP_INTEGRATION.md`](./MCP_INTEGRATION.md)

欢迎 Star ⭐ 和提 Issue。
