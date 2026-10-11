"""
sys_stoploss.py — ATR 波动率指标面板
以 ATR (Average True Range) 为核心，展示当前合约的波动率水平、TR 分解明细，
以及基于 ATR 的多梯度止损位移建议。

数据源: 本地 DuckDB (quant_data_hub)，与 sys_spread 保持一致。
"""

import os
import re
import json
import calendar
from datetime import date, timedelta
from typing import Optional, Dict, Any, List, Tuple
from log_store import add_log

# ================================================================== #
#  数据源: 本地 DuckDB
# ================================================================== #
DB_PATH = os.environ.get("QUANT_DB_PATH") or os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "quant_data_hub", "data", "quant.duckdb"))

DEFAULT_PRODUCT = "RB"
AUTO_CONTRACT = "自动主力"

PERIOD_LABELS = {"D": "日线", "1h": "1小时", "15m": "15分钟"}
PERIOD_OPTIONS = list(PERIOD_LABELS.keys())

ATR_N_OPTIONS = ["7", "14", "20"]
TR_ROWS_OPTIONS = ["5", "10", "14", "20"]


def _db_available():
    return os.path.exists(DB_PATH)


def _load_product_options():
    """从 DuckDB symbols 表读取所有期货品种代码（与 sys_spread 同逻辑）。"""
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
        add_log(f"[ATR面板] 加载品种清单失败: {e}")
        return [DEFAULT_PRODUCT]


_PRODUCT_OPTIONS = _load_product_options()

# ================================================================== #
#  META
# ================================================================== #
META = {
    "name": "ATR波动率",
    "icon": "🛡️",
    "description": "ATR波动率指标面板：当前ATR值、TR分解明细、多梯度止损位移建议",
    "tags": ["行情交易"],
    "default_size": [28, 30],
    "min_size": [22, 20],
    "max_size": [48, 60],
    "refresh_interval": 0,
    "config_fields": [
        {"key": "product", "label": "品种（本地库）", "type": "select",
         "options": _PRODUCT_OPTIONS, "default": DEFAULT_PRODUCT},
        {"key": "contract", "label": "合约", "type": "dynamic-select",
         "depends_on": "product", "endpoint": "/api/spread_viewpoints",
         "default": AUTO_CONTRACT},
        {"key": "period", "label": "K线周期", "type": "select",
         "options": PERIOD_OPTIONS, "default": "D"},
        {"key": "atr_n", "label": "ATR 周期(N)", "type": "select",
         "options": ATR_N_OPTIONS, "default": "14"},
        {"key": "tr_rows", "label": "TR 明细行数", "type": "select",
         "options": TR_ROWS_OPTIONS, "default": "10"},
    ]
}

# ================================================================== #
#  缓存
# ================================================================== #
_CACHE: Dict[str, Any] = {}
CACHE_TTL = 60

# ================================================================== #
#  品种中文名映射
# ================================================================== #
FUTURES_NAME_MAP = {
    "RB": "螺纹钢", "HC": "热轧卷板", "WR": "线材", "SS": "不锈钢",
    "AU": "沪金", "AG": "沪银", "CU": "沪铜", "AL": "沪铝",
    "ZN": "沪锌", "PB": "沪铅", "NI": "沪镍", "SN": "沪锡",
    "BC": "国际铜", "AO": "氧化铝",
    "FU": "燃料油", "BU": "沥青", "RU": "橡胶", "SP": "纸浆", "NR": "20号胶",
    "SC": "原油", "LU": "低硫燃油", "EC": "集运指数",
    "I": "铁矿石", "JM": "焦煤", "J": "焦炭",
    "A": "豆一", "B": "豆二", "M": "豆粕", "Y": "豆油",
    "C": "玉米", "CS": "淀粉", "L": "塑料", "V": "PVC", "PP": "聚丙烯",
    "EB": "苯乙烯", "EG": "乙二醇", "PG": "液化气",
    "JD": "鸡蛋", "LH": "生猪", "P": "棕榈油",
    "TA": "PTA", "MA": "甲醇", "SR": "白糖", "CF": "棉花", "CY": "棉纱",
    "FG": "玻璃", "SA": "纯碱", "SH": "烧碱", "UR": "尿素",
    "AP": "苹果", "CJ": "红枣", "PK": "花生",
    "RM": "菜粕", "OI": "菜油", "RS": "菜籽",
    "SF": "硅铁", "SM": "锰硅",
    "PX": "对二甲苯", "PF": "短纤", "PR": "瓶片",
    "SI": "工业硅", "LC": "碳酸锂",
    "IF": "沪深300", "IH": "上证50", "IC": "中证500", "IM": "中证1000",
    "TS": "两年国债", "TF": "五年国债", "T": "十年国债", "TL": "三十年国债",
}


