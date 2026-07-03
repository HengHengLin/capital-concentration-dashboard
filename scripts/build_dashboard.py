# -*- coding: utf-8 -*-
"""
主流程 -> 纯静态HTML看板（含Chart.js图表）
"""
import os, json, logging, datetime
import sources_cn  as cn
import sources_global as gl
from concentration import (load_history, append_history, compute_score,
                            compute_margin_momentum)
from config import DOCS_DIR, FOCUS_SECTORS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("build")


# ────────────────────────────── data collection ──────────────────────────────

def collect():
    log.info("A股指数...")
    cn_idx = cn.get_cn_indices(days=90)

    log.info("科创50成分股权重...")
    weights = cn.get_kcb50_weights()

    log.info("全市场实时快照...")
    spot = cn.get_realtime_spot()

    log.info("成交额集中度...")
    conc = cn.compute_concentration(weights, spot)

    log.info("QVIX全部历史...")
    qvix = cn.get_all_qvix()

    log.info("板块资金流排名...")
    sector_rank = cn.get_sector_flow_rank()

    log.info("重点板块历史资金流...")
    sector_hist = {}
    for s in FOCUS_SECTORS:
        df = cn.get_sector_flow_hist(s)
        if df is not None and not df.empty:
            sector_hist[s] = df
        else:
            # 有些板块在概念口径里
            df2 = cn.get_concept_flow_hist(s)
            if df2 is not None and not df2.empty:
                sector_hist[s] = df2

    log.info("两融余额...")
    margin = cn.get_margin_history(days=90)
    margin_mom = compute_margin_momentum(margin.get("sse"))

    log.info("期权PCR...")
    pcr = cn.get_pcr_series(days=60)

    log.info("全球市场...")
    global_idx = gl.get_global_indices(period="3mo")

    log.info("Shiller CAPE...")
    cape = gl.get_shiller_cape()

    log.info("美国利率历史...")
    us_rates = gl.get_us_rate_history()

    log.info("日本利率历史...")
    jp_rates = gl.get_japan_rate_history()

    log.info("CME FedWatch...")
    fedwatch = gl.get_cme_fedwatch_probs()

    # 科创板QVIX最新值（用于综合分）
    kcb_qvix_val = None
    kcb_df = qvix.get("科创板QVIX")
    if kcb_df is not None and not kcb_df.empty:
        kcb_qvix_val = float(kcb_df["close"].iloc[-1])

    raw = {
        "sector_turnover_share": conc.get("sector_turnover_share"),
        "top10_turnover_hhi":    conc.get("top10_turnover_hhi"),
        "qvix_kcb_percentile":   kcb_qvix_val,   # will be percentile-ranked against history
        "margin_momentum":       margin_mom,
    }

    return dict(
        cn_idx=cn_idx, weights=weights, raw=raw, qvix=qvix,
        sector_rank=sector_rank, sector_hist=sector_hist,
        margin=margin, pcr=pcr,
        global_idx=global_idx, cape=cape,
        us_rates=us_rates, jp_rates=jp_rates, fedwatch=fedwatch,
    )


# ────────────────────────────── chart helpers ────────────────────────────────

def df_to_chart_json(df, date_col, val_col, tail=60):
    """DataFrame -> {labels:[...], data:[...]} for Chart.js"""
    if df is None or df.empty:
        return {"labels": [], "data": []}
    df = df.copy().tail(tail)
    labels = df[date_col].astype(str).str[:10].tolist()
    data   = df[val_col].astype(float).round(4).tolist()
    return {"labels": labels, "data": data}


def history_to_chart(history, key, tail=60):
    rows = [h for h in history if h.get(key) is not None][-tail:]
    return {
        "labels": [h["timestamp"][:10] for h in rows],
        "data":   [round(h[key], 4) for h in rows],
    }


def score_history_chart(history, tail=60):
    rows = [h for h in history if h.get("score") is not None][-tail:]
    return {
        "labels": [h["timestamp"][:10] for h in rows],
        "data":   [h["score"] for h in rows],
    }


# ────────────────────────────── HTML renderer ────────────────────────────────

