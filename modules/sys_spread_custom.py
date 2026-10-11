"""sys_spread_custom — 跨期价差·自选（本地 DuckDB）

与 sys_spread 的价差视图同一套逻辑（后月-前月的差值曲线 + 20点滚动±2σ通道 + z-score），
但价差对完全由用户自定义：工具栏 [合约A] − [合约B] [＋添加]，
每对 = close(A) - close(B)，存 state 随工作区保存，✕ 可删。
首次打开自动播种 "主力次月-主力" 一对，避免空图。

设计说明（2026-07-26）：
- 不限相邻月、不限视野窗口——A/B 任选（同品种），适合做远月组合、跨代对比
- 分钟级周期只对近月活跃合约有数据，选不到数据的对会被跳过并在信息行体现
- JS 模板 = 普通字符串 + __TOKEN__ 替换；{id} 留给渲染器（同 sys_spread 教训）
"""
import calendar
import json
import os
import re
from datetime import date, timedelta

from log_store import add_log

DB_PATH = os.environ.get("QUANT_DB_PATH") or os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "quant_data_hub", "data", "quant.duckdb"))

PERIOD_LABELS = {"1m": "1分", "5m": "5分", "15m": "15分", "30m": "30分",
                 "1h": "1时", "2h": "2时", "4h": "4时", "D": "日线", "W": "周线"}
PERIODS = ["D", "1h", "1m"]
DAYS_OPTIONS = ["30", "60", "120", "240", "365"]
BAND_WIN = 20
DEFAULT_PRODUCT = "FG"
PALETTE = ["#00e5ff", "#ff9100", "#a3e635", "#f472b6",
           "#facc15", "#34d399", "#c084fc", "#fb7185"]


def _db_available():
    return os.path.exists(DB_PATH)


def _load_product_options():
    if not _db_available():
        return [DEFAULT_PRODUCT]
    try:
        import duckdb
        con = duckdb.connect(DB_PATH, read_only=True)
        syms = [r[0] for r in con.execute(
            "SELECT DISTINCT symbol FROM symbols WHERE asset_class='futures_cn'"
        ).fetchall()]
        con.close()
        prods = sorted({re.match(r"^[A-Za-z]+", s).group(0).upper()
                        for s in syms if re.match(r"^[A-Za-z]+", s)})
        return prods or [DEFAULT_PRODUCT]
    except Exception as e:
        add_log(f"[sys_spread_custom] 加载品种清单失败: {e}")
        return [DEFAULT_PRODUCT]


_PRODUCT_OPTIONS = _load_product_options()
AUTO_VP = "自动主力"


