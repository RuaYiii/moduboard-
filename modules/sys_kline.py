import json
import hashlib
import html as html_lib
import math
import re
import time
import random
import threading
from datetime import datetime, timedelta, timezone

from log_store import add_log

META = {
    "name": "K线行情（在线）",
    "icon": "📊",
    "description": "查看期货/股票K线，包含VP筹码/成交量分布图、底部成交量开关与无偏缩放支持",
    "tags": ["行情交易"],
    "default_size": [32, 24],
    "min_size": [16, 12],
    "max_size": [64, 48],
    "refresh_interval": 0,
    "config_fields": [
        {"key": "symbol", "label": "在线标的", "type": "online-symbol-cascading-select", "default": "SHFE.RB0 螺纹钢连续"},
        {"key": "period", "label": "默认周期", "type": "select", "options": ["1m", "5m", "15m", "30m", "60m", "daily"], "default": "daily"}
    ]
}

LW_SRC = '/static/js/lightweight-charts.standalone.production.js'
DEFAULT_SYMBOL = "SHFE.RB0 螺纹钢连续"
VALID_PERIODS = {"1m", "5m", "15m", "30m", "60m", "daily"}
STOCK_EXCHANGES = {"SSE", "SZSE", "BSE"}
SHANGHAI_TZ = timezone(timedelta(hours=8))
CACHE_TTL_SECONDS = 300
STALE_CACHE_TTL_SECONDS = 3600
FAILURE_CACHE_TTL_SECONDS = 30
MAX_CANDLE_CACHE_ITEMS = 256


def _gen_mock_candles(n=500, base_price=3200.0, seed=None, interval=86400):
    rng = random.Random(42 if seed is None else seed)
    candles = []
    base_ts = int(time.time()) - n * interval
    price = base_price
    move = max(abs(base_price) * 0.008, 0.05)
    digits = 2 if base_price < 1000 else 1
    for i in range(n):
        o = max(0.01, price + rng.uniform(-move * 0.6, move * 0.6))
        c = max(0.01, o + rng.uniform(-move, move))
        h = max(o, c) + rng.uniform(0, move * 0.8)
        l = max(0.01, min(o, c) - rng.uniform(0, move * 0.8))
        candles.append({
            "time": base_ts + i * interval,
            "open": round(o, digits), "high": round(h, digits),
            "low": round(l, digits), "close": round(c, digits),
            "volume": float(rng.randint(5000, 80000))
        })
        price = c
    return candles


_CANDLE_CACHE = {}
_FAILURE_CACHE = {}
_CACHE_LOCK = threading.RLock()


def _prune_caches(now):
    for key, value in list(_CANDLE_CACHE.items()):
        if now - value[0] >= STALE_CACHE_TTL_SECONDS:
            _CANDLE_CACHE.pop(key, None)
    for key, value in list(_FAILURE_CACHE.items()):
        if now - value[0] >= FAILURE_CACHE_TTL_SECONDS:
            _FAILURE_CACHE.pop(key, None)
    if len(_CANDLE_CACHE) > MAX_CANDLE_CACHE_ITEMS:
        oldest = sorted(_CANDLE_CACHE, key=lambda key: _CANDLE_CACHE[key][0])
        for key in oldest[:len(_CANDLE_CACHE) - MAX_CANDLE_CACHE_ITEMS]:
            _CANDLE_CACHE.pop(key, None)
    if len(_FAILURE_CACHE) > MAX_CANDLE_CACHE_ITEMS:
        oldest = sorted(_FAILURE_CACHE, key=lambda key: _FAILURE_CACHE[key][0])
        for key in oldest[:len(_FAILURE_CACHE) - MAX_CANDLE_CACHE_ITEMS]:
            _FAILURE_CACHE.pop(key, None)


def _normalize_period(period):
    return period if period in VALID_PERIODS else "daily"


def _parse_symbol(raw_symbol):
    """Return (display code, asset type, exchange, provider symbol)."""
    raw = str(raw_symbol or DEFAULT_SYMBOL).strip()
    raw = re.sub(r"^【[^】]*】", "", raw).strip()
    code = raw.split()[0] if raw else DEFAULT_SYMBOL

    if "." in code:
        exchange, symbol = code.split(".", 1)
        exchange = exchange.upper()
    else:
        legacy = re.fullmatch(r"(?i)(sh|sz|bj)(\d{6})", code)
        if legacy:
            exchange = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}[legacy.group(1).upper()]
            symbol = legacy.group(2)
        elif code.isdigit():
            symbol = code
            exchange = "SSE" if code.startswith(("5", "6", "9")) else "SZSE"
        else:
            exchange, symbol = "SHFE", code

    asset = "stock_cn" if exchange in STOCK_EXCHANGES or symbol.isdigit() else "futures_cn"
    display_code = f"{exchange}.{symbol}"
    provider_symbol = symbol if asset == "stock_cn" else symbol.upper()
    return display_code, asset, exchange, provider_symbol


