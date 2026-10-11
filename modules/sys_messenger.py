"""
ModuBoard 消息发送模块
支持通过 Telegram Bot API 和 U聊 Webhook 发送文本消息。
两条渠道在本机环境均需走 Clash 代理 (127.0.0.1:7897)。
"""
import json
import ssl
import urllib.request
import urllib.parse
import urllib.error
from log_store import add_log

# ------------------------------------------------------------------ #
#  模块元数据
# ------------------------------------------------------------------ #

import os

# 默认配置：优先从环境变量，否则从 Hermes .env 文件读取，最后用已知值兜底
def _read_default(key: str, fallback: str = "") -> str:
    """读取配置：环境变量 > .env 文件 > 兜底值"""
    val = os.environ.get(key, "")
    if val:
        return val
    # 尝试读取 Hermes 的 .env
    env_path = os.path.expanduser("~/AppData/Local/hermes/.env")
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return fallback

_TG_TOKEN = _read_default("TELEGRAM_BOT_TOKEN")
_TG_CHAT = _read_default("TELEGRAM_HOME_CHANNEL", "523799539")
_UL_TOKEN = "57c0e1fb078556c0e3c34af9c0f1e511"

META = {
    "name": "消息发送",
    "icon": "📨",
    "description": "向 Telegram、U聊 等渠道发送文本消息，支持多选同时发送",
    "tags": ["通讯工具"],
    "default_size": [32, 28],
    "min_size": [24, 20],
    "max_size": [64, 48],
    "refresh_interval": 0,
    "config_fields": [
        {"key": "telegram_token", "label": "Telegram Bot Token", "type": "text", "default": _TG_TOKEN},
        {"key": "telegram_chat_id", "label": "Telegram Chat ID", "type": "text", "default": _TG_CHAT},
        {"key": "uliao_token", "label": "U聊 Webhook Token", "type": "text", "default": _UL_TOKEN},
    ],
}

# 代理配置（优先从环境变量读取，回退至本机默认 7897）
PROXY = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY") or "http://127.0.0.1:7897"


