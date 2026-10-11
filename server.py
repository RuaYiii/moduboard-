"""
ModuBoard 后端服务器
基于 Flask，提供模块 API、配置管理 API 以及静态文件服务。

API 返回格式统一为:
  成功: {"status": "success", ...其他字段}
  失败: {"status": "error", "error": "错误描述"}
"""

import os
import json
import glob
import logging
import mimetypes
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from module_loader import ModuleLoader
from log_store import add_log
from industrial_protocol.modbus_service import IndustrialCommunicationError, real_modbus_service
from industrial_protocol.opcua_service import OpcUaRuntimeError, opcua_service

# ------------------------------------------------------------------ #
#  屏蔽无用的 /render 和 /api/configs 日志，让终端输出更干净
# ------------------------------------------------------------------ #
class NoRenderLogFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        return "/render" not in msg and "/api/configs" not in msg

logging.getLogger("werkzeug").addFilter(NoRenderLogFilter())

# ------------------------------------------------------------------ #
#  修复 Windows 注册表中可能被污染的 MIME 类型
#  某些系统 .js 的 MIME 类型里混入了零宽空格 (\u200b)，导致 HTTP header 编码失败
# ------------------------------------------------------------------ #
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")

# ------------------------------------------------------------------ #
#  日志配置
# ------------------------------------------------------------------ #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
#  路径常量
# ------------------------------------------------------------------ #
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODULES_DIR = os.path.join(BASE_DIR, "modules")
CONFIGS_DIR = os.path.join(BASE_DIR, "configs")
STATIC_DIR = os.path.join(BASE_DIR, "static")

# 确保必要目录存在
os.makedirs(CONFIGS_DIR, exist_ok=True)
os.makedirs(MODULES_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

# ------------------------------------------------------------------ #
#  Flask 应用 & 模块加载器
# ------------------------------------------------------------------ #
app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
CORS(app)  # 开发阶段启用跨域支持

# 确保 JSON 响应使用 utf-8 且格式安全
app.config["JSON_AS_ASCII"] = True  # 强制 ASCII 输出，避免编码问题

loader = ModuleLoader(MODULES_DIR)


def safe_jsonify(data, status_code=200):
    """安全的 JSON 响应构建器，确保不含不可见 Unicode 字符"""
    json_str = json.dumps(data, ensure_ascii=True, default=str)
    return Response(json_str, status=status_code, mimetype="application/json")


# ================================================================== #
#  静态文件路由
# ================================================================== #

@app.route("/")
def index():
    """返回前端主页面"""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index_path):
        return send_from_directory(STATIC_DIR, "index.html")
    return "<h1>ModuBoard</h1><p>Frontend not ready.</p>", 200


@app.route("/industrial")
def industrial_workbench():
    """工业通信调试器的全屏协议工作台。"""
    return send_from_directory(STATIC_DIR, "industrial.html")


# ================================================================== #
#  真实工业通信 API
# ================================================================== #

@app.route("/api/industrial/self-check", methods=["GET"])
def industrial_self_check():
    """现场启动前检查协议依赖和本机串口。"""
    from importlib import metadata
    dependencies = {}
    for package in ("asyncua", "pymodbus", "pyserial"):
        try:
            dependencies[package] = {"installed": True, "version": metadata.version(package)}
        except metadata.PackageNotFoundError:
            dependencies[package] = {"installed": False, "version": None}
    serial_ports = []
    try:
        from serial.tools import list_ports
        serial_ports = [
            {"device": port.device, "description": port.description, "hwid": port.hwid}
            for port in list_ports.comports()
        ]
    except ImportError:
        pass
    ready = all(item["installed"] for item in dependencies.values())
    return safe_jsonify({"status": "success", "ready": ready, "dependencies": dependencies, "serial_ports": serial_ports})


@app.route("/api/industrial/modbus/execute", methods=["POST"])
def industrial_modbus_execute():
    payload = request.get_json(silent=True) or {}
    try:
        result = real_modbus_service.execute(payload)
        return safe_jsonify({"status": "success", "result": result})
    except ValueError as exc:
        return safe_jsonify({"status": "error", "category": "Validation error", "error": str(exc)}, 400)
    except IndustrialCommunicationError as exc:
        return safe_jsonify({"status": "error", "category": exc.category, "error": exc.message, "details": exc.details}, 502)
    except Exception as exc:
        logger.exception("真实 Modbus 请求失败")
        return safe_jsonify({"status": "error", "category": "Internal error", "error": str(exc)}, 500)


