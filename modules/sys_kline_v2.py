import calendar
import json
import os
from datetime import datetime

from log_store import add_log
from symbol_tree import get_symbol_tree, parse_symbol_info, DB_PATH

PERIOD_ORDER = ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "D", "W"]
PERIOD_LABELS = {"1m": "1分", "5m": "5分", "15m": "15分", "30m": "30分",
                 "1h": "1时", "2h": "2时", "4h": "4时", "D": "日线", "W": "周线"}

PERIOD_LIMIT = {"1m": 5000, "5m": 3000, "15m": 3000, "30m": 3000,
                "1h": 2500, "2h": 2000, "4h": 2000, "D": 1500, "W": 1000}

DEFAULT_SYMBOL = "CZCE.FG2609 玻璃2609"


def _db_available():
    return os.path.exists(DB_PATH)


def _load_symbol_options():
    tree = get_symbol_tree()
    opts = []
    for asset_key, a_val in tree.items():
        for ex_key, e_val in a_val.get("exchanges", {}).items():
            for prod_key, p_val in e_val.get("products", {}).items():
                for c_item in p_val.get("contracts", []):
                    opts.append(c_item["val"])
    return opts or [DEFAULT_SYMBOL]


def _load_period_options():
    if not _db_available():
        return ["D", "1h", "1m"]
    try:
        import duckdb
        con = duckdb.connect(DB_PATH, read_only=True)
        rows = [r[0] for r in con.execute("SELECT DISTINCT period FROM bars").fetchall()]
        con.close()
        ordered = [p for p in PERIOD_ORDER if p in rows]
        return ordered or ["D"]
    except Exception:
        return ["D", "1h", "1m"]


_SYMBOL_OPTIONS = _load_symbol_options()
_PERIOD_OPTIONS = _load_period_options()

META = {
    "name": "K线行情V2",
    "icon": "📊",
    "description": "本地DuckDB数据源K线（quant_data_hub），4级联动选单（大类→交易所→品类→合约/时间），无模拟数据",
    "tags": ["行情交易"],
    "default_size": [32, 24],
    "min_size": [16, 12],
    "max_size": [64, 48],
    "refresh_interval": 0,
    "config_fields": [
        {"key": "symbol", "label": "合约", "type": "symbol-cascading-select", "default": DEFAULT_SYMBOL},
        {"key": "period", "label": "默认周期", "type": "select", "options": _PERIOD_OPTIONS, "default": "D"},
    ],
}

LW_SRC = '/static/js/lightweight-charts.standalone.production.js'


def _fetch_candles(exchange, symbol, period, limit):
    if not _db_available():
        return None, None, f"数据库不存在: {DB_PATH}"
    try:
        import duckdb
        con = duckdb.connect(DB_PATH, read_only=True)
    except Exception as e:
        msg = str(e)
        if "lock" in msg.lower() or "conflicting" in msg.lower():
            return None, None, "数据库正在更新写入中，稍候点 ⟳ 刷新"
        return None, None, f"连接失败: {msg}"

    try:
        is_day = period in ("D", "W")
        rows = con.execute(
            """SELECT b.ts, b.trading_day, b.open, b.high, b.low, b.close,
                      b.volume, b.open_interest
               FROM bars b JOIN symbols s USING(symbol_id)
               WHERE s.exchange=? AND s.symbol=? AND b.period=?
               ORDER BY b.ts DESC LIMIT ?""",
            [exchange, symbol, period, limit],
        ).fetchall()
        total = con.execute(
            """SELECT count(*) FROM bars b JOIN symbols s USING(symbol_id)
               WHERE s.exchange=? AND s.symbol=? AND b.period=?""",
            [exchange, symbol, period],
        ).fetchone()[0]
        meta = con.execute(
            "SELECT name, is_active, multiplier, tick_size FROM symbols "
            "WHERE exchange=? AND symbol=?", [exchange, symbol],
        ).fetchone()
        avail = [r[0] for r in con.execute(
            """SELECT DISTINCT b.period FROM bars b JOIN symbols s USING(symbol_id)
               WHERE s.exchange=? AND s.symbol=?""", [exchange, symbol],
        ).fetchall()]
        con.close()

        candles = []
        for ts, td, o, h, l, c, v, oi in reversed(rows):
            if is_day:
                t = str(td) if td else str(ts.date())
            else:
                t = calendar.timegm(ts.timetuple()) - 8 * 3600
            candles.append({"time": t, "open": o, "high": h, "low": l,
                            "close": c, "volume": float(v or 0),
                            "oi": int(oi or 0)})
        info = {
            "total": total,
            "shown": len(candles),
            "name": meta[0] if meta else "",
            "is_active": bool(meta[1]) if meta else None,
            "periods": [p for p in PERIOD_ORDER if p in avail],
        }
        return candles, info, None
    except Exception as e:
        try:
            con.close()
        except Exception:
            pass
        return None, None, f"查询失败: {e}"


