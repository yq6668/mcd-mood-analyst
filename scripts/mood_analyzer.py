#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦当劳情绪食鉴官 · 分析引擎
=========================================
纯 Python 标准库实现，无需安装任何依赖。

用法:
    python3 mood_analyzer.py --orders orders_raw.json --mode bill
    python3 mood_analyzer.py --orders orders_raw.json --mode mood
    python3 mood_analyzer.py --orders orders_raw.json --mode nutrition
    python3 mood_analyzer.py --orders orders_raw.json --mode spend
    python3 mood_analyzer.py --orders orders_raw.json --mode all
    python3 mood_analyzer.py --demo          # 内置样例数据跑通全流程

设计原则:
  1. 所有金额/营养数值只来自 MCP 返回，不估算、不编造。
  2. 情绪结论标注"基于订单推测，非心理诊断"。
  3. 订单为空的处理：给出明确提示而非虚构账单。
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

# ============================================================
# 常量配置
# ============================================================

# 《中国居民膳食指南（2022）》成年人日参考值
DAILY_REFERENCE = {
    "energy_kcal": 2000,
    "protein_g": 60,
    "fat_g": 60,
    "carbohydrate_g": 300,
    "sodium_mg": 2000,
    "calcium_mg": 800,
}

# 情绪分段标签（分数越高 = 情绪性越强）
MOOD_BANDS = [
    (25, "平静日常", "今天的消费很稳，是有规律的日常节奏。"),
    (45, "轻度放纵", "犒劳自己型消费，适度放松没问题，注意别连续高油。"),
    (65, "压力求安慰", "压力偏大，甜食是合理出口，但别只靠它。"),
    (82, "情绪性进食", "建议先歇十分钟，再决定要不要点。"),
    (100, "深夜崩溃局", "关心为主，建议先把睡眠照顾好。"),
]

# 餐品情绪色彩分类：关键词匹配
CATEGORY_RULES = {
    "甜品": ["新地", "派", "麦旋风", "圣代", "奶昔", "冰淇淋", "雪冰", "拉明顿", "奶冻", "酷爽"],
    "炸物": ["麦乐鸡", "薯条", "鸡翅", "鸡块", "脆鸡", "脆汁鸡", "趣鸡球", "鸡排", "油条", "V翅", "脆薯饼"],
    "主食": ["巨无霸", "汉堡", "堡", "麦满分", "三明治", "营养卷", "炒双蛋", "粥", "卷", "鳕鱼", "牛堡"],
    "饮品": ["可乐", "雪碧", "咖啡", "红茶", "奶茶", "豆浆", "牛奶", "奶铁", "美式", "玛奇朵", "卡布奇诺", "阿芙佳朵", "怡泉", "美汁源", "橙"],
    "轻食": ["沙拉", "玉米杯", "苹果片", "纯牛奶", "纯悦", "苹果汁", "叠叠卷"],
}

# 高热量"放纵"单品，用于情绪识别（kcal >= 400）
INDULGENT_THRESHOLD = 400

# 深夜时段定义
NIGHT_START = 22
NIGHT_END = 2  # 次日 2 点


# ============================================================
# 工具函数
# ============================================================

def load_orders(path):
    """读取 MCP order-list 落盘的原始 JSON。"""
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # 兼容 MCP 包装格式与裸数组
    if isinstance(raw, dict):
        orders = raw.get("data", {}).get("list", []) if isinstance(raw.get("data"), dict) else []
    elif isinstance(raw, list):
        orders = raw
    else:
        orders = []

    # 过滤未完成订单：只统计已完成的消费
    done_status = {"FINISHED", "COMPLETED", "DONE", "SUCCESS"}
    result = []
    for o in orders:
        status = str(o.get("orderStatus", "")).upper()
        if status and status not in done_status:
            continue
        result.append(normalize_order(o))
    return result