def _opc_call(callback):
    try:
        return safe_jsonify({"status": "success", "result": callback()})
    except (OpcUaRuntimeError, ValueError, OSError) as exc:
        return safe_jsonify({"status": "error", "error": str(exc)}, 502)
    except Exception as exc:
        logger.exception("真实 OPC UA 操作失败")
        return safe_jsonify({"status": "error", "error": str(exc)}, 500)


@app.route("/api/industrial/opc/connect", methods=["POST"])
def industrial_opc_connect():
    payload = request.get_json(silent=True) or {}
    return _opc_call(lambda: opcua_service.connect(payload))


@app.route("/api/industrial/opc/disconnect", methods=["POST"])
def industrial_opc_disconnect():
    return _opc_call(opcua_service.disconnect)


@app.route("/api/industrial/opc/browse", methods=["POST"])
def industrial_opc_browse():
    payload = request.get_json(silent=True) or {}
    return _opc_call(lambda: opcua_service.browse(str(payload.get("node_id") or "i=85"), int(payload.get("limit", 200))))


@app.route("/api/industrial/opc/read", methods=["POST"])
def industrial_opc_read():
    payload = request.get_json(silent=True) or {}
    return _opc_call(lambda: opcua_service.read(str(payload.get("node_id") or "")))


@app.route("/api/industrial/opc/write", methods=["POST"])
def industrial_opc_write():
    return safe_jsonify({
        "status": "error",
        "error": "真实设备模式为只读：OPC UA Write 已禁用",
    }, 403)


@app.route("/api/industrial/opc/subscription/start", methods=["POST"])
def industrial_opc_subscription_start():
    payload = request.get_json(silent=True) or {}
    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    return _opc_call(lambda: opcua_service.start_subscription(config, items))


@app.route("/api/industrial/opc/subscription/stop", methods=["POST"])
def industrial_opc_subscription_stop():
    return _opc_call(opcua_service.stop_subscription)


@app.route("/api/industrial/opc/status", methods=["GET"])
def industrial_opc_status():
    try:
        since = int(request.args.get("since", "0"))
    except ValueError:
        since = 0
    return safe_jsonify({"status": "success", "result": opcua_service.snapshot(since)})


# ================================================================== #
#  模块 API
# ================================================================== #

@app.route("/api/modules", methods=["GET"])
def list_modules():
    """获取所有可用模块及其 META 信息"""
    modules = loader.discover_modules()
    # 返回格式: {"status": "success", "modules": {"weather": {...META...}, ...}}
    return safe_jsonify({"status": "success", "modules": modules})


@app.route("/api/modules/<type_name>/render", methods=["POST"])
def render_module(type_name: str):
    """渲染指定模块"""
    data = request.get_json(silent=True) or {}
    config = data.get("config", {})
    state = data.get("state", {})

    result = loader.render_module(type_name, config, state)

    if "error" in result:
        return safe_jsonify({"status": "error", "error": result["error"]}, 400)

    # 确保返回格式包含 status
    result["status"] = "success"
    return safe_jsonify(result)


@app.route("/preview/<type_name>")
def preview_module(type_name: str):
    """在独立全屏页面中预览模块，便于调试渲染问题"""
    config = {}
    state = {}
    result = loader.render_module(type_name, config, state)
    module_html = result.get("html", f"<p style='color:red'>模块 {type_name} 无法渲染</p>")
    meta = loader.discover_modules().get(type_name, {})
    module_name = meta.get("name", type_name)

    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>预览: {module_name}</title>
  <link rel="stylesheet" href="/static/css/style.css">
  <style>
    :root {{
      --color-bg: #f8fafc; --color-surface: #ffffff; --color-surface-hover: #f1f5f9;
      --color-border: #e2e8f0; --color-text: #1e293b; --color-text-muted: #64748b;
      --color-primary: #4f6ef7; --color-primary-light: rgba(79,110,247,0.15);
      --space-md: 12px;
    }}
    [data-theme="dark"] {{
      --color-bg: #0f172a; --color-surface: #1e293b; --color-surface-hover: #334155;
      --color-border: #334155; --color-text: #f1f5f9; --color-text-muted: #94a3b8;
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{ height: 100%; background: var(--color-bg); color: var(--color-text); font-family: system-ui, sans-serif; }}
    #preview-shell {{
      width: 100vw; height: 100vh;
      display: flex; flex-direction: column; overflow: hidden;
    }}
    #preview-bar {{
      display: flex; align-items: center; gap: 12px;
      padding: 8px 16px; background: var(--color-surface);
      border-bottom: 1px solid var(--color-border); flex-shrink: 0;
      font-size: 13px;
    }}
    #preview-bar strong {{ font-size: 14px; color: var(--color-primary); }}
    #preview-bar button {{
      padding: 4px 12px; border: 1px solid var(--color-border); border-radius: 6px;
      background: var(--color-surface); color: var(--color-text);
      cursor: pointer; font-size: 12px;
    }}
    #preview-content {{
      flex: 1; min-height: 0; overflow: hidden; position: relative;
      display: flex; flex-direction: column;
    }}
    /* 让模块根元素填满 preview-content，用 flex:1 而非 height:100%（后者在 flex 子元素上经常失效） */
    #preview-content > * {{
      flex: 1; min-height: 0; width: 100%;
    }}
  </style>