def render(score, detail, data, history, ts):
    cape    = data["cape"]
    fedwatch= data["fedwatch"]
    us_rates= data["us_rates"]
    jp_rates= data["jp_rates"]
    pcr_list= data["pcr"]

    def fmt(v, dec=2):
        return "N/A" if v is None else f"{round(v,dec)}"

    def last_close(df_or_dict):
        """works for both pd.DataFrame and dict with 'Close' """
        import pandas as pd
        if df_or_dict is None:
            return "N/A"
        if isinstance(df_or_dict, pd.DataFrame):
            df = df_or_dict
            cc = next((c for c in df.columns if "Close" in c or "收盘" in c), None)
            if cc and not df.empty:
                return round(float(df[cc].iloc[-1]), 2)
        return "N/A"

    def last_chg(df_or_dict):
        import pandas as pd
        if df_or_dict is None:
            return ""
        if isinstance(df_or_dict, pd.DataFrame):
            df = df_or_dict
            cc = next((c for c in df.columns if "Close" in c or "收盘" in c), None)
            if cc and len(df) >= 2:
                chg = (float(df[cc].iloc[-1]) / float(df[cc].iloc[-2]) - 1) * 100
                sign = "+" if chg >= 0 else ""
                color = "#2ecc71" if chg >= 0 else "#e74c3c"
                return f'<span style="color:{color}">{sign}{round(chg,2)}%</span>'
        return ""

    # ── 所有图表数据序列化为JSON ──
    score_chart  = json.dumps(score_history_chart(history))
    sector_share = json.dumps(history_to_chart(history, "sector_turnover_share"))
    hhi_chart    = json.dumps(history_to_chart(history, "top10_turnover_hhi"))
    margin_chart = json.dumps(history_to_chart(history, "margin_momentum"))

    # QVIX multi-line
    qvix_series = {}
    for label, df in data["qvix"].items():
        if not df.empty:
            qvix_series[label] = {"labels": df["date"].tail(90).tolist(),
                                   "data":  df["close"].tail(90).round(2).tolist()}
    qvix_json = json.dumps(qvix_series)

    # PCR
    pcr_json = json.dumps({
        "labels":    [r["date"] for r in pcr_list],
        "pcr_vol":   [r["pcr_volume"] for r in pcr_list],
    })

    # 全球指数
    global_rows = ""
    for name, df in data["global_idx"].items():
        lc = last_close(df)
        chg = last_chg(df)
        global_rows += f"<tr><td>{name}</td><td>{lc}</td><td>{chg}</td></tr>"

    # A股指数
    cn_rows = ""
    for name, df in data["cn_idx"].items():
        lc = last_close(df)
        chg = last_chg(df)
        cn_rows += f"<tr><td>{name}</td><td>{lc}</td><td>{chg}</td></tr>"

    # 板块资金流排名
    import pandas as pd
    sector_rank_rows = ""
    sf = data["sector_rank"]
    if sf is not None and not sf.empty:
        # 找净流入列
        flow_col = next((c for c in sf.columns if "净额" in c or "净流入" in c or "主力" in c), sf.columns[-1])
        name_col = next((c for c in sf.columns if "名称" in c or "板块" in c), sf.columns[0])
        top5 = sf.nlargest(5, flow_col) if flow_col in sf.columns else sf.head(5)
        bot5 = sf.nsmallest(5, flow_col) if flow_col in sf.columns else sf.tail(5)
        for _, row in pd.concat([top5, bot5]).iterrows():
            val = row.get(flow_col, 0)
            color = "#2ecc71" if float(val) >= 0 else "#e74c3c"
            sector_rank_rows += f'<tr><td>{row.get(name_col,"")}</td><td style="color:{color}">{val}</td></tr>'

    # 利率历史
    us_rate_latest = us_rates[-1] if us_rates else {}
    jp_rate_latest = jp_rates[-1] if jp_rates else {}
    us_rate_json   = json.dumps({"labels":[r["date"] for r in us_rates[-24:]],
                                  "data":  [r["rate"]  for r in us_rates[-24:]]})
    jp_rate_json   = json.dumps({"labels":[r["date"] for r in jp_rates[-24:]],
                                  "data":  [r["rate"]  for r in jp_rates[-24:]]})

    # 综合分颜色
    sc = "#c0392b" if score >= 80 else ("#e67e22" if score >= 60 else "#27ae60")

    detail_rows = "".join(
        f"<tr><td>{k}</td><td>{v}</td></tr>" for k,v in detail.items()
    )
    raw = data["raw"]

    fedwatch_note = fedwatch.get("note","") if fedwatch else ""
    fred_rate = fedwatch.get("current_rate_upper","") if fedwatch else ""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>资金集中度看板</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,"PingFang SC",sans-serif;background:#0f1117;color:#e0e0e0;padding:16px}}
