# -*- coding: utf-8 -*-
"""资金集中度综合分 + 历史分位数"""
import json, os
from config import CONCENTRATION_WEIGHTS, HISTORY_FILE


def percentile_rank(value, history):
    if value is None or not history:
        return 50.0
    clean = [v for v in history if v is not None]
    if not clean:
        return 50.0
    return round(100 * sum(1 for v in clean if v <= value) / len(clean), 1)


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    rows = []
    with open(HISTORY_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except:
                    pass
    return rows


def append_history(snap: dict):
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(snap, ensure_ascii=False, default=str) + "\n")


def compute_margin_momentum(margin_df):
    if margin_df is None or margin_df.empty:
        return None
    bal = next((c for c in margin_df.columns if "余额" in c), None)
    if not bal:
        return None
    s = margin_df.sort_values(margin_df.columns[0])[bal].astype(float)
    if len(s) < 6:
        return None
    return round((s.iloc[-1] / s.iloc[-6] - 1) * 100, 2)


def compute_score(raw: dict, history: list):
    """raw keys: sector_turnover_share, top10_turnover_hhi, qvix_kcb_percentile, margin_momentum"""
    detail = {}
    for key, w in CONCENTRATION_WEIGHTS.items():
        hist_vals = [h.get(key) for h in history]
        detail[key] = percentile_rank(raw.get(key), hist_vals)
    score = sum(detail[k] * w for k, w in CONCENTRATION_WEIGHTS.items())
    return round(score, 1), detail