</head>
<body>
<div id="preview-shell">
  <div id="preview-bar">
    <strong>🔍 模块预览: {module_name} ({type_name})</strong>
    <span style="color:var(--color-text-muted);">独立窗口 · 无嵌套容器限制</span>
    <button onclick="location.reload()">🔄 刷新</button>
    <button onclick="document.documentElement.dataset.theme=document.documentElement.dataset.theme==='dark'?'':'dark'">🌓 切换主题</button>
    <button onclick="window.close()">✕ 关闭</button>
    <span style="margin-left:auto;font-size:11px;color:var(--color-text-muted);">
      窗口尺寸: <span id="size-label"></span>
    </span>
  </div>
  <div id="preview-content">
    {module_html}
  </div>
</div>
<script src="/static/js/lightweight-charts.standalone.production.js"></script>
<script>
  // 更新尺寸显示
  function updateSize() {{
    var el = document.getElementById('size-label');
    if (el) el.textContent = window.innerWidth + ' × ' + window.innerHeight;
  }}
  window.addEventListener('resize', updateSize);
  updateSize();

  // 绑定 data-action 按钮（让模块内交互可用）
  document.getElementById('preview-content').addEventListener('click', function(e) {{
    var btn = e.target.closest('[data-action]');
    if (!btn) return;
    var action = btn.dataset.action;
    var payload = {{}};
    try {{ payload = JSON.parse(btn.dataset.payload || '{{}}'); }} catch(ex) {{}}
    // 收集 data-input
    var inputs = document.querySelectorAll('[data-input]');
    inputs.forEach(function(inp) {{ payload[inp.dataset.input] = inp.value; }});
    fetch('/api/modules/{type_name}/action', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{action: action, payload: payload, config: {{}}, state: window.__previewState || {{}}}})
    }}).then(function(r) {{ return r.json(); }}).then(function(data) {{
      if (data.state) window.__previewState = data.state;
      if (data.html) {{
        var content = document.getElementById('preview-content');
        content.innerHTML = data.html;
        // 重新执行 script 标签
        content.querySelectorAll('script').forEach(function(old) {{
          var s = document.createElement('script');
          s.textContent = old.textContent;
          old.parentNode.replaceChild(s, old);
        }});
      }}
    }});
  }});
