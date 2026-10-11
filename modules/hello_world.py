"""
ModuBoard HelloWorld 示例模块
这是一个简单的演示/模板模块，开发新模块时可以以此为起点。
"""

from datetime import datetime

# ------------------------------------------------------------------ #
#  模块元数据
# ------------------------------------------------------------------ #

META = {
    "name": "HelloWorld",
    "icon": "👋",
    "description": "示例模块 —— 开发新模块的起点",
    "tags": ["系统"],
    "default_size": [32, 24],
    "min_size": [16, 16],
    "max_size": [9999, 9999],
    "refresh_interval": 0,
    "config_fields": [
        {"key": "greeting", "label": "问候语", "type": "text", "default": "你好，世界！"},
        {"key": "color", "label": "文字颜色", "type": "text", "default": "#333333"},
    ],
}

# 预设问候语列表
PRESET_GREETINGS: list[str] = [
    "你好，世界！",
    "Hello, World!",
    "こんにちは世界！",
    "Bonjour le monde!",
    "Hola Mundo!",
    "안녕하세요 세계!",
    "Привет, мир!",
]


# ------------------------------------------------------------------ #
#  模块接口
# ------------------------------------------------------------------ #

def render(config: dict, state: dict) -> dict:
    """
    渲染 HelloWorld 模块。

    显示问候语、当前时间、切换按钮和点击计数器。
    """
    greeting = config.get("greeting", "你好，世界！")
    color = config.get("color", "#333333")
    click_count = state.get("click_count", 0)
    current_index = state.get("current_index", 0)

    # 如果用户已通过按钮切换过问候语，使用切换后的
    if click_count > 0 and 0 <= current_index < len(PRESET_GREETINGS):
        greeting = PRESET_GREETINGS[current_index]

    # 当前时间
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html = _build_html(greeting, color, now_str, click_count)
    return {"html": html, "state": state}


def on_action(action: str, payload: dict, config: dict, state: dict) -> dict:
    """
    处理模块动作。

    支持:
    - cycle_greeting: 切换到下一句预设问候语
    """
    if action == "cycle_greeting":
        click_count = state.get("click_count", 0) + 1
        current_index = state.get("current_index", 0)

        # 循环切换到下一句
        current_index = (current_index + 1) % len(PRESET_GREETINGS)

        state["click_count"] = click_count
        state["current_index"] = current_index

        return render(config, state)

    return {"error": f"未知动作: {action}"}


# ------------------------------------------------------------------ #
#  HTML 模板构建
# ------------------------------------------------------------------ #

def _build_html(greeting: str, color: str, time_str: str, click_count: int) -> str:
    """构建 HelloWorld 模块的 HTML"""
    return f"""
<style>
    .hello-container {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        padding: 20px;
        height: 100%;
        box-sizing: border-box;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 14px;
        text-align: center;
    }}
    .hello-icon {{
        font-size: 2.5em;
        animation: hello-wave 1.5s ease-in-out infinite;
    }}
    @keyframes hello-wave {{
        0%, 100% {{ transform: rotate(0deg); }}
        25% {{ transform: rotate(20deg); }}
        75% {{ transform: rotate(-10deg); }}
    }}
    .hello-greeting {{
        font-size: 1.6em;
        font-weight: 600;
        color: {color};
        transition: color 0.3s;
    }}
    .hello-time {{
        font-size: 0.85em;
        color: #999;
    }}
    .hello-footer {{
        display: flex;
        align-items: center;
        gap: 12px;
        margin-top: 4px;
    }}
    .hello-btn {{
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: #fff;
        border: none;
        border-radius: 20px;
        padding: 6px 16px;
        cursor: pointer;
        font-size: 0.9em;
        transition: transform 0.2s, box-shadow 0.2s;
    }}
    .hello-btn:hover {{
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
    }}
    .hello-btn:active {{
        transform: translateY(0);
    }}
    .hello-counter {{
        font-size: 0.8em;
        color: #aaa;
        background: #f0f0f0;
        padding: 3px 10px;
        border-radius: 12px;
    }}
</style>
<div class="hello-container">
    <div class="hello-icon">👋</div>
    <div class="hello-greeting">{greeting}</div>
    <div class="hello-time">🕐 {time_str}</div>
    <div class="hello-footer">
        <button class="hello-btn" data-action="cycle_greeting">🔄 换一句</button>
        <span class="hello-counter">已切换 {click_count} 次</span>
    </div>
</div>
"""
