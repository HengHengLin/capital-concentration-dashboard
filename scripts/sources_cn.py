# -*- coding: utf-8 -*-
"""A股数据源 - akshare"""
import logging
import datetime
import pandas as pd
import akshare as ak
from config import CN_INDICES, KCB50_INDEX_CODE, QVIX_FUNCS, SEMICONDUCTOR_KEYWORDS

log = logging.getLogger("sources_cn")


def safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        log.warning(f"{fn.__name__} failed: {e}")
        return None


# ---------- 指数日线 ----------
def get_cn_indices(days=90):
    start = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%Y%m%d")
    out = {}
    for name, code in CN_INDICES.items():
        df = safe(ak.index_zh_a_hist, symbol=code, period="daily", start_date=start)
        if df is not None and not df.empty:
            out[name] = df
    return out


# ---------- 科创50成分股权重 ----------
def get_kcb50_weights():
    return safe(ak.index_stock_cons_weight_csindex, symbol=KCB50_INDEX_CODE)


def get_semiconductor_codes(weights_df):
    if weights_df is None or weights_df.empty:
        return set()
    name_col = next((c for c in weights_df.columns if "名称" in c), None)
    code_col = next((c for c in weights_df.columns if "代码" in c), None)
    if not name_col or not code_col:
        return set()
    mask = weights_df[name_col].astype(str).apply(
        lambda x: any(k in x for k in SEMICONDUCTOR_KEYWORDS)
    )
    return set(weights_df[mask][code_col].astype(str).str.zfill(6))


# ---------- 全市场实时快照（成交额集中度用） ----------
def get_realtime_spot():
    return safe(ak.stock_zh_a_spot_em)


def compute_concentration(weights_df, spot_df):
    result = {"sector_turnover_share": None, "top10_turnover_hhi": None}
    if weights_df is None or weights_df.empty or spot_df is None or spot_df.empty:
        return result
    code_col = next((c for c in weights_df.columns if "代码" in c), None)
    if not code_col:
        return result
    all_codes  = set(weights_df[code_col].astype(str).str.zfill(6))
    semi_codes = get_semiconductor_codes(weights_df)
    sc = "代码" if "代码" in spot_df.columns else None
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
    result["top10_turnover_hhi"] = round(float((top10_shares ** 2).sum()), 4)
    return result


# ---------- QVIX (全部历史序列) ----------
def get_all_qvix():
    out = {}
    for fn_name, label in QVIX_FUNCS.items():
        fn = getattr(ak, fn_name, None)
        if fn is None:
            continue
        df = safe(fn)
        if df is not None and not df.empty:
            # 统一列名：date, close
            date_col  = next((c for c in df.columns if "date" in c.lower() or "日期" in c), df.columns[0])
            close_col = next((c for c in df.columns if "close" in c.lower() or "收盘" in c), df.columns[-1])
            df = df[[date_col, close_col]].copy()
            df.columns = ["date", "close"]
            df["date"] = df["date"].astype(str).str[:10]
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            out[label] = df.dropna().sort_values("date")
    return out


# ---------- 板块资金流向排名 ----------
def get_sector_flow_rank():
    """今日行业资金流排名，返回 DataFrame，含净流入金额列"""
    return safe(ak.stock_sector_fund_flow_rank, indicator="今日", sector_type="行业资金流")


def get_sector_flow_hist(sector_name: str):
    """某行业历史资金流"""
    return safe(ak.stock_sector_fund_flow_hist, symbol=sector_name)


def get_concept_flow_hist(concept_name: str):
    """某概念历史资金流（航天等走概念板块口径）"""
    return safe(ak.stock_concept_fund_flow_hist, symbol=concept_name)


# ---------- 两融余额 ----------
def get_margin_history(days=90):
    end   = datetime.date.today().strftime("%Y%m%d")
    start = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%Y%m%d")
    sse   = safe(ak.stock_margin_sse,  start_date=start, end_date=end)
    szse  = safe(ak.stock_margin_szse, start_date=start, end_date=end)
    return {"sse": sse, "szse": szse}


# ---------- 期权日统计（Put/Call Ratio） ----------
def get_pcr_series(days=60):
    """
    上交所每日期权统计，含认购/认沽成交量，可算 PCR。
    按日遍历，可能较慢。
    返回 list of {date, pcr_volume, pcr_oi}
    """
    results = []
    today = datetime.date.today()
    for i in range(days, 0, -1):
        d = today - datetime.timedelta(days=i)
        if d.weekday() >= 5:  # skip weekends
            continue
        date_str = d.strftime("%Y%m%d")
        df = safe(ak.option_daily_stats_sse, date=date_str)
        if df is None or df.empty:
            continue
        # 找认购/认沽相关列
        call_vol = put_vol = call_oi = put_oi = None
        for _, row in df.iterrows():
            name = str(row.iloc[0]) if len(row) > 0 else ""
            if "认购" in name:
                try:
                    call_vol = float(str(row.iloc[2]).replace(",", ""))
                    call_oi  = float(str(row.iloc[3]).replace(",", ""))
                except:
                    pass
            elif "认沽" in name:
                try:
                    put_vol = float(str(row.iloc[2]).replace(",", ""))
                    put_oi  = float(str(row.iloc[3]).replace(",", ""))
                except:
                    pass
        if call_vol and put_vol and call_vol > 0:
            results.append({
                "date": d.strftime("%Y-%m-%d"),
                "pcr_volume": round(put_vol / call_vol, 4),
                "pcr_oi":     round(put_oi / call_oi, 4) if call_oi and put_oi and call_oi > 0 else None,
            })
    return results