def _product_cn(product: str) -> str:
    return FUTURES_NAME_MAP.get(product.upper(), product)


# ================================================================== #
#  数据查询
# ================================================================== #
def _resolve_contract(product: str, contract: str) -> Optional[str]:
    """如果是 '自动主力'，从 DuckDB 找持仓量最大的合约。"""
    if contract != AUTO_CONTRACT:
        return contract
    if not _db_available():
        return None
    try:
        import duckdb
        con = duckdb.connect(DB_PATH, read_only=True)
        rows = con.execute(
            "SELECT s.symbol, COALESCE(b.open_interest,0) oi, COALESCE(b.volume,0) vol "
            "FROM bars b JOIN symbols s USING(symbol_id) "
            "WHERE s.asset_class='futures_cn' AND upper(s.symbol) LIKE ? "
            "AND b.period='D' AND b.trading_day = "
            "(SELECT MAX(b2.trading_day) FROM bars b2 JOIN symbols s2 USING(symbol_id) "
            "WHERE s2.asset_class='futures_cn' AND upper(s2.symbol) LIKE ? AND b2.period='D')",
            [product.upper() + "%", product.upper() + "%"]
        ).fetchall()
        con.close()
        # 过滤合法合约（4 位数字后缀）
        valid = []
        n = len(product)
        for sym, oi, vol in rows:
            suffix = sym[n:]
            if len(suffix) == 4 and suffix.isdigit():
                valid.append((sym, oi, vol))
        if not valid:
            return None
        valid.sort(key=lambda r: (r[1], r[2]), reverse=True)
        return valid[0][0]
    except Exception as e:
        add_log(f"[ATR面板] 自动主力解析失败: {e}")
        return None


import time as _time


def _fetch_ohlc(symbol: str, period: str, limit: int = 100) -> Tuple[Optional[List[dict]], Optional[str]]:
    """从 DuckDB bars 表获取 OHLC 数据，返回 (bars_list, error_msg)。"""
    cache_key = f"ohlc_{symbol}_{period}_{limit}"
    now = _time.time()
    if cache_key in _CACHE:
        ct, data, err = _CACHE[cache_key]
        if now - ct < CACHE_TTL:
            return data, err

    if not _db_available():
        return None, "DuckDB 文件不存在"
    try:
        import duckdb
        con = duckdb.connect(DB_PATH, read_only=True)

        # 映射周期标识
        db_period = period
        if period == "15m":
            db_period = "15m"
        elif period == "1h":
            db_period = "1h"
        # D 保持不变

        is_day = period == "D"
        rows = con.execute(
            "SELECT b.ts, b.trading_day, b.open, b.high, b.low, b.close, b.volume "
            "FROM bars b JOIN symbols s USING(symbol_id) "
            "WHERE s.symbol = ? AND b.period = ? "
            "ORDER BY b.ts DESC LIMIT ?",
            [symbol, db_period, limit]
        ).fetchall()
        con.close()

        if not rows:
            _CACHE[cache_key] = (now, None, "无数据")
            return None, f"未找到 {symbol} 的 {period} 数据"

        bars = []
        for ts, td, o, h, l, c, v in reversed(rows):
            if is_day:
                t = str(td) if td else str(ts.date())
            else:
                t = calendar.timegm(ts.timetuple()) - 8 * 3600
                
            bars.append({
                "time": t,
                "date": str(td) if td else "",
                "open": float(o) if o else 0,
                "high": float(h) if h else 0,
                "low": float(l) if l else 0,
                "close": float(c) if c else 0,
                "volume": int(v) if v else 0,
            })
        _CACHE[cache_key] = (now, bars, None)
        return bars, None

    except Exception as e:
        err_str = str(e)
        add_log(f"[ATR面板] OHLC查询失败({symbol} {period}): {err_str}")
        if cache_key in _CACHE:
            return _CACHE[cache_key][1], err_str
        return None, err_str


