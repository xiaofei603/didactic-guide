"""
每天自动抓取 A 股盘面数据，输出 data.json
包含：三大指数、成交额 + 15 日历史、涨跌家数、涨停跌停 + 15 日历史、连板梯队、题材聚合
"""
import json
import requests
from datetime import datetime, timedelta, timezone

BJ_TZ = timezone(timedelta(hours=8))
HISTORY_DAYS = 15

def fetch(url, params=None):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }
    for i in range(3):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if i == 2:
                print(f"[ERROR] {url} 失败: {e}")
                return None
    return None

def get_indices():
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {"fltt":"2","secids":"1.000001,0.399001,0.399006",
              "fields":"f2,f3,f12,f14","ut":"fa5fd1943c7b386f172d6893dbfba10b"}
    data = fetch(url, params)
    if not data or not data.get("data"): return []
    return [{"name":x.get("f14",""),"value":round(x.get("f2") or 0,2),"change":round(x.get("f3") or 0,2)}
            for x in data["data"].get("diff",[]) if x.get("f14")]

def get_breadth():
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {"fltt":"2","secids":"1.000001,0.399001",
              "fields":"f104,f105,f106","ut":"fa5fd1943c7b386f172d6893dbfba10b"}
    data = fetch(url, params)
    if not data or not data.get("data"): return {"up":0,"down":0,"flat":0}
    up=down=flat=0
    for x in data["data"].get("diff",[]):
        up += x.get("f104") or 0
        down += x.get("f105") or 0
        flat += x.get("f106") or 0
    return {"up":up,"down":down,"flat":flat}

def get_zt_pool(date_str):
    url = "https://push2ex.eastmoney.com/getTopicZTPool"
    params = {"ut":"7eea3edcaed734bea9cbfc24409ed989","dpt":"wz.ztzt",
              "Pageindex":"0","pagesize":"1000","sort":"fbt:asc","date":date_str,
              "_":str(int(datetime.now().timestamp()*1000))}
    data = fetch(url, params)
    if not data or not data.get("data"): return {"count":0,"ladder":[]}
    pool = data["data"].get("pool",[]) or []
    ladder = [{"name":x.get("n",""),"code":str(x.get("c","")).zfill(6),
               "boards":x.get("lbc",1) or 1,"theme":(x.get("n","") or "")[:2],
               "change":round(x.get("zdp") or 0,2)} for x in pool]
    ladder.sort(key=lambda x:x["boards"], reverse=True)
    return {"count":len(pool),"ladder":ladder}

def get_dt_count(date_str):
    url = "https://push2ex.eastmoney.com/getTopicDTPool"
    params = {"ut":"7eea3edcaed734bea9cbfc24409ed989","dpt":"wz.ztzt",
              "Pageindex":"0","pagesize":"1000","sort":"fund:asc","date":date_str,
              "_":str(int(datetime.now().timestamp()*1000))}
    data = fetch(url, params)
    if not data or not data.get("data"): return 0
    return data["data"].get("total") or len(data["data"].get("pool",[]) or [])

def get_amount():
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {"fltt":"2","secids":"1.000001,0.399001","fields":"f6",
              "ut":"fa5fd1943c7b386f172d6893dbfba10b"}
    data = fetch(url, params)
    if not data or not data.get("data"): return 0
    return sum(x.get("f6") or 0 for x in data["data"].get("diff",[]))

def get_amount_kline(secid, days):
    """用 K 线接口拿每日成交额"""
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {"secid":secid,"fields1":"f1,f2,f3,f4,f5,f6",
              "fields2":"f51,f57","klt":"101","fqt":"1",
              "end":"20500101","lmt":str(days)}
    data = fetch(url, params)
    if not data or not data.get("data"): return {}
    out = {}
    for line in (data["data"].get("klines",[]) or []):
        parts = line.split(",")
        if len(parts) >= 2:
            out[parts[0]] = float(parts[1])
    return out