def normalize_order(o):
    """把 MCP 订单结构规整为内部标准结构。"""
    amount = o.get("realTotalAmount") or "0"
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        amount = 0.0

    dt = None
    ct = o.get("createTime", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(str(ct)[:19], fmt)
            break
        except ValueError:
            continue

    items = []
    for p in o.get("orderProductList", []) or []:
        try:
            qty = int(p.get("quantity", 1) or 1)
        except (TypeError, ValueError):
            qty = 1
        items.append({"name": p.get("productName", ""), "quantity": max(qty, 1)})

    return {
        "order_id": o.get("orderId", ""),
        "time": dt,
        "amount": amount,
        "store": o.get("storeName", "未知门店"),
        "type": o.get("orderType", ""),
        "items": items,
    }


def classify(name):
    """按关键词判断餐品情绪类别。"""
    for cat, keywords in CATEGORY_RULES.items():
        for kw in keywords:
            if kw in name:
                return cat
    return "其他"


def days_in_month_in_month(dt):
    """返回该日期所在月份的总天数。"""
    if dt.month == 12:
        return 31
    return (datetime(dt.year, dt.month + 1, 1) - timedelta(days=1)).day


def load_nutrition_db(path=None):
    """加载营养库快照。优先读取离线 JSON，失败则返回空表。"""
    if path is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base, "references", "nutrition_db.json")

    db = {}
    if not os.path.exists(path):
        return db

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for row in data.get("items", []):
        if len(row) < 8:
            continue
        db[row[0]] = {
            "energy_kj": row[1], "energy_kcal": row[2],
            "protein_g": row[3], "fat_g": row[4], "carbohydrate_g": row[5],
            "sodium_mg": row[6], "calcium_mg": row[7],
        }
    return db


def lookup_nutrition(db, name):
    """餐品名 → 营养数据。精确匹配失败时退化为包含匹配。"""
    if name in db:
        return db[name]
    for key, val in db.items():
        if key in name or name in key:
            return val
    return None


# ============================================================
# 引擎一：账单统计
# ============================================================

def analyze_bill(orders):
    """账单统计：笔数、总支出、客单价、门店榜、时段分布。"""
    if not orders:
        return {"empty": True}

    amounts = [o["amount"] for o in orders]
    total = sum(amounts)
    count = len(orders)
    avg = total / count

    valid_times = [o["time"] for o in orders if o["time"]]
    store_rank = Counter(o["store"] for o in orders).most_common(5)

    hour_bucket = Counter()
    for o in orders:
        if not o["time"]:
            continue
        h = o["time"].hour
        if 5 <= h < 10:
            hour_bucket["早餐 05-10"] += 1
        elif 10 <= h < 14:
            hour_bucket["午餐 10-14"] += 1
        elif 14 <= h < 17:
            hour_bucket["下午茶 14-17"] += 1
        elif 17 <= h < 21:
            hour_bucket["晚餐 17-21"] += 1
        else:
            hour_bucket["夜间 21-05"] += 1

    item_rank = Counter()
    for o in orders:
        for it in o["items"]:
            item_rank[it["name"]] += it["quantity"]

    # 月度分布
    month_sum = defaultdict(float)
    for o in orders:
        if o["time"]:
            month_sum[o["time"].strftime("%Y-%m")] += o["amount"]

    top_order = max(orders, key=lambda x: x["amount"])

    return {
        "empty": False,
        "count": count,
        "total": round(total, 2),
        "avg": round(avg, 2),
        "max": round(max(amounts), 2),
        "max_order": {"amount": round(top_order["amount"], 2), "items": top_order["items"],
                      "store": top_order["store"], "time": top_order["time"]},
        "store_rank": store_rank,
        "hour_bucket": hour_bucket.most_common(),
        "item_rank": item_rank.most_common(10),
        "month_sum": dict(sorted(month_sum.items())),
        "date_range": (min(valid_times).strftime("%Y-%m-%d"), max(valid_times).strftime("%Y-%m-%d"))
                     if valid_times else None,
    }


# ============================================================
# 引擎二：情绪解码
# ============================================================