# ================================================================== #
#  ATR 核心计算
# ================================================================== #
def _calc_atr_detail(bars: List[dict], n: int = 14, tr_rows: int = 10) -> Optional[dict]:
    """
    计算 ATR 及 TR 分解明细。
    返回: {
        "atr": float,
        "current_price": float,
        "atr_pct": float,          # ATR / 当前价 × 100
        "tr_table": [              # 最近 tr_rows 根 K 线的 TR 分解
            {"date": ..., "hl": ..., "h_pc": ..., "l_pc": ..., "tr": ...}, ...
        ],
        "all_trs": [float, ...],   # 全部 TR 值（用于统计）
    }
    """
    if not bars or len(bars) < n + 1:
        return None

    trs = []
    details = []
    for i in range(1, len(bars)):
        h = bars[i]["high"]
        l = bars[i]["low"]
        pc = bars[i - 1]["close"]
        hl = round(h - l, 2)
        h_pc = round(abs(h - pc), 2)
        l_pc = round(abs(l - pc), 2)
        tr = round(max(hl, h_pc, l_pc), 2)
        trs.append(tr)
        details.append({
            "date": bars[i]["date"],
            "high": h,
            "low": l,
            "prev_close": pc,
            "hl": hl,
            "h_pc": h_pc,
            "l_pc": l_pc,
            "tr": tr,
        })

    if len(trs) < n:
        return None

    atr = round(sum(trs[-n:]) / n, 2)
    current_price = bars[-1]["close"]
    atr_pct = round(atr / current_price * 100, 2) if current_price > 0 else 0

    return {
        "atr": atr,
        "current_price": current_price,
        "atr_pct": atr_pct,
        "tr_table": details[-tr_rows:],
        "all_trs": trs,
        "n": n,
    }