META = {
    "name": "跨期价差-自选",
    "icon": "🎯",
    "description": "本地库自定义价差对（A−B 任选合约）+ ±2σ通道 + z-score",
    "tags": ["行情交易"],
    "default_size": [32, 20],
    "min_size": [16, 12],
    "max_size": [64, 48],
    "refresh_interval": 0,
    "config_fields": [
        {"key": "product", "label": "品种（本地库）", "type": "select",
         "options": _PRODUCT_OPTIONS, "default": DEFAULT_PRODUCT},
        {"key": "viewpoint", "label": "观测视点 (留空或自动主力)", "type": "dynamic-select",
         "depends_on": "product", "endpoint": "/api/spread_viewpoints", "default": AUTO_VP},
        {"key": "days", "label": "回溯天数", "type": "select",
         "options": DAYS_OPTIONS, "default": "120"},
        {"key": "custom_start", "label": "起始日(YYYY-MM-DD，空=按回溯天数)", "type": "text",
         "default": ""},
        {"key": "custom_end", "label": "结束日(YYYY-MM-DD，空=至今)", "type": "text",
         "default": ""},
    ],
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PAIR_RE = re.compile(r"^([A-Za-z]+\d{4})-([A-Za-z]+\d{4})$")


def _month_index(symbol):
    return (2000 + int(symbol[-4:-2])) * 12 + int(symbol[-2:])


def _fetch_contracts(con, product):
    rows = con.execute(
        "SELECT exchange, symbol, COALESCE(name,''), is_active FROM symbols "
        "WHERE asset_class='futures_cn' AND upper(symbol) LIKE ? ORDER BY symbol",
        [(product.upper() + "%")]).fetchall()
    out = []
    for ex, sym, name, active in rows:
        if not sym.upper().startswith(product.upper()):
            continue
        suffix = sym[len(product):]
        if not (len(suffix) == 4 and suffix.isdigit()):
            continue  # 排除主连等拼接代码
        out.append({"exchange": ex, "symbol": sym, "name": name, "active": bool(active)})
    return out


def _find_main(con, symbols):
    if not symbols:
        return None
    ph = ",".join(["?"] * len(symbols))
    rows = con.execute(
        f"SELECT s.symbol, COALESCE(b.open_interest,0), COALESCE(b.volume,0) "
        f"FROM bars b JOIN symbols s USING(symbol_id) "
        f"WHERE s.symbol IN ({ph}) AND b.period='D' AND b.trading_day = "
        f"(SELECT MAX(b2.trading_day) FROM bars b2 JOIN symbols s2 USING(symbol_id) "
        f"WHERE s2.symbol IN ({ph}) AND b2.period='D')",
        symbols + symbols).fetchall()
    if not rows:
        return None
    rows.sort(key=lambda r: (r[1], r[2]), reverse=True)
    return rows[0][0] if (rows[0][1] > 0 or rows[0][2] > 0) else None


def _fetch_prices(con, symbols, period, start, end):
    if not symbols:
        return {}
    ph = ",".join(["?"] * len(symbols))
    sql = ("SELECT s.symbol, b.ts, b.trading_day, b.close "
           "FROM bars b JOIN symbols s USING(symbol_id) "
           f"WHERE s.symbol IN ({ph}) AND b.period=?")
    params = list(symbols) + [period]
    if start:
        sql += " AND b.trading_day >= ?"
        params.append(start)
    if end:
        sql += " AND b.trading_day <= ?"
        params.append(end)
    sql += " ORDER BY s.symbol, b.ts"
    is_day = period in ("D", "W")
    data = {}
    for sym, ts, td, close in con.execute(sql, params).fetchall():
        t = str(td) if is_day else calendar.timegm(ts.timetuple())
        data.setdefault(sym, []).append([t, close])
    return data


def _resolve_range(days, custom_start, custom_end):
    note = ""
    end = custom_end.strip() if custom_end else ""
    if end and not _DATE_RE.match(end):
        note = f"自定义结束日格式无效已忽略: {end}"
        end = ""
    start = custom_start.strip() if custom_start else ""
    if start and not _DATE_RE.match(start):
        note = f"自定义起始日格式无效已忽略: {start}"
        start = ""
    if not start and days > 0:
        start = str(date.today() - timedelta(days=days))
    return start or None, end or None, note


def _rolling_band(pts, win=BAND_WIN):
    vals = [v for _, v in pts]
    mean_p, up_p, dn_p = [], [], []
    for i in range(len(vals)):
        seg = vals[max(0, i - win + 1): i + 1]
        if len(seg) < 5:
            continue
        m = sum(seg) / len(seg)
        sd = (sum((x - m) ** 2 for x in seg) / (len(seg) - 1)) ** 0.5
        t = pts[i][0]
        mean_p.append([t, round(m, 2)])
        up_p.append([t, round(m + 2 * sd, 2)])
        dn_p.append([t, round(m - 2 * sd, 2)])
    z = None
    if mean_p and len(mean_p) >= 2:
        m = mean_p[-1][1]
        sd = (up_p[-1][1] - m) / 2
        z = round((vals[-1] - m) / sd, 1) if sd > 0 else 0.0
    return mean_p, up_p, dn_p, z


def _build_pair_series(data, pairs):
    """每对 'A-B' = close(A) - close(B)，附滚动通道与 z。"""
    series = []
    for idx, pair in enumerate(pairs):
        m = _PAIR_RE.match(pair)
        if not m:
            continue
        a, b = m.group(1), m.group(2)
        pa, pb = data.get(a), data.get(b)
        if not pa or not pb:
            continue
        mb = {t: v for t, v in pb}
        pts = [[t, round(v - mb[t], 4)] for t, v in pa if t in mb]
        if len(pts) < 2:
            continue
        mean_p, up_p, dn_p, z = _rolling_band(pts)
        series.append({
            "label": pair,
            "color": PALETTE[idx % len(PALETTE)],
            "width": 2,
            "points": pts,
            "band_mean": mean_p, "band_up": up_p, "band_dn": dn_p,
            "z": z,
        })
    return series


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
def _error_html(title, detail, extra_btn=""):
    return f"""
<div class="spread-root" style="width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;font-family:system-ui,sans-serif;color:var(--color-text);padding:20px;text-align:center;box-sizing:border-box;">
  <div style="font-size:28px;">🎯</div>
  <div style="font-weight:700;color:#f59e0b;">{title}</div>
  <div style="font-size:12px;color:var(--color-text-muted,#94a3b8);max-width:90%;word-break:break-all;">{detail}</div>
  <div style="font-size:11px;color:var(--color-text-muted,#94a3b8);">数据源: {DB_PATH}</div>
  <div style="display:flex;gap:8px;margin-top:6px;">
    <button class="btn" data-action="reload" data-payload='{{}}' style="background:var(--color-surface);color:var(--color-text);border:1px solid var(--color-border);padding:4px 14px;border-radius:4px;cursor:pointer;font-size:12px;">⟳ 重试</button>
    {extra_btn}
  </div>
</div>"""


def _back_to_d_btn(period):
    """分钟级区间无数据时的逃生按钮（错误面板没有周期栏，必须有出路）。"""
    if period == "D":
        return ""
    return ('<button class="btn" data-action="switch_period" '
            'data-payload=\'{"period":"D"}\' style="background:var(--color-primary);'
            'color:#fff;border:1px solid var(--color-border);padding:4px 14px;'
            'border-radius:4px;cursor:pointer;font-size:12px;">⇄ 切回日线</button>')


def _btn(action, payload, label, active, title=""):
    style = ("background:var(--color-primary);color:#fff;" if active
             else "background:var(--color-surface);color:var(--color-text);")
    t = f' title="{title}"' if title else ""
    return (f'<button class="btn" data-action="{action}" data-payload=\'{payload}\'{t} '
            f'style="{style}border:1px solid var(--color-border);padding:3px 8px;'
            f'border-radius:4px;cursor:pointer;font-size:11px;">{label}</button>')


def _build_html(product, period, series, band_on, candidates, info_line, note):
    payload = json.dumps({
        "view": "spread",
        "minute": period not in ("D", "W"),
        "series": series,
        "days": [],
        "frame": {},
        "bands": band_on,
    }, ensure_ascii=False)

    btns = []
    for p in PERIODS:
        btns.append(_btn("switch_period", json.dumps({"period": p}),
                         PERIOD_LABELS[p], p == period))
    btns.append('<span style="color:var(--color-border);margin:0 2px;">|</span>')
    btns.append(_btn("toggle_band", "{}", f"通道:{'开' if band_on else '关'}", band_on,
                     "20点滚动均值±2σ 历史通道"))
    btns.append('<span style="color:var(--color-border);margin:0 2px;">|</span>')
    if candidates:
        opts = "".join(
            f'<option value="{c["symbol"]}">{c["symbol"]}{" ●" if c["active"] else ""}</option>'
            for c in candidates)
        sel_style = ("background:var(--color-surface);color:var(--color-text);border:1px solid "
                     "var(--color-border);border-radius:4px;font-size:11px;padding:2px 4px;max-width:100px;")
        btns.append(
            f'<select id="spca_{{id}}" title="合约A（被减数，价差为正方向的腿）" style="{sel_style}">{opts}</select>'
            f'<span style="color:#94a3b8;font-size:12px;font-weight:700;">−</span>'
            f'<select id="spcb_{{id}}" title="合约B（减数）" style="{sel_style}">{opts}</select>'
            f'<button id="spcadd_{{id}}" class="btn" data-action="add_pair" data-payload=\'{{}}\' '
            f'title="添加价差对 A−B" style="background:var(--color-surface);color:var(--color-text);'
            f'border:1px solid var(--color-border);padding:3px 8px;border-radius:4px;cursor:pointer;'
            f'font-size:11px;">＋添加</button>')
    toolbar = "".join(btns)

    chips = []
    for i, s in enumerate(series):
        z = s.get("z")
        ztxt = ""
        if z is not None:
            zc = "#ef4444" if abs(z) >= 2 else ("#f59e0b" if abs(z) >= 1 else "#94a3b8")
            ztxt = (f' <span style="color:{zc};" '
                    f'title="当前值在20点滚动分布中的位置，|z|≥2 为极端">z{z:+.1f}</span>')
        rm = (f'<button class="btn" data-action="remove_pair" '
              f'data-payload=\'{json.dumps({"pair": s["label"]})}\' title="删除这对价差" '
              f'style="background:none;border:none;color:#94a3b8;cursor:pointer;'
              f'font-size:10px;padding:0 2px;">✕</button>')
        chips.append(
            f'<span data-idx="{i}" style="color:{s["color"]};cursor:pointer;white-space:nowrap;" '
            f'title="点击隐藏/显示">{s["label"]}</span>{ztxt}{rm}'
            f'<span style="margin-right:8px;"></span>')
    chips_html = "".join(chips)

    note_html = (f'<span style="color:#f59e0b;font-size:10px;"> ⚠ {note}</span>' if note else "")
    caption = "自选价差 = A − B · 高于零轴=A强于B · 虚线通道=20点滚动均值±2σ · |z|≥2 为极端 · 点图例可隐藏"

    html = f"""
<div class="spread-root" style="width:100%;height:100%;display:flex;flex-direction:column;font-family:system-ui,sans-serif;color:var(--color-text);overflow:hidden;">
  <div style="display:flex;align-items:center;gap:4px;flex-wrap:wrap;padding:2px 0;flex-shrink:0;">{toolbar}</div>
  <div style="display:flex;align-items:center;gap:8px;font-size:10px;color:#94a3b8;padding:2px 0;flex-shrink:0;">
    <span style="color:var(--color-text);font-weight:600;">{product} 自选价差</span>
    <span style="color:#10b981;" title="本地 DuckDB: {DB_PATH}">✓ 本地库</span>
    <span>{info_line}</span>{note_html}
  </div>
  <div id="spwrap_{{id}}" style="flex:1;position:relative;min-height:0;">
    <div id="sptip_{{id}}" style="position:absolute;top:2px;left:6px;right:6px;z-index:10;font-size:11px;color:#cbd5e1;pointer-events:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">提示：移动准星查看数值 · 用上方 A − B 下拉添加价差对 · 点下方标签可隐藏</div>
    <div id="spchart_{{id}}" class="spread-chart" style="position:absolute;left:0;right:0;top:18px;bottom:13px;"></div>
    <div style="position:absolute;bottom:0;left:6px;right:6px;z-index:10;font-size:10px;color:#64748b;pointer-events:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="{caption}">{caption}</div>
  </div>
  <div id="spchips_{{id}}" style="font-size:10px;line-height:1.7;max-height:44px;overflow-y:auto;padding:2px 0;flex-shrink:0;{'' if chips_html else 'display:none;'}">{chips_html}</div>
</div>
__JS_TEMPLATE__
"""
    return html.replace("__JS_TEMPLATE__", JS_TEMPLATE).replace("__PAYLOAD__", payload)


JS_TEMPLATE = """
<script>
(function() {
  var PAYLOAD = __PAYLOAD__;
  var VIEW = PAYLOAD.view;
  var chartId = 'spchart_{id}';
  var wrapId = 'spwrap_{id}';
  var LW_SRC = '/static/js/lightweight-charts.standalone.production.js';

  // 全局缩放修正已由 /static/js/globalScaleFix.js 统一提供，此处不再内联

  function ensureLW(cb) {
    if (window.LightweightCharts) { cb(); return; }
    window.__lwCbs = window.__lwCbs || [];
    window.__lwCbs.push(cb);
    if (window.__lwLoading) { return; }
    window.__lwLoading = true;
    var s = document.createElement('script');
    s.src = LW_SRC;
    s.onload = function() {
      window.__lwLoading = false;
      (window.__lwCbs || []).forEach(function(fn) { fn(); });
      window.__lwCbs = [];
    };
    document.head.appendChild(s);
  }

  function doInit() {
    var el = document.getElementById(chartId);
    var wrap = document.getElementById(wrapId);
    if (!el || !wrap) { return; }
    var w = wrap.offsetWidth;
    var h = wrap.offsetHeight - 31;
    if (w < 10 || h < 10) {
      setTimeout(function() { ensureLW(doInit); }, 50);
      return;
    }
    el.innerHTML = '';
    var isDark = document.documentElement.dataset.theme === 'dark';
    var chart = LightweightCharts.createChart(el, {
      width: w, height: h,
      layout: { background: { type: 'solid', color: 'transparent' },
                textColor: isDark ? '#d1d5db' : '#374151' },
      grid: { vertLines: { color: isDark ? '#374151' : '#e5e7eb' },
              horzLines: { color: isDark ? '#374151' : '#e5e7eb' } },
      timeScale: { timeVisible: PAYLOAD.minute, secondsVisible: false,
                   rightOffset: 5, barSpacing: 8, minBarSpacing: 0.5,
                   fixLeftEdge: false, lockVisibleTimeRangeOnResize: true },
      rightPriceScale: { autoScale: true },
      crosshair: { mode: 0 },
      handleScale: { axisPressedMouseMove: { time: true, price: true }, mouseWheel: true, pinch: true },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
    });

    var lines = [];
    var bandLines = [];

    function addLine(opts) {
      return chart.addSeries(LightweightCharts.LineSeries, Object.assign({
        priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false, pointMarkersVisible: false
      }, opts));
    }

    PAYLOAD.series.forEach(function(s, i) {
      var ln = addLine({ color: s.color, lineWidth: s.width || 2,
                         crosshairMarkerVisible: true });
      ln.setData(s.points.map(function(p) { return { time: p[0], value: p[1] }; }));
      if (i === 0) {
        ln.createPriceLine({ price: 0, color: '#94a3b8', lineWidth: 1,
                             lineStyle: LightweightCharts.LineStyle.Dashed,
                             axisLabelVisible: true, title: '' });
      }
      lines.push(ln);
      if (PAYLOAD.bands && s.band_up) {
        var mk = function(pts, dash) {
          var bl = addLine({ color: 'rgba(148,163,184,0.55)', lineWidth: 1,
                             lineStyle: dash });
          bl.setData(pts.map(function(p) { return { time: p[0], value: p[1] }; }));
          return bl;
        };
        bandLines.push([
          mk(s.band_up, LightweightCharts.LineStyle.Dashed),
          mk(s.band_mean, LightweightCharts.LineStyle.Dotted),
          mk(s.band_dn, LightweightCharts.LineStyle.Dashed)
        ]);
      } else {
        bandLines.push([]);
      }
    });

    // 添加价差对：A/B 两个 select 变化时把 {a,b} 写进按钮 data-payload
    var selA = document.getElementById('spca_{id}');
    var selB = document.getElementById('spcb_{id}');
    var addBtn = document.getElementById('spcadd_{id}');
    if (selA && selB && addBtn) {
      var syncPayload = function() {
        addBtn.setAttribute('data-payload', JSON.stringify({ a: selA.value, b: selB.value }));
      };
      selA.addEventListener('change', syncPayload);
      selB.addEventListener('change', syncPayload);
      syncPayload();
    }

    // 图例开关（含通道跟随）
    var hidden = {};
    var chipsBox = document.getElementById('spchips_{id}');
    if (chipsBox) {
      var chips = chipsBox.querySelectorAll('[data-idx]');
      for (var ci = 0; ci < chips.length; ci++) {
        (function(chip) {
          chip.addEventListener('click', function() {
            var i = parseInt(chip.getAttribute('data-idx'), 10);
            hidden[i] = !hidden[i];
            lines[i].applyOptions({ visible: !hidden[i] });
            (bandLines[i] || []).forEach(function(bl) {
              bl.applyOptions({ visible: !hidden[i] });
            });
            chip.style.opacity = hidden[i] ? '0.35' : '1';
          });
        })(chips[ci]);
      }
    }

    // 十字线 tooltip
    var tip = document.getElementById('sptip_{id}');
    chart.subscribeCrosshairMove(function(param) {
      if (!tip) return;
      var t = param && param.time;
      if (!t) {
        tip.textContent = '提示：移动准星查看数值 · 用上方 A − B 下拉添加价差对 · 点下方标签可隐藏';
        return;
      }
      var tstr = (typeof t === 'number')
        ? new Date(t * 1000).toLocaleString('zh-CN', { hour12: false })
        : (t.year ? t.year + '-' + t.month + '-' + t.day : t);
      var parts = [tstr];
      lines.forEach(function(ln, i) {
        var d = param.seriesData.get(ln);
        if (d && d.value !== undefined) {
          parts.push('<span style="color:' + PAYLOAD.series[i].color + '">'
                     + PAYLOAD.series[i].label + ' ' + d.value + '</span>');
        }
      });
      tip.innerHTML = parts.join(' · ');
    });

    chart.timeScale().fitContent();

    var ro = new ResizeObserver(function() {
      var nw = wrap.offsetWidth, nh = wrap.offsetHeight - 31;
      if (nw > 0 && nh > 0) {
        chart.applyOptions({ width: nw, height: nh });
      }
    });
    ro.observe(wrap);

    var card = el.closest('.module-card');
    if (card) {
      card.addEventListener('module-destroy', function cleanup() {
        card.removeEventListener('module-destroy', cleanup);
        ro.disconnect();
        try { chart.remove(); } catch(e) {}
      });
    }
  }

  ensureLW(doInit);
})();
</script>
"""


# ---------------------------------------------------------------------------
# 模块接口
# ---------------------------------------------------------------------------
def _seed_pairs(con, contracts, pairs, vp_symbol=None):
    """首次使用：播种 '视点次月-视点'（无视点则自动主力），避免空图。"""
    if pairs:
        return pairs
    if not vp_symbol:
        vp_symbol = _find_main(con, [c["symbol"] for c in contracts if c["active"]])
    if not vp_symbol:
        return pairs
    by_mi = {_month_index(c["symbol"]): c["symbol"] for c in contracts}
    nxt = by_mi.get(_month_index(vp_symbol) + 1)
    if nxt:
        pairs.append(f"{nxt}-{vp_symbol}")
    return pairs


def _render_with(config, state, period):
    product = (config.get("product") or DEFAULT_PRODUCT).strip()
    days_cfg = int(config.get("days") or 120)
    band_on = bool(state.get("band_on", True))
    pairs = [p for p in state.get("pairs", []) if isinstance(p, str) and _PAIR_RE.match(p)]

    if not _db_available():
        return _error_html("数据库不存在", DB_PATH)
    try:
        import duckdb
        con = duckdb.connect(DB_PATH, read_only=True)
    except Exception as e:
        msg = str(e)
        if "lock" in msg.lower() or "conflicting" in msg.lower():
            return _error_html("数据库正在更新写入中", "稍候点 ⟳ 重试")
        return _error_html("数据库连接失败", msg)

    note = ""
    try:
        contracts = _fetch_contracts(con, product)
        if not contracts:
            con.close()
            return _error_html(f"本地库没有品种 {product} 的合约",
                               "可先在 quant_data_hub 执行 update 入库")

        # 观测视点：决定区间锚点与播种对（含历史合约，支持回看过去）
        all_syms = [c["symbol"] for c in contracts]
        vp_cfg = (config.get("viewpoint") or AUTO_VP).strip()
        vp_is_auto = vp_cfg == AUTO_VP or vp_cfg not in all_syms
        vp_symbol = None if vp_is_auto else vp_cfg

        # 区间：自定义起止日 > 回溯天数；历史视点未指定区间时锚定其最后交易日
        custom = (config.get("custom_start", "") or "").strip() or \
                 (config.get("custom_end", "") or "").strip()
        start, end, note = _resolve_range(days_cfg, config.get("custom_start", ""),
                                          config.get("custom_end", ""))
        if vp_symbol and not custom:
            anchor = con.execute(
                "SELECT MAX(b.trading_day) FROM bars b JOIN symbols s USING(symbol_id) "
                "WHERE s.symbol=? AND b.period='D'", [vp_symbol]).fetchone()
            if anchor and anchor[0]:
                a_end = str(anchor[0])
                if a_end < str(date.today()):
                    end = a_end
                    start = str(date.fromisoformat(a_end) - timedelta(days=days_cfg))
                    note = (note + "；" if note else "") + \
                           f"历史视点：区间锚定 {vp_symbol} 最后交易日"

        pairs = _seed_pairs(con, contracts, pairs, vp_symbol)
        state["pairs"] = pairs
        data = _fetch_prices(con, all_syms, period, start, end)
        con.close()
    except Exception as e:
        try:
            con.close()
        except Exception:
            pass
        return _error_html("查询失败", str(e))

    series = _build_pair_series(data, pairs)
    # A/B 下拉候选：本品种所有合约（活跃优先，有数据优先，远月也能选）
    has_data = {c["symbol"] for c in contracts if len(data.get(c["symbol"], [])) >= 2}
    candidates = list(contracts)
    candidates.sort(key=lambda c: (not c["active"], c["symbol"] not in has_data, c["symbol"]))

    if not series and not candidates:
        # 整个区间无任何数据（如 1h/1m × 历史视点）——周期按钮都没了，给逃生按钮
        hint = "分钟级数据只有近月活跃合约有，含历史合约的对请切回日线"
        return _error_html(f"{product} 在该区间没有可用数据",
                           f"周期={PERIOD_LABELS.get(period, period)} "
                           f"区间={start or '最早'}~{end or '至今'}。{hint}",
                           _back_to_d_btn(period))

    skipped = len(pairs) - len(series)
    if skipped and not series:
        # 对都在但全部跳过：不报错面板，保留工具栏让用户用 A−B 下拉重新选
        note = (note + "；" if note else "") + \
               f"{skipped}对已添加价差在该区间无数据未显示，请用 A−B 下拉重新选择"
    n_pts = sum(len(s["points"]) for s in series)
    vp_tag = f"视点{vp_symbol}" if vp_symbol else "视点自动主力"
    info_line = (f"{vp_tag} · {len(series)}对价差 · {n_pts}点 · "
                 f"{PERIOD_LABELS.get(period, period)} · {start or '最早'} ~ {end or '至今'}"
                 + (f" · {skipped}对无数据已跳过" if skipped and series else ""))
    add_log(f"[sys_spread_custom] {product} {period} {vp_tag}: {len(series)}对 {n_pts}点")
    return _build_html(product, period, series, band_on, candidates, info_line, note)


def render(config: dict, state: dict) -> dict:
    period = state.get("last_period", "D")
    state.update({
        "last_period": period,
        "pairs": state.get("pairs", []),
        "band_on": state.get("band_on", True),
    })
    return {"html": _render_with(config, state, period), "state": state}


def on_action(action: str, payload: dict, config: dict, state: dict) -> dict:
    if action == "switch_period":
        state["last_period"] = payload.get("period", "D")
    elif action == "toggle_band":
        state["band_on"] = not state.get("band_on", True)
    elif action == "add_pair":
        a = (payload.get("a") or "").strip()
        b = (payload.get("b") or "").strip()
        if a and b and a != b:
            pair = f"{a}-{b}"
            pairs = state.setdefault("pairs", [])
            if pair not in pairs:
                pairs.append(pair)
    elif action == "remove_pair":
        pair = (payload.get("pair") or "").strip()
        state["pairs"] = [p for p in state.get("pairs", []) if p != pair]
    elif action == "reload":
        pass
    else:
        return {"state": state}
    return render(config, state)