def analyze_mood(orders, nutrition_db, target_date=None):
    """
    情绪解码：四因子加权模型。
    分数越高代表情绪性越强，不是"心情越好"。
    """
    if not orders:
        return {"empty": True}

    dated = [o for o in orders if o["time"]]
    if target_date:
        day_orders = [o for o in dated if o["time"].strftime("%Y-%m-%d") == target_date]
        # 当日无订单时，退化为分析最近一次有订单的日期
        if not day_orders:
            if not dated:
                return {"empty": True}
            latest = max(o["time"] for o in dated).strftime("%Y-%m-%d")
            day_orders = [o for o in dated if o["time"].strftime("%Y-%m-%d") == latest]
            target_date = latest
    else:
        if not dated:
            return {"empty": True}
        latest = max(o["time"] for o in dated).strftime("%Y-%m-%d")
        day_orders = [o for o in dated if o["time"].strftime("%Y-%m-%d") == latest]
        target_date = latest

    day_amount = sum(o["amount"] for o in day_orders)
    day_count = len(day_orders)

    # --- 因子 1: 深夜因子 ---
    night_hits = []
    for o in day_orders:
        h = o["time"].hour
        if h >= NIGHT_START or h < NIGHT_END:
            night_hits.append(o)
    s_night = min(len(night_hits) / max(day_count, 1), 1.0)

    # --- 因子 2: 高糖高脂因子 ---
    dessert_kcal = 0
    total_kcal = 0
    cat_kcal = defaultdict(float)
    for o in day_orders:
        for it in o["items"]:
            n = lookup_nutrition(nutrition_db, it["name"])
            if not n:
                continue
            kcal = n["energy_kcal"] * it["quantity"]
            total_kcal += kcal
            cat_kcal[classify(it["name"])] += kcal
            if classify(it["name"]) == "甜品":
                dessert_kcal += kcal

    if total_kcal > 0:
        dessert_ratio = dessert_kcal / total_kcal
        s_indulge = min(dessert_ratio / 0.5, 1.0)  # 甜品占比 50% 记满分
    else:
        dessert_ratio = 0.0
        s_indulge = 0.0

    # --- 因子 3: 金额冲动因子 ---
    bill = analyze_bill(orders)
    baseline = bill["avg"] if bill.get("avg") else 0.0
    if baseline > 0:
        ratio = day_amount / baseline
        s_spend = max(0.0, min((ratio - 1) / 1.0, 1.0))  # 2 倍客单价记满分
    else:
        s_spend = 0.0

    # --- 因子 4: 频次因子 ---
    s_freq = min(max(day_count - 1, 0) / 2, 1.0)

    score = round(
        0.30 * s_night * 100 +
        0.30 * s_indulge * 100 +
        0.25 * s_spend * 100 +
        0.15 * s_freq * 100, 1)

    band = MOOD_BANDS[0]
    for threshold, tag, advice in MOOD_BANDS:
        if score <= threshold:
            band = (threshold, tag, advice)
            break

    # --- 触发因子（点名具体餐品）---
    triggers = []
    for o in night_hits:
        triggers.append({
            "icon": "🕐", "type": "深夜下单",
            "detail": "{} 下单 {}（{}）".format(
                o["time"].strftime("%H:%M"),
                "、".join(f"{it['name']}×{it['quantity']}" for it in o["items"]),
                o["store"]),
        })

    if dessert_ratio > 0.25 and dessert_kcal > 0:
        dessert_items = sorted({
            it["name"] for o in day_orders for it in o["items"]
            if classify(it["name"]) == "甜品"
        })
        triggers.append({
            "icon": "🍟", "type": "高糖高脂组合",
            "detail": "甜品占当日热量 {:.0%}：{}".format(
                dessert_ratio, "、".join(dessert_items) or "含糖饮品/甜点"),
        })

    if baseline > 0 and day_amount > baseline * 2:
        triggers.append({
            "icon": "💸", "type": "大额冲动单",
            "detail": "当日 ¥{:.2f}，是客单价 ¥{:.2f} 的 {:.1f} 倍".format(
                day_amount, baseline, day_amount / baseline),
        })

    if day_count >= 2:
        triggers.append({
            "icon": "🔁", "type": "高频连单",
            "detail": "当日下单 {} 次".format(day_count),
        })

    # 品类失衡
    indulgent_ratio = 0.0
    if total_kcal > 0:
        indulgent_ratio = (cat_kcal["甜品"] + cat_kcal["炸物"]) / total_kcal
        if indulgent_ratio > 0.6:
            triggers.append({
                "icon": "⚖️", "type": "品类失衡",
                "detail": "甜品+炸物占热量 {:.0%}".format(indulgent_ratio),
            })

    return {
        "empty": False,
        "date": target_date,
        "score": score,
        "tag": band[1],
        "advice": band[2],
        "day_count": day_count,
        "day_amount": round(day_amount, 2),
        "triggers": triggers,
        "factors": {
            "深夜因子": round(s_night * 100, 1),
            "高糖高脂因子": round(s_indulge * 100, 1),
            "金额冲动因子": round(s_spend * 100, 1),
            "频次因子": round(s_freq * 100, 1),
        },
        "cat_kcal": {k: round(v) for k, v in cat_kcal.items()},
        "dessert_ratio": round(dessert_ratio, 3),
        "indulgent_ratio": round(indulgent_ratio, 3),
        "total_kcal": round(total_kcal),
        "disclaimer": "以上为基于订单数据的推测，不构成心理诊断。",
    }


