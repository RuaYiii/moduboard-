"""sys_spread — 跨期价差分析（本地 DuckDB，视点+视野参数化版 v3）

核心概念（2026-07-26 v2 引入）：
- 观测视点：一条基准合约，默认"自动主力"（本地库最新交易日持仓量最大者）
- 视野宽度：视点 ±N 个月（默认 3），颜色按距视点偏移结构化：
  视点=琥珀加粗；远月(正偏移)=青系；近月(负偏移)=绿系
- 视野外合约：下拉选 + [＋添加] 纳入（虚线显示，可 ✕ 移除），存 state 随工作区保存
- 区间：设置里默认回溯 120 天，自定义起止日优先

v3 新增（2026-07-26）：
- 每个视图左下角有读图注记（caption），图上直接解释视图含义
- 结构视图改为时间滑块：拖动/播放逐日观察期限结构曲线演变，
  当前日=琥珀粗线，前一日=灰色细线对照；每日自动计算结构注记
  （月差均值、升水/贴水判定、最大台阶）
- 价差视图加滚动 ±2σ 历史通道（20点窗口，布林式），图例显示当前 z-score，
  |z|>=2 高亮——判断"价差是否极端"的量化依据，可用 [通道] 按钮开关

教训吸取（见 Hermes skill moduboard-modules）：
- 元素 id 用 {id} 占位符；JS 模板是普通字符串 + __TOKEN__ 替换（花括号零转义）
- LW v5：addSeries(LightweightCharts.LineSeries, ...)
- 根 div 用 width/height:100%（module-body 的 flex 待遇是 :has() 白名单，新类名拿不到）
- 动态参数进 data-action：select change 时写入按钮 data-payload，引擎点击时读取
"""
import calendar
import json
import os
import re
from datetime import date, timedelta

from log_store import add_log

# ---------------------------------------------------------------------------
# 数据源：本地 DuckDB
# ---------------------------------------------------------------------------
DB_PATH = os.environ.get("QUANT_DB_PATH") or os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "quant_data_hub", "data", "quant.duckdb"))

PERIOD_LABELS = {"1m": "1分", "5m": "5分", "15m": "15分", "30m": "30分",
                 "1h": "1时", "2h": "2时", "4h": "4时", "D": "日线", "W": "周线"}
SPREAD_PERIODS = ["D", "1h", "1m"]
VIEWS = [("price", "价格"), ("spread", "价差"), ("curve", "结构")]
VIEW_CAPTIONS = {
    "price": "每条线 = 一个合约的收盘价走势 · 琥珀★=视点主力 青=远月 绿=近月 虚线=手动添加",
    "spread": "价差 = 后月 − 前月 · 高于零轴=远月升水 · 虚线通道=20点滚动均值±2σ · z 越极端越值得研究",
    "curve": "横轴 = 合约到期月（不是时间！）· 线上翘=远月升水(contango) · 下弯=近月贴水(back) · 拖动滑块逐日看形状演变",
}
WIDTH_OPTIONS = ["1", "2", "3", "4", "5", "6"]
GAP_OPTIONS = ["1", "2", "3", "4"]
DAYS_OPTIONS = ["30", "60", "120", "240", "365"]
BAND_WIN = 20  # 滚动通道窗口（数据点）

DEFAULT_PRODUCT = "FG"
AUTO_VP = "自动主力"


def _db_available():
    return os.path.exists(DB_PATH)


def _load_product_options():
    """本地库里的期货品种（symbols 无 product 列，取代码字母前缀去重）。"""
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
        add_log(f"[sys_spread] 加载品种清单失败: {e}")
        return [DEFAULT_PRODUCT]


_PRODUCT_OPTIONS = _load_product_options()

META = {
    "name": "跨期价差",
    "icon": "🔀",
    "description": "本地库期货跨期价差：视点±N月价格叠线/相邻价差(±2σ通道)/期限结构时间滑块",
    "tags": ["行情交易"],
    "default_size": [32, 24],
    "min_size": [16, 12],
    "max_size": [64, 48],
    "refresh_interval": 0,
    "config_fields": [
        {"key": "product", "label": "品种（本地库）", "type": "select",
         "options": _PRODUCT_OPTIONS, "default": DEFAULT_PRODUCT},
        {"key": "viewpoint", "label": "观测视点（含历史合约）", "type": "dynamic-select",
         "depends_on": "product", "endpoint": "/api/spread_viewpoints", "default": AUTO_VP},
        {"key": "width", "label": "视野宽度(±月)", "type": "select",
         "options": WIDTH_OPTIONS, "default": "3"},
        {"key": "gap", "label": "价差间隔(月)", "type": "select",
         "options": GAP_OPTIONS, "default": "1"},
        {"key": "days", "label": "回溯天数", "type": "select",
         "options": DAYS_OPTIONS, "default": "120"},
        {"key": "custom_start", "label": "起始日(YYYY-MM-DD，空=按回溯天数)", "type": "text",
         "default": ""},
        {"key": "custom_end", "label": "结束日(YYYY-MM-DD，空=至今)", "type": "text",
         "default": ""},
    ],
}

