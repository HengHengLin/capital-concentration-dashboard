# -*- coding: utf-8 -*-
"""海外市场数据源: yfinance + akshare宏观 + FRED + CME FedWatch"""
import os
import re
import logging
import datetime
import requests
import akshare as ak
import yfinance as yf

from config import GLOBAL_TICKERS, FRED_API_KEY_ENV

log = logging.getLogger("sources_global")
UA  = {"User-Agent": "Mozilla/5.0 (compatible; dashboard/1.0)"}


def safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        log.warning(f"{getattr(fn,'__name__',str(fn))} failed: {e}")
        return None


# ---------- 全球指数 ----------
def get_global_indices(period="3mo"):
    out = {}
    for name, ticker in GLOBAL_TICKERS.items():
        try:
            df = yf.Ticker(ticker).history(period=period)
            if df is not None and not df.empty:
                out[name] = df[["Close"]].copy()
        except Exception as e:
            log.warning(f"yfinance {name}({ticker}): {e}")
    return out


# ---------- Shiller CAPE ----------
def get_shiller_cape():
    try:
        url = "https://www.gurufocus.com/economic_indicators/56/sp-500-shiller-cape-ratio"
        r = requests.get(url, headers=UA, timeout=15)
        m = re.search(r"Shiller CAPE Ratio(?:\s+is currently|\s+was)?\s*([\d.]+)", r.text)
        return float(m.group(1)) if m else None
    except Exception as e:
        log.warning(f"CAPE scrape: {e}")
        return None


# ---------- 美联储利率（akshare，全历史） ----------
def get_us_rate_history():
    df = safe(ak.macro_bank_usa_interest_rate)
    if df is None or df.empty:
        return []
    # Series or DataFrame - normalise
    if hasattr(df, "reset_index"):
        df = df.reset_index()
    records = []
    for _, row in df.tail(24).iterrows():   # 最近24个月
        records.append({"date": str(row.iloc[0])[:10], "rate": row.iloc[1]})
    return records


# ---------- 日本利率（akshare，全历史） ----------
def get_japan_rate_history():
    df = safe(ak.macro_bank_japan_interest_rate)
    if df is None or df.empty:
        return []
    if hasattr(df, "reset_index"):
        df = df.reset_index()
    records = []
    for _, row in df.tail(24).iterrows():
        records.append({"date": str(row.iloc[0])[:10], "rate": row.iloc[1]})
    return records


# ---------- CME FedWatch 降息概率 ----------
def get_cme_fedwatch_probs():
    """
    CME没有免费JSON API，抓HTML不稳定。
    备用方案：用FRED的Federal Funds Futures隐含利率估算，
    或者直接返回None让看板显示"请手动查看 cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"
    """
    # 先试FRED
    api_key = os.environ.get(FRED_API_KEY_ENV, "")
    if api_key:
        try:
            # 30-day Fed Funds Futures最近一个月均值 vs 当前利率差推算隐含概率
            url = "https://api.stlouisfed.org/fred/series/observations"
            params = {"series_id": "DFEDTARU", "api_key": api_key,
                      "file_type": "json", "sort_order": "desc", "limit": 3}
            r = requests.get(url, params=params, timeout=15)
            obs = r.json().get("observations", [])
            if obs:
                return {"source": "FRED", "current_rate_upper": obs[0]["value"],
                        "note": "具体会议降息概率请查看 cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"}
        except Exception as e:
            log.warning(f"FRED FedWatch: {e}")
    return {"source": "manual",
            "note": "CME FedWatch: cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"}