# ============================================================
# 引擎三：营养画像
# ============================================================

def rate_energy(kcal):
    r = kcal / DAILY_REFERENCE["energy_kcal"]
    if r <= 0.30:
        return "🟢", "≤30%"
    if r <= 0.50:
        return "🟡", "30%-50%"
    return "🔴", ">50%"


def rate_fat_ratio(ratio):
    if 0.20 <= ratio <= 0.30:
        return "🟢", "20%-30% 合理区间"
    if ratio < 0.20 or ratio <= 0.40:
        return "🟡", "偏离合理区间"
    return "🔴", ">40% 偏高"


def rate_sodium(mg):
    if mg <= 800:
        return "🟢", "≤40% 上限"
    if mg <= 1600:
        return "🟡", "40%-80% 上限"
    return "🔴", ">80% 上限"


def rate_protein(g):
    if g >= 20:
        return "🟢", "≥20g 充足"
    if g >= 10:
        return "🟡", "10-20g 偏低"
    return "🔴", "<10g 明显不足"


def rate_calcium(mg):
    if mg >= 200:
        return "🟢", "≥200mg 良好"
    if mg >= 100:
        return "🟡", "100-200mg 不足"
    return "🔴", "<100mg 严重不足"


def analyze_nutrition(orders, nutrition_db, target_date=None):
    """营养画像：按日/按月汇总六项营养素并评级。"""
    if not orders:
        return {"empty": True}

    dated = [o for o in orders if o["time"]]
    if not dated:
        return {"empty": True, "reason": "订单缺少时间字段，无法按日汇总"}

    if target_date:
        subset = [o for o in dated if o["time"].strftime("%Y-%m-%d") == target_date]
        scope = "当日"
    else:
        subset = dated
        scope = "全周期"

    if not subset:
        return {"empty": True, "reason": "指定日期无订单"}

    totals = defaultdict(float)
    matched, unmatched = 0, []
    item_kcal = Counter()

    for o in subset:
        for it in o["items"]:
            n = lookup_nutrition(nutrition_db, it["name"])
            if not n:
                unmatched.append(it["name"])
                continue
            matched += 1
            q = it["quantity"]
            totals["energy_kcal"] += n["energy_kcal"] * q
            totals["protein_g"] += n["protein_g"] * q
            totals["fat_g"] += n["fat_g"] * q
            totals["carbohydrate_g"] += n["carbohydrate_g"] * q
            totals["sodium_mg"] += n["sodium_mg"] * q
            totals["calcium_mg"] += n["calcium_mg"] * q
            item_kcal[it["name"]] += n["energy_kcal"] * q

    kcal = totals["energy_kcal"]
    fat_ratio = (totals["fat_g"] * 9 / kcal * 100) if kcal > 0 else 0

    ratings = {
        "energy_kcal": rate_energy(kcal),
        "fat_ratio": rate_fat_ratio(fat_ratio),
        "sodium_mg": rate_sodium(totals["sodium_mg"]),
        "protein_g": rate_protein(totals["protein_g"]),
        "calcium_mg": rate_calcium(totals["calcium_mg"]),
    }

    # 改进建议（可追溯到具体数值）
    suggestions = []
    if ratings["sodium_mg"][0] == "🔴":
        suggestions.append("钠摄入 {:.0f}mg 已超每日上限 80%，建议减少套餐叠加，"
                           "可换相对低钠的单品。".format(totals["sodium_mg"]))
    elif ratings["sodium_mg"][0] == "🟡":
        suggestions.append("钠摄入 {:.0f}mg 接近上限，注意明日清淡饮食。".format(totals["sodium_mg"]))

    if ratings["energy_kcal"][0] == "🔴":
        suggestions.append("能量 {:.0f}kcal 超过全天参考一半，建议大薯条换迷你薯条"
                           "（379→106 kcal）。".format(kcal))
    elif ratings["energy_kcal"][0] == "🟡":
        suggestions.append("能量 {:.0f}kcal 处于中等，节奏不错。".format(kcal))

    if ratings["fat_ratio"][0] == "🔴":
        suggestions.append("脂肪供能比 {:.0f}% 偏高（合理 20%-30%），"
                           "可用玉米杯（87kcal）或苹果片（32kcal）替代部分餐品。".format(fat_ratio))

    if ratings["protein_g"][0] != "🟢":
        suggestions.append("蛋白质 {:.0f}g 偏低，可选麦香鸡（15g）或猪柳麦满分（16g）补足。".format(
            totals["protein_g"]))

    if ratings["calcium_mg"][0] != "🟢":
        suggestions.append("钙仅 {:.0f}mg，纯牛奶（231mg）与热牛奶大杯（435mg）是良好补充。".format(
            totals["calcium_mg"]))

    if not suggestions:
        suggestions.append("各项指标均在合理区间，继续保持这个节奏。")

    return {
        "empty": False,
        "scope": scope,
        "target_date": target_date,
        "totals": {k: round(v, 1) for k, v in totals.items()},
        "fat_energy_ratio": round(fat_ratio, 1),
        "ratings": ratings,
        "suggestions": suggestions,
        "matched_items": matched,
        "unmatched_items": sorted(set(unmatched)),
        "top_kcal_items": item_kcal.most_common(5),
        "disclaimer": "营养分析仅覆盖麦当劳渠道，为一般性参考，不构成医疗建议。",
    }


