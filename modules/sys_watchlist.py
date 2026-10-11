"""
sys_watchlist.py — 多品种行情列表 v2
- 列表形式：品种名 / 代码 / 最新价 / 涨跌价差与涨跌幅 (+5.0 / +0.55%)
- 支持拖拽调整顺序（纯前端 HTML5 drag & drop，拖拽后保存到 state）
- 配置框支持搜索添加，列表项可单独删除
"""

import sys
import os
import re
import requests

SYS_TRADE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "sys_trade"))
if SYS_TRADE_DIR not in sys.path:
    sys.path.append(SYS_TRADE_DIR)

from data_source import create_source
from log_store import add_log

# 期货品种代码 → 中文名称映射（字母部分）
FUTURES_NAME_MAP = {
    "rb": "螺纹钢", "hc": "热轧卷板", "wr": "线材", "ss": "不锈钢",
    "au": "沪金", "ag": "沪银", "cu": "沪铜", "al": "沪铝",
    "zn": "沪锌", "pb": "沪铅", "ni": "沪镍", "sn": "沪锡",
    "bc": "国际铜", "ao": "氧化铝",
    "fu": "燃料油", "bu": "沥青", "ru": "橡胶", "sp": "纸浆", "nr": "20号胶",
    "sc": "原油", "lu": "低硫燃油", "ec": "集运指数",
    "i": "铁矿石", "jm": "焦煤", "j": "焦炭",
    "a": "豆一", "b": "豆二", "m": "豆粕", "y": "豆油",
    "c": "玉米", "cs": "淀粉", "l": "塑料", "v": "PVC", "pp": "聚丙烯",
    "eb": "苯乙烯", "eg": "乙二醇", "pg": "液化气",
    "jd": "鸡蛋", "lh": "生猪", "p": "棕榈油",
    "TA": "PTA", "MA": "甲醇", "SR": "白糖", "CF": "棉花", "CY": "棉纱",
    "FG": "玻璃", "SA": "纯碱", "SH": "烧碱", "UR": "尿素",
    "AP": "苹果", "CJ": "红枣", "PK": "花生",
    "RM": "菜粕", "OI": "菜油", "RS": "菜籽",
    "SF": "硅铁", "SM": "锰硅",
    "PX": "对二甲苯", "PF": "短纤", "PR": "瓶片",
    "si": "工业硅", "lc": "碳酸锂",
    "IF": "沪深300", "IH": "上证50", "IC": "中证500", "IM": "中证1000",
    "TS": "两年国债", "TF": "五年国债", "T": "十年国债", "TL": "三十年国债",
}


def _code_to_name(symbol: str) -> str:
    """将期货合约代码转换为中文名称，如 DCE.jd2609 → 鸡蛋2609"""
    raw = symbol.split('.')[-1].replace("KQ.m@", "")
    m = re.match(r'^([A-Za-z]+)(\d+)$', raw)
    if m:
        letters, month = m.group(1), m.group(2)
        cn = FUTURES_NAME_MAP.get(letters) or FUTURES_NAME_MAP.get(letters.upper()) or FUTURES_NAME_MAP.get(letters.lower())
        if cn:
            return cn + month
    return raw


META = {
    "name": "多品种列表",
    "icon": "📋",
    "description": "监控多品种实时行情，含最新价、涨跌价差与涨跌幅，自动15秒刷新，支持拖拽排序",
    "tags": ["行情交易"],
    "default_size": [28, 28],
    "min_size": [16, 10],
    "max_size": [64, 64],
    "refresh_interval": 15,
    "config_fields": [
        {"key": "symbols", "label": "监控品种（逗号分隔）", "type": "searchable-tags", "default": "sh600519,DCE.jd2609,SHFE.rb2609"}
    ]
}