def _as_finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"非有限数值: {value}")
    return number


def _row_value(row, *names):
    for name in names:
        if name in row:
            return row[name]
    raise KeyError(f"缺少列: {'/'.join(names)}")


def _to_timestamp(value):
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if not isinstance(value, datetime):
        value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=SHANGHAI_TZ)
    return int(value.timestamp())


def _frame_to_candles(df, is_daily):
    candles_by_time = {}
    for _, row in df.tail(1000).iterrows():
        try:
            raw_time = _row_value(row, "date", "datetime", "日期", "时间", "day")
            candle_time = str(raw_time)[:10] if is_daily else _to_timestamp(raw_time)
            candle = {
                "time": candle_time,
                "open": _as_finite_float(_row_value(row, "open", "开盘")),
                "high": _as_finite_float(_row_value(row, "high", "最高")),
                "low": _as_finite_float(_row_value(row, "low", "最低")),
                "close": _as_finite_float(_row_value(row, "close", "收盘")),
                "volume": _as_finite_float(_row_value(row, "volume", "成交量")),
            }
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if (
            candle["high"] < max(candle["open"], candle["close"])
            or candle["low"] > min(candle["open"], candle["close"])
            or candle["volume"] < 0
        ):
            continue
        candles_by_time[candle_time] = candle
    return [candles_by_time[key] for key in sorted(candles_by_time)]


def _try_fetch_candles(symbol, period):
    display_code, asset, _exchange, provider_symbol = _parse_symbol(symbol)
    period = _normalize_period(period)
    cache_key = f"{display_code}_{period}"
    now = time.time()
    with _CACHE_LOCK:
        _prune_caches(now)
        cached = _CANDLE_CACHE.get(cache_key)
        recent_failure = _FAILURE_CACHE.get(cache_key)
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1], None, "live"
    if recent_failure and now - recent_failure[0] < FAILURE_CACHE_TTL_SECONDS:
        if cached and now - cached[0] < STALE_CACHE_TTL_SECONDS:
            return cached[1], recent_failure[1], "stale"
        return None, recent_failure[1], "error"

    try:
        import akshare as ak

        if period == "daily":
            if asset == "stock_cn":
                df = ak.stock_zh_a_hist(
                    symbol=provider_symbol,
                    period="daily",
                    start_date="19900101",
                    end_date=datetime.now().strftime("%Y%m%d"),
                    adjust="",
                )
            else:
                df = ak.futures_zh_daily_sina(symbol=provider_symbol)
        else:
            p_val = period.replace("m", "")
            if asset == "stock_cn":
                df = ak.stock_zh_a_hist_min_em(symbol=provider_symbol, period=p_val, adjust="")
            else:
                df = ak.futures_zh_minute_sina(symbol=provider_symbol, period=p_val)

        candles = _frame_to_candles(df, period == "daily")
        if not candles:
            raise ValueError("数据源返回空数据或字段格式异常")
        with _CACHE_LOCK:
            _CANDLE_CACHE[cache_key] = (now, candles)
            _FAILURE_CACHE.pop(cache_key, None)
            _prune_caches(now)
        return candles, None, "live"
    except Exception as e:
        with _CACHE_LOCK:
            _FAILURE_CACHE[cache_key] = (now, str(e))
            _prune_caches(now)
        if cached and now - cached[0] < STALE_CACHE_TTL_SECONDS:
            return cached[1], str(e), "stale"
        return None, str(e), "error"