def _build_opener(use_proxy=True):
    """构建 urllib opener，支持可选走代理与自动降级避开写死 127.0.0.1:7897"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    handlers = [urllib.request.HTTPSHandler(context=ctx)]
    
    if use_proxy and PROXY:
        handlers.append(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    else:
        handlers.append(urllib.request.ProxyHandler({})) # 直连
        
    return urllib.request.build_opener(*handlers)


# ------------------------------------------------------------------ #
#  render()
# ------------------------------------------------------------------ #

def render(config: dict, state: dict) -> dict:
    """渲染消息发送界面"""
    tg_token = config.get("telegram_token", "").strip()
    tg_chat = str(config.get("telegram_chat_id", "")).strip()
    ul_token = config.get("uliao_token", "").strip()

    tg_ready = bool(tg_token and tg_chat)
    ul_ready = bool(ul_token)

    ch_tg = state.get("ch_tg", False)
    ch_ul = state.get("ch_ul", False)
    last_text = state.get("last_text", "")
    status_msg = state.get("status_msg", "")
    status_type = state.get("status_type", "")

    html = _build_html(tg_ready, ul_ready, ch_tg, ch_ul, last_text, status_msg, status_type)
    return {"html": html, "state": state}


# ------------------------------------------------------------------ #
#  on_action()
# ------------------------------------------------------------------ #

def on_action(action: str, payload: dict, config: dict, state: dict) -> dict:
    """处理用户交互"""

    if action == "toggle_tg":
        # 保留用户正在键入的文字
        state["last_text"] = payload.get("text", state.get("last_text", ""))
        state["ch_tg"] = not state.get("ch_tg", False)
        state["status_msg"] = ""
        state["status_type"] = ""
        return render(config, state)

    if action == "toggle_ul":
        state["last_text"] = payload.get("text", state.get("last_text", ""))
        state["ch_ul"] = not state.get("ch_ul", False)
        state["status_msg"] = ""
        state["status_type"] = ""
        return render(config, state)

    if action == "send":
        text = (payload.get("text") or "").strip()
        state["last_text"] = text
        state["status_msg"] = ""
        state["status_type"] = ""

        if not text:
            state["status_msg"] = "请输入消息内容"
            state["status_type"] = "err"
            return render(config, state)

        channels = []
        if state.get("ch_tg"):
            channels.append("telegram")
        if state.get("ch_ul"):
            channels.append("uliao")

        if not channels:
            state["status_msg"] = "请先选择发送渠道（点击渠道按钮切换）"
            state["status_type"] = "err"
            return render(config, state)

        results = {}
        for ch in channels:
            if ch == "telegram":
                results[ch] = _send_telegram(config, text)
            elif ch == "uliao":
                results[ch] = _send_uliao(config, text)

        successes = [k for k, v in results.items() if v is True]
        failures = [(k, v) for k, v in results.items() if v is not True]

        add_log(f"消息发送: text={text[:50]}..., ok={successes}, fail={[f[0] for f in failures]}")

        if len(failures) == 0:
            state["status_msg"] = f"✅ 已发送 → {', '.join(successes)}"
            state["status_type"] = "ok"
            state["last_text"] = ""
        elif len(successes) == 0:
            detail = " | ".join(f"{k}: {v}" for k, v in failures)
            state["status_msg"] = f"❌ 发送失败 — {detail}"
            state["status_type"] = "err"
        else:
            detail = " | ".join(f"{k}: {v}" for k, v in failures)
            state["status_msg"] = f"⚠️ 部分成功: {', '.join(successes)} 已发送 | {detail}"
            state["status_type"] = "partial"

        return render(config, state)

    return {"state": state}


# ------------------------------------------------------------------ #
#  发送实现（均走 Clash 代理）
# ------------------------------------------------------------------ #

def _send_telegram(config: dict, text: str):
    """通过 Telegram Bot API 发送消息。"""
    token = config.get("telegram_token", "").strip()
    chat_id = str(config.get("telegram_chat_id", "")).strip()
    if not token or not chat_id:
        return "未配置 Token / Chat ID"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps(
        {"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        ensure_ascii=False,
    )
    data = body.encode("utf-8")

    try:
        try:
            opener = _build_opener(use_proxy=True)
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/json; charset=utf-8")
            resp = opener.open(req, timeout=10)
        except Exception:
            opener = _build_opener(use_proxy=False)
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/json; charset=utf-8")
            resp = opener.open(req, timeout=10)

        with resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("ok"):
                return True
            return result.get("description", f"API 返回异常 (code={result.get('error_code')})")
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            detail = str(e)
        return f"HTTP {e.code}: {detail}"
    except Exception as e:
        return f"网络错误: {e}"


def _send_uliao(config: dict, text: str):
    """通过 U聊 群机器人 Webhook 发送消息。"""
    token = config.get("uliao_token", "").strip()
    if not token:
        return "未配置 Token"

    url = "https://upchat.95516.net/upchat-public-gateway/api/app/webhooks"
    body = urllib.parse.urlencode({"apikey": token, "content": text})
    data = body.encode("utf-8")

    try:
        try:
            opener = _build_opener(use_proxy=False)
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=utf-8")
            resp = opener.open(req, timeout=10)
        except Exception:
            opener = _build_opener(use_proxy=True)
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=utf-8")
            resp = opener.open(req, timeout=10)

        with resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("status") == "0":
                return True
            return result.get("msg", "未知错误")
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            detail = str(e)
        return f"HTTP {e.code}: {detail}"
    except Exception as e:
        return f"网络错误: {e}"


# ------------------------------------------------------------------ #
#  HTML 构建
# ------------------------------------------------------------------ #

def _build_html(
    tg_ready: bool,
    ul_ready: bool,
    ch_tg: bool,
    ch_ul: bool,
    last_text: str,
    status_msg: str,
    status_type: str,
) -> str:
    """构建完整的 HTML 界面"""

    def _ch_btn(name: str, icon: str, active: bool, ready: bool, action: str) -> str:
        if not ready:
            return f"""<span class="msg-ch-btn disabled" title="请在设置中配置 Token">
                <span class="msg-ch-icon">{icon}</span> {name} <small>(未配置)</small>
            </span>"""
        cls = "active" if active else ""
        return f"""<button class="msg-ch-btn {cls}" data-action="{action}">
            <span class="msg-ch-icon">{icon}</span> {name}
        </button>"""

    tg_btn = _ch_btn("Telegram", "✈️", ch_tg, tg_ready, "toggle_tg")
    ul_btn = _ch_btn("U聊", "💬", ch_ul, ul_ready, "toggle_ul")

    status_html = ""
    if status_msg:
        status_html = f'<div class="msg-status show {status_type}">{status_msg}</div>'
    else:
        status_html = '<div class="msg-status"></div>'

    safe_text = (
        last_text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

    return f"""<style>
