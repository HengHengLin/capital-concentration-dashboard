# -*- coding: utf-8 -*-
"""
历史数据回填脚本
- QVIX: 拉全部历史 (接口直接返回，约2年+)
- 两融余额: 拉2年
- 成交额集中度: 逐只科创50成分股拉历史成交额，默认180天，约需10-20分钟

用法:
  python backfill_history.py              # 默认180天
  python backfill_history.py --days 90   # 只回填90天集中度
  python backfill_history.py --skip-concentration  # 跳过集中度，只回填QVIX和两融（几分钟跑完）
"""
import argparse
import datetime
import json
import logging
import os
import time

import akshare as ak
import pandas as pd

from config import (
    KCB50_INDEX_CODE, QVIX_FUNCS,
    SEMICONDUCTOR_KEYWORDS, HISTORY_FILE
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backfill")


def safe(fn, *args, retries=3, delay=8, **kwargs):
    for i in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            log.warning(f"{fn.__name__} attempt {i+1}/{retries}: {e}")
            if i < retries - 1:
                time.sleep(delay)
    return None


def fetch_qvix_history():
    log.info("拉取QVIX全量历史...")
    by_date = {}
    for fn_name in ["index_option_kcb_qvix", "index_option_50etf_qvix"]:
        fn = getattr(ak, fn_name, None)
        if fn is None:
            continue
        df = safe(fn)
        if df is None or df.empty:
            continue
        date_col  = next((c for c in df.columns if "date" in c.lower() or "日期" in c), df.columns[0])
        close_col = next((c for c in df.columns if "close" in c.lower() or "收盘" in c), df.columns[-1])
        for _, row in df.iterrows():
            d = str(row[date_col])[:10]
            if d not in by_date:
                try:
                    by_date[d] = float(row[close_col])
                except:
                    pass
        log.info(f"  {fn_name}: {len(df)} 条")
        time.sleep(2)
    log.info(f"QVIX合并后共 {len(by_date)} 个交易日")
    return by_date


def fetch_margin_history(years=2):
    log.info(f"拉取两融余额历史（{years}年）...")
    end   = datetime.date.today().strftime("%Y%m%d")
    start = (datetime.date.today() - datetime.timedelta(days=365*years)).strftime("%Y%m%d")
    sse   = safe(ak.stock_margin_sse, start_date=start, end_date=end)
    time.sleep(3)
    if sse is None or sse.empty:
        log.warning("两融余额数据为空")
        return {}
    date_col = next((c for c in sse.columns if "日期" in c), sse.columns[0])
    bal_col  = next((c for c in sse.columns if "余额" in c), None)
    if not bal_col:
        log.warning(f"找不到余额列，现有列: {sse.columns.tolist()}")
        return {}
    sse = sse.sort_values(date_col).reset_index(drop=True)
    by_date = {}
    for i in range(5, len(sse)):
        d  = str(sse.loc[i, date_col])[:10]
        v0 = float(sse.loc[i-5, bal_col])
        v1 = float(sse.loc[i,   bal_col])
        if v0 > 0:
            by_date[d] = round((v1/v0 - 1) * 100, 4)
    log.info(f"两融动量共 {len(by_date)} 个交易日")
    return by_date


def fetch_concentration_history(days=180):
    log.info(f"拉取科创50成分股成交额历史（{days}天）...")
    log.info("  逐只股票请求，预计需要 10-20 分钟，请勿中断...")
    weights = safe(ak.index_stock_cons_weight_csindex, symbol=KCB50_INDEX_CODE)
    if weights is None or weights.empty:
        log.warning("获取科创50权重失败，跳过集中度回填")
        return {}
    code_col = next((c for c in weights.columns if "代码" in c), None)
    name_col = next((c for c in weights.columns if "名称" in c), None)
    if not code_col:
        log.warning("权重表找不到代码列")
        return {}
    codes = weights[code_col].astype(str).str.zfill(6).tolist()
    semi_codes = set()
    if name_col:
        mask = weights[name_col].astype(str).apply(
            lambda x: any(k in x for k in SEMICONDUCTOR_KEYWORDS)
        )
        semi_codes = set(weights[mask][code_col].astype(str).str.zfill(6))
    log.info(f"  科创50共 {len(codes)} 只，半导体筛出 {len(semi_codes)} 只")
    end   = datetime.date.today().strftime("%Y%m%d")
    start = (datetime.date.today() - datetime.timedelta(days=days+10)).strftime("%Y%m%d")
    turnover_map = {}
    for idx, code in enumerate(codes):
        log.info(f"  [{idx+1}/{len(codes)}] {code}")
        df = safe(ak.stock_zh_a_hist, symbol=code, period="daily",
                  start_date=start, end_date=end, adjust="", retries=3, delay=8)
        if df is None or df.empty:
            time.sleep(2)
            continue
        date_col_s = next((c for c in df.columns if "日期" in c), None)
        turn_col   = next((c for c in df.columns if "成交额" in c), None)
        if not date_col_s or not turn_col:
            time.sleep(2)
            continue
        for _, row in df.iterrows():
            d = str(row[date_col_s])[:10]
            t = float(row[turn_col]) if row[turn_col] else 0
            if d not in turnover_map:
                turnover_map[d] = {}
            turnover_map[d][code] = t
        time.sleep(1.5)
    if not turnover_map:
        log.warning("成交额数据全部为空")
        return {}
    result = {}
    for d, code_map in sorted(turnover_map.items()):
        total = sum(code_map.values())
        if total <= 0:
            continue
        semi_sum     = sum(v for k,v in code_map.items() if k in semi_codes)
        sector_share = round(semi_sum / total, 4)
        top10        = sorted(code_map.values(), reverse=True)[:10]
        hhi          = round(sum((v/total)**2 for v in top10), 4)
        result[d]    = {"sector_turnover_share": sector_share, "top10_turnover_hhi": hhi}
    log.info(f"成交额集中度共 {len(result)} 个交易日")
    return result


def merge_and_write(qvix_map, margin_map, conc_map):
    all_dates = sorted(set(qvix_map) | set(margin_map) | set(conc_map))
    today     = datetime.date.today().isoformat()
    all_dates = [d for d in all_dates if "2020-01-01" <= d <= today]
    os.makedirs(os.path.dirname(HISTORY_FILE) if os.path.dirname(HISTORY_FILE) else ".", exist_ok=True)
    written = 0
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        for d in all_dates:
            conc = conc_map.get(d, {})
            snap = {
                "timestamp":             d + "T16:00:00",
                "sector_turnover_share": conc.get("sector_turnover_share"),
                "top10_turnover_hhi":    conc.get("top10_turnover_hhi"),
                "qvix_kcb_percentile":   qvix_map.get(d),
                "margin_momentum":       margin_map.get(d),
                "score":                 None,
                "backfilled":            True,
            }
            vals = [snap["sector_turnover_share"], snap["top10_turnover_hhi"],
                    snap["qvix_kcb_percentile"], snap["margin_momentum"]]
            if any(v is not None for v in vals):
                f.write(json.dumps(snap, ensure_ascii=False) + "\n")
                written += 1
    log.info(f"写入 {written} 条历史快照 -> {HISTORY_FILE}")
    return written


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--skip-concentration", action="store_true")
    args = parser.parse_args()

    qvix_map   = fetch_qvix_history()
    margin_map = fetch_margin_history(years=2)
    conc_map   = {} if args.skip_concentration else fetch_concentration_history(days=args.days)

    written = merge_and_write(qvix_map, margin_map, conc_map)
    log.info(f"回填完成！共 {written} 条")


if __name__ == "__main__":
    main()