def _error_html(title, detail):
    return f"""
<div class="kline-v2-root" style="flex:1;min-height:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;font-family:system-ui,sans-serif;color:var(--color-text);padding:20px;text-align:center;">
  <div style="font-size:28px;">🗄️</div>
  <div style="font-weight:700;color:#f59e0b;">{title}</div>
  <div style="font-size:12px;color:var(--color-text-muted,#94a3b8);max-width:90%;word-break:break-all;">{detail}</div>
  <div style="font-size:11px;color:var(--color-text-muted,#94a3b8);">数据源: {DB_PATH}</div>
  <button class="btn" data-action="reload" data-payload='{{}}' style="margin-top:6px;background:var(--color-surface);color:var(--color-text);border:1px solid var(--color-border);padding:4px 14px;border-radius:4px;cursor:pointer;font-size:12px;">⟳ 重试</button>
</div>"""


def _build_html(symbol_label, period, candles, info):
    candles_json = json.dumps(candles, ensure_ascii=False)
    name = info.get("name") or ""
    total, shown = info["total"], info["shown"]
    active = info.get("is_active")
    active_badge = ('<span style="color:#10b981;font-size:10px;">●活跃</span>' if active
                    else '<span style="color:#94a3b8;font-size:10px;">○已到期</span>')

    btn_html = ""
    for p in info["periods"]:
        label = PERIOD_LABELS.get(p, p)
        active_style = ("background:var(--color-primary);color:#fff;" if p == period
                        else "background:var(--color-surface);color:var(--color-text);")
        btn_html += (
            f'<button class="btn" data-action="switch_period" data-payload=\'{{"period":"{p}"}}\' '
            f'style="{active_style}border:1px solid var(--color-border);padding:3px 8px;border-radius:4px;cursor:pointer;font-size:11px;">{label}</button>'
        )

    if period in ("D", "W"):
        range_txt = f"{candles[0]['time']} ~ {candles[-1]['time']}" if candles else "--"
    else:
        range_txt = (datetime.utcfromtimestamp(candles[0]["time"] + 8 * 3600).strftime("%m-%d %H:%M")
                     + " ~ " +
                     datetime.utcfromtimestamp(candles[-1]["time"] + 8 * 3600).strftime("%m-%d %H:%M")
                     ) if candles else "--"

    src_badge = (
        f'<span style="color:#10b981;font-size:10px;" title="本地 DuckDB: {DB_PATH}">'
        f'✓ 本地库</span>'
        f'<span style="color:#94a3b8;font-size:10px;">{shown}/{total}根 {range_txt}</span>'
    )

    chart_id = "klv2_chart_{id}"
    wrap_id = "klv2_wrap_{id}"

    html = f"""
<div class="kline-root" style="flex:1;min-height:0;display:flex;flex-direction:column;font-family:system-ui,sans-serif;overflow:hidden;width:100%;">
  <div style="padding:6px 8px;display:flex;gap:4px;align-items:center;border-bottom:1px solid var(--color-border);flex-wrap:wrap;flex-shrink:0;">
    <!-- 从这里移除了渐进式下拉框，改为在设置中选择 -->
    <span style="font-weight:bold;font-size:12px;cursor:pointer;" title="点击右上角齿轮图标修改合约" onclick="var btn=this.closest('.module-card').querySelector('.btn-mod-settings');if(btn)btn.click();">{symbol_label}</span>

    {active_badge}
    {btn_html}
    <button id="vp_btn_{{id}}" style="background:var(--color-primary);color:#fff;border:1px solid var(--color-border);padding:3px 8px;border-radius:4px;cursor:pointer;font-size:11px;" title="开启/关闭 左侧VP成交量分布">📊 VP:开</button>
    <button id="vol_btn_{{id}}" style="background:var(--color-surface);color:var(--color-text);border:1px solid var(--color-border);padding:3px 8px;border-radius:4px;cursor:pointer;font-size:11px;" title="开启/关闭 底部成交量柱">📈 VOL:关</button>
    <div style="margin-left:auto;display:flex;gap:4px;align-items:center;">
      <button id="zoom_in_{{id}}" title="放大(X轴)" style="background:var(--color-surface);color:var(--color-text);border:1px solid var(--color-border);padding:2px 6px;border-radius:4px;cursor:pointer;font-size:11px;">➕</button>
      <button id="zoom_out_{{id}}" title="缩小(X轴)" style="background:var(--color-surface);color:var(--color-text);border:1px solid var(--color-border);padding:2px 6px;border-radius:4px;cursor:pointer;font-size:11px;">➖</button>
      <button id="reset_{{id}}" title="复位视图" style="background:var(--color-surface);color:var(--color-text);border:1px solid var(--color-border);padding:2px 6px;border-radius:4px;cursor:pointer;font-size:11px;">↺</button>
      <button class="btn" data-action="reload" data-payload='{{}}' title="重新查询本地库" style="background:var(--color-surface);color:var(--color-text);border:1px solid var(--color-border);padding:2px 6px;border-radius:4px;cursor:pointer;font-size:11px;">⟳</button>
      {src_badge}
    </div>
  </div>
  <div id="{wrap_id}" style="flex:1;position:relative;min-height:0;">
    <div id="legend_{{id}}" style="position:absolute;top:6px;left:8px;z-index:10;pointer-events:none;font-family:ui-monospace,monospace;font-size:11px;line-height:1.4;background:rgba(15,23,42,0.7);padding:4px 8px;border-radius:4px;color:#f8fafc;backdrop-filter:blur(2px);box-shadow:0 2px 6px rgba(0,0,0,0.15);">
      <div style="font-weight:bold;display:flex;gap:8px;align-items:center;">
        <span style="color:#38bdf8;">VOL <span id="leg_vol_{{id}}">--</span></span>
        <span style="color:#f59e0b;">OI <span id="leg_oi_{{id}}">--</span></span>
        <span style="color:#94a3b8;font-size:10px;">{symbol_label} {PERIOD_LABELS.get(period, period)}</span>
      </div>
      <div style="font-size:10px;color:#cbd5e1;margin-top:2px;" id="leg_ohlc_{{id}}">开: -- 高: -- 低: -- 收: --</div>
    </div>
    <canvas id="vp_canvas_{{id}}" style="position:absolute;inset:0;pointer-events:none;z-index:1;"></canvas>
    <div id="{chart_id}" class="klv2-chart" style="position:absolute;inset:0;z-index:2;"></div>
  </div>
</div>
<script>
(function() {{
  var CANDLES = {candles_json};
  var CURRENT_SYMBOL = "{symbol_label}";
  var chartId = "{chart_id}";
  var wrapId = "{wrap_id}";
  var LW_SRC = '{LW_SRC}';
  var vpEnabled = true;
  var volEnabled = false;


  // 全局缩放修正已由 /static/js/globalScaleFix.js 统一提供，此处不再内联


  function ensureLW(cb) {{
    if (window.LightweightCharts) {{ cb(); return; }}
    window.__lwCbs = window.__lwCbs || [];
    window.__lwCbs.push(cb);
    if (window.__lwLoading) {{ return; }}
    window.__lwLoading = true;
    var s = document.createElement('script');
    s.src = LW_SRC;
    s.onload = function() {{
      window.__lwLoading = false;
      (window.__lwCbs || []).forEach(function(fn) {{ fn(); }});
      window.__lwCbs = [];
    }};
    document.head.appendChild(s);
  }}

  function doInit() {{
    var el = document.getElementById(chartId);
    var wrap = document.getElementById(wrapId);
    if (!el || !wrap) {{ return; }}


    var w = wrap.offsetWidth;
    var h = wrap.offsetHeight;
    if (w < 10 || h < 10) {{
      setTimeout(function() {{ ensureLW(doInit); }}, 50);
      return;
    }}
    el.innerHTML = '';
    var isDark = document.documentElement.dataset.theme === 'dark';
    var chart = LightweightCharts.createChart(el, {{
      width: w,
      height: h,
      layout: {{ background: {{ type: 'solid', color: 'transparent' }}, textColor: isDark ? '#d1d5db' : '#374151' }},
      grid: {{ vertLines: {{ color: isDark ? '#374151' : '#e5e7eb' }}, horzLines: {{ color: isDark ? '#374151' : '#e5e7eb' }} }},
      timeScale: {{
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 12,
        barSpacing: 8,
        minBarSpacing: 0.5,
        fixLeftEdge: false,
        lockVisibleTimeRangeOnResize: true
      }},
      rightPriceScale: {{
        autoScale: true
      }},
      handleScale: {{
        axisPressedMouseMove: {{ time: true, price: true }},
        mouseWheel: true,
        pinch: true
      }},
      handleScroll: {{
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: true
      }},
      crosshair: {{ mode: 1 }},
    }});
    var series = chart.addSeries(LightweightCharts.CandlestickSeries, {{
      upColor: '#ef4444', downColor: '#22c55e',
      borderVisible: false,
      wickUpColor: '#ef4444', wickDownColor: '#22c55e'
    }});
    var volSeries = chart.addSeries(LightweightCharts.HistogramSeries, {{
      color: '#6b7280', priceFormat: {{ type: 'volume' }},
      priceScaleId: '', scaleMargins: {{ top: 0.75, bottom: 0 }}
    }});

    volSeries.applyOptions({{ visible: volEnabled }});

    series.setData(CANDLES.map(function(d) {{
      return {{ time: d.time, open: d.open, high: d.high, low: d.low, close: d.close }};
    }}));
    volSeries.setData(CANDLES.map(function(d) {{
      return {{ time: d.time, value: d.volume, color: d.close > d.open ? 'rgba(239,68,68,0.35)' : 'rgba(34,197,94,0.35)' }};
    }}));

    function drawVolumeProfile() {{
      var vpCanvas = document.getElementById('vp_canvas_{{id}}');
      if (!vpCanvas) return;
      var ctx = vpCanvas.getContext('2d');
      if (!vpEnabled) {{
        ctx.clearRect(0, 0, vpCanvas.width, vpCanvas.height);
        return;
      }}

      var dpr = window.devicePixelRatio || 1;
      var nw = wrap.offsetWidth;
      var nh = wrap.offsetHeight;
      vpCanvas.style.width = nw + 'px';
      vpCanvas.style.height = nh + 'px';
      var pw = Math.round(nw * dpr);
      var ph = Math.round(nh * dpr);
      vpCanvas.width = pw;
      vpCanvas.height = ph;
      ctx.scale(pw / nw, ph / nh);
      ctx.clearRect(0, 0, nw, nh);

      var range = chart.timeScale().getVisibleLogicalRange();
      if (!range || CANDLES.length === 0) return;

      var fromIdx = Math.max(0, Math.floor(range.from));
      var toIdx = Math.min(CANDLES.length - 1, Math.ceil(range.to));
      if (fromIdx >= toIdx) return;

      var slice = CANDLES.slice(fromIdx, toIdx + 1);
      var minP = Infinity, maxP = -Infinity;
      slice.forEach(function(c) {{
        if (c.low < minP) minP = c.low;
        if (c.high > maxP) maxP = c.high;
      }});

      if (minP >= maxP) return;

      var numBins = 32;
      var binStep = (maxP - minP) / numBins;
      var bins = [];
      for (var b = 0; b < numBins; b++) {{
        bins.push({{ low: minP + b * binStep, high: minP + (b + 1) * binStep, totalVol: 0 }});
      }}

      slice.forEach(function(c) {{
        var rangeSpan = c.high - c.low || 1;
        for (var b = 0; b < numBins; b++) {{
          if (c.high >= bins[b].low && c.low <= bins[b].high) {{
            var overlapLow = Math.max(c.low, bins[b].low);
            var overlapHigh = Math.min(c.high, bins[b].high);
            var ratio = (overlapHigh - overlapLow) / rangeSpan;
            bins[b].totalVol += c.volume * ratio;
          }}
        }}
      }});

      var maxVol = 0;
      var pocBin = null;
      bins.forEach(function(bin) {{
        if (bin.totalVol > maxVol) {{
          maxVol = bin.totalVol;
          pocBin = bin;
        }}
      }});

      if (maxVol === 0) return;

      var maxBarW = Math.min(180, wrap.offsetWidth * 0.3);

      bins.forEach(function(bin) {{
        var yTop = series.priceToCoordinate(bin.high);
        var yBot = series.priceToCoordinate(bin.low);
        if (yTop === null || yBot === null) return;
        var h = Math.max(1, yBot - yTop);
        var totalW = (bin.totalVol / maxVol) * maxBarW;

        ctx.fillStyle = 'rgba(56, 189, 248, 0.35)';
        ctx.fillRect(0, yTop, totalW, h - 0.5);

        ctx.strokeStyle = 'rgba(56, 189, 248, 0.6)';
        ctx.lineWidth = 0.5;
        ctx.strokeRect(0, yTop, totalW, h - 0.5);
      }});

      if (pocBin) {{
        var pocY = series.priceToCoordinate((pocBin.low + pocBin.high) / 2);
        if (pocY !== null) {{
          ctx.strokeStyle = '#f59e0b';
          ctx.lineWidth = 1.5;
          ctx.setLineDash([4, 3]);
          ctx.beginPath();
          ctx.moveTo(0, pocY);
          ctx.lineTo(wrap.offsetWidth, pocY);
          ctx.stroke();
          ctx.setLineDash([]);

          ctx.fillStyle = '#f59e0b';
          ctx.font = '10px monospace';
          ctx.fillText('POC ' + ((pocBin.low + pocBin.high) / 2).toFixed(1), maxBarW + 6, pocY + 3);
        }}
      }}
    }}

    chart.timeScale().subscribeVisibleLogicalRangeChange(function() {{
      drawVolumeProfile();
    }});

    var legVol = document.getElementById('leg_vol_{{id}}');
    var legOi = document.getElementById('leg_oi_{{id}}');
    var legOhlc = document.getElementById('leg_ohlc_{{id}}');

    function updateLegend(param) {{
      var dataItem = null;
      if (param && param.time) {{
        dataItem = param.seriesData.get(series);
      }}
      if (!dataItem && CANDLES.length > 0) {{
        dataItem = CANDLES[CANDLES.length - 1];
      }}
      if (dataItem) {{
        var volVal = dataItem.volume !== undefined ? dataItem.volume : 0;
        var oiVal = dataItem.oi !== undefined ? dataItem.oi : 0;
        if (legVol) legVol.textContent = Number(volVal).toLocaleString();
        if (legOi) legOi.textContent = Number(oiVal).toLocaleString();
        if (legOhlc && dataItem.open !== undefined) {{
          var chg = dataItem.close - dataItem.open;
          var sign = chg >= 0 ? '+' : '';
          legOhlc.textContent = '开:' + dataItem.open + ' 高:' + dataItem.high + ' 低:' + dataItem.low + ' 收:' + dataItem.close + ' (' + sign + chg.toFixed(1) + ')';
        }}
      }}
      drawVolumeProfile();
    }}

    chart.subscribeCrosshairMove(updateLegend);
    updateLegend();

    var vpBtn = document.getElementById('vp_btn_{{id}}');
    if (vpBtn) {{
      vpBtn.addEventListener('click', function() {{
        vpEnabled = !vpEnabled;
        vpBtn.textContent = vpEnabled ? '📊 VP:开' : '📊 VP:关';
        vpBtn.style.background = vpEnabled ? 'var(--color-primary)' : 'var(--color-surface)';
        vpBtn.style.color = vpEnabled ? '#fff' : 'var(--color-text)';
        drawVolumeProfile();
      }});
    }}

    var volBtn = document.getElementById('vol_btn_{{id}}');
    if (volBtn) {{
      volBtn.addEventListener('click', function() {{
        volEnabled = !volEnabled;
        volSeries.applyOptions({{ visible: volEnabled }});
        volBtn.textContent = volEnabled ? '📈 VOL:开' : '📈 VOL:关';
        volBtn.style.background = volEnabled ? 'var(--color-primary)' : 'var(--color-surface)';
        volBtn.style.color = volEnabled ? '#fff' : 'var(--color-text)';
      }});
    }}

    var btnZoomIn = document.getElementById('zoom_in_{{id}}');
    var btnZoomOut = document.getElementById('zoom_out_{{id}}');
    var btnReset = document.getElementById('reset_{{id}}');

    if (btnZoomIn) {{
      btnZoomIn.addEventListener('click', function() {{
        var range = chart.timeScale().getVisibleLogicalRange();
        if (range) {{
          var center = (range.from + range.to) / 2;
          var half = (range.to - range.from) * 0.35;
          chart.timeScale().setVisibleLogicalRange({{ from: center - half, to: center + half }});
        }}
      }});
    }}

    if (btnZoomOut) {{
      btnZoomOut.addEventListener('click', function() {{
        var range = chart.timeScale().getVisibleLogicalRange();
        if (range) {{
          var center = (range.from + range.to) / 2;
          var half = (range.to - range.from) * 0.7;
          chart.timeScale().setVisibleLogicalRange({{ from: center - half, to: center + half }});
        }}
      }});
    }}

    if (btnReset) {{
      btnReset.addEventListener('click', function() {{
        chart.timeScale().fitContent();
        chart.priceScale('right').applyOptions({{ autoScale: true }});
      }});
    }}

    var ro = new ResizeObserver(function() {{
      var nw = wrap.offsetWidth, nh = wrap.offsetHeight;
      if (nw > 0 && nh > 0) {{
        chart.applyOptions({{width:nw, height:nh}});
        drawVolumeProfile();
      }}
    }});
    ro.observe(wrap);

    var card = el.closest('.module-card');
    if (card) {{
      card.addEventListener('module-destroy', function cleanup() {{
        card.removeEventListener('module-destroy', cleanup);
        ro.disconnect();
        try {{ chart.remove(); }} catch(e) {{}}
      }});
    }}
  }}

  ensureLW(doInit);
}})();
</script>
"""
    return html


