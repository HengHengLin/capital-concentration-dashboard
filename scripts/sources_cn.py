# -*- coding: utf-8 -*-
"""A股数据源 - akshare，带重试和分批限速"""
import logging
import datetime
import time
import pandas as pd
import akshare as ak
from config import CN_INDICES, KCB50_INDEX_CODE, QVIX_FUNCS, SEMICONDUCTOR_KEYWORDS

log = logging.getLogger("sources_cn")


def safe(fn, *args, retries=3, delay=5, **kwargs):
    """带重试的安全调用，每次失败等 delay 秒再试"""
    for i in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            log.warning(f"{fn.__name__} attempt {i+1}/{retries} failed: {e}")
            if i < retries - 1:
                time.sleep(delay)
    return None


def get_cn_indices(days=90):
    start = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%Y%m%d")
    out = {}
    for name, code in CN_INDICES.items():
        df = safe(ak.index_zh_a_hist, symbol=code, period="daily", start_date=start)
        if df is not None and not df.empty:
            out[name] = df
        time.sleep(1)
    return out


def get_kcb50_weights():
    return safe(ak.index_stock_cons_weight_csindex, symbol=KCB50_INDEX_CODE)


def get_semiconductor_codes(weights_df):
    if weights_df is None or weights_df.empty:
        return set()
    name_col = next((c for c in weights_df.columns if "名称" in c), None)
    code_col  = next((c for c in weights_df.columns if "代码" in c), None)
    if not name_col or not code_col:
        return set()
    mask = weights_df[name_col].astype(str).apply(
        lambda x: any(k in x for k in SEMICONDUCTOR_KEYWORDS)
    )
    return set(weights_df[mask][code_col].astype(str).str.zfill(6))


def get_realtime_spot():
    return safe(ak.stock_zh_a_spot_em, retries=3, delay=8)


def compute_concentration(weights_df, spot_df):
    result = {"sector_turnover_share": None, "top10_turnover_hhi": None}
    if weights_df is None or weights_df.empty or spot_df is None or spot_df.empty:
        return result
    code_col = next((c for c in weights_df.columns if "代码" in c), None)
    if not code_col:
        return result
    all_codes  = set(weights_df[code_col].astype(str).str.zfill(6))
    semi_codes = get_semiconductor_codes(weights_df)
    sc = "代码"   if "代码"   in spot_df.columns else None
    tc = "成交额" if "成交额" in spot_df.columns else None
    if not sc or not tc:
        return result
    sub = spot_df[spot_df[sc].astype(str).str.zfill(6).isin(all_codes)].copy()
    if sub.empty:
        return result
    total = sub[tc].sum()
    if total <= 0:
        return result
    semi_sum = sub[sub[sc].astype(str).str.zfill(6).isin(semi_codes)][tc].sum()
    result["sector_turnover_share"] = round(semi_sum / total, 4)
    top10_shares = sub.nlargest(10, tc)[tc] / total
    result["top10_turnover_hhi"]    = round(float((top10_shares ** 2).sum()), 4)
    return result


def get_all_qvix():
    out = {}
    for fn_name, label in QVIX_FUNCS.items():
        fn = getattr(ak, fn_name, None)
        if fn is None:
            continue
        df = safe(fn, retries=2, delay=3)
        if df is not None and not df.empty:
            date_col  = next((c for c in df.columns if "date" in c.lower() or "日期" in c), df.columns[0])
            close_col = next((c for c in df.columns if "close" in c.lower() or "收盘" in c), df.columns[-1])
            df = df[[date_col, close_col]].copy()
            df.columns = ["date", "close"]
            df["date"]  = df["date"].astype(str).str[:10]
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            out[label]  = df.dropna().sort_values("date")
        time.sleep(1)
    return out


def get_sector_flow_rank():
    return safe(ak.stock_sector_fund_flow_rank, indicator="今日", sector_type="行业资金流", retries=2, delay=5)


def get_sector_flow_hist(sector_name: str):
    df = safe(ak.stock_sector_fund_flow_hist, symbol=sector_name, retries=2, delay=5)
    time.sleep(2)
    return df


def get_concept_flow_hist(concept_name: str):
    df = safe(ak.stock_concept_fund_flow_hist, symbol=concept_name, retries=2, delay=5)
    time.sleep(2)
    return df


def get_margin_history(days=90):
    end   = datetime.date.today().strftime("%Y%m%d")
    start = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%Y%m%d")
    sse   = safe(ak.stock_margin_sse,  start_date=start, end_date=end, retries=2, delay=5)
    time.sleep(2)
    szse  = safe(ak.stock_margin_szse, start_date=start, end_date=end, retries=2, delay=5)
    return {"sse": sse, "szse": szse}


def get_pcr_series(days=60):
    results = []
    today = datetime.date.today()
    for i in range(days, 0, -1):
        d = today - datetime.timedelta(days=i)
        if d.weekday() >= 5:
            continue
        date_str = d.strftime("%Y%m%d")
        df = safe(ak.option_daily_stats_sse, date=date_str, retries=1, delay=2)
        time.sleep(2)
        if df is None or df.empty:
            continue
        try:
            name_col = df.columns[0]
            call_row = df[df[name_col].astype(str).str.contains("认购", na=False)]
            put_row  = df[df[name_col].astype(str).str.contains("认沽", na=False)]
            if call_row.empty or put_row.empty:
                continue
            if df.shape[1] < 3:
                continue
            vol_col  = df.columns[2]
            call_vol = float(str(call_row[vol_col].values[0]).replace(",", ""))
            put_vol  = float(str(put_row[vol_col].values[0]).replace(",", ""))
            if call_vol > 0:
                results.append({
                    "date":       d.strftime("%Y-%m-%d"),
                    "pcr_volume": round(put_vol / call_vol, 4),
                })
        except Exception as e:
            log.warning(f"PCR parse {date_str}: {e}")
    return results