# ---------------------------------------------------------------------------
# 数据查询与计算
# ---------------------------------------------------------------------------
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _month_index(symbol):
    """FG2609 -> 2026*12+9，跨代比较/相邻月判断用。"""
    return (2000 + int(symbol[-4:-2])) * 12 + int(symbol[-2:])


def _expiry_str(symbol):
    """FG2609 -> '2026-09-01'（结构图 x 轴用到期月）。"""
    return f"20{symbol[-4:-2]}-{symbol[-2:]}-01"


def _fetch_contracts(con, product):
    rows = con.execute(
        "SELECT exchange, symbol, COALESCE(name,''), is_active FROM symbols "
        "WHERE asset_class='futures_cn' AND upper(symbol) LIKE ? ORDER BY symbol",
        [product.upper() + "%"]).fetchall()
    out = []
    for ex, sym, name, active in rows:
        if not sym.upper().startswith(product.upper()):
            continue
        suffix = sym[len(product):]
        if not (len(suffix) == 4 and suffix.isdigit()):
            continue  # 排除主连 FG999 等拼接代码
        out.append({"exchange": ex, "symbol": sym, "name": name, "active": bool(active)})
    return out


def _find_main(con, symbols):
    """主力 = 最新交易日持仓量最大（OI 缺失则退成交量）。"""
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
    if rows[0][1] > 0 or rows[0][2] > 0:
        return rows[0][0]
    return None


def _fallback_vp(contracts):
    """主力识别失败时：取到期月 >= 当月的最近活跃合约。"""
    cur = date.today().year * 12 + date.today().month
    actives = sorted((c for c in contracts if c["active"]),
                     key=lambda c: _month_index(c["symbol"]))
    for c in actives:
        if _month_index(c["symbol"]) >= cur:
            return c["symbol"]
    return actives[-1]["symbol"] if actives else (contracts[-1]["symbol"] if contracts else None)


def _fetch_prices(con, symbols, period, start, end):
    """{symbol: [[t, close], ...]}，D/W t=trading_day 字符串；分钟级 t=UTC 秒。"""
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
    """返回 (start, end, note)。None 表示不过滤。自定义优先于回溯天数。"""
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


def _offset_color(offset):
    """按距视点偏移着色：视点琥珀，远月青系，近月绿系，越远越深。"""
    if offset == 0:
        return "#ff9100"
    if offset > 0:
        return f"hsl(195, 85%, {max(42, 60 - 2 * offset)}%)"
    return f"hsl(150, 65%, {max(42, 60 + 2 * offset)}%)"


def _visible_contracts(contracts, vp_symbol, width, extras):
    """视点±width 的合约 + 用户附加合约。返回 (visible列表, 附加集合)。"""
    syms = [c["symbol"] for c in contracts]
    i = syms.index(vp_symbol)
    base = contracts[max(0, i - width): i + width + 1]
    base_syms = {c["symbol"] for c in base}
    extra_set = {e for e in extras if e in syms and e not in base_syms}
    extra_list = [c for c in contracts if c["symbol"] in extra_set]
    return base + extra_list, extra_set


def _rolling_band(pts, win=BAND_WIN):
    """滚动均值±2σ 通道。返回 (mean, up, dn, last_z)；前 win-1 点不足 5 个则跳过。"""
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


def _curve_stats(pts):
    """单日结构注记。pts=[[expiry, price, code], ...] 已按到期月排序。"""
    diffs = [(b[1] - a[1], a[2], b[2]) for a, b in zip(pts, pts[1:])]
    if not diffs:
        return ""
    avg = sum(d for d, _, _ in diffs) / len(diffs)
    mx = max(diffs, key=lambda x: abs(x[0]))
    struct = "升水(contango)" if avg > 0.5 else ("贴水(back)" if avg < -0.5 else "平坦")
    return (f"月差均值 {avg:+.1f}/月 · {struct} · "
            f"最大台阶 {mx[2][-4:]}-{mx[1][-4:]} {mx[0]:+g}")


