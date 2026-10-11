import sys
import os
import re
import requests

SYS_TRADE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "sys_trade"))
if SYS_TRADE_DIR not in sys.path:
    sys.path.append(SYS_TRADE_DIR)

from data_source import create_source

META = {
    "name": "实时报价",
    "icon": "📈",
    "description": "自由配置并获取指定品种（期货/A股）的最新行情与涨跌价差",
    "tags": ["行情交易"],
    "default_size": [16, 8],
    "min_size": [12, 6],
    "max_size": [32, 16],
    "refresh_interval": 15,
    "config_fields": [
        {"key": "symbol", "label": "合约/股票 (如 DCE.jd2609, SHFE.rb2609, sh600519)", "type": "searchable-text", "default": "SHFE.rb2609"},
        {"key": "size", "label": "字体大小", "type": "select", "options": ["small", "default", "large", "xlarge"], "default": "small"},
        {"key": "default_color", "label": "默认文字颜色", "type": "color-palette", "default": "#000000"}
    ]
}

# 期货品种代码 → 中文名称映射
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
    raw = symbol.split('.')[-1].replace("KQ.m@", "")
    m = re.match(r'^([A-Za-z]+)(\d+)$', raw)
    if m:
        letters, month = m.group(1), m.group(2)
        cn = FUTURES_NAME_MAP.get(letters) or FUTURES_NAME_MAP.get(letters.upper()) or FUTURES_NAME_MAP.get(letters.lower())
        if cn:
            return cn + month
    return raw


def fetch_quote_details(symbol: str) -> dict:
    symbol = symbol.strip()
    if not symbol:
        return None

    m = re.match(r'^(sh|sz|bj)\d{6}$', symbol.lower())
    pure_num = re.match(r'^\d{6}$', symbol)

    if m or pure_num:
        aksym = symbol.lower()
        if pure_num:
            aksym = "sh" + aksym if aksym.startswith('6') else "sz" + aksym
        url = f"https://hq.sinajs.cn/list={aksym}"
        try:
            resp = requests.get(url, headers={"Referer": "https://finance.sina.com.cn"}, timeout=3)
            raw = resp.content.decode("gbk", errors="replace")
            if "FAILED" in raw or len(raw.split(',')) < 10:
                return None
            data = raw.split('"')[1].split(",")
            sym_display = data[0]
            price = float(data[3])
            prev_close = float(data[2])
            change_pts = round(price - prev_close, 2)
            change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0
            return {
                "name": sym_display,
                "price": price,
                "change_pts": change_pts,
                "change_pct": change_pct,
                "prev_close": prev_close
            }
        except Exception:
            return None
    else:
        # 期货合约
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
                        "price": price,
                        "change_pts": change_pts,
                        "change_pct": change_pct,
                        "prev_close": prev_close
                    }
        except Exception:
            pass

        # 回退到 sys_trade akshare 逻辑
        try:
            ds = create_source("akshare")
            quote = ds.get_quote(symbol)
            if quote:
                sym_display = _code_to_name(symbol)
                price = quote.get("price", quote.get("last_price", 0))
                open_p = quote.get("open", price)
                change_pts = round(price - open_p, 2)
                change_pct = round(change_pts / open_p * 100, 2) if open_p > 0 else 0
                return {
                    "name": sym_display,
                    "price": price,
                    "change_pts": change_pts,
                    "change_pct": change_pct,
                    "prev_close": open_p
                }
        except Exception:
            pass

    return None


def render(config: dict, state: dict) -> dict:
    try:
        symbol = config.get("symbol", "SHFE.rb2609").strip()
        size = config.get("size", "small")
        default_color = config.get("default_color", "#000000")

        quote = fetch_quote_details(symbol)
        if not quote:
            return {
                "ui": {
                    "type": "text",
                    "content": f"{symbol} 无数据",
                    "size": "small",
                    "color": "var(--color-text-muted)"
                },
                "state": state
            }

        sym_display = quote["name"]
        price = quote["price"]
        change_pts = quote["change_pts"]
        change_pct = quote["change_pct"]

        # 涨红跌绿
        color = default_color
        if change_pts > 0:
            color = "#ef4444"  # 红
        elif change_pts < 0:
            color = "#22c55e"  # 绿

        sign = "+" if change_pts > 0 else ""
        content = f"{sym_display}: {price}  {sign}{change_pts} ({sign}{change_pct}%)"

        return {
            "ui": {
                "type": "text",
                "content": content,
                "align": "center",
                "size": size,
                "color": color,
                "weight": "bold",
                "fontFamily": "ui-monospace, Consolas, monospace"
            },
            "state": state
        }
    except Exception as e:
        return {
            "ui": {
                "type": "text",
                "content": f"获取失败: {str(e)[:20]}",
                "size": "small",
                "color": "var(--color-text-muted)"
            },
            "state": state
        }


def on_action(action: str, payload: dict, config: dict, state: dict) -> dict:
    return render(config, state)