# ============================================================
# 引擎四：开支账本与趋势
# ============================================================

def analyze_spend(orders, monthly_budget=None):
    """日/周/月开支、预算占比、环比、下月预测。"""
    if not orders:
        return {"empty": True}

    dated = [o for o in orders if o["time"]]
    if not dated:
        return {"empty": True, "reason": "订单缺少时间字段"}

    daily = defaultdict(float)
    daily_count = Counter()
    monthly = defaultdict(float)
    for o in dated:
        d = o["time"].strftime("%Y-%m-%d")
        daily[d] += o["amount"]
        daily_count[d] += 1
        monthly[o["time"].strftime("%Y-%m")] += o["amount"]

    days = sorted(daily)
    span_days = (max(o["time"] for o in dated) - min(o["time"] for o in dated)).days + 1
    total = sum(daily.values())
    daily_avg = total / max(len(daily), 1)

    active_months = sorted(monthly)
    latest_month = active_months[-1]
    latest_total = monthly[latest_month]

    # 环比
    mom_change = None
    if len(active_months) >= 2:
        prev = monthly[active_months[-2]]
        if prev > 0:
            mom_change = round((latest_total - prev) / prev * 100, 1)

    # 下月预测（近 3 个月线性外推，样本不足则不给预测）
    forecast = None
    if len(active_months) >= 2:
        recent = [monthly[m] for m in active_months[-3:]]
        if len(recent) >= 2:
            n = len(recent)
            slope = (recent[-1] - recent[0]) / (n - 1)
            forecast = round(recent[-1] + slope, 2)

    # 周维度
    weekly = defaultdict(float)
    for o in dated:
        monday = o["time"] - timedelta(days=o["time"].weekday())
        weekly[monday.strftime("%Y-%m-%d")] += o["amount"]

    # 建议预算：当月尚未结束时，按当前节奏折算全月，避免"进行中月份"低估预算
    today = datetime.now()
    current_y_m = today.strftime("%Y-%m")
    days_in_month = 31
    if latest_month == current_y_m:
        elapsed = max(today.day, 1)
        days_in_month = elapsed
        full_month_estimate = latest_total / elapsed * days_in_month_in_month(today)
    else:
        full_month_estimate = latest_total

    # 建议预算 = 全月预估 × 1.2 缓冲
    budget = monthly_budget or (full_month_estimate or latest_total) * 1.2
    usage_base = full_month_estimate if not monthly_budget else budget

    active_days = len(daily)
    span_days = span_days

    # 下单最频繁：优先展示单日多笔的高频日；若每日均仅 1 笔则返回 None
    peak_freq = max(daily_count.values()) if daily_count else 0
    busiest = None
    if peak_freq >= 2:
        busiest = (max(daily_count.items(), key=lambda x: x[1]), peak_freq)

    return {
        "empty": False,
        "latest_month": latest_month,
        "latest_month_total": round(latest_total, 2),
        "monthly": {k: round(v, 2) for k, v in sorted(monthly.items())},
        "daily": {k: round(v, 2) for k, v in sorted(daily.items())},
        "weekly": {k: round(v, 2) for k, v in sorted(weekly.items())},
        "daily_avg": round(daily_avg, 2),
        "monthly_avg": round(total / len(active_months), 2),
        "mom_change": mom_change,
        "forecast": forecast,
        "budget_suggestion": round(budget, 2),
        "budget_usage": round(latest_total / usage_base * 100, 1) if usage_base else None,
        "month_is_running": latest_month == current_y_m,
        "active_days": active_days,
        "span_days": span_days,
        "peak_day": max(daily.items(), key=lambda x: x[1]) if daily else None,
        "busiest_day": busiest,
    }


