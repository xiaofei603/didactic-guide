"""
每天自动抓取 A 股盘面数据 + 龙虎榜 + 涨停概念 + 封板率 + 涨跌家数
数据源：东方财富 + 腾讯
"""
import json
import time
import requests
from datetime import datetime, timedelta, timezone

BJ_TZ = timezone(timedelta(hours=8))
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
        except Exception:
            if i == retry - 1: return None
            time.sleep(1)

def load_prev():
    try:
        r = requests.get(GH_RAW + "?_=" + str(int(time.time())), timeout=15)
        if r.status_code == 200: return r.json()
    except: pass
    try:
        with open("data.json", "r", encoding="utf-8") as f: return json.load(f)
    except: return None

# ==================== 腾讯：找真实的最近交易日 ====================
def get_real_trade_date():
    """用腾讯K线判断今天是不是真实的交易日，避免东财返回上周五的数据"""
    now = datetime.now(BJ_TZ)
    today_str = now.strftime("%Y-%m-%d")
    url = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
    params = {"param": "sh000001,day,,,5,qfq"}
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        days = data["data"]["sh000001"]["day"]
        last_day = days[-1][0] # 最近真实开市的一天
        print(f"  腾讯真实交易日: {last_day}")
        
        # 如果今天在K线里，说明今天有数据；否则用最后一天
        if last_day == today_str:
            return today_str.replace("-", ""), now
        else:
            # 用最后一天的日期
            dt = datetime.strptime(last_day, "%Y-%m-%d").replace(tzinfo=BJ_TZ)
            return last_day.replace("-", ""), dt
    except Exception as e:
        print(f"  腾讯判断失败: {e}")
        # 如果失败，就退回用今天
        return today_str.replace("-", ""), now

# ==================== 腾讯：涨跌家数 ====================
def get_breadth_tencent():
    print("  抓取腾讯涨跌家数...")
    ranges = [("sh", 600000, 604000), ("sh", 688000, 689100), ("sz", 1, 1000), ("sz", 300000, 301000)]
    codes = []
    for prefix, start, end in ranges:
        for n in range(start, end, 5): codes.append(prefix + str(n).zfill(6))

    up = down = flat = 0
    for i in range(0, len(codes), 300):
        chunk = codes[i:i + 300]
        try:
            r = requests.get("http://qt.gtimg.cn/q=" + ",".join(chunk), timeout=5)
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
        except: break

    if up + down + flat == 0: return None
    scale = 5000 / (up + down + flat)
    return {"up": int(up*scale), "down": int(down*scale), "flat": int(flat*scale)}

# ==================== 东方财富接口 ====================
def get_indices():
    data = fetch_json("https://push2.eastmoney.com/api/qt/ulist.np/get", {"fltt": "2", "secids": "1.000001,0.399001,0.399006", "fields": "f2,f3,f12,f14", "ut": "fa5fd1943c7b386f172d6893dbfba10b"})
    if not data or not data.get("data"): return []
    return [{"name": x.get("f14", ""), "value": round(x.get("f2") or 0, 2), "change": round(x.get("f3") or 0, 2)} for x in data["data"].get("diff", []) if x.get("f14")]

def get_zt_pool(date_str):
    data = fetch_json("https://push2ex.eastmoney.com/getTopicZTPool", {"ut": "7eea3edcaed734bea9cbfc24409ed989", "dpt": "wz.ztzt", "Pageindex": "0", "pagesize": "1000", "sort": "fbt:asc", "date": date_str})
    if not data or not data.get("data"): return {"count": 0, "ladder": []}
    pool = data["data"].get("pool", [])
    ladder = [{"name": x.get("n", ""), "code": str(x.get("c", "")).zfill(6), "boards": x.get("lbc", 1) or 1, "change": round(x.get("zdp") or 0, 2), "industry": x.get("hybk", "") or "", "concepts": [x.get("hybk", "")] if x.get("hybk") else [], "reason": ""} for x in pool]
    ladder.sort(key=lambda x: x["boards"], reverse=True)
    return {"count": len(pool), "ladder": ladder}

def get_zb_count(date_str):
    data = fetch_json("https://push2ex.eastmoney.com/getTopicZBPool", {"ut": "7eea3edcaed734bea9cbfc24409ed989", "dpt": "wz.ztzt", "Pageindex": "0", "pagesize": "1000", "sort": "fbt:asc", "date": date_str})
    return data["data"].get("total") or 0 if data and data.get("data") else 0

def get_dt_count(date_str):
    data = fetch_json("https://push2ex.eastmoney.com/getTopicDTPool", {"ut": "7eea3edcaed734bea9cbfc24409ed989", "dpt": "wz.ztzt", "Pageindex": "0", "pagesize": "1000", "sort": "fund:asc", "date": date_str})
    return data["data"].get("total") or 0 if data and data.get("data") else 0

def get_amount():
    data = fetch_json("https://push2.eastmoney.com/api/qt/ulist.np/get", {"fltt": "2", "secids": "1.000001,0.399001", "fields": "f6", "ut": "fa5fd1943c7b386f172d6893dbfba10b"})
    return sum(x.get("f6") or 0 for x in data["data"].get("diff", [])) if data and data.get("data") else 0

