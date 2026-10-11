from datetime import datetime

META = {
    "name": "极简时钟 (数据驱动)",
    "icon": "⏱️",
    "description": "演示纯数据驱动渲染的文本模块，无需编写任何前端 HTML 代码",
    "tags": ["系统"],
    "default_size": [12, 6],
    "min_size": [8, 4],
    "max_size": [32, 16],
    "refresh_interval": 1,
    "config_fields": []
}

def render(config: dict, state: dict) -> dict:
    """
    直接返回纯数据，前端会自动套用通用文本组件进行渲染。
    无需关心 CSS，无需关心 <div> 等前端标记语言。
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    return {
        "ui": {
            "type": "text",
            "content": now_str,
            "align": "center",
            "size": "large",
            "color": "var(--color-primary)",
            "weight": "bold",
            "fontFamily": "ui-monospace, SFMono-Regular, Consolas, monospace"
        },
        "state": state
    }

def on_action(action: str, payload: dict, config: dict, state: dict) -> dict:
    # 极简时钟没有交互动作
    return render(config, state)
