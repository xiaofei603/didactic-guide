"""
每天自动抓取 A 股盘面数据 + 龙虎榜 + 涨停概念 + 封板率 + 涨跌家数
数据源：东方财富 + 腾讯
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

def load_prev_from_github():
    try:
        r = requests.get(GH_RAW + "?_=" + str(int(time.time())), timeout=20)
        if r.status_code == 200:
            d = r.json()
            print("  OK 从 GitHub 读到上次快照")
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

def get_breadth_tencent():
    print("  尝试从腾讯获取当天全市场涨跌家数...")
    ranges = [("sh", 600000, 604000), ("sh", 688000, 689100), ("sz", 1, 1000), ("sz", 300000, 301000)]
    codes = []
    for prefix, start, end in ranges:
        for n in range(start, end, 3): codes.append(prefix + str(n).zfill(6))

    up = down = flat = 0
    batch = 300
    for i in range(0, len(codes), batch):
        chunk = codes[i:i + batch]
        try:
            r = requests.get("http://qt.gtimg.cn/q=" + ",".join(chunk), timeout=5, headers={"User-Agent": "Mozilla/5.0"})
            r.encoding = "gbk"
            for line in r.text.split(";"):
                if "=" not in line: continue
                try:
                    val = line.split('="', 1)[1].rstrip('"')
                    fields = val.split("~")
                    if len(fields) >= 33:
                        chg = float(fields[32])
                        if chg > 0: up += 1
                        elif chg < 0: down += 1
                        else: flat += 1
                except: pass
        except Exception:
            break

    if up + down + flat == 0: return None
    scale = 5000 / (up + down + flat + 0.001)
    return {"up": int(up*scale), "down": int(down*scale), "flat": int(flat*scale)}

def get_indices():
    data = fetch_json("https://push2.eastmoney.com/api/qt/ulist.np/get", {"fltt": "2", "secids": "1.000001,0.399001,0.399006", "fields": "f2,f3,f12,f14", "ut": "fa5fd1943c7b386f172d6893dbfba10b"})
    if not data or not data.get("data"): return []
    return [{"name": x.get("f14", ""), "value": round(x.get("f2") or 0, 2), "change": round(x.get("f3") or 0, 2)} for x in data["data"].get("diff", []) if x.get("f14")]

def get_zt_pool(date_str):
    data = fetch_json("https://push2ex.eastmoney.com/getTopicZTPool", {"ut": "7eea3edcaed734bea9cbfc24409ed989", "dpt": "wz.ztzt", "Pageindex": "0", "pagesize": "1000", "sort": "fbt:asc", "date": date_str, "_": str(int(datetime.now().timestamp() * 1000))})
    if not data or not data.get("data"): return {"count": 0, "ladder": []}
    pool = data["data"].get("pool", []) or []
    ladder = [{"name": x.get("n", ""), "code": str(x.get("c", "")).zfill(6), "boards": x.get("lbc", 1) or 1, "change": round(x.get("zdp") or 0, 2), "industry": x.get("hybk", "") or "", "concepts": [x.get("hybk", "")] if x.get("hybk") else [], "reason": ""} for x in pool]
    ladder.sort(key=lambda x: x["boards"], reverse=True)
    return {"count": len(pool), "ladder": ladder}

def get_zb_count(date_str):
    data = fetch_json("https://push2ex.eastmoney.com/getTopicZBPool", {"ut": "7eea3edcaed734bea9cbfc24409ed989", "dpt": "wz.ztzt", "Pageindex": "0", "pagesize": "1000", "sort": "fbt:asc", "date": date_str, "_": str(int(datetime.now().timestamp() * 1000))})
    if data and data.get("data"):
        # ★ 兼容处理：接口有时不返回 total，需要数 pool 的长度
        total = data["data"].get("total")
        if total is not None: return int(total)
        return len(data["data"].get("pool", []) or [])
    return 0

def get_dt_count(date_str):
    data = fetch_json("https://push2ex.eastmoney.com/getTopicDTPool", {"ut": "7eea3edcaed734bea9cbfc24409ed989", "dpt": "wz.ztzt", "Pageindex": "0", "pagesize": "1000", "sort": "fund:asc", "date": date_str, "_": str(int(datetime.now().timestamp() * 1000))})
    if data and data.get("data"):
        total = data["data"].get("total")
        if total is not None: return int(total)
        return len(data["data"].get("pool", []) or [])
    return 0

def get_amount():
    data = fetch_json("https://push2.eastmoney.com/api/qt/ulist.np/get", {"fltt": "2", "secids": "1.000001,0.399001", "fields": "f6", "ut": "fa5fd1943c7b386f172d6893dbfba10b"})
    return sum(x.get("f6") or 0 for x in data["data"].get("diff", [])) if data and data.get("data") else 0

def get_history(prev):
    if prev:
        pa = (prev.get("amount") or {}).get("history") or []
        if pa:
            return {"dates": prev.get("dates", []), "amount": pa,
                    "zt": (prev.get("limit") or {}).get("history") or [],
                    "dt": (prev.get("limit") or {}).get("downHistory") or [],
                    "zb": (prev.get("limit") or {}).get("zbHistory") or [],
                    "sr": (prev.get("limit") or {}).get("sealHistory") or []}
    return {"dates": [], "amount": [], "zt": [], "dt": [], "zb": [], "sr": []}

def get_lhb(date_str):
    date_fmt = date_str[:4] + "-" + date_str[4:6] + "-" + date_str[6:]
    data = fetch_json("https://datacenter-web.eastmoney.com/api/data/v1/get", {"reportName": "RPT_DAILYBILLBOARD_DETAILSNEW", "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE,EXPLANATION,CHANGE_RATE,BILLBOARD_NET_AMT,BILLBOARD_BUY_AMT,BILLBOARD_SELL_AMT", "filter": f"(TRADE_DATE<='{date_fmt}')(TRADE_DATE>='{date_fmt}')", "pageNumber": "1", "pageSize": "50", "sortColumns": "BILLBOARD_NET_AMT", "sortTypes": "-1", "source": "WEB", "client": "WEB"}, referer="https://data.eastmoney.com/")
    if not data or not data.get("result") or not data["result"].get("data"): return []
    return [{"name": r.get("SECURITY_NAME_ABBR"), "code": r.get("SECURITY_CODE"), "reason": r.get("EXPLANATION") or "—", "change": round(r.get("CHANGE_RATE") or 0, 2), "buy": r.get("BILLBOARD_BUY_AMT") or 0, "sell": r.get("BILLBOARD_SELL_AMT") or 0, "net": r.get("BILLBOARD_NET_AMT") or 0} for r in data["result"]["data"]]

def find_latest_trade_date():
    now = datetime.now(BJ_TZ)
    for i in range(10):
        d = now - timedelta(days=i)
        if d.weekday() >= 5: continue
        ds = d.strftime("%Y%m%d")
        if get_zt_pool(ds)["count"] > 0: return ds, d
    return now.strftime("%Y%m%d"), now

def main():
    print("开始抓取...")
    prev = load_prev_from_github() or load_prev()
    trade_date_str, trade_dt = find_latest_trade_date()

    indices = get_indices()
    zt = get_zt_pool(trade_date_str)
    limit_up = zt["count"]
    ladder = zt["ladder"]
    max_board = max([s["boards"] for s in ladder], default=0)
    
    zb_count = get_zb_count(trade_date_str)
    limit_down = get_dt_count(trade_date_str)

    # 如果抓到的跌停/炸板是 0，但前一天有数据，大概率是接口挂了，强行拿上一次的兜底
    if prev:
        prev_zb = (prev.get("limit") or {}).get("zb")
        if zb_count == 0 and prev_zb: zb_count = prev_zb
        
        prev_dt = (prev.get("limit") or {}).get("down")
        if limit_down == 0 and prev_dt: limit_down = prev_dt

    seal_rate = round(limit_up / (limit_up + zb_count) * 100, 1) if (limit_up + zb_count) > 0 else 0
    print(f"涨停 {limit_up}，跌停 {limit_down}，炸板 {zb_count}，封板率 {seal_rate}%")

    history = get_history(prev)
    amount = get_amount() or (history["amount"][-1] if history["amount"] else 0)
    lhb = get_lhb(trade_date_str) or (prev.get("lhb", []) if prev else [])

    bh_map = {}
    if prev:
        prev_dates = prev.get("dates") or []
        prev_bh_list = (prev.get("breadth") or {}).get("history") or []
        for i, d in enumerate(prev_dates):
            if i < len(prev_bh_list): bh_map[d] = prev_bh_list[i]
    
    breadth = get_breadth_tencent()
    today_short = trade_dt.strftime("%m-%d")
    
    if breadth and (breadth["up"] > 0 or breadth["down"] > 0):
        bh_map[today_short] = [breadth["up"], breadth["down"]]
    else:
        if today_short in bh_map and (bh_map[today_short][0] > 0 or bh_map[today_short][1] > 0):
            breadth = {"up": bh_map[today_short][0], "down": bh_map[today_short][1], "flat": 0}
        else:
            breadth = {"up": 0, "down": 0, "flat": 0}
            bh_map[today_short] = [0, 0]

    # 对齐历史
    if today_short not in history["dates"]:
        history["dates"].append(today_short)
        history["amount"].append(amount)
        history["zt"].append(limit_up)
        history["dt"].append(limit_down)
        history["zb"].append(zb_count)
        history["sr"].append(seal_rate)
    else:
        idx = history["dates"].index(today_short)
        history["amount"][idx] = amount
        history["zt"][idx] = limit_up
        history["dt"][idx] = limit_down
        history["zb"][idx] = zb_count
        history["sr"][idx] = seal_rate

    breadth_history = [bh_map.get(d, [0, 0]) for d in history["dates"]]

    result = {
        "updated_at": datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M"),
        "trade_date": trade_dt.strftime("%Y-%m-%d"),
        "source": "东方财富 + 腾讯",
        "dates": history["dates"],
        "indices": indices,
        "amount": {"total": amount, "history": history["amount"]},
        "breadth": {"up": breadth["up"], "down": breadth["down"], "flat": breadth["flat"], "history": breadth_history},
        "limit": {"up": limit_up, "down": limit_down, "zb": zb_count, "sealRate": seal_rate, "history": history["zt"], "downHistory": history["dt"], "zbHistory": history["zb"], "sealHistory": history["sr"]},
        "streak": {"max": max_board, "ladder": ladder},
        "themes": prev.get("themes", []) if prev else [],
        "lhb": lhb,
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("已写入 data.json")

if __name__ == "__main__":
    main()
