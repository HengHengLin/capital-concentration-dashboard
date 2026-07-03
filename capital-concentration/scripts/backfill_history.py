# -*- coding: utf-8 -*-
"""
回填历史数据，让第一次跑起来就有20-30个交易日的真实分位数，不用干等一个月。
用法: python backfill_history.py [--days 30]

只需要跑一次（首次部署时）。之后 build_dashboard.py 每次运行会自动往 history.jsonl
追加当天数据，不需要重复回填。如果重跑，会覆盖 data/history.jsonl。
"""
import sys
import json
import logging
import argparse
import datetime

import pandas as pd
import sources_cn as cn
from config import HISTORY_FILE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backfill")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30, help="回填多少个自然日 (交易日会更少)")
    return p.parse_args()


def main():
    args = parse_args()
    end = datetime.date.today()
    start = end - datetime.timedelta(days=args.days + 10)  # 多留几天缓冲给动量计算
    start_str = start.strftime("%Y%m%d")
    end_str = end.strftime("%Y%m%d")

    log.info(f"回填区间: {start_str} ~ {end_str}")

    # 1. 科创50成分股权重 (用当前最新权重，简化处理，见 sources_cn.py 里的注释)
    log.info("拉取科创50成分股权重...")
    weights = cn.get_kcb50_weights()
    if weights is None or weights.empty:
        log.error("拿不到科创50权重表，无法回填成交额集中度，中止")
        sys.exit(1)

    # 2. 每只成分股的历史成交额 -> 逐日集中度
    log.info(f"拉取科创50成分股 ({len(weights)}只) 历史成交额，这一步比较慢，请耐心等...")
    turnover_wide = cn.get_stock_turnover_history(weights, start_str, end_str)
    concentration_by_date = cn.compute_turnover_concentration_series(turnover_wide, weights)
    log.info(f"成交额集中度回填了 {len(concentration_by_date)} 个交易日")

    # 3. QVIX 历史 (接口本身就返回全部历史，不需要传日期参数)
    log.info("拉取期权QVIX历史...")
    qvix_dict = cn.get_qvix()
    kcb_qvix = qvix_dict.get("index_option_kcb_qvix")
    qvix_by_date = {}
    if kcb_qvix is not None and not kcb_qvix.empty:
        date_col = next((c for c in kcb_qvix.columns if "date" in c.lower() or "日期" in c), kcb_qvix.columns[0])
        close_col = next((c for c in kcb_qvix.columns if "close" in c.lower() or "收盘" in c), kcb_qvix.columns[-1])
        for _, row in kcb_qvix.iterrows():
            d = str(row[date_col])[:10]
            qvix_by_date[d] = float(row[close_col])
    log.info(f"QVIX回填了 {len(qvix_by_date)} 个交易日")

    # 4. 融资融券余额历史 -> 逐日5日动量
    log.info("拉取融资融券余额历史...")
    margin_df = cn.safe_call(cn.ak.stock_margin_sse, start_date=start_str, end_date=end_str)
    margin_momentum_by_date = {}
    if margin_df is not None and not margin_df.empty:
        date_col = next((c for c in margin_df.columns if "日期" in c), margin_df.columns[0])
        balance_col = next((c for c in margin_df.columns if "余额" in c), None)
        if balance_col:
            margin_df = margin_df.sort_values(date_col).reset_index(drop=True)
            for i in range(5, len(margin_df)):
                d = str(margin_df.loc[i, date_col])[:10]
                v0 = float(margin_df.loc[i - 5, balance_col])
                v1 = float(margin_df.loc[i, balance_col])
                if v0:
                    margin_momentum_by_date[d] = round((v1 / v0 - 1) * 100, 2)
    log.info(f"两融动量回填了 {len(margin_momentum_by_date)} 个交易日")

    # 5. 北向资金历史 -> 逐日5日累计 (2024-05-13后口径变化，见 sources_cn.py 注释)
    log.info("拉取北向资金历史...")
    hsgt_df = cn.get_northbound_flow()
    northbound_by_date = {}
    if hsgt_df is not None and not hsgt_df.empty:
        date_col = next((c for c in hsgt_df.columns if "日期" in c), hsgt_df.columns[0])
        flow_col = next((c for c in hsgt_df.columns if "净买额" in c or "净流入" in c), None)
        if flow_col:
            hsgt_df = hsgt_df.sort_values(date_col).reset_index(drop=True)
            hsgt_df = hsgt_df[hsgt_df[date_col].astype(str) >= start.strftime("%Y-%m-%d")]
            for i in range(4, len(hsgt_df)):
                window = hsgt_df.iloc[i - 4:i + 1]
                d = str(hsgt_df.iloc[i][date_col])[:10]
                northbound_by_date[d] = round(float(window[flow_col].astype(float).sum()), 2)
    log.info(f"北向资金回填了 {len(northbound_by_date)} 个交易日")

    # 6. 合并所有日期，写入 history.jsonl
    all_dates = sorted(set(concentration_by_date) | set(qvix_by_date) |
                        set(margin_momentum_by_date) | set(northbound_by_date))
    all_dates = [d for d in all_dates if d >= start_str[:4] + "-" + start_str[4:6] + "-" + start_str[6:]]

    written = 0
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        for d in all_dates:
            conc = concentration_by_date.get(d, {})
            snapshot = {
                "timestamp": d,
                "sector_turnover_share": conc.get("sector_turnover_share"),
                "top10_turnover_hhi": conc.get("top10_turnover_hhi"),
                "qvix_level": qvix_by_date.get(d),
                "margin_momentum": margin_momentum_by_date.get(d),
                "northbound_5d": northbound_by_date.get(d),
                "backfilled": True,
            }
            # 至少要有一个非空字段才写，纯空行没意义
            if any(v is not None for k, v in snapshot.items() if k not in ("timestamp", "backfilled")):
                f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
                written += 1

    log.info(f"回填完成，写入 {written} 条历史快照到 {HISTORY_FILE}")
    log.info("现在可以直接跑 build_dashboard.py，分位数就是有意义的了，不用再等20-30天。")


if __name__ == "__main__":
    main()