# ================================================================== #
#  render
# ================================================================== #
def render(config: dict, state: dict) -> dict:
    product = config.get("product", DEFAULT_PRODUCT)
    contract_cfg = config.get("contract", AUTO_CONTRACT)
    period = config.get("period", "D")
    atr_n = int(config.get("atr_n", "14"))
    tr_rows = int(config.get("tr_rows", "10"))

    # 解析合约
    symbol = _resolve_contract(product, contract_cfg)
    if not symbol:
        return _render_error("无法识别合约", f"品种 {product}，请检查本地 DuckDB 数据", state)

    # 获取 OHLC
    needed = max(atr_n + 1, tr_rows + 1) + 10  # 多取一些余量
    bars, data_err = _fetch_ohlc(symbol, period, limit=needed)
    if not bars:
        return _render_error("无K线数据", data_err or f"{symbol} / {period} 无数据", state)

    # 计算 ATR
    result = _calc_atr_detail(bars, n=atr_n, tr_rows=tr_rows)
    if not result:
        return _render_error("数据不足", f"需要至少 {atr_n + 1} 根 K 线，当前仅 {len(bars)} 根", state)

    cn_name = _product_cn(product)
    period_label = PERIOD_LABELS.get(period, period)

    # ---- 构建 HTML ----
    atr = result["atr"]
    price = result["current_price"]
    atr_pct = result["atr_pct"]
    n = result["n"]

    # 数据源徽章
    src_html = (
        f'<span style="{_badge_s()}background:var(--color-warning-light);color:var(--color-warning);"'
        f' title="{data_err}">⚠ {data_err[:20]}</span>'
        if data_err else
        f'<span style="{_badge_s()}background:var(--color-success-light);color:var(--color-success);">✓ 本地数据</span>'
    )

    # ---- 波动率判定 ----
    if atr_pct >= 3.0:
        vol_level = "高波动"
        vol_color = "var(--color-danger)"
        vol_bg = "var(--color-danger-light)"
    elif atr_pct >= 1.5:
        vol_level = "中波动"
        vol_color = "var(--color-warning)"
        vol_bg = "var(--color-warning-light)"
    else:
        vol_level = "低波动"
        vol_color = "var(--color-success)"
        vol_bg = "var(--color-success-light)"

    # ---- 固定头部区 ----
    header_html = f'''
    <div style="padding:12px 14px;display:flex;flex-direction:column;gap:10px;
                border-bottom:1px solid var(--color-border);flex-shrink:0;background:var(--color-surface);">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <span style="font-weight:800;font-size:var(--font-size-lg);color:var(--color-primary);">
                🛡️ {cn_name} <span style="font-size:var(--font-size-xs);color:var(--color-text-tertiary);font-weight:normal;">({symbol})</span>
            </span>
            <div style="display:flex;gap:8px;align-items:center;">
                <span style="{_badge_s()}background:var(--color-surface-elevated);color:var(--color-text-secondary);">
                    {period_label}
                </span>
                <button data-action="refresh" title="刷新数据" style="cursor:pointer;background:none;border:none;font-size:16px;padding:2px;color:var(--color-text-secondary);">
                    🔄
                </button>
            </div>
        </div>
        <div style="display:flex;gap:12px;align-items:center;font-size:var(--font-size-sm);flex-wrap:wrap;">
            <span style="color:var(--color-text-secondary);">当前价: <b style="color:var(--color-text-primary);font-family:var(--font-mono);font-size:15px;">{price:,.2f}</b></span>
            <span style="color:var(--color-text-secondary);">当前ATR({n}): <b style="color:var(--color-text-primary);font-family:var(--font-mono);font-size:15px;">{atr}</b></span>
            <span style="{_badge_s()}background:{vol_bg};color:{vol_color};border:1px solid {vol_color};padding:2px 8px;font-size:11px;">
                {vol_level} ({atr_pct}%)
            </span>
            <div style="margin-left:auto;">{src_html}</div>
        </div>
    </div>
    '''

    # ---- 止损建议表 ----
    tiers = [
        ("保守", 1.0, "正常行情，适合短线或窄止损策略"),
        ("标准", 1.5, "最常用的止损倍数，兼顾安全与空间"),
        ("宽松", 2.0, "给趋势行情更多呼吸空间"),
        ("吊灯", 3.0, "Chandelier Exit，适合持仓盈利后锁定利润"),
    ]
    recommend_idx = 1  # 标准

    tier_rows = ""
    for i, (label, mult, desc) in enumerate(tiers):
        pts = round(atr * mult, 2)
        pct = round(pts / price * 100, 2) if price > 0 else 0
        upper = round(price + pts, 2)
        lower = round(price - pts, 2)
        is_rec = (i == recommend_idx)
        
        # 初始默认高亮在 JS 中处理
        rec_badge = (
            '<span style="margin-left:6px;font-size:10px;padding:1px 6px;'
            'border-radius:var(--radius-full);background:var(--color-primary);'
            'color:#fff;font-weight:700;">推荐</span>'
            if is_rec else ""
        )
        tier_rows += f"""
        <tr class="sl-tier-row_{{id}}" data-upper="{upper}" data-lower="{lower}" style="cursor:pointer;transition:background 0.2s;" onmouseover="if(this.style.background!=='var(--color-primary-light)')this.style.background='var(--color-surface-elevated)'" onmouseout="if(this.style.background!=='var(--color-primary-light)')this.style.background=''">
            <td style="padding:8px 10px;border-bottom:1px solid var(--color-border-light); font-size:var(--font-size-sm);font-weight:600;white-space:nowrap;">
                {label}{rec_badge}
            </td>
            <td style="padding:8px 6px;border-bottom:1px solid var(--color-border-light); font-size:var(--font-size-xs);text-align:center;font-family:var(--font-mono); color:var(--color-text-tertiary);">{mult}×</td>
            <td style="padding:8px 10px;border-bottom:1px solid var(--color-border-light); font-size:var(--font-size-sm);text-align:right;font-family:var(--font-mono); font-weight:700;color:var(--color-text-primary);">{pts}</td>
            <td style="padding:8px 10px;border-bottom:1px solid var(--color-border-light); font-size:var(--font-size-sm);text-align:right;font-family:var(--font-mono); font-weight:700;color:var(--color-danger);">{upper}</td>
            <td style="padding:8px 10px;border-bottom:1px solid var(--color-border-light); font-size:var(--font-size-sm);text-align:right;font-family:var(--font-mono); font-weight:700;color:var(--color-success);">{lower}</td>
        </tr>
        """

    stoploss_section = f'''
    <div style="margin-bottom: 16px;">
        <div style="font-size:var(--font-size-xs);font-weight:700;color:var(--color-text-secondary);margin-bottom:8px;display:flex;align-items:center;gap:6px;">
            <span style="display:inline-block;width:3px;height:12px;background:var(--color-primary);border-radius:2px;"></span>
            科学止损点位参考 (基于当前价 {price:,.2f}) — <span style="color:var(--color-text-tertiary);font-weight:normal;">点击策略在图表中高亮</span>
        </div>
        <div style="border-radius:var(--radius-md);background:var(--color-surface);
                    border:1px solid var(--color-border);overflow-x:auto;">
            <table style="width:100%;border-collapse:collapse;">
                <thead>
                    <tr style="background:var(--color-surface-elevated);">
                        <th style="padding:6px 10px;font-size:var(--font-size-xs);text-align:left;font-weight:600;
                                   color:var(--color-text-tertiary);border-bottom:1px solid var(--color-border);">策略</th>
                        <th style="padding:6px;font-size:var(--font-size-xs);text-align:center;font-weight:600;
                                   color:var(--color-text-tertiary);border-bottom:1px solid var(--color-border);">乘数</th>
                        <th style="padding:6px 10px;font-size:var(--font-size-xs);text-align:right;font-weight:600;
                                   color:var(--color-text-tertiary);border-bottom:1px solid var(--color-border);">空间</th>
                        <th style="padding:6px 10px;font-size:var(--font-size-xs);text-align:right;font-weight:600;
                                   color:var(--color-danger);border-bottom:1px solid var(--color-border);">上边界(做空止损)</th>
                        <th style="padding:6px 10px;font-size:var(--font-size-xs);text-align:right;font-weight:600;
                                   color:var(--color-success);border-bottom:1px solid var(--color-border);">下边界(做多止损)</th>
                    </tr>
                </thead>
                <tbody>
                    {tier_rows}
                </tbody>
            </table>
        </div>
        <div id="chart_{{id}}" style="height:250px;width:100%;margin-top:10px;border-radius:var(--radius-md);border:1px solid var(--color-border);background:var(--color-surface);overflow:hidden;"></div>
    </div>
    '''

    # ---- TR 分解明细表 (折叠面板) ----
    tr_table = result["tr_table"]
    rows_html = ""
    for d in tr_table:
        is_hl = d["tr"] == d["hl"]
        is_hpc = d["tr"] == d["h_pc"]
        is_lpc = d["tr"] == d["l_pc"]
        hl_style = "font-weight:700;color:var(--color-primary);" if is_hl else ""
        hpc_style = "font-weight:700;color:var(--color-primary);" if is_hpc else ""
        lpc_style = "font-weight:700;color:var(--color-primary);" if is_lpc else ""

        date_short = d["date"][-5:] if len(d["date"]) >= 5 else d["date"]
        rows_html += f'''
        <tr>
            <td style="padding:4px 6px;border-bottom:1px solid var(--color-border-light);
                       font-size:var(--font-size-xs);color:var(--color-text-secondary);">{date_short}</td>
            <td style="padding:4px 6px;border-bottom:1px solid var(--color-border-light);
                       font-size:var(--font-size-xs);text-align:right;font-family:var(--font-mono);{hl_style}">{d["hl"]}</td>
            <td style="padding:4px 6px;border-bottom:1px solid var(--color-border-light);
                       font-size:var(--font-size-xs);text-align:right;font-family:var(--font-mono);{hpc_style}">{d["h_pc"]}</td>
            <td style="padding:4px 6px;border-bottom:1px solid var(--color-border-light);
                       font-size:var(--font-size-xs);text-align:right;font-family:var(--font-mono);{lpc_style}">{d["l_pc"]}</td>
            <td style="padding:4px 6px;border-bottom:1px solid var(--color-border-light);
                       font-size:var(--font-size-xs);text-align:right;font-family:var(--font-mono);
                       font-weight:700;color:var(--color-warning);">{d["tr"]}</td>
        </tr>
        '''

    details_section = f'''
    <details style="border:1px solid var(--color-border);border-radius:var(--radius-md);background:var(--color-surface);overflow:hidden;">
        <summary style="padding:10px 14px;cursor:pointer;background:var(--color-surface-elevated);
                        font-size:var(--font-size-sm);font-weight:600;outline:none;user-select:none;
                        color:var(--color-text-primary);">
            📊 展开查看 ATR 计算逻辑与明细
        </summary>
        
        <div style="padding:12px;border-top:1px solid var(--color-border);">
            <div style="font-size:var(--font-size-xs);color:var(--color-text-secondary);line-height:1.6;margin-bottom:12px;padding:8px;background:var(--color-surface-elevated);border-radius:var(--radius-sm);">
                <b>为什么是 ATR({n}) 且只展示 {len(tr_table)} 根明细？</b><br>
                1. <b>TR (True Range)</b>：衡量单根 K 线的极值波动，考虑了可能发生的跳空。<br>
                   <span style="font-family:var(--font-mono);color:var(--color-text-tertiary);margin-left:14px;">计算公式: Max( 高−低 , |高−昨收| , |低−昨收| )</span><br>
                2. <b>ATR({n})</b>：代表将过去连续 {n} 根 K 线的 TR 值相加并取算术平均。<br>
                3. 为了保持面板紧凑，下方的“TR 取值追溯表”仅节选了最近 <b>{len(tr_table)}</b> 根 K 线的明细计算过程，而实际的均值计算严格使用了 {n} 周期。<br>
            </div>
            <div style="font-size:var(--font-size-xs);font-weight:600;color:var(--color-text-tertiary);margin-bottom:6px;">
                TR 取值明细节选（最近 {len(tr_table)} 根 K 线）
            </div>
            <div style="overflow-x:auto;">
                <table style="width:100%;border-collapse:collapse;">
                    <thead>
                        <tr style="background:var(--color-surface-elevated);">
                            <th style="padding:6px;font-size:var(--font-size-xs);text-align:left;font-weight:600;
                                       color:var(--color-text-tertiary);border-bottom:1px solid var(--color-border);">日期</th>
                            <th style="padding:6px;font-size:var(--font-size-xs);text-align:right;font-weight:600;
                                       color:var(--color-text-tertiary);border-bottom:1px solid var(--color-border);">H−L</th>
                            <th style="padding:6px;font-size:var(--font-size-xs);text-align:right;font-weight:600;
                                       color:var(--color-text-tertiary);border-bottom:1px solid var(--color-border);">|H−PC|</th>
                            <th style="padding:6px;font-size:var(--font-size-xs);text-align:right;font-weight:600;
                                       color:var(--color-text-tertiary);border-bottom:1px solid var(--color-border);">|L−PC|</th>
                            <th style="padding:6px;font-size:var(--font-size-xs);text-align:right;font-weight:600;
                                       color:var(--color-warning);border-bottom:1px solid var(--color-border);">TR</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html}
                    </tbody>
                </table>
            </div>
        </div>
    </details>
    '''

    import json
    bars_json = json.dumps(bars, ensure_ascii=False)

    js_script = f'''
    <script>
    (function() {{
        var LW_SRC = '/static/js/lightweight-charts.standalone.production.js';
        function ensureLW(cb) {{
            if (window.LightweightCharts) {{ cb(); return; }}
            window.__lwCbs = window.__lwCbs || [];
            window.__lwCbs.push(cb);
            if (window.__lwLoading) return;
            window.__lwLoading = true;
            var s = document.createElement('script');
            s.src = LW_SRC;
            s.onload = function() {{
                window.__lwLoading = false;
                window.__lwCbs.forEach(function(fn) {{ fn(); }});
                window.__lwCbs = [];
            }};
            document.head.appendChild(s);
        }}

        function initChart() {{
            var chartContainer = document.getElementById('chart_{{id}}');
            if (!chartContainer) return;
            var w = chartContainer.offsetWidth;
            var h = chartContainer.offsetHeight;
            if (w < 10) {{ setTimeout(initChart, 50); return; }}
            
            var isDark = document.documentElement.dataset.theme === 'dark';
            var chart = LightweightCharts.createChart(chartContainer, {{
                width: w, height: h,
                layout: {{ background: {{ type: 'solid', color: 'transparent' }}, textColor: isDark ? '#d1d5db' : '#374151' }},
                grid: {{ vertLines: {{ color: isDark ? '#374151' : '#e5e7eb' }}, horzLines: {{ color: isDark ? '#374151' : '#e5e7eb' }} }},
                timeScale: {{ timeVisible: true, rightOffset: 5 }},
                crosshair: {{ mode: 1 }}
            }});
            
            var candleSeries = chart.addSeries(LightweightCharts.CandlestickSeries, {{
                upColor: '#ef4444', downColor: '#22c55e', borderVisible: false, wickUpColor: '#ef4444', wickDownColor: '#22c55e'
            }});
            
            var upperLine = chart.addSeries(LightweightCharts.LineSeries, {{
                color: '#ef4444', lineWidth: 2, lineStyle: 2, crosshairMarkerVisible: false, lastValueVisible: true, priceLineVisible: false
            }});
            
            var lowerLine = chart.addSeries(LightweightCharts.LineSeries, {{
                color: '#22c55e', lineWidth: 2, lineStyle: 2, crosshairMarkerVisible: false, lastValueVisible: true, priceLineVisible: false
            }});
            
            var barsData = {bars_json};
            barsData.sort(function(a, b) {{ return (a.time > b.time) ? 1 : -1; }});
            candleSeries.setData(barsData);
            
            if (barsData.length > 0) {{
                var firstTime = barsData[0].time;
                var lastTime = barsData[barsData.length - 1].time;
                
                var rows = document.querySelectorAll('.sl-tier-row_{{id}}');
                rows.forEach(function(row) {{
                    row.addEventListener('click', function() {{
                        rows.forEach(function(r) {{ r.style.background = ''; }});
                        row.style.background = 'var(--color-primary-light)';
                        
                        var upper = parseFloat(row.getAttribute('data-upper'));
                        var lower = parseFloat(row.getAttribute('data-lower'));
                        
                        upperLine.setData([{{time: firstTime, value: upper}}, {{time: lastTime, value: upper}}]);
                        lowerLine.setData([{{time: firstTime, value: lower}}, {{time: lastTime, value: lower}}]);
                        
                        // Fit bounds to show lines
                        chart.timeScale().fitContent();
                    }});
                }});
                
                // Trigger default
                if (rows.length > 1) {{
                    rows[1].click();
                }} else if (rows.length > 0) {{
                    rows[0].click();
                }}
            }}
            
            var ro = new ResizeObserver(function() {{
                if (chartContainer.offsetWidth > 0) {{
                    chart.applyOptions({{width: chartContainer.offsetWidth, height: chartContainer.offsetHeight}});
                }}
            }});
            ro.observe(chartContainer);
            
            var moduleCard = chartContainer.closest('.module-card');
            if (moduleCard) {{
                moduleCard.addEventListener('module-destroy', function cleanup() {{
                    moduleCard.removeEventListener('module-destroy', cleanup);
                    ro.disconnect();
                    try {{ chart.remove(); }} catch(e) {{}}
                }});
            }}
        }}
        ensureLW(initChart);
    }})();
    </script>
    '''

    # ---- 组装 ----
    html = f'''
    <div style="width:100%;height:100%;display:flex;flex-direction:column;
                font-family:var(--font-family);overflow:hidden;color:var(--color-text-primary);">
        {header_html}
        <div style="flex:1;min-height:0;overflow-y:auto;padding:14px;background:var(--color-bg, var(--color-surface));">
            {stoploss_section}
            {details_section}
        </div>
    </div>
    {js_script}
    '''
    return {"html": html, "state": state}