h1{{font-size:18px;margin-bottom:4px}}
.meta{{color:#666;font-size:12px;margin-bottom:16px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:16px}}
.card{{background:#1a1d27;border-radius:10px;padding:16px}}
.card h2{{font-size:13px;color:#888;margin-bottom:12px;text-transform:uppercase;letter-spacing:.5px}}
.score{{font-size:52px;font-weight:700;color:{sc};line-height:1}}
.score-sub{{font-size:12px;color:#666;margin-top:4px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
td{{padding:5px 6px;border-bottom:1px solid #22253a}}
td:last-child{{text-align:right}}
.chart-wrap{{position:relative;height:180px}}
.tag{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;margin-top:8px}}
.rate-box{{display:flex;gap:16px;flex-wrap:wrap}}
.rate-item{{flex:1;min-width:160px}}
.rate-val{{font-size:24px;font-weight:600;color:#74b9ff}}
a{{color:#74b9ff;font-size:11px}}
</style>
</head>
<body>
<h1>资金集中度看板</h1>
<div class="meta">更新: {ts} &nbsp;|&nbsp; 数据源: akshare / yfinance / gurufocus</div>

<div class="grid">

<!-- 综合分 -->
<div class="card">
  <h2>资金集中度综合分</h2>
  <div class="score">{score}</div>
  <div class="score-sub">历史分位数加权（0=最低 / 100=最高集中度）</div>
  <table style="margin-top:12px">{detail_rows}</table>
  <table style="margin-top:8px">
    <tr><td>半导体成交额占比</td><td>{fmt(raw['sector_turnover_share'])}</td></tr>
    <tr><td>前十权重股HHI</td><td>{fmt(raw['top10_turnover_hhi'])}</td></tr>
    <tr><td>科创板QVIX</td><td>{fmt(raw['qvix_kcb_percentile'])}</td></tr>
    <tr><td>两融余额5日动量%</td><td>{fmt(raw['margin_momentum'])}</td></tr>
  </table>
</div>

<!-- 综合分历史走势 -->
<div class="card">
  <h2>综合分历史走势</h2>
  <div class="chart-wrap"><canvas id="scoreChart"></canvas></div>
</div>

<!-- A股指数 -->
<div class="card">
  <h2>A股指数</h2>
  <table>{cn_rows}</table>
</div>

<!-- 全球市场 -->
<div class="card">
  <h2>全球市场</h2>
  <table>{global_rows}</table>
</div>

<!-- 半导体成交额占比 -->
<div class="card">
  <h2>科创50半导体成交额占比 历史</h2>
  <div class="chart-wrap"><canvas id="sectorChart"></canvas></div>
</div>

<!-- 前十权重股HHI -->
<div class="card">
  <h2>科创50前十权重股成交额HHI 历史</h2>
  <div class="chart-wrap"><canvas id="hhiChart"></canvas></div>
</div>

<!-- QVIX多指数 -->
<div class="card">
  <h2>期权波动率 QVIX（科创/创业/50ETF/300ETF）</h2>
  <div class="chart-wrap"><canvas id="qvixChart"></canvas></div>
</div>

<!-- 期权PCR -->
<div class="card">
  <h2>期权 Put/Call Ratio（成交量口径）</h2>
  <div class="chart-wrap"><canvas id="pcrChart"></canvas></div>
  <div style="font-size:11px;color:#666;margin-top:6px">PCR&gt;1 偏悲观 / PCR&lt;1 偏乐观</div>
</div>

<!-- 两融余额动量 -->
<div class="card">
  <h2>两融余额5日动量% 历史</h2>
  <div class="chart-wrap"><canvas id="marginChart"></canvas></div>
</div>

<!-- 板块资金流 -->
<div class="card">
  <h2>今日行业资金流（前5流入 / 前5流出）</h2>
  <table>
    <tr><th style="text-align:left">板块</th><th style="text-align:right">净流入(万元)</th></tr>
    {sector_rank_rows if sector_rank_rows else '<tr><td colspan="2" style="color:#666">数据获取中...</td></tr>'}
  </table>
</div>

<!-- 利率 -->
<div class="card">
  <h2>利率</h2>
  <div class="rate-box">
    <div class="rate-item">
      <div style="font-size:12px;color:#888">美联储利率</div>
      <div class="rate-val">{us_rate_latest.get('rate','N/A')}%</div>
      <div style="font-size:11px;color:#666">{us_rate_latest.get('date','')}</div>
    </div>
    <div class="rate-item">
      <div style="font-size:12px;color:#888">日本央行利率</div>
      <div class="rate-val">{jp_rate_latest.get('rate','N/A')}%</div>
      <div style="font-size:11px;color:#666">{jp_rate_latest.get('date','')}</div>
    </div>
  </div>
  <div style="margin-top:12px">
    <div style="font-size:12px;color:#888;margin-bottom:4px">CME FedWatch 降息概率</div>
    <div style="font-size:11px;color:#aaa">{fedwatch_note}</div>
    {f'<div style="font-size:11px;color:#666;margin-top:2px">FRED上限利率: {fred_rate}%</div>' if fred_rate else ''}
    <a href="https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html" target="_blank">→ 查看 CME FedWatch</a>
  </div>
</div>

<!-- 美国利率历史 -->
<div class="card">
  <h2>美联储 / 日本央行 利率历史</h2>
  <div class="chart-wrap"><canvas id="rateChart"></canvas></div>
</div>

<!-- Shiller CAPE -->
<div class="card">
  <h2>美股 Shiller CAPE</h2>
  <div style="font-size:36px;font-weight:600;color:#fd79a8">{fmt(cape,1)}</div>
  <div style="font-size:11px;color:#666;margin-top:4px">历史均值≈16，历史高点44.2（2021）<br>当前高于长期均值约150%</div>
  <a href="https://www.gurufocus.com/shiller-PE.php" target="_blank">→ gurufocus Shiller P/E</a>
</div>

</div><!-- /grid -->

<script>
const SCORE   = {score_chart};
const SECTOR  = {sector_share};
const HHI     = {hhi_chart};
const MARGIN  = {margin_chart};
const QVIX    = {qvix_json};
const PCR     = {pcr_json};
const US_RATE = {us_rate_json};
const JP_RATE = {jp_rate_json};

const COLORS = ['#74b9ff','#fd79a8','#55efc4','#fdcb6e','#a29bfe','#e17055'];

function lineChart(id, labels, datasets) {{
  const ctx = document.getElementById(id);
  if (!ctx) return;
  new Chart(ctx, {{
    type: 'line',
    data: {{ labels, datasets }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{ legend: {{ labels: {{ color:'#aaa', font:{{ size:11 }} }} }} }},
      scales: {{
        x: {{ ticks:{{ color:'#666', font:{{size:10}}, maxTicksLimit:6 }}, grid:{{ color:'#1e2130' }} }},
        y: {{ ticks:{{ color:'#888', font:{{size:10}} }}, grid:{{ color:'#1e2130' }} }}
      }}
    }}
  }});
}}

function ds(label, data, color, fill=false) {{
  return {{ label, data, borderColor:color, backgroundColor: fill ? color+'22' : 'transparent',
            borderWidth:1.5, pointRadius:0, tension:0.3, fill }};
}}

// 综合分走势
lineChart('scoreChart', SCORE.labels,
  [ds('综合分', SCORE.data, '#e17055', true)]);

// 半导体占比
lineChart('sectorChart', SECTOR.labels,
  [ds('半导体成交额占比', SECTOR.data, '#74b9ff', true)]);

// HHI
lineChart('hhiChart', HHI.labels,
  [ds('前十权重股HHI', HHI.data, '#fd79a8', true)]);

// QVIX 多线
const qvixLabels = Object.values(QVIX).reduce((a,b) => b.labels.length > a.length ? b.labels : a, []);
const qvixDS = Object.entries(QVIX).map(([k,v],i) => ds(k, v.data, COLORS[i]));
lineChart('qvixChart', qvixLabels, qvixDS);

// PCR
lineChart('pcrChart', PCR.labels,
  [ds('PCR(成交量)', PCR.pcr_vol, '#fdcb6e', false)]);

// 两融动量
lineChart('marginChart', MARGIN.labels,
  [ds('两融5日动量%', MARGIN.data, '#55efc4', false)]);

// 利率双线
const rateLabels = US_RATE.labels.length >= JP_RATE.labels.length ? US_RATE.labels : JP_RATE.labels;
lineChart('rateChart', rateLabels, [
  ds('美联储', US_RATE.data, '#74b9ff'),
  ds('日本央行', JP_RATE.data, '#fd79a8'),
]);
</script>
</body>
</html>"""
    return html


# ────────────────────────────── main ─────────────────────────────────────────

def main():
    data     = collect()
    history  = load_history()
    score, detail = compute_score(data["raw"], history)

    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    snap = dict(data["raw"])
    snap.update({"timestamp": ts, "score": score})
    append_history(snap)

    os.makedirs(DOCS_DIR, exist_ok=True)
    html = render(score, detail, data, history, ts)
    with open(os.path.join(DOCS_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)

    log.info(f"完成 score={score}")


if __name__ == "__main__":
    main()