def _build_series(view, contracts, visible, extra_set, data, vp_symbol, gap=1):
    """按视图构建前端载荷。price/spread -> series；curve -> days（滑块）+ frame（全局参考系）。"""
    vp_mi = _month_index(vp_symbol)
    series, days, frame = [], [], {}
    if view == "price":
        for c in visible:
            pts = data.get(c["symbol"])
            if not pts or len(pts) < 2:
                continue
            off = _month_index(c["symbol"]) - vp_mi
            series.append({
                "label": c["symbol"],
                "color": _offset_color(off),
                "width": 3 if off == 0 else 1,
                "dashed": c["symbol"] in extra_set,
                "points": pts,
            })
    elif view == "spread":
        # 配对规则：到期月差 == gap 个月（gap=1 相邻月，gap=2/3 隔月远月组合）
        vis = {c["symbol"] for c in visible}
        by_mi = {_month_index(c["symbol"]): c for c in contracts}
        for a in contracts:
            if a["symbol"] not in vis:
                continue
            b = by_mi.get(_month_index(a["symbol"]) + gap)
            if not b or b["symbol"] not in vis:
                continue
            pa, pb = data.get(a["symbol"]), data.get(b["symbol"])
            if not pa or not pb:
                continue
            ma = {t: v for t, v in pa}
            pts = [[t, round(v - ma[t], 4)] for t, v in pb if t in ma]
            if len(pts) < 2:
                continue
            off = _month_index(b["symbol"]) - vp_mi
            mean_p, up_p, dn_p, z = _rolling_band(pts)
            series.append({
                "label": f'{b["symbol"]}-{a["symbol"]}',
                "color": _offset_color(off),
                "width": 2 if off in (0, 1) else 1,
                "dashed": a["symbol"] in extra_set or b["symbol"] in extra_set,
                "points": pts,
                "band_mean": mean_p, "band_up": up_p, "band_dn": dn_p,
                "z": z,
            })
    else:  # curve：逐日结构（滑块），只画视野内合约
        maps = {c["symbol"]: dict(data.get(c["symbol"], [])) for c in visible}
        dates = sorted({t for m in maps.values() for t in m})
        all_exps, all_prices = [], []
        for d in dates:
            pts = []
            for c in visible:
                v = maps[c["symbol"]].get(d)
                if v is not None:
                    pts.append([_expiry_str(c["symbol"]), v, c["symbol"]])
            if len(pts) >= 2:
                pts.sort(key=lambda p: p[0])
                days.append({"d": d, "points": pts, "stats": _curve_stats(pts)})
                all_exps.extend(p[0] for p in pts)
                all_prices.extend(p[1] for p in pts)
        if days:
            # 全局参考系：播放时坐标轴锁定不跳变
            gmin, gmax = min(all_prices), max(all_prices)
            pad = max(1.0, (gmax - gmin) * 0.06)
            xmax = (date.fromisoformat(max(all_exps)) + timedelta(days=40)).isoformat()
            frame = {"gmin": round(gmin - pad, 2), "gmax": round(gmax + pad, 2),
                     "xmin": min(all_exps), "xmax": xmax}
    return series, days, frame


