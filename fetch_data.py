"""
每天自动抓取 A 股盘面数据 + 龙虎榜 + 涨停概念
数据源：东方财富 + 腾讯（K线兜底）
"""
import json
import time
import requests
from datetime import datetime, timedelta, timezone

BJ_TZ = timezone(timedelta(hours=8))
HISTORY_DAYS = 15
GH_RAW = "https://raw.githubusercontent.com/xiaofei603/didactic-guide/main/data.json"

def _headers(referer="https://quote.eastmoney.com/"):
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Referer": referer,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

def fetch_json(url, params=None, referer="https://quote.eastmoney.com/", retry=3, timeout=20):
    for i in range(retry):
        try:
            r = requests.get(url, params=params, headers=_headers(referer), timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if i == retry - 1:
                print(f"[ERR] {url}: {e}")
                return None
            time.sleep(1.5 * (i + 1))
    return None

# ============ 备用兜底：从 GitHub raw 读上一次 data.json ============
def load_prev_from_github():
    try:
        r = requests.get(GH_RAW + "?_=" + str(int(time.time())), timeout=20)
        if r.status_code == 200:
            d = r.json()
            print("  ✓ 从 GitHub 读到上次快照")
            return d
    except Exception as e:
        print(f"  GitHub 兜底失败: {e}")
    return None

def load_prev():
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

# ============ 各接口 ============

def get_indices():
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {"fltt":"2","secids":"1.000001,0.399001,0.399006",
              "fields":"f2,f3,f12,f14","ut":"fa5fd1943c7b386f172d6893dbfba10b"}
    data = fetch_json(url, params)
    if not data or not data.get("data"): return []
    return [{"name":x.get("f14",""),"value":round(x.get("f2") or 0,2),"change":round(x.get("f3") or 0,2)}
            for x in data["data"].get("diff",[]) if x.get("f14")]

def get_breadth():
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {"fltt":"2","secids":"1.000001,0.399001",
              "fields":"f104,f105,f106","ut":"fa5fd1943c7b386f172d6893dbfba10b"}
    data = fetch_json(url, params)
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
    data = fetch_json(url, params)
    if not data or not data.get("data"): return {"count":0,"ladder":[]}
    pool = data["data"].get("pool",[]) or []
    ladder = []
    for x in pool:
        code = str(x.get("c","")).zfill(6)
        hybk = x.get("hybk","") or ""
        ladder.append({
            "name": x.get("n",""), "code": code,
            "boards": x.get("lbc",1) or 1,
            "change": round(x.get("zdp") or 0, 2),
            "industry": hybk,
            "concepts": [hybk] if hybk else [],
            "reason": "",
        })
    ladder.sort(key=lambda x:x["boards"], reverse=True)
    return {"count":len(pool),"ladder":ladder}

def get_dt_count(date_str):
    url = "https://push2ex.eastmoney.com/getTopicDTPool"
    params = {"ut":"7eea3edcaed734bea9cbfc24409ed989","dpt":"wz.ztzt",
              "Pageindex":"0","pagesize":"1000","sort":"fund:asc","date":date_str,
              "_":str(int(datetime.now().timestamp()*1000))}
    data = fetch_json(url, params)
    if not data or not data.get("data"): return 0
    return data["data"].get("total") or len(data["data"].get("pool",[]) or [])

def get_amount():
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {"fltt":"2","secids":"1.000001,0.399001","fields":"f6",
              "ut":"fa5fd1943c7b386f172d6893dbfba10b"}
    data = fetch_json(url, params)
    if not data or not data.get("data"): return 0
    return sum(x.get("f6") or 0 for x in data["data"].get("diff",[]))

def get_amount_kline_tencent(code):
    """
    腾讯K线接口（对 GitHub 服务器友好，比东财稳）
    返回 {日期: 成交额(元)}
    腾讯 day 数组每项: [日期, 开, 收, 高, 低, 成交量(手)]
    成交额估算 = 成交量 × 100股 × (开盘+收盘+最高+最低)/4
    """
    url = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
    params = {"param": f"{code},day,,,{HISTORY_DAYS + 5},qfq"}
    try:
        r = requests.get(url, params=params, timeout=20,
                         headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"})
        data = r.json()
        day_list = (data.get("data", {}).get(code) or {}).get("day", []) or []
        out = {}
        for row in day_list:
            if len(row) >= 6:
                try:
                    d = row[0]
                    o, c, h, l = float(row[1]), float(row[2]), float(row[3]), float(row[4])
                    vol = float(row[5])  # 手
                    avg = (o + c + h + l) / 4
                    out[d] = vol * 100 * avg
                except: pass
        if out:
            print(f"  腾讯K线 {code}: {len(out)} 天")
        return out
    except Exception as e:
        print(f"  腾讯K线失败 {code}: {e}")
        return {}

def get_amount_kline_east(secid, days):
    """东方财富K线（首选）"""
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {"secid":secid,"fields1":"f1,f2,f3,f4,f5,f6",
              "fields2":"f51,f57","klt":"101","fqt":"1",
              "beg":"0","end":"20500101","lmt":str(days),
              "ut":"fa5fd1943c7b386f172d6893dbfba10b",
              "_":str(int(datetime.now().timestamp()*1000))}
    data = fetch_json(url, params, retry=2, timeout=25)
    if data and data.get("data"):
        klines = data["data"].get("klines", []) or []
        out = {}
        for line in klines:
            parts = line.split(",")
            if len(parts) >= 2:
                try: out[parts[0]] = float(parts[1])
                except: pass
        if out:
            print(f"  东财K线 {secid}: {len(out)} 天")
            return out
    return {}

def get_history(prev):
    """优先东财，失败用腾讯；都失败用上次快照"""
    print(f"  抓取过去 {HISTORY_DAYS} 个交易日...")
    amt_sh = get_amount_kline_east("1.000001", HISTORY_DAYS + 5)
    amt_sz = get_amount_kline_east("0.399001", HISTORY_DAYS + 5)

    if not amt_sh or not amt_sz:
        print("  东财K线失败 → 用腾讯接口")
        amt_sh = get_amount_kline_tencent("sh000001")
        amt_sz = get_amount_kline_tencent("sz399001")

    common = sorted(set(amt_sh.keys()) & set(amt_sz.keys()))[-HISTORY_DAYS:]

    if not common:
        print("  所有K线接口失败 → 用上次快照")
        if prev:
            pa = (prev.get("amount") or {}).get("history") or []
            pz = (prev.get("limit") or {}).get("history") or []
            pd = (prev.get("limit") or {}).get("downHistory") or []
            pdates = prev.get("dates") or []
            if pa:
                return {"dates": pdates, "amount": pa, "zt": pz, "dt": pd}
        return {"dates": [], "amount": [], "zt": [], "dt": []}

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

def get_lhb(date_str):
    date_fmt = date_str[:4] + "-" + date_str[4:6] + "-" + date_str[6:]
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
        "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE,EXPLANATION,"
                   "CHANGE_RATE,BILLBOARD_NET_AMT,BILLBOARD_BUY_AMT,BILLBOARD_SELL_AMT",
        "filter": f"(TRADE_DATE<='{date_fmt}')(TRADE_DATE>='{date_fmt}')",
        "pageNumber": "1","pageSize": "50",
        "sortColumns": "BILLBOARD_NET_AMT","sortTypes": "-1",
        "source": "WEB","client": "WEB",
    }
    data = fetch_json(url, params, referer="https://data.eastmoney.com/")
    if not data or not data.get("result") or not data["result"].get("data"):
        return []
    rows = data["result"]["data"]
    out = []
    for r in rows:
        out.append({
            "name": r.get("SECURITY_NAME_ABBR") or "",
            "code": r.get("SECURITY_CODE") or "",
            "reason": r.get("EXPLANATION") or "—",
            "change": round(r.get("CHANGE_RATE") or 0, 2),
            "buy": r.get("BILLBOARD_BUY_AMT") or 0,
            "sell": r.get("BILLBOARD_SELL_AMT") or 0,
            "net": r.get("BILLBOARD_NET_AMT") or 0,
        })
    print(f"  龙虎榜：{len(out)} 条")
    return out

def find_latest_trade_date():
    now = datetime.now(BJ_TZ)
    for i in range(10):
        d = now - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        ds = d.strftime("%Y%m%d")
        if get_zt_pool(ds)["count"] > 0:
            return ds, d
    return now.strftime("%Y%m%d"), now

def main():
    print("开始抓取...")
    prev = load_prev() or load_prev_from_github()

    trade_date_str, trade_dt = find_latest_trade_date()
    print(f"最近交易日：{trade_dt.strftime('%Y-%m-%d')}")

    indices = get_indices()
    zt = get_zt_pool(trade_date_str)
    limit_up = zt["count"]
    ladder = zt["ladder"]
    max_board = max([s["boards"] for s in ladder], default=0)
    limit_down = get_dt_count(trade_date_str)
    print(f"涨停 {limit_up} 家，最高 {max_board} 板，跌停 {limit_down} 家")

    history = get_history(prev)
    breadth = get_breadth()
    amount = get_amount()

    if amount == 0 and history["amount"]:
        amount = history["amount"][-1]
        print(f"  成交额兜底：{amount/1e8:.0f} 亿")

    if breadth["up"] == 0 and prev:
        ob = prev.get("breadth") or {}
        if (ob.get("up") or 0) > 0:
            breadth = {"up": ob["up"], "down": ob["down"], "flat": ob["flat"]}
            print(f"  涨跌家数兜底")

    print(f"  上涨 {breadth['up']}，下跌 {breadth['down']}")
    print(f"  成交额 {amount/1e8:.0f} 亿")

    lhb = get_lhb(trade_date_str)
    if not lhb and prev:
        lhb = prev.get("lhb", []) or []
        if lhb: print(f"  龙虎榜兜底 {len(lhb)} 条")

    # 用行业板块聚合题材
    theme_map = {}
    for s in ladder:
        ind = s.get("industry","")
        if not ind: continue
        if ind not in theme_map:
            theme_map[ind] = {"name":ind,"limitUp":0,"maxBoard":0,"leaders":[]}
        theme_map[ind]["limitUp"] += 1
        theme_map[ind]["maxBoard"] = max(theme_map[ind]["maxBoard"], s["boards"])
        if len(theme_map[ind]["leaders"]) < 3:
            theme_map[ind]["leaders"].append(s["name"])

    themes = list(theme_map.values())
    themes.sort(key=lambda x: x["limitUp"], reverse=True)
    themes = themes[:12]

    if not themes and prev:
        themes = prev.get("themes", []) or []

    prev_bh = (prev or {}).get("breadth", {}).get("history", [])
    if breadth["up"] > 0:
        breadth_history = (prev_bh + [[breadth["up"], breadth["down"]]])[-HISTORY_DAYS:]
    elif prev_bh:
        breadth_history = prev_bh
    else:
        breadth_history = [[0,0]] * len(history["dates"])

    now = datetime.now(BJ_TZ)
    result = {
        "updated_at": now.strftime("%Y-%m-%d %H:%M"),
        "trade_date": trade_dt.strftime("%Y-%m-%d"),
        "source": "东方财富 + 腾讯公开接口",
        "dates": history["dates"],
        "indices": indices,
        "amount": {"total": amount, "history": history["amount"]},
        "breadth": {
            "up": breadth["up"], "down": breadth["down"], "flat": breadth["flat"],
            "history": breadth_history,
        },
        "limit": {
            "up": limit_up, "down": limit_down,
            "history": history["zt"], "downHistory": history["dt"],
        },
        "streak": {"max": max_board, "ladder": ladder},
        "themes": themes,
        "lhb": lhb,
    }

    with open("data.json","w",encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"已写入 data.json")

if __name__ == "__main__":
    main()
