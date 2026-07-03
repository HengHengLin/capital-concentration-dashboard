# -*- coding: utf-8 -*-
"""
iFinD Excel数据导入脚本
把从iFinD导出的指数数据合并进 history.jsonl
用法: python import_ifind.py --file data/指数0703.xlsx
"""
import argparse
import json
import os
import pandas as pd
import logging

from config import HISTORY_FILE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("import_ifind")


def parse_ifind_excel(filepath):
    df = pd.read_excel(filepath, header=None)
    log.info(f"读取文件: {filepath}, 共 {len(df)} 行 {len(df.columns)} 列")

    indicator_cols = {}
    for col in range(len(df.columns)):
        val = df.iloc[1, col]
        if isinstance(val, str) and val in ['开盘价','最高价','最低价','收盘价','成交金额','振幅']:
            indicator_cols[val] = col

    log.info(f"找到指标列: {indicator_cols}")
    dates = pd.to_datetime(df.iloc[4:, 0], errors='coerce')
    result = {}

    for indicator in ['收盘价', '成交金额']:
        prefix = 'close' if indicator == '收盘价' else 'amt'
        if indicator not in indicator_cols:
            continue
        start = indicator_cols[indicator]
        names = df.iloc[3, start:start+8].tolist()
        for i, name in enumerate(names):
            if not isinstance(name, str) or name == '时间':
                continue
            col_idx = start + i
            for row_idx, date in enumerate(dates):
                if pd.isna(date):
                    continue
                d = date.strftime('%Y-%m-%d')
                val = df.iloc[row_idx + 4, col_idx]
                if pd.notna(val):
                    if d not in result:
                        result[d] = {}
                    result[d][f'{prefix}_{name}'] = round(float(val), 4)

    log.info(f"解析完成，共 {len(result)} 个交易日")
    return result


def merge_into_history(new_data: dict):
    existing = {}
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    ts = row.get('timestamp', '')[:10]
                    existing[ts] = row
                except:
                    pass
    log.info(f"现有历史: {len(existing)} 条")

    merged = added = 0
    for date, data in new_data.items():
        if date in existing:
            existing[date].update(data)
            merged += 1
        else:
            row = {'timestamp': date + 'T16:00:00', 'backfilled': True}
            row.update(data)
            existing[date] = row
            added += 1

    os.makedirs(os.path.dirname(HISTORY_FILE) if os.path.dirname(HISTORY_FILE) else '.', exist_ok=True)
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        for date in sorted(existing.keys()):
            f.write(json.dumps(existing[date], ensure_ascii=False, default=str) + '\n')

    log.info(f"合并完成：更新 {merged} 条，新增 {added} 条，总计 {len(existing)} 条")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', required=True, help='iFinD导出的Excel文件路径')
    args = parser.parse_args()
    data = parse_ifind_excel(args.file)
    merge_into_history(data)
    log.info("导入完成！")


if __name__ == '__main__':
    main()
