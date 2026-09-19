"""
每天自动抓取 A 股盘面数据，生成 data.json
数据来源：东方财富公开接口（免费、无需 key）

在 GitHub Actions 里运行时，系统时间是 UTC，
脚本内部会自动转成北京时间（UTC+8）再取日期。
"""
import json
import requests
from datetime import datetime, timedelta, timezone

# 北京时间时区
BJ_TZ = timezone(timedelta(hours=8))


# ========== 工具函数 ==========

def fetch(url, params=None):
    """带 3 次重试的 GET 请求，返回 JSON 或 None"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0 Safari/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if attempt == 2:
                print(f"[ERROR] {url} 请求失败: {e}")
                return None
            print(f"[WARN] 第 {attempt + 1} 次失败，重试...")
    return None


def get_indices():
    """获取三大指数行情"""
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {
        "fltt": "2",
        "secids": "1.000001,0.399001,0.399006",   # 上证、深证、创业板
        "fields": "f2,f3,f12,f14",
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
    }
    data = fetch(url, params)
    if not data or not data.get("data"):
        return []

    result = []
    for item in data["data"].get("diff", []):
        name = item.get("f14", "")
        value = (item.get("f2") or 0) / 100      # 接口返回的是分，需要除以 100
        change = (item.get("f3") or 0) / 100
        if name:
            result.append({
                "name": name,
                "value": round(value, 2),
                "change": round(change, 2),
            })
    return result


def get_zt_pool():
    """获取涨停股池，返回 {'count': 涨停家数, 'ladder': 连板梯队}"""
    url = "https://push2ex.eastmoney.com/getTopicZTPool"
    today = datetime.now(BJ_TZ).strftime("%Y%m%d")
    params = {
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "dpt": "wz.ztzt",
        "Pageindex": "0",
        "pagesize": "1000",
        "sort": "fbt:asc",
        "date": today,
        "_": str(int(datetime.now().timestamp() * 1000)),
    }
    data = fetch(url, params)
    if not data or not data.get("data"):
        return {"count": 0, "ladder": []}

    pool = data["data"].get("pool", []) or []
    count = len(pool)

    # 按连板数从高到低排序，方便前端分组
    ladder = []
    for stock in pool:
        name = stock.get("n", "")
        code = str(stock.get("c", "")).zfill(6)
        boards = stock.get("lbc", 1) or 1
        change = (stock.get("zdp") or 0)
        # 简单用名称前两个字当题材标签，前端会聚合
        theme = name[:2] if len(name) >= 2 else name

        ladder.append({
            "name": name,
            "code": code,
            "boards": boards,
            "theme": theme,
            "change": round(change, 2),
        })

    ladder.sort(key=lambda x: x["boards"], reverse=True)
    return {"count": count, "ladder": ladder}


def get_dt_count():
    """获取跌停家数"""
    url = "https://push2ex.eastmoney.com/getTopicDTPool"
    today = datetime.now(BJ_TZ).strftime("%Y%m%d")
    params = {
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "dpt": "wz.ztzt",
        "Pageindex": "0",
        "pagesize": "1000",
        "sort": "fund:asc",
        "date": today,
        "_": str(int(datetime.now().timestamp() * 1000)),
    }
    data = fetch(url, params)
    if not data or not data.get("data"):
        return 0
    return data["data"].get("total") or len(data["data"].get("pool", []) or [])


def get_breadth():
    """获取全市场上涨 / 下跌 / 平盘家数"""
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {
        "fltt": "2",
        "secids": "1.000001,0.399001",       # 上证、深证，都带涨跌统计字段
        "fields": "f104,f105,f106",
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
    }
    data = fetch(url, params)
    if not data or not data.get("data"):
        return {"up": 0, "down": 0, "flat": 0}

    diff = data["data"].get("diff", [])
    if not diff:
        return {"up": 0, "down": 0, "flat": 0}

    # 只取一个市场（上证）的统计数据即可，避免重复相加
    item = diff[0]
    return {
        "up": item.get("f104") or 0,
        "down": item.get("f105") or 0,
        "flat": item.get("f106") or 0,
    }


def get_amount():
    """获取两市总成交额（单位：元）"""
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {
        "fltt": "2",
        "secids": "1.000001,0.399001",       # 上证 + 深证 成交额相加
        "fields": "f6",
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
    }
    data = fetch(url, params)
    if not data or not data.get("data"):
        return 0

    total = 0
    for item in data["data"].get("diff", []):
        total += item.get("f6") or 0
    return total


# ========== 主流程 ==========

def main():
    print("开始抓取数据...")

    # 1. 指数
    indices = get_indices()
    print(f"  指数：{len(indices)} 个")

    # 2. 涨停池 & 连板梯队
    zt = get_zt_pool()
    limit_up = zt["count"]
    ladder = zt["ladder"]
    max_board = max([s["boards"] for s in ladder], default=0)
    print(f"  涨停：{limit_up} 家，最高连板：{max_board} 板")

    # 3. 跌停家数
    limit_down = get_dt_count()
    print(f"  跌停：{limit_down} 家")

    # 4. 涨跌家数
    breadth = get_breadth()
    print(f"  上涨：{breadth['up']}，下跌：{breadth['down']}，平盘：{breadth['flat']}")

    # 5. 成交额
    amount = get_amount()
    print(f"  成交额：{amount / 1e8:.0f} 亿")

    # 6. 题材聚合（从连板股里按题材标签统计）
    theme_map = {}
    for s in ladder:
        t = s["theme"]
        if t not in theme_map:
            theme_map[t] = {"name": t, "limitUp": 0, "maxBoard": 0, "leaders": []}
        theme_map[t]["limitUp"] += 1
        theme_map[t]["maxBoard"] = max(theme_map[t]["maxBoard"], s["boards"])
        if len(theme_map[t]["leaders"]) < 3:
            theme_map[t]["leaders"].append(s["name"])

    themes = sorted(theme_map.values(), key=lambda x: x["limitUp"], reverse=True)[:10]

    # 7. 换手率榜（先用连板股占位，后续可换专门接口）
    turnover = []
    for s in ladder[:5]:
        turnover.append({
            "name": s["name"],
            "code": s["code"],
            "rate": 0.0,
            "change": s["change"],
        })

    # 8. 日期序列（近 10 个自然日）
    now = datetime.now(BJ_TZ)
    dates = [(now - timedelta(days=i)).strftime("%m-%d") for i in range(9, -1, -1)]

    # 9. 组装 JSON
    # 注意：历史序列暂时用当前值填充，等脚本连续跑几天后可以改成读历史存档
    result = {
        "updated_at": now.strftime("%Y-%m-%d %H:%M"),
        "trade_date": now.strftime("%Y-%m-%d"),
        "source": "东方财富公开接口",
        "dates": dates,
        "indices": indices,
        "amount": {
            "total": amount,
            "history": [amount] * 10,
        },
        "breadth": {
            "up": breadth["up"],
            "down": breadth["down"],
            "flat": breadth["flat"],
            "history": [[breadth["up"], breadth["down"]]] * 10,
        },
        "limit": {
            "up": limit_up,
            "down": limit_down,
            "history": [limit_up] * 10,
            "downHistory": [limit_down] * 10,
        },
        "streak": {"max": max_board, "ladder": ladder},
        "themes": themes,
        "turnover": turnover,
        "lhb": [],
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("已写入 data.json")


if __name__ == "__main__":
    main()