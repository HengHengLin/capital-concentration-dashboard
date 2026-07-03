# -*- coding: utf-8 -*-
"""配置文件 - 所有标的、权重、板块名称集中在这里改"""

# ---------- A股指数 ----------
CN_INDICES = {
    "科创50":     "000688",
    "上证指数":   "000001",
    "深证成指":   "399001",
    "创业板指":   "399006",
    "沪深300":    "000300",
    "中证1000":   "000852",
    "中证2000":   "932000",
    "中证芯片":   "H30184",
}

# ---------- 科创50成分股权重 ----------
KCB50_INDEX_CODE = "000688"

# ---------- QVIX 期权波动率 (akshare函数名 -> 展示名) ----------
QVIX_FUNCS = {
    "index_option_kcb_qvix":      "科创板QVIX",
    "index_option_cyb_qvix":      "创业板QVIX",
    "index_option_50etf_qvix":    "50ETF QVIX",
    "index_option_300etf_qvix":   "300ETF QVIX",
    "index_option_500etf_qvix":   "500ETF QVIX",
    "index_option_1000index_qvix":"中证1000 QVIX",
}

# ---------- 重点监控板块（行业资金流） ----------
FOCUS_SECTORS = [
    "半导体", "航天", "国防军工", "银行", "券商", "新能源", "人工智能",
]

# ---------- 全球市场 (yfinance) ----------
GLOBAL_TICKERS = {
    "标普500":        "^GSPC",
    "纳斯达克":       "^IXIC",
    "SOX半导体":      "^SOX",
    "KOSPI韩国":      "^KS11",
    "三星电子":       "005930.KS",
    "SK海力士":       "000660.KS",
    "特斯拉":         "TSLA",
    "英伟达":         "NVDA",
}

# ---------- 利率 ----------
# akshare: macro_bank_japan_interest_rate / macro_bank_usa_interest_rate
# FRED备用: DFEDTARU (美联储上限)
FRED_API_KEY_ENV = "FRED_API_KEY"   # 环境变量名

# ---------- CME FedWatch降息概率 ----------
# 从CME公开页面抓取，不需要key
CME_FEDWATCH_URL = "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"

# ---------- 半导体关键词筛选 ----------
SEMICONDUCTOR_KEYWORDS = ["半导体", "芯片", "集成电路", "存储", "封测", "设备"]

# ---------- 资金集中度子指标权重 ----------
CONCENTRATION_WEIGHTS = {
    "sector_turnover_share":  0.35,
    "top10_turnover_hhi":     0.30,
    "qvix_kcb_percentile":    0.20,
    "margin_momentum":        0.15,
}

# ---------- 路径 ----------
DATA_DIR  = "data"
DOCS_DIR  = "docs"
HISTORY_FILE = "data/history.jsonl"