def fetch_single_quote(symbol: str) -> dict:
    """拉取单个标的的行情，返回 name/code/price/change_pts/change_pct"""
    symbol = symbol.strip()
    if not symbol:
        return None

    m = re.match(r'^(sh|sz|bj)\d{6}$', symbol.lower())
    pure_num = re.match(r'^\d{6}$', symbol)

    try:
        if m or pure_num:
            aksym = symbol.lower()
            if pure_num:
                aksym = "sh" + aksym if aksym.startswith('6') else "sz" + aksym
            url = f"https://hq.sinajs.cn/list={aksym}"
            resp = requests.get(url, headers={"Referer": "https://finance.sina.com.cn"}, timeout=3)
            raw = resp.content.decode("gbk", errors="replace")
            if "FAILED" in raw or len(raw.split(',')) < 10:
                return {"name": symbol, "code": symbol, "price": "-", "change_pts": 0, "change_pct": 0, "status": "error"}
            data = raw.split('"')[1].split(",")
            sym_name = data[0]
            price = float(data[3])
            prev_close = float(data[2])
            change_pts = round(price - prev_close, 2)
            change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0
            return {
                "name": sym_name,
                "code": aksym.upper(),
                "price": price,
                "change_pts": change_pts,
                "change_pct": change_pct,
                "status": "ok"
            }
        else:
            # 期货合约：优先走新浪期货 HQ 获取全量实时字段
            raw_code = symbol.split('.')[-1].replace("KQ.m@", "")
            sina_code = f"nf_{raw_code.upper()}"
            url = f"https://hq.sinajs.cn/list={sina_code}"
            try:
                resp = requests.get(url, headers={"Referer": "https://finance.sina.com.cn"}, timeout=3)
                raw = resp.content.decode("gbk", errors="replace")
                if '="' in raw:
                    content = raw.split('"')[1]
                    fields = content.split(",")
                    if len(fields) >= 11 and fields[0]:
                        sym_display = _code_to_name(symbol)
                        price = float(fields[8]) if float(fields[8]) > 0 else float(fields[2])
                        prev_close = float(fields[10]) if float(fields[10]) > 0 else float(fields[2])
                        change_pts = round(price - prev_close, 2)
                        change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0
                        return {
                            "name": sym_display,
                            "code": symbol,
                            "price": price,
                            "change_pts": change_pts,
                            "change_pct": change_pct,
                            "status": "ok"
                        }
            except Exception:
                pass

            # 回退到 sys_trade akshare 数据源
            ds = create_source("akshare")
            quote = ds.get_quote(symbol)
            if not quote:
                return {"name": _code_to_name(symbol), "code": symbol, "price": "-", "change_pts": 0, "change_pct": 0, "status": "error"}

            sym_display = _code_to_name(symbol)
            price = quote.get("price", quote.get("last_price", 0))
            open_p = quote.get("open", price)
            change_pts = round(price - open_p, 2)
            change_pct = round(change_pts / open_p * 100, 2) if open_p > 0 else 0
            return {
                "name": sym_display,
                "code": symbol,
                "price": price,
                "change_pts": change_pts,
                "change_pct": change_pct,
                "status": "ok"
            }

    except Exception as e:
        return {"name": symbol.split('.')[-1], "code": symbol, "price": "ERR", "change_pts": 0, "change_pct": 0, "status": "error"}


