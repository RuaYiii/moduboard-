"""
sys_display_test.py — ModuBoard 渲染能力测试模块 v2
6个Tab: 列表 / 表格(筛选+列显隐) / 字典(多层折叠) / 图片 / 进度&徽章 / K线图
"""
import json
import time
import random
from log_store import add_log

META = {
    "name": "渲染测试",
    "icon": "🧪",
    "description": "测试各种数据渲染类型：列表/表格/字典/图片/进度条/K线",
    "tags": ["系统"],
    "default_size": [32, 30],
    "min_size": [20, 20],
    "max_size": [64, 64],
    "refresh_interval": 0,
    "config_fields": []
}

TABS = ["列表", "表格", "字典", "图片", "进度/徽章", "K线图"]


# ─── 公共工具 ─────────────────────────────────

def _tab_bar(active):
    btns = ""
    for i, label in enumerate(TABS):
        a = i == active
        s = ("background:var(--color-primary);color:#fff;"
             if a else
             "background:var(--color-surface);color:var(--color-text-muted);")
        btns += (
            f'<button data-action="switch_tab" data-payload=\'{{"tab":{i}}}\' '
            f'style="{s}border:1px solid var(--color-border);padding:4px 10px;'
            f'border-radius:6px;font-size:11px;cursor:pointer;">{label}</button>'
        )
    preview_btn = (
        '<a href="/preview/sys_display_test" target="_blank" '
        'style="margin-left:auto;padding:4px 10px;border:1px solid var(--color-border);'
        'border-radius:6px;font-size:11px;color:var(--color-text-muted);text-decoration:none;'
        'background:var(--color-surface);white-space:nowrap;" title="在独立窗口中预览此模块">🔍 新窗口</a>'
    )
    return (
        '<div style="padding:8px;display:flex;gap:6px;flex-wrap:wrap;align-items:center;'
        f'border-bottom:1px solid var(--color-border);">{btns}{preview_btn}</div>'
    )


def _wrap(tb, subtitle, body):
    return f"""
<div style="width:100%;height:100%;display:flex;flex-direction:column;overflow:hidden;font-family:system-ui,sans-serif;">
  {tb}
  <div style="padding:5px 12px;font-size:11px;color:var(--color-text-muted);border-bottom:1px solid var(--color-border);">{subtitle}</div>
  <div style="flex:1;overflow:auto;">{body}</div>
</div>"""


# ─── Tab 0 · 列表 ─────────────────────────────

def _render_list(tb):
    items = [
        ("螺纹钢", "SHFE.rb2609", "3245", "+1.2%", "#ef4444"),
        ("沪金",   "SHFE.au2412", "612.5", "-0.4%", "#22c55e"),
        ("铁矿石", "DCE.i2409",   "782",   "+0.8%", "#ef4444"),
        ("豆粕",   "DCE.m2501",   "2956",  "-1.1%", "#22c55e"),
        ("原油",   "INE.sc2410",  "534",   "+2.3%", "#ef4444"),
        ("沪铜",   "SHFE.cu2412", "79800", "+0.1%", "#ef4444"),
    ]
    rows = ""
    for name, code, price, chg, color in items:
        rows += f"""
<div style="display:flex;align-items:center;padding:9px 12px;border-bottom:1px solid var(--color-border);gap:10px;transition:background .1s;"
     onmouseenter="this.style.background='var(--color-surface-hover)'" onmouseleave="this.style.background=''">
  <div style="width:6px;height:6px;border-radius:50%;background:{color};flex-shrink:0;"></div>
  <div style="flex:1;font-size:13px;font-weight:600;">{name}</div>
  <div style="font-size:11px;color:var(--color-text-muted);font-family:monospace;">{code}</div>
  <div style="font-size:13px;font-weight:700;font-family:monospace;min-width:56px;text-align:right;">{price}</div>
  <div style="font-size:12px;font-weight:700;color:{color};min-width:52px;text-align:right;">{chg}</div>
</div>"""
    return _wrap(tb, "普通列表：品种 / 代码 / 价格 / 涨跌幅（带颜色状态指示）", rows)


# ─── Tab 1 · 表格（筛选 + 列显隐） ─────────────

