import os
import sys

# 把上级目录加入 sys.path 以便导入 log_store
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from log_store import system_logs

META = {
    "name": "系统日志",
    "icon": "📝",
    "description": "显示后端实时接收到的事件日志",
    "tags": ["系统"],
    "default_size": [32, 24],
    "min_size": [24, 16],
    "max_size": [9999, 9999],
    "refresh_interval": 1,  # 每秒刷新一次获取最新日志
    "config_fields": []
}

def render(config: dict, state: dict) -> dict:
    return {"html": _build_html(), "state": state}

def on_action(action: str, payload: dict, config: dict, state: dict) -> dict:
    """
    处理后端动作
    """
    if action == "refresh":
        return render(config, state)
    elif action == "clear":
        system_logs.clear()
        return render(config, state)

    return {"error": f"未知动作: {action}"}


# ------------------------------------------------------------------ #
#  HTML 构建
# ------------------------------------------------------------------ #

def _build_html() -> str:
    """构建日志列表的 HTML"""
    # 提取所有日志
    logs = list(system_logs)
    
    # 构建日志条目 HTML
    logs_html = ""
    for log in reversed(logs):
        if isinstance(log, str):
            timestamp = ""
            message = log
        else:
            timestamp = log.get("timestamp", "")
            message = log.get("message", "")
            
        time_span = f'<span class="syslog-time">[{timestamp}]</span> ' if timestamp else ''
        logs_html += f"""
        <div class="syslog-item">
            {time_span}<span class="syslog-msg">{message}</span>
        </div>
        """
        
    if not logs_html:
        logs_html = '<div class="syslog-empty">暂无系统日志...</div>'

    # 为避免冲突，CSS 类加上 syslog- 前缀
    return f"""
<style>
    .syslog-container {{
        display: flex;
        flex-direction: column;
        height: 100%;
        background-color: var(--color-bg);
        color: var(--color-text);
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        font-size: 13px;
    }}
    .syslog-toolbar {{
        display: flex;
        justify-content: flex-end;
        gap: 8px;
        padding: 4px 8px;
        border-bottom: 1px solid var(--color-border);
        background-color: var(--color-bg-secondary);
    }}
    .syslog-btn {{
        background: none;
        border: 1px solid var(--color-border);
        border-radius: 4px;
        padding: 2px 8px;
        font-size: 12px;
        cursor: pointer;
        color: var(--color-text);
        transition: all 0.2s;
    }}
    .syslog-btn:hover {{
        background-color: var(--color-hover);
    }}
    .syslog-list {{
        flex: 1;
        overflow-y: auto;
        padding: 8px;
    }}
    .syslog-item {{
        margin-bottom: 4px;
        line-height: 1.4;
        word-break: break-all;
    }}
    .syslog-time {{
        color: var(--color-info);
        margin-right: 8px;
    }}
    .syslog-empty {{
        color: var(--color-text-muted);
        text-align: center;
        margin-top: 20px;
    }}
</style>

<div class="syslog-container">
    <div class="syslog-toolbar">
        <button class="syslog-btn" data-action="clear">清空</button>
        <button class="syslog-btn" onclick="
            const logs = Array.from(this.closest('.syslog-container').querySelectorAll('.syslog-item')).map(el => el.innerText).join('\\n');
            navigator.clipboard.writeText(logs).then(() => {{
                const old = this.innerText;
                this.innerText = '已复制!';
                setTimeout(() => this.innerText = old, 2000);
            }});
        ">复制</button>
    </div>
    <div class="syslog-list">
        {logs_html}
    </div>
</div>
"""