def _build_html(symbol_list, quotes):
    """构建列表 HTML，支持拖拽排序"""
    rows = ""
    for idx, sym in enumerate(symbol_list):
        q = quotes.get(sym, {"name": sym, "code": sym, "price": "...", "change_pts": 0, "change_pct": 0, "status": "loading"})

        change_pts = q.get("change_pts", 0)
        change_pct = q.get("change_pct", 0)
        status = q.get("status", "error")

        if status == "ok" and change_pts > 0:
            color = "#ef4444"
            sign = "+"
            bg_accent = "rgba(239,68,68,0.08)"
        elif status == "ok" and change_pts < 0:
            color = "#22c55e"
            sign = ""
            bg_accent = "rgba(34,197,94,0.08)"
        else:
            color = "var(--color-text-muted)"
            sign = ""
            bg_accent = "transparent"

        price_str = str(q.get("price", "--"))
        pct_str = f"{sign}{change_pts} ({sign}{change_pct}%)" if status == "ok" else "--"
        name = q.get("name", sym)
        code = q.get("code", sym)

        rows += f"""
<div class="wl-row" draggable="true" data-sym="{sym}" data-idx="{idx}"
     style="display:flex;align-items:center;padding:9px 12px;border-bottom:1px solid var(--color-border);
            gap:10px;cursor:grab;background:{bg_accent};transition:background .15s,opacity .15s;"
     onmouseenter="this.style.background='var(--color-surface-hover)'"
     onmouseleave="this.style.background='{bg_accent}'">
  <span style="color:var(--color-text-muted);font-size:12px;cursor:grab;">⠿</span>
  <div style="width:6px;height:6px;border-radius:50%;background:{color};flex-shrink:0;"></div>
  <div style="flex:1;min-width:0;">
    <div style="font-size:13px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{name}</div>
    <div style="font-size:10px;color:var(--color-text-muted);font-family:monospace;margin-top:1px;">{code}</div>
  </div>
  <div style="text-align:right;flex-shrink:0;">
    <div style="font-size:14px;font-weight:800;font-family:monospace;">{price_str}</div>
    <div style="font-size:11px;font-weight:700;color:{color};font-family:monospace;margin-top:1px;">{pct_str}</div>
  </div>
  <button data-action="remove_sym" data-payload='{{"sym":"{sym}"}}'
          style="background:none;border:none;color:var(--color-text-muted);cursor:pointer;font-size:14px;padding:2px 4px;opacity:0.4;transition:opacity .15s;"
          onmouseenter="this.style.opacity='1'" onmouseleave="this.style.opacity='0.4'">✕</button>
</div>"""

    # 拖拽排序脚本
    drag_script = """
<script>
(function() {
  var list = document.querySelector('.module-scope-{id} .wl-list');
  if (!list) return;
  var dragging = null;
  list.addEventListener('dragstart', function(e) {
    dragging = e.target.closest('.wl-row');
    if (dragging) { dragging.style.opacity = '0.4'; }
  });
  list.addEventListener('dragend', function(e) {
    if (dragging) dragging.style.opacity = '';
    dragging = null;
    var rows = list.querySelectorAll('.wl-row');
    var syms = Array.from(rows).map(function(r) { return r.dataset.sym; });
    var btn = list.closest('.module-body').querySelector('[data-action="reorder"]');
    if (btn) {
      btn.dataset.payload = JSON.stringify({order: syms});
      btn.click();
    }
  });
  list.addEventListener('dragover', function(e) {
    e.preventDefault();
    var target = e.target.closest('.wl-row');
    if (target && dragging && target !== dragging) {
      var rect = target.getBoundingClientRect();
      var mid = rect.top + rect.height / 2;
      if (e.clientY < mid) {
        list.insertBefore(dragging, target);
      } else {
        list.insertBefore(dragging, target.nextSibling);
      }
    }
  });
})();
</script>"""

    return f"""
<div style="width:100%;height:100%;display:flex;flex-direction:column;overflow:hidden;font-family:system-ui,sans-serif;">
  <div style="flex:1;overflow-y:auto;" class="wl-list">
    {rows}
  </div>
  <button data-action="reorder" data-payload='{{"order":[]}}' style="display:none;"></button>
</div>
{drag_script}"""