# ============================================================
# 报告渲染
# ============================================================

def render_report(bill, mood, nutrition, spend):
    """把四个引擎的结果渲染成 Markdown 报告。"""
    lines = []
    add = lines.append

    add("## 🍔 麦当劳情绪食鉴报告")
    add("")

    # 情绪概览
    if not mood.get("empty"):
        add("> {} —— {}（{} 分）".format(mood["date"], mood["tag"], mood["score"]))
        add("")

    add("### 💗 情绪解读")
    add("")
    if mood.get("empty"):
        add("_订单数据不足，无法解码情绪。_")
        add("")
    else:
        add("**情绪标签：{}（{} 分）**".format(mood["tag"], mood["score"]))
        add("")
        add("| 因子 | 强度 |")
        add("|---|---|")
        for k, v in mood["factors"].items():
            add("| {} | {:.0f}/100 |".format(k, v))
        add("")
        if mood["triggers"]:
            add("**触发因子：**")
            add("")
            for t in mood["triggers"]:
                add("- {} **{}** — {}".format(t["icon"], t["type"], t["detail"]))
        else:
            add("**触发因子：** 无明显情绪信号，属于常规节奏消费。")
        add("")
        add("> 💬 {}".format(mood["advice"]))
        add(">")
        add("> *{}*".format(mood["disclaimer"]))
        add("")

    # 账单
    add("### 💰 账单统计")
    add("")
    if bill.get("empty"):
        add("_暂无可分析的订单。_")
    else:
        add("| 指标 | 数值 |")
        add("|---|---|")
        add("| 订单笔数 | {} 笔 |".format(bill["count"]))
        add("| 总支出 | ¥{:.2f} |".format(bill["total"]))
        add("| 客单价 | ¥{:.2f} |".format(bill["avg"]))
        add("| 最高单笔 | ¥{:.2f} |".format(bill["max"]))
        if bill.get("date_range"):
            add("| 统计区间 | {} ~ {} |".format(bill["date_range"][0], bill["date_range"][1]))
        add("")
        if bill["store_rank"]:
            add("**门店 TOP3：** " + " / ".join(
                "{}（{} 次）".format(s, c) for s, c in bill["store_rank"][:3]))
            add("")
        if bill["hour_bucket"]:
            add("**时段分布：**")
            add("")
            for label, cnt in bill["hour_bucket"]:
                add("- {}: {} 笔".format(label, cnt))
            add("")

    # 营养
    add("### 🥗 营养画像")
    add("")
    if nutrition.get("empty"):
        add("_营养数据不足（{}）。_".format(nutrition.get("reason", "订单为空")))
    else:
        t = nutrition["totals"]
        add("统计范围：{}".format(nutrition["scope"]))
        add("")
        add("| 营养素 | 摄入 | 参考 | 评级 |")
        add("|---|---|---|---|")
        rows = [
            ("能量", "{:.0f} kcal".format(t["energy_kcal"]), "≤2000 kcal", "energy_kcal"),
            ("脂肪供能比", "{:.0f}%".format(nutrition["fat_energy_ratio"]), "20%-30%", "fat_ratio"),
            ("钠", "{:.0f} mg".format(t["sodium_mg"]), "≤2000 mg", "sodium_mg"),
            ("蛋白质", "{:.0f} g".format(t["protein_g"]), "60 g", "protein_g"),
            ("钙", "{:.0f} mg".format(t["calcium_mg"]), "800 mg", "calcium_mg"),
        ]
        for label, val, ref, key in rows:
            icon, note = nutrition["ratings"][key]
            add("| {} | {} | {} | {} {} |".format(label, val, ref, icon, note))
        add("")
        add("**💡 改进建议：**")
        add("")
        for i, s in enumerate(nutrition["suggestions"], 1):
            add("{}. {}".format(i, s))
        add("")
        if nutrition["unmatched_items"]:
            add("_未匹配营养数据的餐品（{} 项）：{}。建议在营养库中补充。_".format(
                len(nutrition["unmatched_items"]),
                "、".join(nutrition["unmatched_items"][:5])))
            add("")
        add("> *{}*".format(nutrition["disclaimer"]))
        add("")

    # 开支
    add("### 📅 开支账本")
    add("")
    if spend.get("empty"):
        add("_开支数据不足。_")
    else:
        add("| 指标 | 数值 |")
        add("|---|---|")
        add("| 本月（{}） | ¥{:.2f} |".format(spend["latest_month"], spend["latest_month_total"]))
        add("| 月均开支 | ¥{:.2f} |".format(spend["monthly_avg"]))
        add("| 日均开支 | ¥{:.2f} |".format(spend["daily_avg"]))
        if spend["mom_change"] is not None:
            arrow = "↑" if spend["mom_change"] > 0 else "↓"
            add("| 环比上月 | {} {:.1f}% |".format(arrow, abs(spend["mom_change"])))
        add("| 下月预测 | {} |".format(
            "¥{:.2f}".format(spend["forecast"]) if spend["forecast"] else "数据积累中，暂不预测"))
        add("| 建议月度预算 | ¥{:.2f} |".format(spend["budget_suggestion"]))
        if spend["budget_usage"]:
            add("| 当前预算占比 | {:.1f}% |".format(spend["budget_usage"]))
        add("")
        if spend["peak_day"]:
            add("- **消费最高日**：{} ¥{:.2f}".format(spend["peak_day"][0], spend["peak_day"][1]))
        if spend["busiest_day"]:
            (day, cnt), _ = spend["busiest_day"]
            add("- **下单最频繁**：{} 共 {} 笔".format(day, cnt))
        if spend.get("month_is_running"):
            add("- _本月仍在进行中，预算与占比已按当前节奏折算全月。_")
        add("")

    add("---")
    add("")
    add("_数据来源：麦当劳 MCP Server（order-list / list-nutrition-foods / now-time-info）_")
    return "\n".join(lines)


