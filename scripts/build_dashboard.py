# -*- coding: utf-8 -*-
"""主流程 -> 静态HTML看板（含Chart.js图表 + 中文解读）"""
import os, json, logging, datetime
import sources_cn  as cn
import sources_global as gl
from concentration import (load_history, append_history, compute_score,
                            compute_margin_momentum)
from config import DOCS_DIR, FOCUS_SECTORS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("build")

LABEL_ZH = {
    "sector_turnover_share": "半导体成交额占比",
    "top10_turnover_hhi":    "前十权重股集中度(HHI)",
    "qvix_kcb_percentile":   "科创板期权波动率(QVIX)",
    "margin_momentum":       "融资余额5日动量",
}

def interpret_score(score, history_len):
    if history_len < 10:
        return "历史数据积累中（建议先运行回填脚本），当前分位数仅供参考"
    if score >= 85:
        return "极度集中 ⚠️ 资金高度抱团，历史上仅约15%的时间比现在更集中，需警惕回调风险"
    if score >= 70:
        return "明显过热 🔴 资金集中度处于历史较高水平，情绪偏亢奋，上行空间或有限"
    if score >= 55:
        return "偏高 🟡 资金集中度略高于历史中位，市场热度尚可但需关注边际变化"
    if score >= 40:
        return "中性 🟢 资金集中度接近历史平均水平，市场情绪平稳"
    if score >= 25:
        return "偏低 🔵 资金较为分散，市场热度偏低，可能处于底部蓄力阶段"
    return "极度分散 资金高度分散，市场情绪冷淡，历史上仅约25%的时间比现在更分散"


def interpret_sub(key, percentile, raw_value):
    if percentile is None or raw_value is None:
        return "数据获取中"
    p = percentile
    v = raw_value
    if key == "sector_turnover_share":
        pct = f"{round(v*100,1)}%"
        if p >= 80:
            return f"半导体成交额占科创50的 {pct}，处于历史 {p}% 分位 —— 资金极度集中在半导体，抱团特征明显"
        if p >= 60:
            return f"半导体成交额占科创50的 {pct}，处于历史 {p}% 分位 —— 资金偏向半导体，集中度偏高"
        if p >= 40:
            return f"半导体成交额占科创50的 {pct}，处于历史 {p}% 分位 —— 集中度适中"
        return f"半导体成交额占科创50的 {pct}，处于历史 {p}% 分位 —— 资金相对分散，未见明显抱团"
    if key == "top10_turnover_hhi":
        if p >= 80:
            return f"HHI={round(v,3)}，处于历史 {p}% 分位 —— 成交额高度集中在少数龙头股，散户跟风风险高"
        if p >= 60:
            return f"HHI={round(v,3)}，处于历史 {p}% 分位 —— 集中度偏高，主力资金有明显偏好方向"
        if p >= 40:
            return f"HHI={round(v,3)}，处于历史 {p}% 分位 —— 集中度正常"
        return f"HHI={round(v,3)}，处于历史 {p}% 分位 —— 成交额相对均匀，无明显龙头效应"
    if key == "qvix_kcb_percentile":
        if p >= 80:
            return f"科创板QVIX={round(v,1)}，处于历史 {p}% 分位 —— 期权市场恐慌情绪较重，波动预期高"
        if p >= 60:
            return f"科创板QVIX={round(v,1)}，处于历史 {p}% 分位 —— 市场情绪偏紧张，波动率高于历史均值"
        if p >= 40:
            return f"科创板QVIX={round(v,1)}，处于历史 {p}% 分位 —— 市场情绪平稳，波动率正常"
        return f"科创板QVIX={round(v,1)}，处于历史 {p}% 分位 —— 市场情绪平静，波动预期低"
    if key == "margin_momentum":
        direction = "流入" if v > 0 else "流出"
        speed = "快速" if abs(v) > 1 else ("温和" if abs(v) > 0.3 else "缓慢")
        if p >= 80:
            return f"融资余额5日变化{round(v,2)}%，处于历史 {p}% 分位 —— 杠杆资金{speed}{direction}，加杠杆情绪强烈，需警惕踩踏风险"
        if p >= 60:
            return f"融资余额5日变化{round(v,2)}%，处于历史 {p}% 分位 —— 杠杆资金{speed}{direction}，情绪偏积极"
        if p >= 40:
            return f"融资余额5日变化{round(v,2)}%，处于历史 {p}% 分位 —— 杠杆资金变化平稳"
        return f"融资余额5日变化{round(v,2)}%，处于历史 {p}% 分位 —— 杠杆资金{speed}{direction}，去杠杆或观望"
    return f"分位数 {p}%"


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
            df2 = cn.get_concept_flow_hist(s)
            if df2 is not None and not df2.empty:
                sector_hist[s] = df2
    log.info("两融余额...")
    margin     = cn.get_margin_history(days=90)
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

    kcb_qvix_val = None
    kcb_df = qvix.get("科创板QVIX")
    if kcb_df is not None and not kcb_df.empty:
        kcb_qvix_val = float(kcb_df["close"].iloc[-1])

    raw = {
        "sector_turnover_share": conc.get("sector_turnover_share"),
        "top10_turnover_hhi":    conc.get("top10_turnover_hhi"),
        "qvix_kcb_percentile":   kcb_qvix_val,
        "margin_momentum":       margin_mom,
    }
    return dict(cn_idx=cn_idx, weights=weights, raw=raw, qvix=qvix,
                sector_rank=sector_rank, sector_hist=sector_hist,
                margin=margin, pcr=pcr, global_idx=global_idx,
                cape=cape, us_rates=us_rates, jp_rates=jp_rates, fedwatch=fedwatch)