# ================================================================== #
#  on_action
# ================================================================== #
def on_action(action: str, payload: dict, config: dict, state: dict) -> dict:
    if action == "refresh":
        # 清除本模块缓存
        keys_to_del = [k for k in _CACHE if k.startswith("ohlc_")]
        for k in keys_to_del:
            del _CACHE[k]
        return render(config, state)

    return {"state": state}


# ================================================================== #
#  错误渲染
# ================================================================== #
def _render_error(title: str, detail: str, state: dict) -> dict:
    html = f'''
    <div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;
                font-family:var(--font-family);padding:20px;">
        <div style="text-align:center;max-width:360px;">
            <div style="font-size:36px;margin-bottom:12px;">⚠️</div>
            <div style="font-size:var(--font-size-lg);font-weight:700;color:var(--color-text-primary);margin-bottom:8px;">
                {title}
            </div>
            <div style="font-size:var(--font-size-sm);color:var(--color-text-tertiary);line-height:1.6;">
                {detail}
            </div>
        </div>
    </div>
    '''
    return {"html": html, "state": state}


def _badge_s() -> str:
    return (
        "display:inline-flex;align-items:center;gap:4px;padding:3px 10px;"
        "border-radius:var(--radius-full);font-size:var(--font-size-xs);"
        "font-weight:600;letter-spacing:0.3px;"
    )