def fetch_batch_quotes(symbol_list: list) -> dict:
    """批量合并拉取所有标的行情（1个 HTTP 请求替代串行 N 个 HTTP 请求）"""
    quotes = {}
    sina_query_map = {}
    query_codes = []

    for sym in symbol_list:
        sym_clean = sym.strip()
        if not sym_clean:
            continue
        m = re.match(r'^(sh|sz|bj)\d{6}$', sym_clean.lower())
        pure_num = re.match(r'^\d{6}$', sym_clean)
        if m or pure_num:
            aksym = sym_clean.lower()
            if pure_num:
                aksym = "sh" + aksym if aksym.startswith('6') else "sz" + aksym
            sina_query_map[aksym] = sym_clean
            query_codes.append(aksym)
        else:
            raw_code = sym_clean.split('.')[-1].replace("KQ.m@", "")
            sina_code = f"nf_{raw_code.upper()}"
            sina_query_map[sina_code.lower()] = sym_clean
            query_codes.append(sina_code)

    if not query_codes:
        return quotes

    url = f"https://hq.sinajs.cn/list={','.join(query_codes)}"
    try:
        resp = requests.get(url, headers={"Referer": "https://finance.sina.com.cn"}, timeout=3)
        raw_text = resp.content.decode("gbk", errors="replace")
        for line in raw_text.splitlines():
            if '="' not in line:
                continue
            left, right = line.split('="')
            var_name = left.split("_str_")[-1].lower().strip()
            content = right.rstrip('";')
            orig_sym = sina_query_map.get(var_name)
            if not orig_sym or not content:
                continue
            fields = content.split(",")
            if var_name.startswith("nf_"):  # 期货
                if len(fields) >= 11 and fields[0]:
                    sym_display = _code_to_name(orig_sym)
                    price = float(fields[8]) if float(fields[8]) > 0 else float(fields[2])
                    prev_close = float(fields[10]) if float(fields[10]) > 0 else float(fields[2])
                    change_pts = round(price - prev_close, 2)
                    change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0
                    quotes[orig_sym] = {
                        "name": sym_display,
                        "code": orig_sym,
                        "price": price,
                        "change_pts": change_pts,
                        "change_pct": change_pct,
                        "status": "ok"
                    }
            else:  # 股票
                if len(fields) >= 10 and fields[0]:
                    sym_name = fields[0]
                    price = float(fields[3])
                    prev_close = float(fields[2])
                    change_pts = round(price - prev_close, 2)
                    change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0
                    quotes[orig_sym] = {
                        "name": sym_name,
                        "code": var_name.upper(),
                        "price": price,
                        "change_pts": change_pts,
                        "change_pct": change_pct,
                        "status": "ok"
                    }
    except Exception as e:
        add_log(f"[sys_watchlist] 批量行情抓取失败: {e}")

    return quotes


def render(config: dict, state: dict) -> dict:
    symbols_str = config.get("symbols", "sh600519,DCE.jd2609,SHFE.rb2609").strip()
    symbol_list = [s.strip() for s in symbols_str.split(',') if s.strip()]

    saved_order = state.get("order", [])
    if saved_order:
        symbol_list = [s for s in saved_order if s in symbol_list] + \
                      [s for s in symbol_list if s not in saved_order]

    # 1. 优先批量拉取全量行情（单次网络请求）
    quotes = fetch_batch_quotes(symbol_list)

    # 2. 对缺失项回退单标的拉取
    for sym in symbol_list:
        if sym not in quotes:
            q = fetch_single_quote(sym)
            if q:
                quotes[sym] = q

    state["order"] = symbol_list
    return {"html": _build_html(symbol_list, quotes), "state": state}


def on_action(action: str, payload: dict, config: dict, state: dict) -> dict:
    symbols_str = config.get("symbols", "").strip()
    symbol_list = [s.strip() for s in symbols_str.split(',') if s.strip()]

    if action == "reorder":
        new_order = payload.get("order", [])
        if new_order:
            state["order"] = [s for s in new_order if s in symbol_list]
        return {"state": state}

    if action == "remove_sym":
        sym = payload.get("sym", "")
        order = state.get("order", symbol_list)
        state["order"] = [s for s in order if s != sym]
        return render(config, state)
    return {"state": state}