def _render_table(tb, search="", hidden_cols=None):
    if hidden_cols is None:
        hidden_cols = []

    all_cols = ["合约", "最新价", "涨跌额", "涨跌%", "成交量", "持仓量", "昨结"]
    rows_data = [
        ["rb2609", "3245",  "+12",   "+0.37%", "1,234,567", "2,456,789", "3233"],
        ["au2412", "612.5", "-2.5",  "-0.41%", "345,678",   "1,234,567", "615"],
        ["i2409",  "782",   "+5.5",  "+0.71%", "876,543",   "3,456,789", "776.5"],
        ["m2501",  "2956",  "-18",   "-0.60%", "654,321",   "4,567,890", "2974"],
        ["sc2410", "534",   "+6.5",  "+1.20%", "234,567",   "567,890",   "527.5"],
        ["cu2412", "79800", "+80",   "+0.10%", "123,456",   "456,789",   "79720"],
        ["FG2609", "1102",  "-8",    "-0.72%", "432,100",   "1,234,000", "1110"],
    ]

    if search:
        rows_data = [r for r in rows_data if search.lower() in r[0].lower()]

    visible_cols = [c for c in all_cols if c not in hidden_cols]
    visible_idxs = [all_cols.index(c) for c in visible_cols]

    # 列切换按钮
    col_btns = ""
    for col in all_cols:
        hidden = col in hidden_cols
        new_hidden = [c for c in hidden_cols if c != col] if hidden else hidden_cols + [col]
        new_hidden_json = json.dumps(new_hidden)
        s = ("background:var(--color-border);color:var(--color-text-muted);"
             if hidden else
             "background:var(--color-primary);color:#fff;")
        col_btns += (
            f'<button data-action="toggle_col" data-payload=\'{{"hidden":{new_hidden_json}}}\' '
            f'style="{s}border:none;padding:2px 8px;border-radius:4px;font-size:11px;cursor:pointer;">{col}</button>'
        )

    # 搜索：Enter 触发 或 点按钮
    search_bar = f"""
<div style="padding:6px 8px;display:flex;gap:8px;align-items:center;border-bottom:1px solid var(--color-border);flex-wrap:wrap;">
  <input data-input="search" type="text" placeholder="输入后回车搜索..." value="{search}"
         style="padding:4px 8px;border:1px solid var(--color-border);border-radius:4px;font-size:12px;
                background:var(--color-surface);color:var(--color-text);min-width:140px;"
         onkeydown="if(event.key==='Enter'){{var b=this.closest('.module-body').querySelector('[data-action=\\'do_search\\']');if(b)b.click();}}" />
  <button data-action="do_search"
          style="padding:4px 12px;background:var(--color-primary);color:#fff;border:none;border-radius:4px;font-size:12px;cursor:pointer;">搜索</button>
  <div style="display:flex;gap:4px;flex-wrap:wrap;">{col_btns}</div>
</div>"""

    thead = "".join(
        f'<th style="padding:7px 10px;text-align:left;font-size:11px;color:var(--color-text-muted);font-weight:600;'
        f'border-bottom:1px solid var(--color-border);position:sticky;top:0;background:var(--color-surface);white-space:nowrap;">{visible_cols[j]}</th>'
        for j in range(len(visible_cols))
    )
    tbody = ""
    for i, r in enumerate(rows_data):
        bg = "var(--color-surface-hover)" if i % 2 == 0 else "transparent"
        cells = "".join(
            f'<td style="padding:7px 10px;font-size:12px;border-bottom:1px solid var(--color-border);font-family:monospace;">{r[idx]}</td>'
            for idx in visible_idxs
        )
        tbody += f'<tr style="background:{bg};">{cells}</tr>'

    table = f'<table style="width:100%;border-collapse:collapse;"><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>'

    body = search_bar + f'<div style="overflow:auto;">{table}</div>'
    return _wrap(tb, f"表格：Enter搜索 & 点列名切换列显隐  ·  {len(rows_data)} 行", body)


# ─── Tab 2 · 字典（多层折叠） ────────────────────

