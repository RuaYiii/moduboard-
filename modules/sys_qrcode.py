"""
ModuBoard 二维码生成器模块
将文本/URL 编码为二维码，支持导出 PNG 图片。
"""

import io
import base64
import json
import qrcode


# ------------------------------------------------------------------ #
#  模块元数据
# ------------------------------------------------------------------ #

META = {
    "name": "二维码生成器",
    "icon": "📱",
    "description": "将文本或链接编码为二维码，支持导出图片",
    "tags": ["实用工具"],
    "default_size": [28, 36],
    "min_size": [20, 24],
    "max_size": [9999, 9999],
    "refresh_interval": 0,
    "config_fields": [],
}

# ------------------------------------------------------------------ #
#  默认状态
# ------------------------------------------------------------------ #

DEFAULT_STATE: dict = {
    "text": "",                # 用户输入的文本
    "error_correction": "M",   # 纠错等级: L / M / Q / H
    "status_msg": "",
    "status_type": "",         # "ok" / "err" / ""
}

EC_MAP = {
    "L": qrcode.constants.ERROR_CORRECT_L,
    "M": qrcode.constants.ERROR_CORRECT_M,
    "Q": qrcode.constants.ERROR_CORRECT_Q,
    "H": qrcode.constants.ERROR_CORRECT_H,
}

EC_LABELS = {
    "L": "低 (7%)",
    "M": "中 (15%)",
    "Q": "较高 (25%)",
    "H": "高 (30%)",
}


def _ensure_state(state: dict) -> dict:
    """确保 state 拥有所有必要的键"""
    for key, default_val in DEFAULT_STATE.items():
        if key not in state:
            state[key] = default_val
    return state


def _generate_qr_base64(text: str, ec_level: str) -> str:
    """
    生成二维码并返回 base64 编码的 PNG 数据 URI。
    """
    ec = EC_MAP.get(ec_level, qrcode.constants.ERROR_CORRECT_M)
    qr = qrcode.QRCode(
        version=None,  # 自动选择版本
        error_correction=ec,
        box_size=10,
        border=2,
    )
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1a1a2e", back_color="#ffffff")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


# ------------------------------------------------------------------ #
#  HTML 构建
# ------------------------------------------------------------------ #

def _build_html(text: str, ec_level: str, status_msg: str, status_type: str) -> str:
    """构建二维码生成器的 HTML 界面"""

    # 生成二维码预览（如果有文本）
    if text.strip():
        data_uri = _generate_qr_base64(text, ec_level)
        qr_preview = f"""
    <div class="qr-preview-wrapper">
        <img class="qr-preview-img" src="{data_uri}" alt="QR Code" />
    </div>"""
    else:
        qr_preview = """
    <div class="qr-preview-wrapper qr-empty">
        <div class="qr-empty-icon">⬜</div>
        <div class="qr-empty-text">输入内容后预览二维码</div>
    </div>"""

    # 纠错等级选择按钮
    ec_options = ""
    for key, label in EC_LABELS.items():
        selected = "active" if key == ec_level else ""
        payload = json.dumps({"level": key})
        ec_options += (
            f"<button class='qr-ec-btn {selected}' "
            f"data-action='set_ec' data-payload='{payload}'>"
            f"{label}</button>\n"
        )

    # 状态消息
    status_html = ""
    if status_msg:
        css_cls = status_type if status_type in ("ok", "err") else ""
        status_html = f'<div class="qr-status show {css_cls}">{status_msg}</div>'
    else:
        status_html = '<div class="qr-status"></div>'

    # 字符计数
    char_count = len(text)

    # 安全转义文本
    safe_text = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

    return f"""<style>
.qr-root {{
    display: flex; flex-direction: column;
    height: 100%; width: 100%;
    box-sizing: border-box;
    padding: 10px; gap: 8px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}}
.qr-textarea {{
    min-height: 56px; max-height: 100px;
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
    box-sizing: border-box;
    width: 100%;
}}
.qr-textarea:focus {{ border-color: var(--color-primary); }}
.qr-label {{
    font-size: 11px;
    color: var(--color-text-muted);
    letter-spacing: 0.5px;
}}
.qr-char-count {{
    font-size: 11px;
    color: var(--color-text-muted);
    text-align: right;
    margin-top: 2px;
}}

/* --- Error Correction --- */
.qr-ec-row {{
    display: flex; gap: 6px;
}}
.qr-ec-btn {{
    flex: 1;
    display: flex; align-items: center; justify-content: center;
    padding: 5px 4px;
    border: 1px solid var(--color-border);
    border-radius: 6px;
    background: var(--color-surface);
    color: var(--color-text);
    cursor: pointer;
    font-size: 12px;
    font-family: inherit;
    transition: all 0.15s;
    white-space: nowrap;
}}
.qr-ec-btn:hover {{
    border-color: var(--color-primary);
    background: var(--color-surface-hover);
}}
.qr-ec-btn.active {{
    border-color: var(--color-primary);
    background: var(--color-primary);
    color: #fff;
    font-weight: 600;
}}

/* --- QR Preview --- */
.qr-preview-wrapper {{
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: 8px;
    min-height: 120px;
    overflow: hidden;
}}
.qr-preview-img {{
    max-width: 88%;
    max-height: 88%;
    image-rendering: pixelated;
    border-radius: 4px;
}}
.qr-empty {{
    flex-direction: column; gap: 8px;
}}
.qr-empty-icon {{
    font-size: 2.2em; opacity: 0.25;
}}
.qr-empty-text {{
    font-size: 12px;
    color: var(--color-text-muted);
}}

/* --- Action Buttons --- */
.qr-actions {{
    display: flex; gap: 8px; align-items: center;
}}
.qr-btn-generate {{
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
.qr-btn-generate:hover {{ opacity: 0.85; }}
.qr-btn-generate:active {{ opacity: 0.7; }}
.qr-btn-export {{
    padding: 7px 16px;
    background: var(--color-surface);
    color: var(--color-text);
    border: 1px solid var(--color-border);
    border-radius: 6px;
    cursor: pointer;
    font-size: 13px;
    font-family: inherit;
    transition: all 0.15s;
    white-space: nowrap;
}}
.qr-btn-export:hover {{
    border-color: var(--color-primary);
    background: var(--color-surface-hover);
}}

/* --- Status --- */
.qr-status {{
    font-size: 12px; padding: 6px 10px;
    border-radius: 4px;
    display: none;
    word-break: break-all;
    line-height: 1.4;
}}
.qr-status.show {{ display: block; }}
.qr-status.ok  {{ background: #e6ffe6; color: #237804; }}
.qr-status.err {{ background: #fff1f0; color: #cf1322; }}
</style>

<div class="qr-root">
    <div style="display:flex;flex-direction:column;gap:4px;">
        <span class="qr-label">输入内容</span>
        <textarea class="qr-textarea"
                  placeholder="输入文本、URL、Wi-Fi 信息等…"
                  data-input="text">{safe_text}</textarea>
        <span class="qr-char-count">{char_count} 字符</span>
    </div>

    <div style="display:flex;flex-direction:column;gap:4px;">
        <span class="qr-label">纠错等级</span>
        <div class="qr-ec-row">
            {ec_options}
        </div>
    </div>

    {qr_preview}

    <div class="qr-actions">
        <button class="qr-btn-generate" data-action="generate">生成</button>
        <button class="qr-btn-export" data-action="export">导出 PNG</button>
    </div>

    {status_html}
</div>
"""