def history_chart(history, key, tail=120):
    rows = [h for h in history if h.get(key) is not None][-tail:]
    return {"labels": [h["timestamp"][:10] for h in rows],
            "data":   [round(h[key], 4) for h in rows]}

def score_chart(history, tail=120):
    rows = [h for h in history if h.get("score") is not None][-tail:]
    return {"labels": [h["timestamp"][:10] for h in rows],
            "data":   [h["score"] for h in rows]}

def history_date_range(history):
    dates = [h["timestamp"][:10] for h in history if h.get("timestamp")]
    if not dates:
        return "暂无历史数据"
    return f"{min(dates)} 至 {max(dates)}（共 {len(dates)} 个交易日）"


def render(score, detail, data, history, ts):
    import pandas as pd
    raw      = data["raw"]
    cape     = data["cape"]
    fedwatch = data["fedwatch"] or {}
    us_rates = data["us_rates"]
    jp_rates = data["jp_rates"]
    pcr_list = data["pcr"]

    def fmt(v, dec=2):
        return "N/A" if v is None else f"{round(v,dec)}"

    def last_close(df):
        if df is None or df.empty: return "N/A"
        cc = next((c for c in df.columns if "Close" in c or "收盘" in c), None)
        return round(float(df[cc].iloc[-1]), 2) if cc else "N/A"

    def last_chg(df):
        if df is None or df.empty: return ""
        cc = next((c for c in df.columns if "Close" in c or "收盘" in c), None)
        if cc and len(df) >= 2:
            chg = (float(df[cc].iloc[-1]) / float(df[cc].iloc[-2]) - 1) * 100
            color = "#2ecc71" if chg >= 0 else "#e74c3c"
            sign  = "+" if chg >= 0 else ""
            return f'<span style="color:{color}">{sign}{round(chg,2)}%</span>'
        return ""

    hist_range = history_date_range(history)
    hist_len   = len(history)
    score_text = interpret_score(score, hist_len)
    score_color = "#c0392b" if score >= 80 else ("#e67e22" if score >= 60 else ("#f1c40f" if score >= 40 else "#27ae60"))

    sub_rows = ""
    for key, weight in [("sector_turnover_share",0.35),("top10_turnover_hhi",0.30),
                         ("qvix_kcb_percentile",0.20),("margin_momentum",0.15)]:
        pct    = detail.get(key)
        rval   = raw.get(key)
        label  = LABEL_ZH.get(key, key)
        interp = interpret_sub(key, pct, rval)
        pct_str = f"{pct}%" if pct is not None else "N/A"
        sub_rows += f"""
        <tr>
          <td style="color:#aaa;width:180px">{label}<br><span style="color:#555;font-size:10px">权重{int(weight*100)}%</span></td>
          <td style="color:#74b9ff;font-size:13px;width:60px">{pct_str}</td>
          <td style="color:#ccc;font-size:12px">{interp}</td>
        </tr>"""

    cn_rows = "".join(
        f"<tr><td>{n}</td><td>{last_close(df)}</td><td>{last_chg(df)}</td></tr>"
        for n, df in data["cn_idx"].items()
    )
    global_rows = "".join(
        f"<tr><td>{n}</td><td>{last_close(df)}</td><td>{last_chg(df)}</td></tr>"
        for n, df in data["global_idx"].items()
    )

    sector_rows = ""
    sf = data["sector_rank"]
    if sf is not None and not sf.empty:
        flow_col = next((c for c in sf.columns if "净额" in c or "净流入" in c or "主力" in c), sf.columns[-1])
        name_col = next((c for c in sf.columns if "名称" in c or "板块" in c), sf.columns[0])
        try:
            top5 = sf.nlargest(5, flow_col)
            bot5 = sf.nsmallest(5, flow_col)
            for _, row in pd.concat([top5, bot5]).iterrows():
                val   = row.get(flow_col, 0)
                color = "#2ecc71" if float(val) >= 0 else "#e74c3c"
                sector_rows += f'<tr><td>{row.get(name_col,"")}</td><td style="color:{color};text-align:right">{val}</td></tr>'
        except:
            pass

    us_latest = us_rates[-1] if us_rates else {}
    jp_latest = jp_rates[-1] if jp_rates else {}

    sc_json     = json.dumps(score_chart(history))
    sector_json = json.dumps(history_chart(history, "sector_turnover_share"))
    hhi_json    = json.dumps(history_chart(history, "top10_turnover_hhi"))
    margin_json = json.dumps(history_chart(history, "margin_momentum"))
    pcr_json    = json.dumps({"labels":[r["date"] for r in pcr_list],
                               "data":  [r["pcr_volume"] for r in pcr_list]})
    us_rate_json= json.dumps({"labels":[r["date"] for r in us_rates[-24:]],
                               "data":  [r["rate"]  for r in us_rates[-24:]]})
    jp_rate_json= json.dumps({"labels":[r["date"] for r in jp_rates[-24:]],
                               "data":  [r["rate"]  for r in jp_rates[-24:]]})
    qvix_series = {}
    for label, df in data["qvix"].items():
        if not df.empty:
            qvix_series[label] = {"labels": df["date"].tail(120).tolist(),
                                   "data":   df["close"].tail(120).round(2).tolist()}
    qvix_json = json.dumps(qvix_series)

    fedwatch_note = fedwatch.get("note","")
    fred_rate     = fedwatch.get("current_rate_upper","")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>资金集中度看板</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,"PingFang SC",sans-serif;background:#0f1117;color:#e0e0e0;padding:16px}}