# ---------------------------------------------------------------------------
# HTML 构建
# ---------------------------------------------------------------------------
def _error_html(title, detail, extra_btn=""):
    return f"""
<div class="spread-root" style="width:100%;height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;font-family:system-ui,sans-serif;color:var(--color-text);padding:20px;text-align:center;box-sizing:border-box;">
  <div style="font-size:28px;">🔀</div>
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


def _build_html(product, view, period, vp_symbol, vp_is_auto, width,
                contracts, visible, extra_set, series, days, frame, band_on,
                add_options, info_line, note):
    payload = json.dumps({
        "view": view,
        "minute": period not in ("D", "W"),
        "series": series,
        "days": days,
        "frame": frame,
        "bands": band_on and view == "spread",
    }, ensure_ascii=False)

    btns = []
    for v, label in VIEWS:
        btns.append(_btn("switch_view", json.dumps({"view": v}), label, v == view,
                         {"price": "视野内合约收盘价叠线",
                          "spread": "后月-前月 方向性价差（仅相邻月）",
                          "curve": "期限结构时间滑块（基于日线）"}[v]))
    btns.append('<span style="color:var(--color-border);margin:0 2px;">|</span>')
    for p in SPREAD_PERIODS:
        btns.append(_btn("switch_period", json.dumps({"period": p}),
                         PERIOD_LABELS[p], p == period,
                         "结构图始终基于日线" if p != "D" else ""))
    if view == "spread":
        btns.append('<span style="color:var(--color-border);margin:0 2px;">|</span>')
        btns.append(_btn("toggle_band", "{}", f"通道:{'开' if band_on else '关'}", band_on,
                         "20点滚动均值±2σ 历史通道"))
    btns.append('<span style="color:var(--color-border);margin:0 2px;">|</span>')
    # 视野外合约添加：下拉选 + ＋按钮（select change 时由 JS 把值写进按钮 data-payload）
    if add_options:
        opts = "".join(
            f'<option value="{c["symbol"]}">{c["symbol"]}{" ●" if c["active"] else ""}</option>'
            for c in add_options)
        btns.append(
            f'<select id="spaddsel_{{id}}" title="选择要添加的视野外合约（仅列当前区间有数据的）" '
            f'style="background:var(--color-surface);color:var(--color-text);border:1px solid '
            f'var(--color-border);border-radius:4px;font-size:11px;padding:2px 4px;max-width:110px;">'
            f'{opts}</select>'
            f'<button id="spaddbtn_{{id}}" class="btn" data-action="add_extra" data-payload=\'{{}}\' '
            f'title="把选中的合约加入图表（虚线显示）" '
            f'style="background:var(--color-surface);color:var(--color-text);border:1px solid '
            f'var(--color-border);padding:3px 8px;border-radius:4px;cursor:pointer;font-size:11px;">＋添加</button>')
    toolbar = "".join(btns)

    # 图例（curve 视图不用图例，用滑块）
    chips_html = ""
    if view != "curve":
        chips = []
        for i, s in enumerate(series):
            sym = s["label"]
            rm = ""
            if view == "price" and sym in extra_set:
                rm = (f'<button class="btn" data-action="remove_extra" '
                      f'data-payload=\'{json.dumps({"symbol": sym})}\' title="移出图表" '
                      f'style="background:none;border:none;color:#94a3b8;cursor:pointer;'
                      f'font-size:10px;padding:0 2px;">✕</button>')
            anchor = " ★" if view == "price" and sym == vp_symbol else ""
            ztxt = ""
            if view == "spread" and s.get("z") is not None:
                z = s["z"]
                zc = "#ef4444" if abs(z) >= 2 else ("#f59e0b" if abs(z) >= 1 else "#94a3b8")
                ztxt = f' <span style="color:{zc};" title="当前值在20点滚动分布中的位置，|z|≥2 为极端">z{z:+.1f}</span>'
            chips.append(
                f'<span data-idx="{i}" style="color:{s["color"]};cursor:pointer;margin-right:2px;'
                f'white-space:nowrap;" title="点击隐藏/显示">{sym}{anchor}</span>{ztxt}{rm}'
                f'<span style="margin-right:6px;"></span>')
        chips_html = "".join(chips)

    # 结构视图：时间滑块行
    slider_html = ""
    if view == "curve" and days:
        n = len(days)
        prev_d = days[-2]["d"] if n > 1 else "无"
        slider_html = f"""
  <div style="display:flex;align-items:center;gap:8px;padding:2px 0;flex-shrink:0;">
    <button id="spplay_{{id}}" title="播放/暂停：逐日动画" style="background:var(--color-surface);color:var(--color-text);border:1px solid var(--color-border);padding:2px 10px;border-radius:4px;cursor:pointer;font-size:11px;">▶</button>
    <input type="range" id="spslider_{{id}}" min="0" max="{n - 1}" value="{n - 1}" style="flex:1;accent-color:#ff9100;height:14px;" title="拖动选择定格日">
    <span id="spdate_{{id}}" style="font-size:12px;font-weight:700;color:#ff9100;min-width:76px;">{days[-1]['d']}</span>
    <span style="font-size:10px;color:#64748b;">对照(灰·前5日渐隐):</span>
    <span id="spprev_{{id}}" style="font-size:10px;color:#94a3b8;min-width:70px;">{prev_d}</span>
    <button id="spymode_{{id}}" title="Y轴范围：局部=当前曲线放大看形态(播放时缓慢滚动)；全局=锁定全区间便于跨日对比" style="background:var(--color-surface);color:var(--color-text);border:1px solid var(--color-border);padding:2px 8px;border-radius:4px;cursor:pointer;font-size:10px;">Y:局部</button>
  </div>
  <div id="spstats_{{id}}" style="font-size:11px;color:#cbd5e1;padding:1px 0 3px;flex-shrink:0;">{days[-1]['stats']}</div>"""

    note_html = (f'<span style="color:#f59e0b;font-size:10px;"> ⚠ {note}</span>' if note else "")
    view_label = dict(VIEWS)[view]
    vp_tag = f"{vp_symbol}{'(主力)' if vp_is_auto else ''}"
    caption = VIEW_CAPTIONS[view]

    html = f"""