# ============================================================
# 演示数据
# ============================================================

DEMO_ORDERS = [
    {"orderId": "D001", "orderType": "delivery", "createTime": "2026-09-03 12:15:00",
     "storeName": "麦当劳陆家嘴中心店", "orderStatus": "FINISHED", "realTotalAmount": "42.50",
     "orderProductList": [{"productName": "巨无霸套餐", "quantity": 1}]},
    {"orderId": "D002", "orderType": "delivery", "createTime": "2026-09-08 21:40:00",
     "storeName": "麦当劳南京西路店", "orderStatus": "FINISHED", "realTotalAmount": "58.00",
     "orderProductList": [{"productName": "麦辣鸡腿汉堡套餐", "quantity": 1}]},
    {"orderId": "D003", "orderType": "dine_in", "createTime": "2026-09-15 12:30:00",
     "storeName": "麦当劳陆家嘴中心店", "orderStatus": "FINISHED", "realTotalAmount": "35.00",
     "orderProductList": [{"productName": "板烧鸡腿堡套餐", "quantity": 1}]},
    {"orderId": "D004", "orderType": "delivery", "createTime": "2026-09-22 23:05:00",
     "storeName": "麦当劳静安寺店", "orderStatus": "FINISHED", "realTotalAmount": "88.50",
     "orderProductList": [{"productName": "巨无霸套餐", "quantity": 1},
                          {"productName": "麦乐鸡5块", "quantity": 1},
                          {"productName": "朱古力新地", "quantity": 1}]},
    {"orderId": "D005", "orderType": "dine_in", "createTime": "2026-09-28 19:20:00",
     "storeName": "麦当劳南京西路店", "orderStatus": "FINISHED", "realTotalAmount": "61.00",
     "orderProductList": [{"productName": "双层吉士汉堡套餐", "quantity": 1},
                          {"productName": "中薯条", "quantity": 1}]},
    {"orderId": "D006", "orderType": "delivery", "createTime": "2026-10-05 22:50:00",
     "storeName": "麦当劳静安寺店", "orderStatus": "FINISHED", "realTotalAmount": "96.00",
     "orderProductList": [{"productName": "双层原味板烧鸡腿麦满分套餐", "quantity": 1},
                          {"productName": "奥利奥麦旋风", "quantity": 1}]},
    {"orderId": "D007", "orderType": "delivery", "createTime": "2026-10-11 23:30:00",
     "storeName": "麦当劳陆家嘴中心店", "orderStatus": "FINISHED", "realTotalAmount": "112.00",
     "orderProductList": [{"productName": "巨无霸套餐", "quantity": 1},
                          {"productName": "麦辣鸡翅-2块", "quantity": 1},
                          {"productName": "香芋派", "quantity": 2}]},
    {"orderId": "D008", "orderType": "dine_in", "createTime": "2026-10-12 08:10:00",
     "storeName": "静安寺地铁站麦当劳", "orderStatus": "FINISHED", "realTotalAmount": "28.00",
     "orderProductList": [{"productName": "猪柳麦满分", "quantity": 1},
                          {"productName": "小杯玉米杯", "quantity": 1}]},
]