def _build_html(symbol, period, candles, source_status="live", err_msg=""):
    candles_json = json.dumps(candles, ensure_ascii=False).replace("</", "<\\/")
    safe_symbol = html_lib.escape(symbol)
    safe_error = html_lib.escape(err_msg, quote=True)
    if source_status == "mock":
        source_label = f'<span style="color:#f59e0b" title="{safe_error}">⚠ 模拟数据</span>'
    elif source_status == "stale":
        source_label = f'<span style="color:#f59e0b" title="实时接口失败：{safe_error}">⚠ 缓存数据</span>'
    else:
        source_label = '<span style="color:#10b981">✓ 真实数据</span>'
    period_labels = {"1m": "1分", "5m": "5分", "15m": "15分", "30m": "30分", "60m": "1小时", "daily": "日线"}

    btn_html = ""
    for p, label in period_labels.items():
        active = "background:var(--color-primary);color:#fff;" if p == period else "background:var(--color-surface);color:var(--color-text);"
        btn_html += (
            f'<button class="btn btn-period" data-action="switch_period" data-payload=\'{{"period":"{p}"}}\' '
            f'style="{active}border:1px solid var(--color-border);padding:3px 8px;border-radius:4px;cursor:pointer;font-size:11px;">{label}</button>'
        )

    chart_id = "kline_chart_{id}"
    wrap_id = "kline_wrap_{id}"

    html = f"""
<div class="kline-root" style="flex:1;min-height:0;display:flex;flex-direction:column;font-family:system-ui,sans-serif;overflow:hidden;width:100%;">
  <div style="padding:6px 8px;display:flex;gap:6px;align-items:center;border-bottom:1px solid var(--color-border);flex-wrap:wrap;flex-shrink:0;">
    <span id="symbol_settings_{id}" title="点击更换在线标的" style="font-weight:700;font-size:13px;color:var(--color-primary);cursor:pointer;text-decoration:underline dotted;text-underline-offset:3px;">{safe_symbol}</span>
    {btn_html}
    <button id="vp_btn_{id}" style="background:var(--color-primary);color:#fff;border:1px solid var(--color-border);padding:3px 8px;border-radius:4px;cursor:pointer;font-size:11px;" title="开启/关闭 可见区成交量分布（含POC与70%价值区）">📊 VP 70%:开</button>
    <button id="vol_btn_{id}" style="background:var(--color-surface);color:var(--color-text);border:1px solid var(--color-border);padding:3px 8px;border-radius:4px;cursor:pointer;font-size:11px;" title="开启/关闭 底部成交量柱">📈 底部成交量:关</button>
    <div style="margin-left:auto;display:flex;gap:4px;align-items:center;">
      <button id="zoom_in_{id}" title="放大(X轴)" style="background:var(--color-surface);color:var(--color-text);border:1px solid var(--color-border);padding:2px 6px;border-radius:4px;cursor:pointer;font-size:11px;">➕</button>
      <button id="zoom_out_{id}" title="缩小(X轴)" style="background:var(--color-surface);color:var(--color-text);border:1px solid var(--color-border);padding:2px 6px;border-radius:4px;cursor:pointer;font-size:11px;">➖</button>
      <button id="reset_{id}" title="复位视图" style="background:var(--color-surface);color:var(--color-text);border:1px solid var(--color-border);padding:2px 6px;border-radius:4px;cursor:pointer;font-size:11px;">↺</button>
      {source_label}
    </div>
  </div>
  <div id="{wrap_id}" style="flex:1;position:relative;min-height:0;">
    <div id="legend_{id}" style="position:absolute;top:6px;left:8px;z-index:10;pointer-events:none;font-family:ui-monospace,monospace;font-size:11px;line-height:1.4;background:rgba(15,23,42,0.7);padding:4px 8px;border-radius:4px;color:#f8fafc;backdrop-filter:blur(2px);box-shadow:0 2px 6px rgba(0,0,0,0.15);">
      <div style="font-weight:bold;display:flex;gap:8px;align-items:center;">
        <span style="color:#38bdf8;">VOL <span id="leg_vol_{id}">--</span></span>
        <span style="color:#94a3b8;font-size:10px;">{safe_symbol}</span>
      </div>
      <div style="font-size:10px;color:#cbd5e1;margin-top:2px;" id="leg_ohlc_{id}">开: -- 高: -- 低: -- 收: --</div>
    </div>
    <canvas id="vp_canvas_{id}" style="position:absolute;inset:0;pointer-events:none;z-index:5;"></canvas>
    <div id="{chart_id}" style="position:absolute;inset:0;"></div>
  </div>
</div>
<script>
(function() {{
  var CANDLES = {candles_json};
  var chartId = "{chart_id}";
  var wrapId = "{wrap_id}";
  var LW_SRC = '{LW_SRC}';
  var vpEnabled = true;
  var volEnabled = false; // 默认关闭底部成交量柱，避免与左侧VP重叠
  var candlesByTime = Object.create(null);
  function candleKey(value) {{
    if (value && typeof value === 'object' && value.year) {{
      return String(value.year) + '-' + String(value.month).padStart(2, '0') + '-' + String(value.day).padStart(2, '0');
    }}
    return String(value);
  }}
  CANDLES.forEach(function(c) {{ candlesByTime[candleKey(c.time)] = c; }});

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
      priceScaleId: ''
    }});
    volSeries.priceScale().applyOptions({{
      scaleMargins: {{ top: 0.75, bottom: 0 }}
    }});

    volSeries.applyOptions({{ visible: volEnabled }});

    series.setData(CANDLES.map(function(d) {{
      return {{ time: d.time, open: d.open, high: d.high, low: d.low, close: d.close }};
    }}));
    volSeries.setData(CANDLES.map(function(d) {{
      return {{ time: d.time, value: d.volume, color: d.close > d.open ? 'rgba(239,68,68,0.35)' : 'rgba(34,197,94,0.35)' }};
    }}));

    var vpFrame = 0;
    function scheduleVolumeProfile() {{
      if (vpFrame) return;
      vpFrame = window.requestAnimationFrame(function() {{
        vpFrame = 0;
        drawVolumeProfile();
      }});
    }}

    // 可见区 Volume Profile：70% 实体量 + 30% 影线量，保留零振幅K线成交量。
    function drawVolumeProfile() {{
      var vpCanvas = document.getElementById('vp_canvas_{id}');
      if (!vpCanvas) return;
      var ctx = vpCanvas.getContext('2d');
      if (!vpEnabled) {{
        ctx.clearRect(0, 0, vpCanvas.width, vpCanvas.height);
        return;
      }}

      var dpr = window.devicePixelRatio || 1;
      var nw = wrap.offsetWidth;
      var nh = wrap.offsetHeight;
      if (nw < 1 || nh < 1) return;
      vpCanvas.style.width = nw + 'px';
      vpCanvas.style.height = nh + 'px';
      var pw = Math.round(nw * dpr);
      var ph = Math.round(nh * dpr);
      if (vpCanvas.width !== pw || vpCanvas.height !== ph) {{
        vpCanvas.width = pw;
        vpCanvas.height = ph;
      }}
      ctx.setTransform(pw / nw, 0, 0, ph / nh, 0, 0);
      ctx.clearRect(0, 0, nw, nh);

      var range = chart.timeScale().getVisibleLogicalRange();
      if (!range || CANDLES.length === 0) return;

      var fromIdx = Math.max(0, Math.floor(range.from));
      var toIdx = Math.min(CANDLES.length - 1, Math.ceil(range.to));
      if (fromIdx > toIdx) return;

      var slice = CANDLES.slice(fromIdx, toIdx + 1);
      var minP = Infinity, maxP = -Infinity;
      slice.forEach(function(c) {{
        if (c.low < minP) minP = c.low;
        if (c.high > maxP) maxP = c.high;
      }});

      if (minP > maxP) return;
      if (minP === maxP) {{
        var pricePad = Math.max(Math.abs(minP) * 0.001, 0.01);
        minP -= pricePad;
        maxP += pricePad;
      }}

      var numBins = Math.max(18, Math.min(56, Math.floor(nh / 12)));
      var binStep = (maxP - minP) / numBins;
      var bins = [];
      for (var b = 0; b < numBins; b++) {{
        bins.push({{ low: minP + b * binStep, high: minP + (b + 1) * binStep, upVol: 0, downVol: 0, totalVol: 0 }});
      }}

      function allocateRange(low, high, volume, isUp) {{
        volume = Math.max(0, Number(volume) || 0);
        if (!volume) return;
        low = Math.max(minP, Math.min(maxP, Number(low)));
        high = Math.max(minP, Math.min(maxP, Number(high)));
        if (high < low) {{ var swap = low; low = high; high = swap; }}
        var span = high - low;
        if (span <= Number.EPSILON * Math.max(1, Math.abs(high), Math.abs(low))) {{
          var pointIdx = Math.max(0, Math.min(numBins - 1, Math.floor((low - minP) / binStep)));
          bins[pointIdx][isUp ? 'upVol' : 'downVol'] += volume;
          return;
        }}
        for (var i = 0; i < numBins; i++) {{
          var overlap = Math.max(0, Math.min(high, bins[i].high) - Math.max(low, bins[i].low));
          if (overlap > 0) bins[i][isUp ? 'upVol' : 'downVol'] += volume * overlap / span;
        }}
      }}

      slice.forEach(function(c) {{
        var isUp = Number(c.close) >= Number(c.open);
        allocateRange(Math.min(c.open, c.close), Math.max(c.open, c.close), Number(c.volume) * 0.7, isUp);
        allocateRange(c.low, c.high, Number(c.volume) * 0.3, isUp);
      }});

      var maxVol = 0, totalProfileVol = 0, pocIndex = 0;
      bins.forEach(function(bin, index) {{
        bin.totalVol = bin.upVol + bin.downVol;
        totalProfileVol += bin.totalVol;
        if (bin.totalVol > maxVol) {{
          maxVol = bin.totalVol;
          pocIndex = index;
        }}
      }});

      if (maxVol === 0) return;

      // 从 POC 向两侧扩展，得到覆盖总成交量 70% 的 Value Area。
      var vaLow = pocIndex, vaHigh = pocIndex, vaVol = bins[pocIndex].totalVol;
      var vaTarget = totalProfileVol * 0.7;
      while (vaVol < vaTarget && (vaLow > 0 || vaHigh < bins.length - 1)) {{
        var leftVol = vaLow > 0 ? bins[vaLow - 1].totalVol : -1;
        var rightVol = vaHigh < bins.length - 1 ? bins[vaHigh + 1].totalVol : -1;
        if (rightVol > leftVol) {{ vaHigh += 1; vaVol += bins[vaHigh].totalVol; }}
        else {{ vaLow -= 1; vaVol += bins[vaLow].totalVol; }}
      }}

      var maxBarW = Math.min(170, wrap.offsetWidth * 0.26);

      bins.forEach(function(bin, index) {{
        var yTop = series.priceToCoordinate(bin.high);
        var yBot = series.priceToCoordinate(bin.low);
        if (yTop === null || yBot === null) return;
        var y = Math.min(yTop, yBot);
        var h = Math.max(1, Math.abs(yBot - yTop));
        var totalW = (bin.totalVol / maxVol) * maxBarW;
        var downW = bin.totalVol ? totalW * bin.downVol / bin.totalVol : 0;
        var upW = totalW - downW;

        if (index >= vaLow && index <= vaHigh) {{
          ctx.fillStyle = 'rgba(59, 130, 246, 0.08)';
          ctx.fillRect(0, y, maxBarW, Math.max(0.5, h - 0.5));
        }}
        ctx.fillStyle = 'rgba(34, 197, 94, 0.48)';
        ctx.fillRect(0, y, downW, Math.max(0.5, h - 0.5));
        ctx.fillStyle = 'rgba(239, 68, 68, 0.48)';
        ctx.fillRect(downW, y, upW, Math.max(0.5, h - 0.5));
      }});

      function drawLevel(price, color, label, fullWidth) {{
        var levelY = series.priceToCoordinate(price);
        if (levelY !== null) {{
          ctx.strokeStyle = color;
          ctx.lineWidth = label === 'POC' ? 1.5 : 1;
          ctx.setLineDash(label === 'POC' ? [4, 3] : [2, 3]);
          ctx.beginPath();
          ctx.moveTo(0, levelY);
          ctx.lineTo(fullWidth ? nw : maxBarW, levelY);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.fillStyle = color;
          ctx.font = '10px monospace';
          ctx.fillText(label + ' ' + Number(price).toFixed(2), maxBarW + 5, levelY + 3);
        }}
      }}
      var pocBin = bins[pocIndex];
      drawLevel((pocBin.low + pocBin.high) / 2, '#f59e0b', 'POC', true);
      drawLevel(bins[vaHigh].high, '#60a5fa', 'VAH', false);
      drawLevel(bins[vaLow].low, '#60a5fa', 'VAL', false);
    }}

    var onVisibleRangeChange = function() {{ scheduleVolumeProfile(); }};
    var onVpInteractionEnd = function() {{ scheduleVolumeProfile(); }};
    chart.timeScale().subscribeVisibleLogicalRangeChange(onVisibleRangeChange);
    wrap.addEventListener('wheel', onVpInteractionEnd, {{ passive: true }});
    wrap.addEventListener('pointerup', onVpInteractionEnd);

    // 左侧贴边 VOL / OHLC 数据挂载
    var legVol = document.getElementById('leg_vol_{id}');
    var legOhlc = document.getElementById('leg_ohlc_{id}');

    function updateLegend(param) {{
      var dataItem = null;
      if (param && param.time != null) {{
        dataItem = candlesByTime[candleKey(param.time)] || param.seriesData.get(series);
      }}
      if (!dataItem && CANDLES.length > 0) {{
        dataItem = CANDLES[CANDLES.length - 1];
      }}
      if (dataItem) {{
        var volVal = dataItem.volume !== undefined ? dataItem.volume : 0;
        if (legVol) legVol.textContent = Number(volVal).toLocaleString();
        if (legOhlc && dataItem.open !== undefined) {{
          var chg = dataItem.close - dataItem.open;
          var sign = chg >= 0 ? '+' : '';
          legOhlc.textContent = '开:' + dataItem.open + ' 高:' + dataItem.high + ' 低:' + dataItem.low + ' 收:' + dataItem.close + ' (' + sign + chg.toFixed(1) + ')';
        }}
      }}
    }}

    chart.subscribeCrosshairMove(updateLegend);
    updateLegend();
    scheduleVolumeProfile();

    // 切换 VP 筹码分布
    var vpBtn = document.getElementById('vp_btn_{id}');
    if (vpBtn) {{
      vpBtn.addEventListener('click', function() {{
        vpEnabled = !vpEnabled;
        vpBtn.textContent = vpEnabled ? '📊 VP 70%:开' : '📊 VP 70%:关';
        vpBtn.style.background = vpEnabled ? 'var(--color-primary)' : 'var(--color-surface)';
        vpBtn.style.color = vpEnabled ? '#fff' : 'var(--color-text)';
        scheduleVolumeProfile();
      }});
    }}

    var symbolSettings = document.getElementById('symbol_settings_{id}');
    if (symbolSettings) {{
      symbolSettings.addEventListener('click', function() {{
        var moduleCard = symbolSettings.closest('.module-card');
        var settingsButton = moduleCard && moduleCard.querySelector('.btn-mod-settings');
        if (settingsButton) settingsButton.click();
      }});
    }}

    // 切换 底部成交量柱
    var volBtn = document.getElementById('vol_btn_{id}');
    if (volBtn) {{
      volBtn.addEventListener('click', function() {{
        volEnabled = !volEnabled;
        volSeries.applyOptions({{ visible: volEnabled }});
        volBtn.textContent = volEnabled ? '📈 底部成交量:开' : '📈 底部成交量:关';
        volBtn.style.background = volEnabled ? 'var(--color-primary)' : 'var(--color-surface)';
        volBtn.style.color = volEnabled ? '#fff' : 'var(--color-text)';
      }});
    }}

    // 缩放/复位按钮绑定
    var btnZoomIn = document.getElementById('zoom_in_{id}');
    var btnZoomOut = document.getElementById('zoom_out_{id}');
    var btnReset = document.getElementById('reset_{id}');

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
        scheduleVolumeProfile();
      }}
    }});
    ro.observe(wrap);

    var card = el.closest('.module-card');
    if (card) {{
      card.addEventListener('module-destroy', function cleanup() {{
        card.removeEventListener('module-destroy', cleanup);
        ro.disconnect();
        wrap.removeEventListener('wheel', onVpInteractionEnd);
        wrap.removeEventListener('pointerup', onVpInteractionEnd);
        chart.timeScale().unsubscribeVisibleLogicalRangeChange(onVisibleRangeChange);
        chart.unsubscribeCrosshairMove(updateLegend);
        if (vpFrame) window.cancelAnimationFrame(vpFrame);
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
    symbol, asset, _exchange, _provider_symbol = _parse_symbol(raw_symbol)
    period = _normalize_period(config.get("period"))
    candles, err, source_status = _try_fetch_candles(symbol, period)
    if not candles:
        add_log(f"[sys_kline] API失败: {err}，使用模拟数据")
        interval = 86400 if period == "daily" else int(period[:-1]) * 60
        seed = int(hashlib.sha256(f"{symbol}:{period}".encode("utf-8")).hexdigest()[:8], 16)
        base_price = 100.0 if asset == "stock_cn" else 3200.0
        candles = _gen_mock_candles(base_price=base_price, seed=seed, interval=interval)
        source_status = "mock"
    else:
        status_text = "缓存" if source_status == "stale" else "实时"
        add_log(f"[sys_kline] 成功获取 {len(candles)} 根K线({status_text}): {symbol} {period}")

    state["last_period"] = period
    state["last_symbol"] = symbol
    return {"html": _build_html(symbol, period, candles, source_status, err or ""), "state": state}


def on_action(action: str, payload: dict, config: dict, state: dict) -> dict:
    if action == "switch_period":
        config["period"] = _normalize_period(payload.get("period"))
        result = render(config, state)
        result["config"] = config
        return result
    return {"state": state}