<div class="spread-root" style="width:100%;height:100%;display:flex;flex-direction:column;font-family:system-ui,sans-serif;color:var(--color-text);overflow:hidden;">
  <div style="display:flex;align-items:center;gap:4px;flex-wrap:wrap;padding:2px 0;flex-shrink:0;">{toolbar}</div>
  <div style="display:flex;align-items:center;gap:8px;font-size:10px;color:#94a3b8;padding:2px 0;flex-shrink:0;">
    <span style="color:var(--color-text);font-weight:600;">{product} {view_label}</span>
    <span style="color:#ff9100;font-weight:600;" title="观测视点：{vp_tag}，视野 ±{width} 月">视点 {vp_tag} ±{width}月</span>
    <span style="color:#10b981;" title="本地 DuckDB: {DB_PATH}">✓ 本地库</span>
    <span>{info_line}</span>{note_html}
  </div>{slider_html}
  <div id="spwrap_{{id}}" style="flex:1;position:relative;min-height:0;">
    <div id="sptip_{{id}}" style="position:absolute;top:2px;left:6px;right:6px;z-index:10;font-size:11px;color:#cbd5e1;pointer-events:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">提示：移动准星查看数值 · 点击下方彩色标签可隐藏/显示对应线</div>
    <div id="spchart_{{id}}" class="spread-chart" style="position:absolute;left:0;right:0;top:18px;bottom:13px;"></div>
    <div style="position:absolute;bottom:0;left:6px;right:6px;z-index:10;font-size:10px;color:#64748b;pointer-events:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="{caption}">{caption}</div>
  </div>
  <div id="spchips_{{id}}" style="font-size:10px;line-height:1.7;max-height:44px;overflow-y:auto;padding:2px 0;flex-shrink:0;{'' if chips_html else 'display:none;'}">{chips_html}</div>
