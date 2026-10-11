"""symbol_tree.py — 全系统统一 4 级渐进式合约树服务

提供层级划分：
Level 1: 资产大类 (Asset Class: futures_cn / stock_cn)
Level 2: 交易所 (Exchange: SHFE, CZCE, DCE, GFEX, CFFEX, INE, SZSE, SSE)
Level 3: 品类/品种 (Product: rb 螺纹, FG 玻璃, SA 纯碱...)
Level 4: 合约/到期时间 (Contract: rb2605 2026年05月到期...)
"""
import os
import re
import duckdb

DB_PATH = os.environ.get("QUANT_DB_PATH") or os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "quant_data_hub", "data", "quant.duckdb"
))

EXCHANGE_LABELS = {
    "SHFE": "上期所 (SHFE)",
    "CZCE": "郑商所 (CZCE)",
    "DCE": "大商所 (DCE)",
    "GFEX": "广期所 (GFEX)",
    "CFFEX": "中金所 (CFFEX)",
    "INE": "上期能源 (INE)",
    "SZSE": "深市 (SZSE)",
    "SSE": "沪市 (SSE)"
}

PRODUCT_NAMES = {
    "FG": "玻璃", "SA": "纯碱", "TA": "PTA", "MA": "甲醇", "UR": "尿素", "SR": "白糖", "CF": "棉花", "AP": "苹果",
    "rb": "螺纹钢", "hc": "热卷", "cu": "沪铜", "al": "沪铝", "zn": "沪锌", "ni": "沪镍", "sn": "沪锡", "au": "沪金", "ag": "沪银", "ru": "橡胶", "bu": "沥青", "sp": "纸浆", "ss": "不锈钢",
    "i": "铁矿石", "j": "焦炭", "jm": "焦煤", "m": "豆粕", "y": "豆油", "p": "棕榈油", "c": "玉米", "cs": "玉米淀粉", "jd": "鸡蛋", "l": "塑料", "v": "PVC", "pp": "聚丙烯", "eg": "乙二醇", "eb": "苯乙烯",
    "lc": "碳酸锂", "si": "工业硅", "sc": "原油", "ec": "集运欧线",
    "IF": "沪深300", "IH": "上证50", "IC": "中证500", "IM": "中证1000", "T": "10年国债",
    "002624": "完美世界"
}


def get_symbol_tree():
    """读取本地 DuckDB 动态生成 4 级层级树"""
    tree = {
        "futures_cn": {"label": "国内期货", "exchanges": {}},
        "stock_cn": {"label": "A股股票", "exchanges": {}}
    }
    if not os.path.exists(DB_PATH):
        return tree

    try:
        con = duckdb.connect(DB_PATH, read_only=True)
        rows = con.execute("""
            SELECT asset_class, exchange, symbol, COALESCE(name, ''), is_active
            FROM symbols
            ORDER BY asset_class, exchange, symbol
        """).fetchall()
        con.close()
    except Exception:
        return tree

    for asset, ex, sym, name, is_active in rows:
        if asset not in tree:
            tree[asset] = {"label": asset, "exchanges": {}}

        ex_label = EXCHANGE_LABELS.get(ex, ex)
        if ex not in tree[asset]["exchanges"]:
            tree[asset]["exchanges"][ex] = {"label": ex_label, "products": {}}

        if asset == "stock_cn":
            prod_code = sym
            prod_name = name or PRODUCT_NAMES.get(sym, sym)
        else:
            m = re.match(r"^([A-Za-z]+)", sym)
            prod_code = m.group(1) if m else sym
            prod_name = PRODUCT_NAMES.get(prod_code, name or prod_code)

        prod_label = f"{prod_name} ({prod_code})"
        if prod_code not in tree[asset]["exchanges"][ex]["products"]:
            tree[asset]["exchanges"][ex]["products"][prod_code] = {"label": prod_label, "contracts": []}

        full_val = f"{ex}.{sym} {name}".strip() if name else f"{ex}.{sym}"

        # 格式化合约时间标签
        if asset == "futures_cn" and len(sym) >= 5 and sym[-4:].isdigit():
            yy = "20" + sym[-4:-2]
            mm = sym[-2:]
            time_label = f"{sym} ({yy}年{mm}月到期)"
        else:
            time_label = f"{sym} {name}".strip()

        if not is_active:
            time_label += " [已到期]"

        tree[asset]["exchanges"][ex]["products"][prod_code]["contracts"].append({
            "val": full_val,
            "sym": sym,
            "label": time_label,
            "active": bool(is_active)
        })

    return tree


def parse_symbol_info(raw_symbol):
    """从原始合约字符串解析出 (asset, exchange, product, symbol, name) 级联参数"""
    raw = (raw_symbol or "").strip()
    parts = raw.split()
    if parts and parts[0].startswith("【"):
        parts[0] = parts[0].split("】", 1)[-1]
    code = parts[0]
    name = parts[1] if len(parts) > 1 else ""

    if "." in code:
        ex, sym = code.split(".", 1)
    else:
        ex, sym = "CZCE", code

    if ex in ("SZSE", "SSE") or code.isdigit():
        asset = "stock_cn"
        prod = sym
    else:
        asset = "futures_cn"
        m = re.match(r"^([A-Za-z]+)", sym)
        prod = m.group(1) if m else sym

    return asset, ex, prod, sym, name