def _render_dict_node(key, value, depth=0, path=""):
    indent = depth * 16
    full_path = f"{path}.{key}" if path else str(key)
    base_style = f"padding-left:{indent}px;"

    if isinstance(value, dict):
        children = "".join(_render_dict_node(k, v, depth + 1, full_path) for k, v in value.items())
        return f"""
<details open style="{base_style}">
  <summary style="cursor:pointer;padding:6px 8px;font-size:12px;font-weight:600;color:var(--color-primary);
                  border-bottom:1px solid var(--color-border);list-style:none;display:flex;align-items:center;gap:6px;user-select:none;">
    <span style="font-size:10px;display:inline-block;transition:transform .2s;">▶</span> {key}
    <span style="margin-left:auto;font-size:10px;color:var(--color-text-muted);">dict · {len(value)} 项</span>
  </summary>
  {children}
</details>"""
    elif isinstance(value, list):
        items_html = "".join(_render_dict_node(f"[{i}]", item, depth + 1, full_path) for i, item in enumerate(value[:20]))
        more = (f'<div style="padding:4px 8px;padding-left:{indent+16}px;font-size:11px;color:var(--color-text-muted);">'
                f'... 共 {len(value)} 项</div>') if len(value) > 20 else ""
        return f"""
<details open style="{base_style}">
  <summary style="cursor:pointer;padding:6px 8px;font-size:12px;font-weight:600;color:#8b5cf6;
                  border-bottom:1px solid var(--color-border);list-style:none;display:flex;align-items:center;gap:6px;user-select:none;">
    <span style="font-size:10px;">▶</span> {key}
    <span style="margin-left:auto;font-size:10px;color:var(--color-text-muted);">list · {len(value)} 项</span>
  </summary>
  {items_html}{more}
</details>"""
    else:
        if isinstance(value, bool):
            color = "#10b981" if value else "#ef4444"
            display = str(value)
        elif isinstance(value, (int, float)):
            color = "var(--color-primary)"
            display = str(value)
        elif value is None:
            color = "var(--color-text-muted)"
            display = "null"
        else:
            color = "var(--color-text)"
            display = f'"{value}"'

        return f"""
<div style="{base_style}display:flex;align-items:baseline;padding:5px 8px;border-bottom:1px solid var(--color-border);gap:8px;
     transition:background .1s;" onmouseenter="this.style.background='var(--color-surface-hover)'" onmouseleave="this.style.background=''">
  <span style="font-size:12px;color:var(--color-text-muted);min-width:80px;flex-shrink:0;">{key}</span>
  <span style="font-size:12px;font-family:monospace;color:{color};">{display}</span>
</div>"""


def _render_dict(tb):
    sample = {
        "account": {
            "id": "U12345678",
            "name": "张三",
            "level": "VIP3",
            "is_active": True
        },
        "portfolio": {
            "net_value": 1023456.78,
            "available": 234567.89,
            "margin_ratio": 0.184,
            "positions": [
                {"symbol": "SHFE.rb2609", "side": "long",  "qty": 10, "pnl": 1234.5},
                {"symbol": "DCE.m2501",   "side": "short", "qty": 5,  "pnl": -567.8},
            ]
        },
        "settings": {
            "theme": "dark",
            "notify": True,
            "risk_limit": 0.05,
            "channels": ["telegram", "uliao"],
            "metadata": {
                "created_at": "2024-01-01",
                "version": "2.1.0",
                "flags": {"debug": False, "beta": True}
            }
        },
        "last_update": "2026-07-20 00:04:46",
        "error_count": 0
    }
    nodes = "".join(_render_dict_node(k, v) for k, v in sample.items())
    return _wrap(tb, "多层字典：▶ 点击折叠/展开  ·  dict/list/str/num/bool 分色", f'<div>{nodes}</div>')


# ─── Tab 3 · 图片 ─────────────────────────────