def render(config: dict, state: dict) -> dict:
    raw_symbol = config.get("symbol") or DEFAULT_SYMBOL
    period = config.get("period") or "D"
    asset, exchange, prod, symbol, name = parse_symbol_info(raw_symbol)
    limit = PERIOD_LIMIT.get(period, 2000)

    candles, info, err = _fetch_candles(exchange, symbol, period, limit)
    if err or not candles:
        add_log(f"[sys_kline_v2] {raw_symbol} {period} 失败: {err}")
        return {"html": _error_html(f"{raw_symbol} 数据不足或未找到", err or "本地库中无记录，请在 quant_data_hub 执行更新。"), "state": state}

    add_log(f"[sys_kline_v2] {exchange}.{symbol} {period}: {len(candles)}/{info['total']} 条")
    state["last_symbol"] = raw_symbol
    state["last_period"] = period

    label = f"{exchange}.{symbol}"
    return {"html": _build_html(label, period, candles, info), "state": state}


def on_action(action: str, payload: dict, config: dict, state: dict) -> dict:
    if action == "switch_period":
        config["period"] = payload.get("period", config.get("period", "D"))
    elif action == "switch_symbol":
        config["symbol"] = payload.get("symbol", config.get("symbol", DEFAULT_SYMBOL))

    raw_symbol = config.get("symbol") or DEFAULT_SYMBOL
    period = config.get("period") or "D"
    asset, exchange, prod, symbol, name = parse_symbol_info(raw_symbol)
    limit = PERIOD_LIMIT.get(period, 2000)

    candles, info, err = _fetch_candles(exchange, symbol, period, limit)
    if err or not candles:
        add_log(f"[sys_kline_v2] {raw_symbol} {period} 失败: {err}")
        return {"html": _error_html(f"{raw_symbol} 切换失败", err or "数据不可用"), "state": state}

    state["last_symbol"] = raw_symbol
    state["last_period"] = period

    label = f"{exchange}.{symbol}"
    return {"html": _build_html(label, period, candles, info), "state": state, "config": config}
