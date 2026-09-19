"""
每天自动抓取 A 股盘面数据 + 龙虎榜 + 同花顺涨停原因
"""
import json
import time
import requests
from datetime import datetime, timedelta, timezone

BJ_TZ = timezone(timedelta(hours=8))
HISTORY_DAYS = 15

def _headers(referer="https://quote.eastmoney.com/"):
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Referer": referer,
        "Accept": "application/json, text/plain, */*",
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
            time.sleep(1.2 * (i + 1))
    return None

# ============== 同花顺 Session ==============
_ths_session = None
def get_ths_session():
    global _ths_session
    if _ths_session is not None:
        return _ths_session
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Referer": "https://data.10jqka.com.cn/",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    try:
        s.get("https://data.10jqka.com.cn/", timeout=10)
    except Exception:
        pass
    _ths_session = s
    return s

# ============== 各接口 ==============

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
        ladder.append({
            "name": x.get("n",""), "code": code,
            "boards": x.get("lbc",1) or 1,
            "change": round(x.get("zdp") or 0, 2),
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

def get_amount_kline(secid, days):
    """K 线接口，4 次重试"""
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {"secid":secid,"fields1":"f1,f2,f3,f4,f5,f6",
              "fields2":"f51,f57","klt":"101","fqt":"1",
              "end":"20500101","lmt":str(days)}
    for i in range(4):
        data = fetch_json(url, params, referer="https://quote.eastmoney.com/center/", timeout=25)
        if data and data.get("data"):
            klines = data["data"].get("klines", []) or []
            out = {}
            for line in klines:
                parts = line.split(",")
                if len(parts) >= 2:
                    try:
                        out[parts[0]] = float(parts[1])
                    except:
                        pass
            if out:
                return out
        time.sleep(1.5 * (i + 1))
    print(f"  [WARN] K线接口失败 {secid}")
    return {}

def get_history(prev):
    print(f"  抓取过去 {HISTORY_DAYS} 个交易日...")
    amt_sh = get_amount_kline("1.000001", HISTORY_DAYS + 5)
    amt_sz = get_amount_kline("0.399001", HISTORY_DAYS + 5)
    common = sorted(set(amt_sh.keys()) & set(amt_sz.keys()))[-HISTORY_DAYS:]

    if not common and prev:
        pa = prev.get("amount", {}).get("history") or []
        pz = prev.get("limit", {}).get("history") or []
        pd = prev.get("limit", {}).get("downHistory") or []
        pdates = prev.get("dates") or []
        if pa:
            print("  K线失败 → 用上次历史数据")
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

def get_ths_zt_reason(date_str):
    """同花顺涨停原因（带 cookie 的 Session）"""
    s = get_ths_session()
    url = "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool"
    params = {
        "page": "1", "limit": "300",
        "field": "199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004",
        "filter": "HS,GEM2STAR",
        "order_field": "330324", "order_type": "0",
        "date": date_str,
    }
    for i in range(2):
        try:
            r = s.get(url, params=params, timeout=20)
            if r.status_code != 200:
                print(f"  同花顺 HTTP {r.status_code}")
                continue
            data = r.json()
            if data.get("status_code") != 0:
                print(f"  同花顺状态异常: {data.get('status_msg')}")
                continue
            info = data.get("data", {}).get("info", []) or []
            result = {}
            for x in info:
                code = str(x.get("code", "")).zfill(6)
                reason_tags = x.get("330323", "") or ""
                reason_detail = x.get("330329", "") or ""
                concepts = [t.strip() for t in reason_tags.split("+") if t.strip()]
                result[code] = {"concepts": concepts, "reason": reason_detail}
            print(f"  同花顺：{len(result)} 只")
            return result
        except Exception as e:
            print(f"  同花顺失败：{e}")
            time.sleep(1)
    return {}

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
        print(f"  龙虎榜无数据")
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

def load_prev():
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

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
    prev = load_prev()

    trade_date_str, trade_dt = find_latest_trade_date()
    print(f"最近交易日：{trade_dt.strftime('%Y-%m-%d')}")

    indices = get_indices()
    zt = get_zt_pool(trade_date_str)
    limit_up = zt["count"]
    ladder = zt["ladder"]
    max_board = max([s["boards"] for s in ladder], default=0)
    limit_down = get_dt_count(trade_date_str)
    print(f"涨停 {limit_up} 家，最高 {max_board} 板，跌停 {limit_down} 家")

    ths_map = get_ths_zt_reason(trade_date_str)
    for s in ladder:
        ths = ths_map.get(s["code"], {})
        s["concepts"] = ths.get("concepts", [])
        s["reason"] = ths.get("reason", "")

    history = get_history(prev)
    breadth = get_breadth()
    amount = get_amount()

    if amount == 0 and history["amount"]:
        amount = history["amount"][-1]
        print(f"  成交额兜底：{amount/1e8:.0f} 亿")

    if breadth["up"] == 0 and breadth["down"] == 0 and breadth["flat"] == 0 and prev:
        ob = (prev.get("breadth") or {})
        if (ob.get("up") or 0) > 0:
            breadth = {"up": ob["up"], "down": ob["down"], "flat": ob["flat"]}
            print(f"  涨跌家数兜底")

    print(f"  上涨 {breadth['up']}，下跌 {breadth['down']}")
    print(f"  成交额 {amount/1e8:.0f} 亿")

    lhb = get_lhb(trade_date_str)
    if not lhb and prev:
        prev_lhb = prev.get("lhb", [])
        if prev_lhb:
            lhb = prev_lhb
            print(f"  龙虎榜兜底 {len(lhb)} 条")

    theme_map = {}
    for s in ladder:
        for t in s.get("concepts", []) or []:
            if not t: continue
            if t not in theme_map:
                theme_map[t] = {"name":t,"limitUp":0,"maxBoard":0,"leaders":[]}
            theme_map[t]["limitUp"] += 1
            theme_map[t]["maxBoard"] = max(theme_map[t]["maxBoard"], s["boards"])
            if len(theme_map[t]["leaders"]) < 3 and s["name"] not in theme_map[t]["leaders"]:
                theme_map[t]["leaders"].append(s["name"])

    themes = [t for t in theme_map.values() if t["limitUp"] >= 2]
    themes.sort(key=lambda x: x["limitUp"], reverse=True)
    themes = themes[:12]

    if not themes and prev:
        pthemes = prev.get("themes", [])
        if pthemes:
            themes = pthemes
            print(f"  题材兜底 {len(themes)} 个")

    prev_bh = (prev or {}).get("breadth", {}).get("history", [])
    if breadth["up"] > 0:
        breadth_history = (prev_bh + [[breadth["up"], breadth["down"]]])[-HISTORY_DAYS:]
    elif prev_bh:
        breadth_history = prev_bh
    else:
        breadth_history = [[0,0]] * len(history["dates"])

    if ladder and not any(s.get("concepts") for s in ladder) and prev:
        prev_ladder = (prev.get("streak") or {}).get("ladder", [])
        prev_map = {s["code"]: s for s in prev_ladder}
        for s in ladder:
            ps = prev_map.get(s["code"])
            if ps:
                s["concepts"] = ps.get("concepts", [])
                s["reason"] = ps.get("reason", "")
        print(f"  涨停原因兜底")

    now = datetime.now(BJ_TZ)
    result = {
        "updated_at": now.strftime("%Y-%m-%d %H:%M"),
        "trade_date": trade_dt.strftime("%Y-%m-%d"),
        "source": "东方财富 + 同花顺公开接口",
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