</div>
__JS_TEMPLATE__
"""
    return html.replace("__JS_TEMPLATE__", JS_TEMPLATE).replace("__PAYLOAD__", payload)


# ---------------------------------------------------------------------------
# JS 模板（普通字符串，非 f-string：花括号零转义；{id} 留给渲染器替换）
# ---------------------------------------------------------------------------
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
    var h = wrap.offsetHeight - 31;  // 顶部 tooltip 18px + 底部读图注记 13px
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

    var lines = [];    // 主线（图例/十字线 tooltip 只针对它们）
    var bandLines = [];// 通道线（跟随主线显隐，不进 tooltip）

    function addLine(opts) {
      return chart.addSeries(LightweightCharts.LineSeries, Object.assign({
        priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false, pointMarkersVisible: false
      }, opts));
    }

    if (VIEW === 'curve') {
      // ---------- 结构视图：时间滑块 ----------
      // 设计：前5日残影按透明度渐隐（运动尾迹）；播放时 rAF 补间（线流动+变色）
      var days = PAYLOAD.days || [];
      var frame = PAYLOAD.frame || {};
      // 预映射，播放时零计算
      var mapped = days.map(function(dy) {
        return dy.points.map(function(p) { return { time: p[0], value: p[1] }; });
      });
      var GHOST_N = 5;
      var GHOST_A = [0.55, 0.42, 0.30, 0.20, 0.12];
      var ghostLns = [];
      for (var g = 0; g < GHOST_N; g++) {
        ghostLns.push(addLine({ color: 'rgba(148,163,184,' + GHOST_A[g] + ')', lineWidth: 1 }));
      }
      var curLn = addLine({ color: '#ff9100', lineWidth: 3,
                            crosshairMarkerVisible: true, pointMarkersVisible: true });
      lines.push(curLn);
      PAYLOAD.series = [{ label: '当日', color: '#ff9100' }];

      // Y 轴：双模式。local=当前日+残影滚动窗口(形态拉满)；global=全区间锁定(跨日对比)
      var yMode = 'local';
      var yRange = { minValue: frame.gmin, maxValue: frame.gmax };
      function computeLocalRange() {
        var lo = Infinity, hi = -Infinity;
        for (var k = Math.max(0, sel - GHOST_N); k <= sel && k < mapped.length; k++) {
          mapped[k].forEach(function(pt) {
            if (pt.value < lo) lo = pt.value;
            if (pt.value > hi) hi = pt.value;
          });
        }
        if (!isFinite(lo)) { lo = frame.gmin; hi = frame.gmax; }
        var pad = Math.max(2, (hi - lo) * 0.10);
        yRange.minValue = lo - pad;
        yRange.maxValue = hi + pad;
      }
      var dynProvider = function() { return { priceRange: yRange }; };
      curLn.applyOptions({ autoscaleInfoProvider: dynProvider });
      ghostLns.forEach(function(gl) {
        gl.applyOptions({ autoscaleInfoProvider: dynProvider });
      });
      var yModeBtn = document.getElementById('spymode_{id}');
      if (yModeBtn) {
        yModeBtn.addEventListener('click', function() {
          yMode = (yMode === 'local') ? 'global' : 'local';
          if (yMode === 'global') {
            yRange.minValue = frame.gmin; yRange.maxValue = frame.gmax;
          } else {
            computeLocalRange();
          }
          yModeBtn.textContent = 'Y:' + (yMode === 'local' ? '局部' : '全局');
          if (days.length) curLn.setData(mapped[sel]);  // 戳一下触发重算
        });
      }
      // X 轴：每月都标注（t 三种形态都可能：BusinessDay对象 / 'YYYY-MM-DD'字符串 / 数字时间戳）
      chart.timeScale().applyOptions({
        fixLeftEdge: true, fixRightEdge: true,
        tickMarkFormatter: function(t) {
          var m = NaN;
          if (t && typeof t === 'object') { m = t.month; }
          else if (typeof t === 'string') { m = parseInt(t.slice(5, 7), 10); }
          else if (typeof t === 'number') { m = new Date(t * 1000).getUTCMonth() + 1; }
          if (!isFinite(m)) return '';
          return (m < 10 ? '0' : '') + m + '月';
        }
      });

      var slider = document.getElementById('spslider_{id}');
      var dateEl = document.getElementById('spdate_{id}');
      var statsEl = document.getElementById('spstats_{id}');
      var prevEl = document.getElementById('spprev_{id}');
      var playBtn = document.getElementById('spplay_{id}');
      var sel = days.length - 1;
      var timer = null;
      var raf = null;

      function lerpData(from, to, p) {
        var fm = {};
        from.forEach(function(pt) { fm[pt.time] = pt.value; });
        return to.map(function(pt) {
          var fv = fm[pt.time];
          return { time: pt.time,
                   value: fv === undefined ? pt.value : fv + (pt.value - fv) * p };
        });
      }
      function lerpColor(p) {  // 石板灰 -> 琥珀
        var c1 = [100, 116, 139], c2 = [255, 145, 0];
        return 'rgb(' + Math.round(c1[0] + (c2[0] - c1[0]) * p) + ','
                      + Math.round(c1[1] + (c2[1] - c1[1]) * p) + ','
                      + Math.round(c1[2] + (c2[2] - c1[2]) * p) + ')';
      }
      function applyTexts() {
        var day = days[sel];
        if (slider) slider.value = sel;
        if (dateEl) dateEl.textContent = day.d;
        if (statsEl) statsEl.textContent = day.stats;
        if (prevEl) prevEl.textContent = sel > 0 ? days[sel - 1].d + ' 及更早' : '无';
      }
      function applyGhosts() {
        for (var g = 0; g < GHOST_N; g++) {
          ghostLns[g].setData(sel - 1 - g >= 0 ? mapped[sel - 1 - g] : []);
        }
      }
      function renderDay(i, animate) {
        var next = Math.max(0, Math.min(days.length - 1, i));
        if (raf) { cancelAnimationFrame(raf); raf = null; }
        if (!animate || next === sel) {
          sel = next;
          if (yMode === 'local') computeLocalRange();
          curLn.setData(mapped[sel]);
          curLn.applyOptions({ color: '#ff9100' });
          applyTexts();
          applyGhosts();
          return;
        }
        var from = mapped[sel], to = mapped[next];
        sel = next;
        if (yMode === 'local') computeLocalRange();
        applyTexts();      // 文字与残影立即就位，主线做补间
        applyGhosts();
        var t0 = performance.now(), DUR = 240;
        var step = function(now) {
          var p = Math.min(1, (now - t0) / DUR);
          var e = p * (2 - p);  // easeOut
          curLn.setData(lerpData(from, to, e));
          curLn.applyOptions({ color: lerpColor(e) });
          if (p < 1) {
            raf = requestAnimationFrame(step);
          } else {
            raf = null;
            curLn.setData(to);
            curLn.applyOptions({ color: '#ff9100' });
          }
        };
        raf = requestAnimationFrame(step);
      }
      if (slider) {
        slider.addEventListener('input', function() {
          if (timer) { clearInterval(timer); timer = null; if (playBtn) playBtn.textContent = '▶'; }
          renderDay(parseInt(slider.value, 10), false);  // 手动拖动即时响应，不做补间
        });
      }
      if (playBtn) {
        playBtn.addEventListener('click', function() {
          if (timer) { clearInterval(timer); timer = null; playBtn.textContent = '▶'; return; }
          if (sel >= days.length - 1) renderDay(0, false);  // 在末尾则从头播
          playBtn.textContent = '⏸';
          timer = setInterval(function() {
            if (sel >= days.length - 1) {
              clearInterval(timer); timer = null; playBtn.textContent = '▶'; return;
            }
            renderDay(sel + 1, true);   // 240ms 补间 + 260ms 停留
          }, 500);
        });
      }
      if (days.length) {
        renderDay(days.length - 1, false);
        // 数据就位后再锁定完整到期月域（先于 setData 调用会被初始自适应冲掉）
        if (frame.xmin) {
          chart.timeScale().setVisibleRange({ from: frame.xmin, to: frame.xmax });
        }
      }
    } else {
      // ---------- 价格 / 价差视图 ----------
      PAYLOAD.series.forEach(function(s, i) {
        var ln = addLine({
          color: s.color,
          lineWidth: s.width || 1,
          lineStyle: s.dashed ? LightweightCharts.LineStyle.Dashed : LightweightCharts.LineStyle.Solid,
          crosshairMarkerVisible: true
        });
        ln.setData(s.points.map(function(p) { return { time: p[0], value: p[1] }; }));
        if (VIEW === 'spread' && i === 0) {
          ln.createPriceLine({ price: 0, color: '#94a3b8', lineWidth: 1,
                               lineStyle: LightweightCharts.LineStyle.Dashed,
                               axisLabelVisible: true, title: '' });
        }
        lines.push(ln);
        // 滚动 ±2σ 通道
        if (VIEW === 'spread' && PAYLOAD.bands && s.band_up) {
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
    }

    // 添加合约：select 变化时把当前值写进 ＋ 按钮的 data-payload（引擎点击时读取）
    var addSel = document.getElementById('spaddsel_{id}');
    var addBtn = document.getElementById('spaddbtn_{id}');
    if (addSel && addBtn) {
      var syncPayload = function() {
        addBtn.setAttribute('data-payload', JSON.stringify({ symbol: addSel.value }));
      };
      addSel.addEventListener('change', syncPayload);
      syncPayload();
    }

    // 图例开关（纯客户端；价差视图同时切换对应通道）
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

    // 十字线 tooltip：该时刻主线的数值
    var tip = document.getElementById('sptip_{id}');
    chart.subscribeCrosshairMove(function(param) {
      if (!tip) return;
      var t = param && param.time;
      if (!t) {
        tip.textContent = '提示：移动准星查看数值 · 点击下方彩色标签可隐藏/显示对应线';
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

    if (VIEW !== 'curve') {
      chart.timeScale().fitContent();  // curve 用锁定的全局 X 域，不能 fit
    }

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
def _render_with(config, state, view, period):
    product = (config.get("product") or DEFAULT_PRODUCT).strip()
    width = int(config.get("width") or 3)
    gap = int(config.get("gap") or 1)
    days_cfg = int(config.get("days") or 120)
    extras = [e for e in state.get("extras", []) if isinstance(e, str)]
    band_on = bool(state.get("band_on", True))

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

        # 观测视点：配置指定 or 自动主力（含历史合约，支持回看过去的视点）
        all_syms = [c["symbol"] for c in contracts]
        vp_cfg = (config.get("viewpoint") or AUTO_VP).strip()
        vp_is_auto = vp_cfg == AUTO_VP
        if vp_is_auto or vp_cfg not in all_syms:
            vp_symbol = _find_main(con, [c["symbol"] for c in contracts if c["active"]]) \
                        or _fallback_vp(contracts)
            if not vp_is_auto:
                note = f"视点 {vp_cfg} 不在本地库已回退自动主力"
                vp_is_auto = True
        else:
            vp_symbol = vp_cfg

        # 区间：自定义起止日 > 回溯天数；历史视点未指定区间时锚定其最后交易日
        custom = (config.get("custom_start", "") or "").strip() or \
                 (config.get("custom_end", "") or "").strip()
        start, end, range_note = _resolve_range(days_cfg, config.get("custom_start", ""),
                                                config.get("custom_end", ""))
        if range_note:
            note = (note + "；" if note else "") + range_note
        if not vp_is_auto and not custom:
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

        visible, extra_set = _visible_contracts(contracts, vp_symbol, width, extras)

        # 结构图始终用日线；其余视图用当前周期。
        # 数据按"全部合约"查询：既驱动图表，也用于筛出"当前区间有数据"的可添加候选
        query_period = "D" if view == "curve" else period
        data = _fetch_prices(con, all_syms, query_period, start, end)
        con.close()
    except Exception as e:
        try:
            con.close()
        except Exception:
            pass
        return _error_html("查询失败", str(e))

    series, days, frame = _build_series(view, contracts, visible, extra_set, data, vp_symbol, gap)
    if not series and not days:
        return _error_html(
            f"{product} 在该区间没有可用数据",
            f"视点={vp_symbol} ±{width}月 视图={dict(VIEWS)[view]} "
            f"周期={PERIOD_LABELS.get(query_period, query_period)} "
            f"区间={start or '最早'}~{end or '至今'}。分钟级数据只有近月合约有（约 5 千根），"
            "试试切换到日线或加大回溯天数",
            _back_to_d_btn(query_period))

    # 可添加候选 = 不在视野内 且 当前区间有数据
    visible_syms = {c["symbol"] for c in visible}
    add_options = [c for c in contracts
                   if c["symbol"] not in visible_syms and len(data.get(c["symbol"], [])) >= 2]
    add_options.sort(key=lambda c: (not c["active"], c["symbol"]))  # 活跃优先

    if view == "curve":
        info_line = f"{len(days)}个交易日可拖动 · {PERIOD_LABELS['D']} · {start or '最早'} ~ {end or '至今'}"
        add_log(f"[sys_spread] {product} curve D 视点{vp_symbol}±{width}: {len(days)}天")
    else:
        n_pts = sum(len(s["points"]) for s in series)
        series_unit = "条线" if view == "price" else "对价差"
        gap_note = f" · 间隔{gap}月" if view == "spread" and gap > 1 else ""
        info_line = (f"{len(series)}{series_unit} · {n_pts}点 · "
                     f"{PERIOD_LABELS.get(query_period, query_period)}{gap_note} · {start or '最早'} ~ {end or '至今'}")
        add_log(f"[sys_spread] {product} {view} {query_period} 视点{vp_symbol}±{width}: "
                f"{len(series)}{series_unit} {n_pts}点")
    return _build_html(product, view, period, vp_symbol, vp_is_auto, width,
                       contracts, visible, extra_set, series, days, frame, band_on,
                       add_options, info_line, note)


def render(config: dict, state: dict) -> dict:
    view = state.get("last_view", "price")
    period = state.get("last_period", "D")
    state.update({
        "last_view": view,
        "last_period": period,
        "extras": state.get("extras", []),
        "band_on": state.get("band_on", True),
    })
    return {"html": _render_with(config, state, view, period), "state": state}


def on_action(action: str, payload: dict, config: dict, state: dict) -> dict:
    if action == "switch_view":
        state["last_view"] = payload.get("view", "price")
    elif action == "switch_period":
        state["last_period"] = payload.get("period", "D")
    elif action == "toggle_band":
        state["band_on"] = not state.get("band_on", True)
    elif action == "add_extra":
        sym = (payload.get("symbol") or "").strip()
        extras = state.setdefault("extras", [])
        if sym and sym not in extras:
            extras.append(sym)
    elif action == "remove_extra":
        sym = (payload.get("symbol") or "").strip()
        state["extras"] = [e for e in state.get("extras", []) if e != sym]
    elif action == "reload":
        pass
    else:
        return {"state": state}
    return render(config, state)