def run_demo():
    """用内置样例跑通全流程。"""
    db = load_nutrition_db()
    orders = [normalize_order(o) for o in DEMO_ORDERS]
    return orders, db


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="麦当劳情绪食鉴官 · 分析引擎",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--orders", help="MCP order-list 落盘的 JSON 路径")
    parser.add_argument("--mode", default="all",
                        choices=["bill", "mood", "nutrition", "spend", "all"],
                        help="分析模式")
    parser.add_argument("--date", help="指定分析日期 YYYY-MM-DD，默认最近一次下单日")
    parser.add_argument("--budget", type=float, help="自定义月度预算（元）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 而非 Markdown")
    parser.add_argument("--demo", action="store_true", help="使用内置样例数据运行")
    args = parser.parse_args()

    db = load_nutrition_db()

    if args.demo:
        orders = [normalize_order(o) for o in DEMO_ORDERS]
        print("⚠️  当前为演示模式，数据为样例数据，非真实用户账单。\n", file=sys.stderr)
    elif args.orders:
        if not os.path.exists(args.orders):
            print("❌ 订单文件不存在：{}".format(args.orders), file=sys.stderr)
            return 1
        orders = load_orders(args.orders)
    else:
        print("❌ 请通过 --orders 指定订单文件，或使用 --demo 演示模式。", file=sys.stderr)
        return 1

    if not orders:
        msg = ("暂无可分析的订单记录。\n"
               "可能原因：\n"
               "  1. 麦当劳 MCP 账号未完成授权\n"
               "  2. 该账号确实没有历史订单\n"
               "请先在 WorkBuddy 中完成 MCP 授权，再重新执行。")
        if args.json:
            print(json.dumps({"empty": True, "message": msg}, ensure_ascii=False, indent=2))
        else:
            print(msg)
        return 0

    bill = analyze_bill(orders)
    mood = analyze_mood(orders, db, args.date)
    nutrition = analyze_nutrition(orders, db, args.date)
    spend = analyze_spend(orders, args.budget)

    if args.mode == "bill":
        result = bill
    elif args.mode == "mood":
        result = mood
    elif args.mode == "nutrition":
        result = nutrition
    elif args.mode == "spend":
        result = spend
    else:
        result = {"bill": bill, "mood": mood, "nutrition": nutrition, "spend": spend}

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    elif args.mode == "all":
        print(render_report(bill, mood, nutrition, spend))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    return 0


if __name__ == "__main__":
    sys.exit(main())