def _render_image(tb):
    colors = ["#ef4444", "#f59e0b", "#10b981", "#3b82f6", "#8b5cf6", "#ec4899", "#14b8a6", "#f97316"]
    swatches = "".join(
        f'<div title="{c}" onclick="navigator.clipboard&&navigator.clipboard.writeText(\'{c}\')" '
        f'style="width:36px;height:36px;border-radius:6px;background:{c};cursor:pointer;transition:transform .1s;" '
        f'onmouseenter="this.style.transform=\'scale(1.15)\'" onmouseleave="this.style.transform=\'\'"></div>'
        for c in colors
    )
    # 内联 SVG 占位图
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="120">'
           '<rect fill="#4f6ef7" width="400" height="120"/>'
           '<text y="50%" x="50%" dominant-baseline="middle" text-anchor="middle" '
           'fill="white" font-size="18" font-family="system-ui">🖼 图片占位</text></svg>')
    import base64
    svg_b64 = 'data:image/svg+xml;base64,' + base64.b64encode(svg.encode()).decode()

    body = f"""
<div style="padding:12px;display:flex;flex-direction:column;gap:16px;">
  <div>
    <div style="font-size:11px;color:var(--color-text-muted);margin-bottom:6px;">横幅图片</div>
    <img src="{svg_b64}" alt="Banner" style="width:100%;border-radius:8px;border:1px solid var(--color-border);" />
  </div>
  <div>
    <div style="font-size:11px;color:var(--color-text-muted);margin-bottom:6px;">调色板（点击复制 HEX）</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;">{swatches}</div>
  </div>
  <div>
    <div style="font-size:11px;color:var(--color-text-muted);margin-bottom:6px;">Emoji 图标组</div>
    <div style="font-size:28px;display:flex;gap:12px;">📈 📉 💹 🔔 ⚡ 🎯 🔮 📊</div>
  </div>
</div>"""
    return _wrap(tb, "图片 & 调色板（点色块复制HEX）", body)


# ─── Tab 4 · 进度 & 徽章 ─────────────────────────

def _render_progress(tb):
    metrics = [
        ("仓位使用",    68, "#ef4444"),
        ("可用资金比",  45, "#f59e0b"),
        ("盈亏目标达成", 72, "#10b981"),
        ("风险占用",    81, "#3b82f6"),
        ("账户健康度",  91, "#8b5cf6"),
    ]
    bars = "".join(f"""
<div style="margin-bottom:12px;">
  <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px;">
    <span>{n}</span><span style="font-weight:700;color:{c};">{p}%</span>
  </div>
  <div style="background:var(--color-border);border-radius:4px;height:8px;overflow:hidden;">
    <div style="width:{p}%;height:100%;background:{c};border-radius:4px;"></div>
  </div>
</div>""" for n, p, c in metrics)

    badges = [
        ("正常",  "#10b981", "#d1fae5"), ("警告",  "#f59e0b", "#fef3c7"),
        ("错误",  "#ef4444", "#fee2e2"), ("信息",  "#3b82f6", "#dbeafe"),
        ("Beta",  "#8b5cf6", "#ede9fe"), ("新功能", "#ec4899", "#fce7f3"),
        ("已弃用","#6b7280", "#f3f4f6"), ("实验性", "#f97316", "#ffedd5"),
    ]
    badge_html = "".join(
        f'<span style="background:{bg};color:{fg};padding:3px 10px;border-radius:12px;font-size:11px;font-weight:700;">{l}</span>'
        for l, fg, bg in badges
    )
    body = f"""
<div style="padding:12px;">
  <div style="font-size:12px;color:var(--color-text-muted);margin-bottom:10px;">进度条</div>
  {bars}
  <div style="font-size:12px;color:var(--color-text-muted);margin:12px 0 8px;">状态徽章 (Badge)</div>
  <div style="display:flex;gap:6px;flex-wrap:wrap;">{badge_html}</div>
</div>"""
    return _wrap(tb, "进度条 + 状态徽章组件库", body)


# ─── Tab 5 · K线图（自包含全高） ─────────────────

def _gen_mock_candles(n=500, base_price=3200.0, seed=42):
    random.seed(seed)
    candles = []
    base_ts = int(time.time()) - n * 86400
    price = base_price
    for i in range(n):
        o = price + random.uniform(-15, 15)
        c = o + random.uniform(-25, 25)
        h = max(o, c) + random.uniform(0, 18)
        l = min(o, c) - random.uniform(0, 18)
        candles.append({
            "time": base_ts + i * 86400,
            "open": round(o, 1), "high": round(h, 1),
            "low": round(l, 1), "close": round(c, 1),
            "volume": float(random.randint(5000, 80000))
        })
        price = c
    return candles