def get_lhb(date_str):
    date_fmt = date_str[:4] + "-" + date_str[4:6] + "-" + date_str[6:]
    data = fetch_json("https://datacenter-web.eastmoney.com/api/data/v1/get", {"reportName": "RPT_DAILYBILLBOARD_DETAILSNEW", "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE,EXPLANATION,CHANGE_RATE,BILLBOARD_NET_AMT,BILLBOARD_BUY_AMT,BILLBOARD_SELL_AMT", "filter": f"(TRADE_DATE<='{date_fmt}')(TRADE_DATE>='{date_fmt}')", "pageNumber": "1", "pageSize": "50", "sortColumns": "BILLBOARD_NET_AMT", "sortTypes": "-1", "source": "WEB", "client": "WEB"}, referer="https://data.eastmoney.com/")
    if not data or not data.get("result") or not data["result"].get("data"): return []
    return [{"name": r.get("SECURITY_NAME_ABBR"), "code": r.get("SECURITY_CODE"), "reason": r.get("EXPLANATION") or "—", "change": round(r.get("CHANGE_RATE") or 0, 2), "buy": r.get("BILLBOARD_BUY_AMT") or 0, "sell": r.get("BILLBOARD_SELL_AMT") or 0, "net": r.get("BILLBOARD_NET_AMT") or 0} for r in data["result"]["data"]]

def main():
    print("开始抓取...")
    prev = load_prev() or {}
    
    # 核心修复：通过腾讯找真正交易日，杜绝旧数据贴新标签
    trade_date_str, trade_dt = get_real_trade_date()
    today_short = trade_dt.strftime("%m-%d")
    print(f"锁定交易日: {today_short}")

    # 抓当天数据
    indices = get_indices()
    zt = get_zt_pool(trade_date_str)
    limit_up = zt["count"]
    ladder = zt["ladder"]
    max_board = max([s["boards"] for s in ladder], default=0)
    
    zb_count = get_zb_count(trade_date_str)
    limit_down = get_dt_count(trade_date_str)
    if prev:
        if zb_count == 0: zb_count = prev.get("limit", {}).get("zb") or 1
        if limit_down == 0: limit_down = prev.get("limit", {}).get("down") or 1
    
    seal_rate = round(limit_up / (limit_up + zb_count) * 100, 1)
    amount = get_amount() or prev.get("amount", {}).get("total") or 0
    lhb = get_lhb(trade_date_str) or prev.get("lhb", [])

    breadth = get_breadth_tencent() or {"up": 0, "down": 0, "flat": 0}
    if breadth["up"] == 0 and prev.get("breadth"):
        breadth = {"up": prev["breadth"]["up"], "down": prev["breadth"]["down"], "flat": prev["breadth"]["flat"]}

    # 拼接历史
    history_dates = prev.get("dates", [])
    history_amount = prev.get("amount", {}).get("history", [])
    history_zt = prev.get("limit", {}).get("history", [])
    history_dt = prev.get("limit", {}).get("downHistory", [])
    history_zb = prev.get("limit", {}).get("zbHistory", [])
    history_sr = prev.get("limit", {}).get("sealHistory", [])
    history_bh = prev.get("breadth", {}).get("history", [])

    # 强制对齐
    if today_short in history_dates:
        idx = history_dates.index(today_short)
        history_amount[idx] = amount
        history_zt[idx] = limit_up
        history_dt[idx] = limit_down
        history_zb[idx] = zb_count
        history_sr[idx] = seal_rate
        history_bh[idx] = [breadth["up"], breadth["down"]]
    else:
        history_dates.append(today_short)
        history_amount.append(amount)
        history_zt.append(limit_up)
        history_dt.append(limit_down)
        history_zb.append(zb_count)
        history_sr.append(seal_rate)
        history_bh.append([breadth["up"], breadth["down"]])

    # 截取最近15天
    history_dates = history_dates[-15:]
    history_amount = history_amount[-15:]
    history_zt = history_zt[-15:]
    history_dt = history_dt[-15:]
    history_zb = history_zb[-15:]
    history_sr = history_sr[-15:]
    history_bh = history_bh[-15:]

    result = {
        "updated_at": datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M"),
        "trade_date": trade_dt.strftime("%Y-%m-%d"),
        "source": "东方财富 + 腾讯",
        "dates": history_dates,
        "indices": indices,
        "amount": {"total": amount, "history": history_amount},
        "breadth": {"up": breadth["up"], "down": breadth["down"], "flat": breadth["flat"], "history": history_bh},
        "limit": {"up": limit_up, "down": limit_down, "zb": zb_count, "sealRate": seal_rate, "history": history_zt, "downHistory": history_dt, "zbHistory": history_zb, "sealHistory": history_sr},
        "streak": {"max": max_board, "ladder": ladder},
        "themes": prev.get("themes", []),
        "lhb": lhb,
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"成功写入！真实交易日: {today_short}")

if __name__ == "__main__":
    main()
