"""Online symbol discovery for the live K-line module.

Unlike ``symbol_tree.py``, this module never reads the local DuckDB. Futures
products and currently tradable contracts come from AKShare's online sources;
the A-share directory is loaded from the current online code/name list.
"""

import re
import threading
import time
from datetime import datetime, timedelta


CATALOG_TTL_SECONDS = 12 * 3600
CONTRACT_TTL_SECONDS = 10 * 60
STOCK_TTL_SECONDS = 12 * 3600

EXCHANGE_LABELS = {
    "SHFE": "上期所",
    "INE": "上期能源",
    "DCE": "大商所",
    "CZCE": "郑商所",
    "GFEX": "广期所",
    "CFFEX": "中金所",
    "SSE": "上交所",
    "SZSE": "深交所",
    "BSE": "北交所",
}

_CACHE_LOCK = threading.RLock()
_CATALOG_CACHE = None
_CONTRACT_CACHE = {}
_STOCK_CACHE = None


def _row_value(row, *names):
    for name in names:
        if name in row:
            return row[name]
    return None


def _normalize_exchange(value):
    text = str(value or "").strip()
    upper = text.upper()
    if upper in EXCHANGE_LABELS:
        return upper
    mappings = (
        ("能源", "INE"),
        ("上海", "SHFE"),
        ("郑州", "CZCE"),
        ("大连", "DCE"),
        ("广州", "GFEX"),
        ("金融", "CFFEX"),
        ("中金", "CFFEX"),
        ("上交", "SSE"),
        ("深交", "SZSE"),
        ("北交", "BSE"),
    )
    for marker, exchange in mappings:
        if marker in text:
            return exchange
    return upper


def _product_code(value):
    match = re.search(r"[A-Za-z]+", str(value or ""))
    return match.group(0).upper() if match else ""


def _catalog_from_rules(ak):
    last_error = None
    for offset in range(10):
        day = datetime.now() - timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        try:
            frame = ak.futures_rule(date=day.strftime("%Y%m%d"))
            rows = []
            for _, row in frame.iterrows():
                exchange = _normalize_exchange(_row_value(row, "交易所", "exchange"))
                code = _product_code(_row_value(row, "代码", "code", "symbol"))
                name = str(_row_value(row, "品种", "name") or code).strip()
                if exchange in EXCHANGE_LABELS and code:
                    rows.append((exchange, code, name))
            if rows:
                return rows, day.strftime("%Y-%m-%d"), "futures_rule"
        except Exception as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise RuntimeError("最近交易日没有返回期货品种目录")


def _catalog_from_sina_marks(ak):
    frame = ak.futures_symbol_mark()
    rows = []
    for _, row in frame.iterrows():
        exchange = _normalize_exchange(_row_value(row, "exchange", "交易所"))
        name = str(_row_value(row, "symbol", "品种") or "").strip()
        code = _product_code(_row_value(row, "mark", "code", "代码"))
        if exchange in EXCHANGE_LABELS and code and name:
            rows.append((exchange, code, name))
    if not rows:
        raise RuntimeError("新浪期货品种目录为空")
    return rows, datetime.now().strftime("%Y-%m-%d"), "futures_symbol_mark"


def get_online_catalog(force=False):
    global _CATALOG_CACHE
    now = time.time()
    with _CACHE_LOCK:
        if not force and _CATALOG_CACHE and now - _CATALOG_CACHE[0] < CATALOG_TTL_SECONDS:
            return _CATALOG_CACHE[1]

    import akshare as ak

    warning = ""
    try:
        rows, as_of, source = _catalog_from_rules(ak)
    except Exception as primary_error:
        rows, as_of, source = _catalog_from_sina_marks(ak)
        warning = f"交易所规则目录暂不可用，已使用新浪品种目录：{primary_error}"

    tree = {
        "futures_cn": {"label": "国内期货", "exchanges": {}},
        "stock_cn": {
            "label": "A股股票",
            "exchanges": {
                exchange: {"label": EXCHANGE_LABELS[exchange], "products": {}}
                for exchange in ("SSE", "SZSE", "BSE")
            },
        },
    }
    for exchange, code, name in rows:
        exchange_obj = tree["futures_cn"]["exchanges"].setdefault(
            exchange,
            {"label": EXCHANGE_LABELS.get(exchange, exchange), "products": {}},
        )
        exchange_obj["products"][code] = {
            "label": f"{name} ({code})",
            "name": name,
            "code": code,
        }

    result = {"tree": tree, "as_of": as_of, "source": source, "warning": warning}
    with _CACHE_LOCK:
        _CATALOG_CACHE = (now, result)
    return result


def _find_product(exchange, product):
    catalog = get_online_catalog()
    products = (
        catalog["tree"]
        .get("futures_cn", {})
        .get("exchanges", {})
        .get(exchange, {})
        .get("products", {})
    )
    return products.get(product)


def _contract_sort_key(item):
    symbol = item["sym"]
    if symbol.endswith("0") and not re.search(r"\d{3,4}$", symbol):
        return (0, 0, symbol)
    match = re.search(r"(\d{3,4})$", symbol)
    return (1, int(match.group(1)) if match else 99999, symbol)