def _render_kline(tb):
    candles = _gen_mock_candles()
    candles_json = json.dumps(candles)
    chart_id = "dt_kline_chart_{id}"
    wrap_id  = "dt_kline_wrap_{id}"
    lw_src = '/static/js/lightweight-charts.standalone.production.js'

    return f"""
<div class="dt-kline-root" style="flex:1;min-height:0;display:flex;flex-direction:column;font-family:system-ui,sans-serif;overflow:hidden;width:100%;">
  {tb}
  <div style="padding:5px 12px;font-size:11px;border-bottom:1px solid var(--color-border);display:flex;gap:8px;align-items:center;flex-shrink:0;">
    <span style="color:var(--color-text-muted);">K线图：LightweightCharts</span>
    <span style="color:#f59e0b;">⚠ 模拟随机数据 500根日线</span>
    <button id="dt_vp_btn_{id}" style="background:var(--color-surface);color:var(--color-text);border:1px solid var(--color-border);padding:2px 6px;border-radius:4px;cursor:pointer;font-size:11px;" title="开启/关闭 左侧VP筹码分布">📊 VP分布:开</button>
    <button id="dt_vol_btn_{id}" style="background:var(--color-surface);color:var(--color-text);border:1px solid var(--color-border);padding:2px 6px;border-radius:4px;cursor:pointer;font-size:11px;" title="开启/关闭 底部成交量柱">📈 底部成交量:关</button>
    <div style="margin-left:auto;display:flex;gap:4px;align-items:center;">
      <button id="dt_zoom_in_{id}" title="放大(X轴)" style="background:var(--color-surface);color:var(--color-text);border:1px solid var(--color-border);padding:2px 6px;border-radius:4px;cursor:pointer;font-size:11px;">➕</button>
      <button id="dt_zoom_out_{id}" title="缩小(X轴)" style="background:var(--color-surface);color:var(--color-text);border:1px solid var(--color-border);padding:2px 6px;border-radius:4px;cursor:pointer;font-size:11px;">➖</button>
      <button id="dt_reset_{id}" title="复位视图" style="background:var(--color-surface);color:var(--color-text);border:1px solid var(--color-border);padding:2px 6px;border-radius:4px;cursor:pointer;font-size:11px;">↺</button>
    </div>
  </div>
  <div id="{wrap_id}" style="flex:1;position:relative;min-height:0;">
    <div id="dt_legend_{id}" style="position:absolute;top:6px;left:8px;z-index:10;pointer-events:none;font-family:ui-monospace,monospace;font-size:11px;line-height:1.4;background:rgba(15,23,42,0.7);padding:4px 8px;border-radius:4px;color:#f8fafc;backdrop-filter:blur(2px);box-shadow:0 2px 6px rgba(0,0,0,0.15);">
      <div style="font-weight:bold;display:flex;gap:8px;align-items:center;">
        <span style="color:#38bdf8;">VOL <span id="dt_leg_vol_{id}">--</span></span>
        <span style="color:#94a3b8;font-size:10px;">模拟K线</span>
      </div>
      <div style="font-size:10px;color:#cbd5e1;margin-top:2px;" id="dt_leg_ohlc_{id}">开: -- 高: -- 低: -- 收: --</div>
    </div>
    <canvas id="dt_vp_canvas_{id}" style="position:absolute;inset:0;pointer-events:none;z-index:5;"></canvas>
    <div id="{chart_id}" class="dt-kline-chart" style="position:absolute;inset:0;"></div>
  </div>
</div>
<script>
(function() {{
  var DATA = {candles_json};
  var chartId = "{chart_id}";
  var wrapId  = "{wrap_id}";
  var LW_SRC = '{lw_src}';
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
    var el   = document.getElementById(chartId);
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
      width:  w,
      height: h,
      layout: {{ background: {{type:'solid',color:'transparent'}}, textColor: isDark?'#d1d5db':'#374151' }},
      grid: {{ vertLines: {{color:isDark?'#374151':'#e5e7eb'}}, horzLines: {{color:isDark?'#374151':'#e5e7eb'}} }},
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
    var s = chart.addSeries(LightweightCharts.CandlestickSeries, {{
      upColor:'#ef4444', downColor:'#22c55e',
      borderVisible:false, wickUpColor:'#ef4444', wickDownColor:'#22c55e'
    }});
    var v = chart.addSeries(LightweightCharts.HistogramSeries, {{
      color:'#6b7280', priceFormat:{{type:'volume'}},
      priceScaleId:''
    }});
    v.priceScale().applyOptions({{
      scaleMargins:{{top:0.75, bottom:0}}
    }});

    v.applyOptions({{ visible: volEnabled }});

    s.setData(DATA.map(function(d){{ return {{time:d.time,open:d.open,high:d.high,low:d.low,close:d.close}}; }}));
    v.setData(DATA.map(function(d){{ return {{time:d.time,value:d.volume,color:d.close>d.open?'rgba(239,68,68,.35)':'rgba(34,197,94,.35)'}}; }}));

    function drawVolumeProfile() {{
      var vpCanvas = document.getElementById('dt_vp_canvas_{id}');
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
      if (!range || DATA.length === 0) return;

      var fromIdx = Math.max(0, Math.floor(range.from));
      var toIdx = Math.min(DATA.length - 1, Math.ceil(range.to));
      if (fromIdx >= toIdx) return;

      var slice = DATA.slice(fromIdx, toIdx + 1);
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
        var yTop = s.priceToCoordinate(bin.high);
        var yBot = s.priceToCoordinate(bin.low);
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
        var pocY = s.priceToCoordinate((pocBin.low + pocBin.high) / 2);
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

    // 左侧贴边 VOL / OHLC 数据挂载
    var legVol = document.getElementById('dt_leg_vol_{id}');
    var legOhlc = document.getElementById('dt_leg_ohlc_{id}');

    function updateLegend(param) {{
      var dataItem = null;
      if (param && param.time) {{
        dataItem = param.seriesData.get(s);
      }}
      if (!dataItem && DATA.length > 0) {{
        dataItem = DATA[DATA.length - 1];
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
      drawVolumeProfile();
    }}

    chart.subscribeCrosshairMove(updateLegend);
    updateLegend();

    // 切换 VP 筹码分布
    var vpBtn = document.getElementById('dt_vp_btn_{id}');
    if (vpBtn) {{
      vpBtn.addEventListener('click', function() {{
        vpEnabled = !vpEnabled;
        vpBtn.textContent = vpEnabled ? '📊 VP分布:开' : '📊 VP分布:关';
        vpBtn.style.background = vpEnabled ? 'var(--color-primary)' : 'var(--color-surface)';
        vpBtn.style.color = vpEnabled ? '#fff' : 'var(--color-text)';
        drawVolumeProfile();
      }});
    }}

    // 切换 底部成交量柱
    var volBtn = document.getElementById('dt_vol_btn_{id}');
    if (volBtn) {{
      volBtn.addEventListener('click', function() {{
        volEnabled = !volEnabled;
        v.applyOptions({{ visible: volEnabled }});
        volBtn.textContent = volEnabled ? '📈 底部成交量:开' : '📈 底部成交量:关';
        volBtn.style.background = volEnabled ? 'var(--color-primary)' : 'var(--color-surface)';
        volBtn.style.color = volEnabled ? '#fff' : 'var(--color-text)';
      }});
    }}

    // 缩放/复位按钮绑定
    var btnZoomIn = document.getElementById('dt_zoom_in_{id}');
    var btnZoomOut = document.getElementById('dt_zoom_out_{id}');
    var btnReset = document.getElementById('dt_reset_{id}');

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
</script>"""


# ─── 路由 ────────────────────────────────────────

def _build(state):
    tab = state.get("tab", 0)
    tb = _tab_bar(tab)
    if tab == 0:   return _render_list(tb)
    elif tab == 1: return _render_table(tb, state.get("search",""), state.get("hidden_cols",[]))
    elif tab == 2: return _render_dict(tb)
    elif tab == 3: return _render_image(tb)
    elif tab == 4: return _render_progress(tb)
    elif tab == 5: return _render_kline(tb)
    return _render_list(tb)


def render(config: dict, state: dict) -> dict:
    return {"html": _build(state), "state": state}


def on_action(action: str, payload: dict, config: dict, state: dict) -> dict:
    if action == "switch_tab":
        state["tab"] = int(payload.get("tab", 0))
    elif action == "toggle_col":
        state["hidden_cols"] = payload.get("hidden", [])
    elif action == "do_search":
        state["search"] = payload.get("search", "")
    return render(config, state)