def get_history():
    """抓过去 N 个交易日：成交额（K 线） + 涨停跌停（逐日）"""
    print(f"  抓取过去 {HISTORY_DAYS} 个交易日历史...")
    amt_sh = get_amount_kline("1.000001", HISTORY_DAYS + 5)
    amt_sz = get_amount_kline("0.399001", HISTORY_DAYS + 5)
    common = sorted(set(amt_sh.keys()) & set(amt_sz.keys()))[-HISTORY_DAYS:]

    zt_hist, dt_hist = {}, {}
    for d in common:
        ds = d.replace("-","")
        zt_hist[d] = get_zt_pool(ds)["count"]
        dt_hist[d] = get_dt_count(ds)
        print(f"    {d}: 涨停 {zt_hist[d]}, 跌停 {dt_hist[d]}")

    return {
        "dates": [d[5:] for d in common],
        "amount": [amt_sh[d] + amt_sz[d] for d in common],
        "zt": [zt_hist[d] for d in common],
        "dt": [dt_hist[d] for d in common],
    }

def find_latest_trade_date():
    now = datetime.now(BJ_TZ)
    for i in range(10):
        d = now - timedelta(days=i)
        if d.weekday() >= 5:
            print(f"  {d.strftime('%Y-%m-%d')} 周末跳过")
            continue
        ds = d.strftime("%Y%m%d")
        if get_zt_pool(ds)["count"] > 0:
            return ds, d
        print(f"  {d.strftime('%Y-%m-%d')} 无数据")
    return now.strftime("%Y%m%d"), now

def main():
    print("开始抓取...")
    trade_date_str, trade_dt = find_latest_trade_date()
    print(f"最近交易日：{trade_dt.strftime('%Y-%m-%d')}")

    indices = get_indices()
    print(f"指数 {len(indices)} 个")

    zt = get_zt_pool(trade_date_str)
    limit_up = zt["count"]
    ladder = zt["ladder"]
    max_board = max([s["boards"] for s in ladder], default=0)
    print(f"涨停 {limit_up} 家，最高 {max_board} 板")

    limit_down = get_dt_count(trade_date_str)
    print(f"跌停 {limit_down} 家")

    breadth = get_breadth()
    print(f"涨 {breadth['up']} / 跌 {breadth['down']} / 平 {breadth['flat']}")

    amount = get_amount()
    print(f"成交额 {amount/1e8:.0f} 亿")

    history = get_history()

    theme_map = {}
    for s in ladder:
        t = s["theme"]
        if t not in theme_map:
            theme_map[t] = {"name":t,"limitUp":0,"maxBoard":0,"leaders":[]}
        theme_map[t]["limitUp"] += 1
        theme_map[t]["maxBoard"] = max(theme_map[t]["maxBoard"], s["boards"])
        if len(theme_map[t]["leaders"]) < 3:
            theme_map[t]["leaders"].append(s["name"])
    themes = sorted(theme_map.values(), key=lambda x:x["limitUp"], reverse=True)[:10]

    turnover = [{"name":s["name"],"code":s["code"],"rate":0.0,"change":s["change"]}
                for s in ladder[:5]]

    now = datetime.now(BJ_TZ)
    result = {
        "updated_at": now.strftime("%Y-%m-%d %H:%M"),
        "trade_date": trade_dt.strftime("%Y-%m-%d"),
        "source": "东方财富公开接口",
        "dates": history["dates"],
        "indices": indices,
        "amount": {"total": amount, "history": history["amount"]},
        "breadth": {
            "up": breadth["up"], "down": breadth["down"], "flat": breadth["flat"],
            "history": [[breadth["up"], breadth["down"]] for _ in history["dates"]],
        },
        "limit": {
            "up": limit_up, "down": limit_down,
            "history": history["zt"], "downHistory": history["dt"],
        },
        "streak": {"max": max_board, "ladder": ladder},
        "themes": themes,
        "turnover": turnover,
        "lhb": [],
    }

    with open("data.json","w",encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("已写入 data.json")

if __name__ == "__main__":
    main()