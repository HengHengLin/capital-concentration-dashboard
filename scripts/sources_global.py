# -*- coding: utf-8 -*-
"""海外市场数据源: yfinance + akshare宏观 + FRED"""
import os, re, logging, time, requests
import akshare as ak
import yfinance as yf
from config import GLOBAL_TICKERS, FRED_API_KEY_ENV

log = logging.getLogger("sources_global")
UA  = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}


def safe(fn, *args, retries=2, delay=5, **kwargs):
    for i in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            log.warning(f"{getattr(fn,'__name__',str(fn))} attempt {i+1}/{retries}: {e}")
            if i < retries - 1:
                time.sleep(delay)
    return None


def get_global_indices(period="3mo"):
    out = {}
    for name, ticker in GLOBAL_TICKERS.items():
        try:
            df = yf.Ticker(ticker).history(period=period)
            if df is not None and not df.empty:
                out[name] = df[["Close"]].copy()
        except Exception as e:
            log.warning(f"yfinance {name}({ticker}): {e}")
        time.sleep(1)
    return out


def get_shiller_cape():
    # 源1: gurufocus
    try:
        r = requests.get(
            "https://www.gurufocus.com/economic_indicators/56/sp-500-shiller-cape-ratio",
            headers=UA, timeout=20
        )
        m = re.search(r"(?:currently|was)\s+([\d.]+)", r.text)
        if m:
            val = float(m.group(1))
            if 5 < val < 100:
                return val
    except Exception as e:
        log.warning(f"CAPE gurufocus: {e}")

    # 源2: multpl.com
    try:
        r = requests.get("https://www.multpl.com/shiller-pe", headers=UA, timeout=20)
        m = re.search(r"([\d.]+)\s*<", r.text)
        if m:
            val = float(m.group(1))
            if 5 < val < 100:
                return val
    except Exception as e:
        log.warning(f"CAPE multpl: {e}")

    return None


def get_us_rate_history():
    df = safe(ak.macro_bank_usa_interest_rate, retries=2, delay=5)
    if df is None or df.empty:
        return []
    if hasattr(df, "reset_index"):
        df = df.reset_index()
    records = []
    for _, row in df.tail(24).iterrows():
        try:
            records.append({"date": str(row.iloc[0])[:10], "rate": float(row.iloc[1])})
        except:
            pass
    return records


def get_japan_rate_history():
    df = safe(ak.macro_bank_japan_interest_rate, retries=2, delay=5)
    if df is None or df.empty:
        return []
    if hasattr(df, "reset_index"):
        df = df.reset_index()
    records = []
    for _, row in df.tail(24).iterrows():
        try:
            records.append({"date": str(row.iloc[0])[:10], "rate": float(row.iloc[1])})
        except:
            pass
    return records


def get_cme_fedwatch_probs():
    api_key = os.environ.get(FRED_API_KEY_ENV, "")
    if api_key:
        try:
            r = requests.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={"series_id": "DFEDTARU", "api_key": api_key,
                        "file_type": "json", "sort_order": "desc", "limit": 3},
                timeout=15
            )
            obs = r.json().get("observations", [])
            if obs:
                return {"source": "FRED",
                        "current_rate_upper": obs[0]["value"],
                        "note": "CME FedWatch: cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"}
        except Exception as e:
            log.warning(f"FRED: {e}")
    return {"source": "manual",
            "note": "CME FedWatch: cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"}