h1{{font-size:18px;margin-bottom:2px}}
.meta{{color:#555;font-size:12px;margin-bottom:16px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(440px,1fr));gap:16px}}
.card{{background:#1a1d27;border-radius:10px;padding:16px}}
.card h2{{font-size:12px;color:#666;margin-bottom:10px;text-transform:uppercase;letter-spacing:.5px}}
.score-num{{font-size:52px;font-weight:700;line-height:1;color:{score_color}}}
.score-interp{{font-size:13px;color:#ccc;margin:8px 0;line-height:1.5;padding:8px;background:#12151f;border-radius:6px;border-left:3px solid {score_color}}}
.hist-range{{font-size:11px;color:#555;margin-top:6px}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
td{{padding:6px 6px;border-bottom:1px solid #1e2130;vertical-align:top}}
.chart-wrap{{position:relative;height:180px}}
.rate-val{{font-size:26px;font-weight:600;color:#74b9ff}}
a{{color:#74b9ff;font-size:11px;text-decoration:none}}
a:hover{{text-decoration:underline}}
</style>
</head>
<body>
<h1>资金集中度看板</h1>
<div class="meta">更新: {ts} &nbsp;|&nbsp; 历史区间: {hist_range}</div>
<div class="grid">

<div class="card">
  <h2>资金集中度综合分</h2>
  <div class="score-num">{score}</div>
  <div class="score-interp">{score_text}</div>
  <div class="hist-range">说明：分数 = 今日集中度在历史所有交易日中的分位数，80分=历史上仅20%的时候比今天更集中</div>
  <table style="margin-top:12px">
    <tr style="color:#555;font-size:11px"><td>指标</td><td>分位</td><td>解读</td></tr>
    {sub_rows}
  </table>
</div>

<div class="card">
  <h2>综合分历史走势</h2>
  <div class="chart-wrap"><canvas id="scoreChart"></canvas></div>
  <div style="font-size:11px;color:#555;margin-top:4px">分数越高=历史上资金越集中的时刻</div>
</div>

<div class="card">
  <h2>A股指数</h2>
  <table>
    <tr style="color:#555;font-size:11px"><td>指数</td><td>收盘</td><td>涨跌</td></tr>
    {cn_rows if cn_rows else '<tr><td colspan="3" style="color:#555">交易日收盘后更新</td></tr>'}
  </table>
</div>

<div class="card">
  <h2>全球市场</h2>
  <table>
    <tr style="color:#555;font-size:11px"><td>标的</td><td>收盘</td><td>涨跌</td></tr>
    {global_rows if global_rows else '<tr><td colspan="3" style="color:#555">数据获取中</td></tr>'}
  </table>
</div>

<div class="card">
  <h2>科创50半导体成交额占比 历史</h2>
  <div class="chart-wrap"><canvas id="sectorChart"></canvas></div>
  <div style="font-size:11px;color:#555;margin-top:4px">占比越高=资金越集中在半导体，需关注拥挤度风险</div>
</div>

<div class="card">
  <h2>科创50前十权重股成交额集中度(HHI) 历史</h2>
  <div class="chart-wrap"><canvas id="hhiChart"></canvas></div>
  <div style="font-size:11px;color:#555;margin-top:4px">HHI越高=成交额越集中在少数龙头，市场越窄</div>
</div>

<div class="card">
  <h2>期权波动率 QVIX 历史</h2>
  <div class="chart-wrap"><canvas id="qvixChart"></canvas></div>
  <div style="font-size:11px;color:#555;margin-top:4px">QVIX越高=市场恐慌/不确定性越大；蓝线=科创板QVIX</div>
</div>

<div class="card">
  <h2>期权 Put/Call Ratio 历史（成交量口径）</h2>
  <div class="chart-wrap"><canvas id="pcrChart"></canvas></div>
  <div style="font-size:11px;color:#555;margin-top:4px">PCR&gt;1=买保护的人更多偏悲观 | PCR&lt;1=偏乐观</div>
</div>

<div class="card">
  <h2>融资余额5日动量% 历史</h2>
  <div class="chart-wrap"><canvas id="marginChart"></canvas></div>
  <div style="font-size:11px;color:#555;margin-top:4px">正值=杠杆资金净流入，绝对值越大=加/去杠杆速度越快</div>
</div>

<div class="card">
  <h2>今日行业资金流（前5流入 / 前5流出）</h2>
  <table>
    <tr style="color:#555;font-size:11px"><td>板块</td><td style="text-align:right">净流入(万元)</td></tr>
    {sector_rows if sector_rows else '<tr><td colspan="2" style="color:#555">交易日收盘后更新，周末无数据</td></tr>'}
  </table>
</div>

<div class="card">
  <h2>利率 & 货币政策</h2>
  <div style="display:flex;gap:24px;flex-wrap:wrap;margin-bottom:12px">
    <div>
      <div style="font-size:11px;color:#666">美联储利率（最新）</div>
      <div class="rate-val">{us_latest.get('rate','N/A')}%</div>
      <div style="font-size:11px;color:#555">{us_latest.get('date','')}</div>
    </div>
    <div>
      <div style="font-size:11px;color:#666">日本央行利率（最新）</div>
      <div class="rate-val">{jp_latest.get('rate','N/A')}%</div>
      <div style="font-size:11px;color:#555">{jp_latest.get('date','')}</div>
    </div>
  </div>
  <div style="font-size:11px;color:#aaa;margin-bottom:6px">{fedwatch_note}</div>
  {f'<div style="font-size:11px;color:#666;margin-bottom:4px">FRED联邦基金利率上限: {fred_rate}%</div>' if fred_rate else ''}
  <a href="https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html" target="_blank">→ 打开 CME FedWatch 查看降息概率</a>
</div>

<div class="card">
  <h2>美联储 / 日本央行 利率历史（近2年）</h2>
  <div class="chart-wrap"><canvas id="rateChart"></canvas></div>
</div>

<div class="card">
  <h2>美股 Shiller CAPE（周期调整市盈率）</h2>
  <div style="font-size:40px;font-weight:600;color:#fd79a8">{fmt(cape,1)}</div>
  <div style="font-size:12px;color:#888;margin-top:8px;line-height:1.6">
    历史均值≈16 &nbsp;|&nbsp; 历史高点44.2（2021）<br>
    当前若为40+，高于历史均值约150%，处于极度高估区间<br>
    高CAPE通常预示未来10-20年美股回报率偏低
  </div>
  <a href="https://www.gurufocus.com/shiller-PE.php" target="_blank">→ gurufocus Shiller P/E 实时数据</a>
</div>

</div>
<script>
const SCORE  = {sc_json};
const SECTOR = {sector_json};
const HHI    = {hhi_json};
const MARGIN = {margin_json};
const QVIX   = {qvix_json};
const PCR    = {pcr_json};
const US_R   = {us_rate_json};
const JP_R   = {jp_rate_json};
const COLORS = ['#74b9ff','#fd79a8','#55efc4','#fdcb6e','#a29bfe','#e17055'];

function line(id, labels, datasets) {{
  const ctx = document.getElementById(id);
  if (!ctx || !labels || labels.length === 0) return;
  new Chart(ctx, {{
    type:'line', data:{{labels, datasets}},
    options:{{
      responsive:true, maintainAspectRatio:false,
      plugins:{{legend:{{labels:{{color:'#aaa',font:{{size:11}}}}}}}},
      scales:{{
        x:{{ticks:{{color:'#555',font:{{size:10}},maxTicksLimit:6}},grid:{{color:'#1a1d2a'}}}},
        y:{{ticks:{{color:'#666',font:{{size:10}}}},grid:{{color:'#1a1d2a'}}}}
      }}
    }}
  }});
}}

function ds(label, data, color, fill=false) {{
  return {{label, data, borderColor:color,
           backgroundColor:fill?color+'22':'transparent',
           borderWidth:1.5, pointRadius:0, tension:0.3, fill}};
}}

line('scoreChart',  SCORE.labels,  [ds('综合分',SCORE.data,'#e17055',true)]);
line('sectorChart', SECTOR.labels, [ds('半导体成交额占比',SECTOR.data,'#74b9ff',true)]);
line('hhiChart',    HHI.labels,    [ds('前十权重股HHI',HHI.data,'#fd79a8',true)]);
line('marginChart', MARGIN.labels, [ds('融资5日动量%',MARGIN.data,'#55efc4',false)]);
line('pcrChart',    PCR.labels,    [ds('PCR(成交量)',PCR.data,'#fdcb6e',false)]);
const qvixLabels=Object.values(QVIX).reduce((a,b)=>b.labels.length>a.length?b.labels:a,[]);
line('qvixChart', qvixLabels, Object.entries(QVIX).map(([k,v],i)=>ds(k,v.data,COLORS[i])));
const rateLabels=US_R.labels.length>=JP_R.labels.length?US_R.labels:JP_R.labels;
line('rateChart', rateLabels, [ds('美联储',US_R.data,'#74b9ff'),ds('日本央行',JP_R.data,'#fd79a8')]);
</script>
</body>
</html>"""
    return html


def main():
    data    = collect()
    history = load_history()
    score, detail = compute_score(data["raw"], history)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    snap = dict(data["raw"])
    snap.update({"timestamp": ts, "score": score})
    append_history(snap)
    os.makedirs(DOCS_DIR, exist_ok=True)
    html = render(score, detail, data, history, ts)
    with open(os.path.join(DOCS_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    log.info(f"完成 score={score}  history={len(history)}条")

if __name__ == "__main__":
    main()