</script>
</body>
</html>"""
    return Response(page, mimetype="text/html")


@app.route("/api/modules/<type_name>/action", methods=["POST"])
def module_action(type_name: str):
    raw_data = request.get_data(as_text=True)
    # print(f"[DEBUG] Raw request to /{type_name}/action: {raw_data}")
    
    data = {}
    try:
        data = json.loads(raw_data) if raw_data else {}
    except Exception as e:
        add_log(f"API Action JSON解析失败: {e} | raw: {raw_data[:100]}")
        
    action = data.get("action", "")
    payload = data.get("payload", {})
    config = data.get("config", {})
    state = data.get("state", {})

    # 总是记录日志
    add_log(f"API Action 被调用: {type_name}.{action} | raw: {raw_data[:100]}")

    if not action:
        add_log("错误: missing action")
        return safe_jsonify({"status": "error", "error": "missing action"}, 400)

    result = loader.call_action(type_name, action, payload, config, state)

    if "error" in result:
        return safe_jsonify({"status": "error", "error": result["error"]}, 400)

    result["status"] = "success"
    return safe_jsonify(result)


# ================================================================== #
#  搜索 API (自动补全)
# ================================================================== #

@app.route("/api/search_symbol", methods=["GET"])
def search_symbol():
    """统一搜索接口：聚合新浪股票搜索与本地期货搜索"""
    import requests
    import re
    q = request.args.get("q", "").strip()
    if not q:
        return safe_jsonify({"status": "success", "results": []})
        
    results = []
    
    # 0. 本地期货快速匹配字典
    FUTURES_MAP = {
        "螺纹": ("SHFE", "rb"), "螺纹钢": ("SHFE", "rb"), "线材": ("SHFE", "wr"), "热卷": ("SHFE", "hc"),
        "烧碱": ("CZCE", "SH"), "纯碱": ("CZCE", "SA"), "玻璃": ("CZCE", "FG"),
        "苹果": ("CZCE", "AP"), "白糖": ("CZCE", "SR"), "棉花": ("CZCE", "CF"), "棉纱": ("CZCE", "CY"),
        "甲醇": ("CZCE", "MA"), "铁矿石": ("DCE", "i"), "铁矿": ("DCE", "i"),
        "焦煤": ("DCE", "jm"), "焦炭": ("DCE", "j"), "硅铁": ("CZCE", "SF"), "锰硅": ("CZCE", "SM"),
        "鸡蛋": ("DCE", "jd"), "生猪": ("DCE", "lh"), "豆粕": ("DCE", "m"),
        "豆油": ("DCE", "y"), "棕榈油": ("DCE", "p"), "黄大豆1号": ("DCE", "a"), "豆一": ("DCE", "a"), "黄大豆2号": ("DCE", "b"), "豆二": ("DCE", "b"),
        "玉米": ("DCE", "c"), "玉米淀粉": ("DCE", "cs"), "淀粉": ("DCE", "cs"),
        "塑料": ("DCE", "l"), "PVC": ("DCE", "v"), "PP": ("DCE", "pp"), "聚丙烯": ("DCE", "pp"),
        "苯乙烯": ("DCE", "eb"), "乙二醇": ("DCE", "eg"), "液化气": ("DCE", "pg"),
        "黄金": ("SHFE", "au"), "白银": ("SHFE", "ag"), "铜": ("SHFE", "cu"), "国际铜": ("INE", "bc"),
        "铝": ("SHFE", "al"), "锌": ("SHFE", "zn"), "镍": ("SHFE", "ni"),
        "锡": ("SHFE", "sn"), "铅": ("SHFE", "pb"), "氧化铝": ("SHFE", "ao"),
        "燃油": ("SHFE", "fu"), "沥青": ("SHFE", "bu"), "橡胶": ("SHFE", "ru"), "纸浆": ("SHFE", "sp"),
        "20号胶": ("INE", "nr"), "原油": ("INE", "sc"), "低硫燃料油": ("INE", "lu"), "集运指数": ("INE", "ec"),
        "PTA": ("CZCE", "TA"), "菜粕": ("CZCE", "RM"), "菜油": ("CZCE", "OI"), "菜籽": ("CZCE", "RS"),
        "红枣": ("CZCE", "CJ"), "花生": ("CZCE", "PK"), "尿素": ("CZCE", "UR"),
        "对二甲苯": ("CZCE", "PX"), "短纤": ("CZCE", "PF"), "瓶片": ("CZCE", "PR"),
        "工业硅": ("GFEX", "si"), "碳酸锂": ("GFEX", "lc"),
        "沪深300": ("CFFEX", "IF"), "上证50": ("CFFEX", "IH"), "中证500": ("CFFEX", "IC"), "中证1000": ("CFFEX", "IM"),
        "两年国债": ("CFFEX", "TS"), "五年国债": ("CFFEX", "TF"), "十年国债": ("CFFEX", "T"), "三十年国债": ("CFFEX", "TL")
    }

    base_q = q
    month = ""
    # 如果包含中文+数字（如鸡蛋2609）或字母+数字但没被sys_trade识别，手动拆分
    match = re.match(r'^([\u4e00-\u9fa5]+|[a-zA-Z]+)(\d{2,4})$', q)
    if match:
        base_q = match.group(1)
        month = match.group(2)

    # 优先本地匹配
    if base_q in FUTURES_MAP or base_q.upper() in FUTURES_MAP:
        key = base_q if base_q in FUTURES_MAP else base_q.upper()
        exchange, code = FUTURES_MAP[key]
        if month:
            # 对于 CZCE，akshare 或其他系统可能接受大写字母，直接拼接
            tq = f"{exchange}.{code}{month}"
            name = f"{key}{month}"
            results.append({"label": f"[{tq}] {name} (精准匹配)", "value": tq})
        else:
            tq = f"KQ.m@{exchange}.{code}"
            name = f"{key}主连"
            results.append({"label": f"[{tq}] {name} (精准匹配)", "value": tq})
    
    # 1. 搜股票 (Sina API)
    try:
        url = f"https://suggest3.sinajs.cn/suggest/type=&key={q}"
        resp = requests.get(url, timeout=3)
        raw = resp.content.decode("gbk", errors="ignore")
        if '="' in raw:
            val_str = raw.split('="')[1].split('";')[0]
            if val_str:
                items = val_str.split(';')
                for item in items:
                    parts = item.split(',')
                    if len(parts) > 4:
                        name = parts[4] if parts[4] else parts[0]
                        code = parts[3]
                        if code.startswith("sh") or code.startswith("sz") or code.startswith("bj"):
                            results.append({"label": f"[{code}] {name}", "value": code})
    except Exception as e:
        logger.error(f"Sina search error: {e}")
        
    # 2. 搜期货 (sys_trade API)
    try:
        url = f"http://127.0.0.1:8890/api/search?q={base_q}"
        resp = requests.get(url, timeout=1, proxies={"http": None, "https": None})
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                for item in data:
                    if month:
                        # 组装特定月份合约
                        tq = f"{item.get('exchange', 'KQ.m')}.{item.get('code', '').lower()}{month}"
                        name = f"{item.get('name', '')}{month}"
                        if item.get('code'):
                            # 避免重复添加
                            if not any(r['value'] == tq for r in results):
                                results.append({"label": f"[{tq}] {name}", "value": tq})
                    else:
                        tq = item.get("tqsdk", item.get("akshare", item.get("code", "")))
                        name = item.get("name", "")
                        if tq and not any(r['value'] == tq for r in results):
                            results.append({"label": f"[{tq}] {name}", "value": tq})
    except Exception as e:
        logger.error(f"sys_trade search error: {e}")
        
    return safe_jsonify({"status": "success", "results": results})


@app.route("/api/symbol_tree", methods=["GET"])
def api_symbol_tree():
    """获取所有品种的层级树"""
    try:
        from symbol_tree import get_symbol_tree
        tree = get_symbol_tree()
        return safe_jsonify({"status": "success", "tree": tree})
    except Exception as e:
        return safe_jsonify({"status": "error", "error": str(e)}, 500)


@app.route("/api/online_symbols/catalog", methods=["GET"])
def api_online_symbol_catalog():
    """V1 在线行情的资产/交易所/品种目录（不读取本地 DuckDB）。"""
    try:
        from online_symbols import get_online_catalog
        return safe_jsonify({"status": "success", **get_online_catalog()})
    except Exception as e:
        logger.exception("Online symbol catalog error")
        return safe_jsonify({"status": "error", "error": str(e)}, 502)


@app.route("/api/online_symbols/contracts", methods=["GET"])
def api_online_symbol_contracts():
    """按交易所和品种返回在线数据源当前实际挂牌的期货合约。"""
    exchange = request.args.get("exchange", "").strip()
    product = request.args.get("product", "").strip()
    if not exchange or not product:
        return safe_jsonify({"status": "error", "error": "缺少 exchange 或 product"}, 400)
    try:
        from online_symbols import get_online_contracts
        return safe_jsonify({"status": "success", **get_online_contracts(exchange, product)})
    except ValueError as e:
        return safe_jsonify({"status": "error", "error": str(e)}, 400)
    except Exception as e:
        logger.exception("Online contract lookup error: %s.%s", exchange, product)
        return safe_jsonify({"status": "error", "error": str(e)}, 502)


@app.route("/api/online_symbols/stocks", methods=["GET"])
def api_online_symbol_stocks():
    """按交易所返回在线 A 股代码/名称目录。"""
    exchange = request.args.get("exchange", "").strip()
    if not exchange:
        return safe_jsonify({"status": "error", "error": "缺少 exchange"}, 400)
    try:
        from online_symbols import get_online_stocks
        return safe_jsonify({"status": "success", **get_online_stocks(exchange)})
    except ValueError as e:
        return safe_jsonify({"status": "error", "error": str(e)}, 400)
    except Exception as e:
        logger.exception("Online stock lookup error: %s", exchange)
        return safe_jsonify({"status": "error", "error": str(e)}, 502)


@app.route("/api/spread_viewpoints", methods=["GET"])
def api_spread_viewpoints():
    """为 sys_spread 提供动态视点选项"""
    product = request.args.get("product", "FG")
    try:
        import duckdb
        import os
        db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "quant_data_hub", "data", "quant.duckdb"))
        con = duckdb.connect(db_path, read_only=True)
        rows = con.execute(
            "SELECT symbol, is_active FROM symbols WHERE asset_class='futures_cn' "
            "AND upper(symbol) LIKE ? ORDER BY symbol",
            [(product + "%").upper()]).fetchall()
        con.close()
        
        n = len(product)
        valid = []
        for s, a in rows:
            if s.upper().startswith(product.upper()):
                suffix = s[n:]
                if len(suffix) == 4 and suffix.isdigit():
                    valid.append((s, a))
        actives = [s for s, a in valid if a]
        expired = sorted((s for s, a in valid if not a), reverse=True)
        options = ["自动主力"] + actives + expired
        return safe_jsonify({"status": "success", "options": options})
    except Exception as e:
        return safe_jsonify({"status": "error", "error": str(e)}, 500)


# ================================================================== #
#  配置管理 API
# ================================================================== #

def _config_path(name: str) -> str:
    """根据配置名生成 .json 文件路径（防止路径穿越）"""
    safe_name = os.path.basename(name)
    if not safe_name or safe_name != name:
        raise ValueError(f"invalid config name: {name}")
    return os.path.join(CONFIGS_DIR, f"{safe_name}.json")


@app.route("/api/configs", methods=["GET"])
def list_configs():
    """列出所有配置文件名"""
    pattern = os.path.join(CONFIGS_DIR, "*.json")
    files = glob.glob(pattern)
    names = [os.path.splitext(os.path.basename(f))[0] for f in files]
    names.sort()
    return safe_jsonify({"status": "success", "configs": names})


@app.route("/api/configs/<name>", methods=["GET"])
def get_config(name: str):
    """读取指定配置"""
    try:
        filepath = _config_path(name)
    except ValueError as e:
        return safe_jsonify({"status": "error", "error": str(e)}, 400)

    if not os.path.isfile(filepath):
        return safe_jsonify({"status": "error", "error": f"config '{name}' not found"}, 404)

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            config = json.load(f)
        return safe_jsonify({"status": "success", "config": config})
    except json.JSONDecodeError:
        return safe_jsonify({"status": "error", "error": f"config '{name}' invalid JSON"}, 500)


@app.route("/api/configs/<name>", methods=["POST"])
def save_config(name: str):
    """保存配置"""
    try:
        filepath = _config_path(name)
    except ValueError as e:
        return safe_jsonify({"status": "error", "error": str(e)}, 400)

    data = request.get_json(silent=True)
    if data is None:
        return safe_jsonify({"status": "error", "error": "body must be JSON"}, 400)

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("config saved: %s", filepath)
        return safe_jsonify({"status": "success", "name": name})
    except OSError as e:
        return safe_jsonify({"status": "error", "error": str(e)}, 500)


@app.route("/api/configs/<name>", methods=["DELETE"])
def delete_config(name: str):
    """删除配置"""
    try:
        filepath = _config_path(name)
    except ValueError as e:
        return safe_jsonify({"status": "error", "error": str(e)}, 400)

    if not os.path.isfile(filepath):
        return safe_jsonify({"status": "error", "error": f"config '{name}' not found"}, 404)

    try:
        os.remove(filepath)
        logger.info("config deleted: %s", filepath)
        return safe_jsonify({"status": "success", "name": name})
    except OSError as e:
        return safe_jsonify({"status": "error", "error": str(e)}, 500)


# ================================================================== #
#  启动入口
# ================================================================== #

if __name__ == "__main__":
    port = int(os.environ.get("MODUBOARD_PORT", 5000))

    print()
    print("=" * 50)
    print("  ModuBoard - Modular Dashboard")
    print(f"  http://127.0.0.1:{port}")
    print("=" * 50)

    modules = loader.discover_modules()
    if modules:
        print(f"  Loaded {len(modules)} module(s):")
        for name, meta in modules.items():
            print(f"    - {name}")
    else:
        print("  No modules found in modules/ directory")
    print()

    host = os.environ.get("MODUBOARD_HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=True, use_reloader=False)