.msg-root {{
    display: flex; flex-direction: column;
    height: 100%; width: 100%;
    box-sizing: border-box;
    padding: 10px; gap: 8px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}}
.msg-textarea {{
    flex: 1; min-height: 50px;
    resize: none;
    border: 1px solid var(--color-border);
    border-radius: 6px;
    padding: 10px;
    font-size: 13px;
    font-family: inherit;
    background: var(--color-surface);
    color: var(--color-text);
    outline: none;
    line-height: 1.5;
    transition: border-color 0.2s;
}}
.msg-textarea:focus {{ border-color: var(--color-primary); }}
.msg-channels {{
    display: flex; gap: 8px; flex-wrap: wrap;
}}
.msg-ch-btn {{
    display: flex; align-items: center; gap: 5px;
    padding: 5px 12px;
    border: 1px solid var(--color-border);
    border-radius: 6px;
    background: var(--color-surface);
    color: var(--color-text);
    cursor: pointer;
    font-size: 12px;
    font-family: inherit;
    transition: all 0.15s;
    white-space: nowrap;
    line-height: 1.4;
}}
.msg-ch-btn:hover {{ border-color: var(--color-primary); background: var(--color-surface-hover); }}
.msg-ch-btn.active {{
    border-color: var(--color-primary);
    background: var(--color-primary);
    color: #fff;
}}
.msg-ch-btn.disabled {{
    opacity: 0.4; cursor: not-allowed; text-decoration: none;
    border-style: dashed;
    background: transparent;
    color: var(--color-text-muted);
    font-size: 11px;
}}
.msg-ch-icon {{ font-size: 14px; }}
.msg-actions {{
    display: flex; gap: 8px; align-items: center;
}}
.msg-send-btn {{
    padding: 7px 24px;
    background: var(--color-primary);
    color: #fff;
    border: none;
    border-radius: 6px;
    cursor: pointer;
    font-size: 13px;
    font-weight: 600;
    font-family: inherit;
    transition: opacity 0.2s;
    white-space: nowrap;
}}
.msg-send-btn:hover {{ opacity: 0.85; }}
.msg-send-btn:active {{ opacity: 0.7; }}
.msg-char-count {{
    font-size: 11px; color: var(--color-text-muted);
    margin-left: auto;
}}
.msg-status {{
    font-size: 12px; padding: 6px 10px;
    border-radius: 4px;
    display: none;
    word-break: break-all;
    line-height: 1.4;
}}
.msg-status.show {{ display: block; }}
.msg-status.ok    {{ background: #e6ffe6; color: #237804; }}
.msg-status.err   {{ background: #fff1f0; color: #cf1322; }}
.msg-status.partial {{ background: #fffbe6; color: #ad6800; }}
</style>

<div class="msg-root">
    <textarea class="msg-textarea"
              placeholder="输入要发送的消息..."
              data-input="text"
              maxlength="4000"
              oninput="(function(t){{ var s=t.parentElement.querySelector('.msg-char-count'); if(s)s.textContent=t.value.length+'/4000'; }})(this)">{safe_text}</textarea>

    <div class="msg-channels">
        {tg_btn}
        {ul_btn}
    </div>

    <div class="msg-actions">
        <button class="msg-send-btn" data-action="send">发送</button>
        <span class="msg-char-count">0/4000</span>
    </div>

    {status_html}
</div>
"""