def _extract_contracts(frame, exchange, product):
    contracts = []
    seen = set()
    for _, row in frame.iterrows():
        row_exchange = _normalize_exchange(_row_value(row, "exchange", "交易所") or exchange)
        symbol = str(_row_value(row, "symbol", "代码") or "").strip().upper()
        name = str(_row_value(row, "name", "名称") or symbol).strip()
        symbol_product = _product_code(symbol)
        if row_exchange != exchange or symbol_product != product or symbol in seen:
            continue
        if not (symbol == f"{product}0" or re.fullmatch(rf"{re.escape(product)}\d{{3,4}}", symbol)):
            continue
        seen.add(symbol)
        contracts.append({
            "val": f"{exchange}.{symbol} {name}".strip(),
            "sym": symbol,
            "label": name,
            "active": True,
            "continuous": symbol == f"{product}0",
        })
    contracts.sort(key=_contract_sort_key)
    return contracts


def _find_sina_product_name(ak, exchange, product):
    marks = ak.futures_symbol_mark()
    for _, row in marks.iterrows():
        mark_code = _product_code(_row_value(row, "mark", "code", "代码"))
        mark_exchange = _normalize_exchange(_row_value(row, "exchange", "交易所"))
        if mark_code == product and mark_exchange == exchange:
            return str(_row_value(row, "symbol", "品种") or "").strip()
    return ""


def get_online_contracts(exchange, product, force=False):
    exchange = _normalize_exchange(exchange)
    product = _product_code(product)
    if exchange not in EXCHANGE_LABELS or not product:
        raise ValueError("无效的交易所或品种")

    key = f"{exchange}.{product}"
    now = time.time()
    with _CACHE_LOCK:
        cached = _CONTRACT_CACHE.get(key)
        if not force and cached and now - cached[0] < CONTRACT_TTL_SECONDS:
            return cached[1]

    product_info = _find_product(exchange, product)
    if not product_info:
        raise ValueError(f"在线目录中不存在 {key}")

    import akshare as ak

    query_name = product_info["name"]
    first_error = None
    try:
        frame = ak.futures_zh_realtime(symbol=query_name)
        contracts = _extract_contracts(frame, exchange, product)
    except Exception as exc:
        first_error = exc
        contracts = []

    # 规则表的品种名称偶尔与新浪检索词不同；空表也必须尝试标准映射。
    if not contracts:
        matched_name = _find_sina_product_name(ak, exchange, product)
        if matched_name and (matched_name != query_name or first_error is not None):
            frame = ak.futures_zh_realtime(symbol=matched_name)
            contracts = _extract_contracts(frame, exchange, product)

    if not contracts:
        if first_error:
            raise RuntimeError(f"{key} 实时合约查询失败：{first_error}") from first_error
        raise RuntimeError(f"{key} 当前没有可交易合约")

    result = {"contracts": contracts, "as_of": datetime.now().strftime("%Y-%m-%d %H:%M"), "source": "futures_zh_realtime"}
    with _CACHE_LOCK:
        _CONTRACT_CACHE[key] = (now, result)
    return result


def _stock_exchange(code):
    if code.startswith(("4", "8", "92")):
        return "BSE"
    if code.startswith(("5", "6", "9")):
        return "SSE"
    return "SZSE"


def _load_stocks(force=False):
    global _STOCK_CACHE
    now = time.time()
    with _CACHE_LOCK:
        if not force and _STOCK_CACHE and now - _STOCK_CACHE[0] < STOCK_TTL_SECONDS:
            return _STOCK_CACHE[1]

    import akshare as ak

    frame = ak.stock_info_a_code_name()
    stocks = {exchange: [] for exchange in ("SSE", "SZSE", "BSE")}
    for _, row in frame.iterrows():
        code = str(_row_value(row, "code", "代码", "证券代码") or "").strip()
        if re.fullmatch(r"\d+\.0", code):
            code = code[:-2]
        code = code.zfill(6)
        name = str(_row_value(row, "name", "名称", "证券简称") or "").strip()
        if not re.fullmatch(r"\d{6}", code) or not name:
            continue
        exchange = _stock_exchange(code)
        stocks[exchange].append({
            "val": f"{exchange}.{code} {name}",
            "sym": code,
            "label": f"{code} {name}",
            "active": True,
        })
    for values in stocks.values():
        values.sort(key=lambda item: item["sym"])

    result = {"stocks": stocks, "as_of": datetime.now().strftime("%Y-%m-%d"), "source": "stock_info_a_code_name"}
    with _CACHE_LOCK:
        _STOCK_CACHE = (now, result)
    return result


def get_online_stocks(exchange, force=False):
    exchange = _normalize_exchange(exchange)
    if exchange not in ("SSE", "SZSE", "BSE"):
        raise ValueError("无效的股票交易所")
    result = _load_stocks(force=force)
    return {
        "stocks": result["stocks"][exchange],
        "as_of": result["as_of"],
        "source": result["source"],
    }


def clear_caches():
    global _CATALOG_CACHE, _STOCK_CACHE
    with _CACHE_LOCK:
        _CATALOG_CACHE = None
        _CONTRACT_CACHE.clear()
        _STOCK_CACHE = None