# ------------------------------------------------------------------ #
#  模块接口
# ------------------------------------------------------------------ #

def render(config: dict, state: dict) -> dict:
    """渲染二维码生成器界面"""
    state = _ensure_state(state)
    html = _build_html(state["text"], state["error_correction"],
                       state["status_msg"], state["status_type"])
    return {"html": html, "state": state}


def on_action(action: str, payload: dict, config: dict, state: dict) -> dict:
    """处理用户交互"""
    state = _ensure_state(state)

    if action == "generate":
        text = payload.get("text", "").strip()
        if not text:
            state["status_msg"] = "⚠️ 请输入要编码的内容"
            state["status_type"] = "err"
            state["text"] = ""
            return render(config, state)

        state["text"] = text
        state["status_msg"] = "✅ 二维码已生成"
        state["status_type"] = "ok"
        return render(config, state)

    elif action == "set_ec":
        level = payload.get("level", "M")
        if level in EC_MAP:
            state["error_correction"] = level
        # 保留已输入的文本
        text = payload.get("text", "")
        if text:
            state["text"] = text
        state["status_msg"] = ""
        state["status_type"] = ""
        return render(config, state)

    elif action == "export":
        text = payload.get("text", "").strip()
        if not text and not state["text"].strip():
            state["status_msg"] = "⚠️ 请先输入内容并生成二维码"
            state["status_type"] = "err"
            return render(config, state)

        # 使用 payload 中的最新文本
        if text:
            state["text"] = text
        export_text = state["text"]
        ec_level = state["error_correction"]

        # 生成高分辨率导出用的二维码
        ec = EC_MAP.get(ec_level, qrcode.constants.ERROR_CORRECT_M)
        qr = qrcode.QRCode(
            version=None,
            error_correction=ec,
            box_size=20,
            border=3,
        )
        qr.add_data(export_text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#1a1a2e", back_color="#ffffff")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        data_uri = f"data:image/png;base64,{b64}"

        # 通过在 HTML 中嵌入一个自动触发下载的脚本实现导出
        state["status_msg"] = "✅ 正在下载二维码图片…"
        state["status_type"] = "ok"
        result = render(config, state)

        # 注入下载脚本
        download_script = f"""
<script>
(function() {{
    var a = document.createElement('a');
    a.href = '{data_uri}';
    a.download = 'qrcode.png';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}})();
</script>
"""
        result["html"] = result["html"] + download_script
        return result

    return render(config, state)
