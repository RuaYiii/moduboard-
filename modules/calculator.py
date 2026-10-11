"""
ModuBoard 计算器模块
标准四则运算计算器，通过 on_action 处理按键事件，状态保存在 state 中。
"""

import re

# ------------------------------------------------------------------ #
#  模块元数据
# ------------------------------------------------------------------ #

META = {
    "name": "计算器",
    "icon": "🧮",
    "description": "标准四则运算计算器",
    "tags": ["实用工具"],
    "default_size": [24, 40],
    "min_size": [24, 32],
    "max_size": [9999, 9999],
    "refresh_interval": 0,
    "config_fields": [],
}

# ------------------------------------------------------------------ #
#  默认状态
# ------------------------------------------------------------------ #

DEFAULT_STATE: dict = {
    "display": "0",       # 当前显示值
    "expression": "",     # 正在构建的完整表达式
    "last_result": None,  # 上次计算结果
    "new_input": True,    # 下一个数字是否开始新输入
}

# 安全表达式校验：只允许数字、运算符、小数点、括号、空格
SAFE_EXPR_PATTERN = re.compile(r'^[\d\+\-\*/\.\(\)\s]+$')


def _ensure_state(state: dict) -> dict:
    """确保 state 拥有所有必要的键"""
    for key, default_val in DEFAULT_STATE.items():
        if key not in state:
            state[key] = default_val
    return state


def _safe_eval(expression: str) -> str:
    """
    安全地计算数学表达式。
    只允许数字、基本运算符、小数点和括号。
    """
    if not expression or not expression.strip():
        return "0"

    # 将显示用的运算符替换为 Python 运算符
    expr = expression.replace("×", "*").replace("÷", "/")

    # 安全检查
    if not SAFE_EXPR_PATTERN.match(expr):
        return "Error"

    try:
        # 使用受限的命名空间执行计算
        result = eval(expr, {"__builtins__": {}}, {})

        # 处理除以零
        if isinstance(result, float) and (result == float('inf') or result == float('-inf')):
            return "Error"

        # 如果结果是整数浮点数（如 4.0），显示为整数
        if isinstance(result, float) and result == int(result) and abs(result) < 1e15:
            return str(int(result))

        # 限制小数位数
        if isinstance(result, float):
            # 去掉末尾多余的零
            formatted = f"{result:.10g}"
            return formatted

        return str(result)
    except ZeroDivisionError:
        return "Error"
    except Exception:
        return "Error"


# ------------------------------------------------------------------ #
#  模块接口
# ------------------------------------------------------------------ #

def render(config: dict, state: dict) -> dict:
    """
    渲染计算器界面。

    返回包含 HTML 的字典，HTML 中的每个按钮都有 data-action 和 data-payload 属性。
    """
    state = _ensure_state(state)
    display = state["display"]
    expression = state["expression"]

    html = _build_html(display, expression)
    return {"html": html, "state": state}


def on_action(action: str, payload: dict, config: dict, state: dict) -> dict:
    """
    处理计算器按键动作。

    Args:
        action:  固定为 "press"
        payload: {"key": "按键值"}
        config:  模块配置（计算器不使用）
        state:   当前状态

    Returns:
        包含更新后 HTML 和 state 的字典
    """
    state = _ensure_state(state)
    key = payload.get("key", "")

    if not key:
        return render(config, state)

    # 如果当前显示为 Error，除了 C 以外的按键都忽略
    if state["display"] == "Error" and key != "C":
        return render(config, state)

    # 按键分发处理
    if key in "0123456789":
        _handle_digit(state, key)
    elif key == ".":
        _handle_decimal(state)
    elif key in "+-×÷":
        _handle_operator(state, key)
    elif key == "=":
        _handle_equals(state)
    elif key == "C":
        _handle_clear(state)
    elif key == "±":
        _handle_negate(state)
    elif key == "%":
        _handle_percent(state)

    return render(config, state)


# ------------------------------------------------------------------ #
#  按键处理逻辑
# ------------------------------------------------------------------ #

def _handle_digit(state: dict, digit: str) -> None:
    """处理数字键"""
    if state["new_input"]:
        state["display"] = digit
        state["new_input"] = False
    else:
        if state["display"] == "0":
            state["display"] = digit
        else:
            state["display"] += digit


def _handle_decimal(state: dict) -> None:
    """处理小数点"""
    if state["new_input"]:
        state["display"] = "0."
        state["new_input"] = False
    elif "." not in state["display"]:
        state["display"] += "."


def _handle_operator(state: dict, op: str) -> None:
    """处理运算符（+, -, ×, ÷）"""
    current = state["display"]

    if state["expression"] and state["new_input"]:
        # 替换上一个运算符
        expr = state["expression"].rstrip()
        if expr and expr[-1] in "+-×÷":
            state["expression"] = expr[:-1] + f" {op} "
        else:
            state["expression"] += f" {op} "
    else:
        # 将当前数值追加到表达式，然后添加运算符
        state["expression"] += f"{current} {op} "

    state["new_input"] = True


def _handle_equals(state: dict) -> None:
    """处理等号，计算结果"""
    current = state["display"]

    if state["expression"]:
        # 完成表达式并计算
        if not state["new_input"]:
            full_expr = state["expression"] + current
        else:
            # 去掉尾部运算符
            full_expr = state["expression"].rstrip()
            if full_expr and full_expr[-1] in "+-×÷":
                full_expr = full_expr[:-1].rstrip()

        result = _safe_eval(full_expr)
        state["display"] = result
        state["expression"] = ""
        state["last_result"] = result if result != "Error" else None
        state["new_input"] = True
    else:
        # 没有表达式，不做计算
        pass


def _handle_clear(state: dict) -> None:
    """处理清除键"""
    state["display"] = "0"
    state["expression"] = ""
    state["last_result"] = None
    state["new_input"] = True


def _handle_negate(state: dict) -> None:
    """处理正负号切换"""
    if state["display"] == "0" or state["display"] == "Error":
        return
    if state["display"].startswith("-"):
        state["display"] = state["display"][1:]
    else:
        state["display"] = "-" + state["display"]


def _handle_percent(state: dict) -> None:
    """处理百分号（当前值除以 100）"""
    try:
        val = float(state["display"])
        result = val / 100
        if result == int(result):
            state["display"] = str(int(result))
        else:
            state["display"] = f"{result:.10g}"
        state["new_input"] = True
    except ValueError:
        state["display"] = "Error"


# ------------------------------------------------------------------ #
#  HTML 模板构建
# ------------------------------------------------------------------ #

def _build_html(display: str, expression: str) -> str:
    """构建计算器的 HTML 界面"""

    # 按钮布局定义: (显示文本, 按键值, CSS额外类, 列跨度)
    buttons = [
        ("C",  "C",  "calc-btn-func",  1),
        ("±",  "±",  "calc-btn-func",  1),
        ("%",  "%",  "calc-btn-func",  1),
        ("÷",  "÷",  "calc-btn-op",    1),
        ("7",  "7",  "calc-btn-num",   1),
        ("8",  "8",  "calc-btn-num",   1),
        ("9",  "9",  "calc-btn-num",   1),
        ("×",  "×",  "calc-btn-op",    1),
        ("4",  "4",  "calc-btn-num",   1),
        ("5",  "5",  "calc-btn-num",   1),
        ("6",  "6",  "calc-btn-num",   1),
        ("-",  "-",  "calc-btn-op",    1),
        ("1",  "1",  "calc-btn-num",   1),
        ("2",  "2",  "calc-btn-num",   1),
        ("3",  "3",  "calc-btn-num",   1),
        ("+",  "+",  "calc-btn-op",    1),
        ("0",  "0",  "calc-btn-num calc-btn-wide", 2),
        (".",  ".",  "calc-btn-num",   1),
        ("=",  "=",  "calc-btn-eq",    1),
    ]

    # 构建按钮 HTML
    buttons_html = ""
    for label, key, css_class, span in buttons:
        payload_json = '{"key":"' + key + '"}'
        span_style = f" style='grid-column: span {span};'" if span > 1 else ""
        buttons_html += (
            f"<button class='calc-btn {css_class}'{span_style} "
            f"data-action='press' data-payload='{payload_json}'>"
            f"{label}</button>\n"
        )

    # 调整显示字体大小：数字过长时缩小
    display_len = len(display)
    if display_len > 12:
        font_size = "1.2em"
    elif display_len > 9:
        font_size = "1.6em"
    elif display_len > 7:
        font_size = "2em"
    else:
        font_size = "2.4em"

    return f"""
<style>
    .calc-container {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        padding: 10px;
        height: 100%;
        box-sizing: border-box;
        display: flex;
        flex-direction: column;
        gap: 8px;
        background: #f8f9fa;
        border-radius: 8px;
    }}
    .calc-display {{
        background: #2c3e50;
        border-radius: 8px;
        padding: 12px 16px;
        text-align: right;
        min-height: 60px;
        display: flex;
        flex-direction: column;
        justify-content: flex-end;
    }}
    .calc-expression {{
        font-size: 0.85em;
        color: #95a5a6;
        min-height: 1.2em;
        word-break: break-all;
    }}
    .calc-value {{
        font-size: {font_size};
        font-weight: 300;
        color: #ecf0f1;
        word-break: break-all;
        line-height: 1.2;
    }}
    .calc-keypad {{
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 6px;
        flex: 1;
    }}
    .calc-btn {{
        border: none;
        border-radius: 6px;
        font-size: 1.2em;
        cursor: pointer;
        padding: 8px;
        transition: all 0.15s;
        display: flex;
        align-items: center;
        justify-content: center;
    }}
    .calc-btn:active {{
        transform: scale(0.95);
    }}
    .calc-btn-num {{
        background: #fff;
        color: #2c3e50;
        border: 1px solid #e0e0e0;
    }}
    .calc-btn-num:hover {{
        background: #f0f0f0;
    }}
    .calc-btn-func {{
        background: #e0e0e0;
        color: #2c3e50;
    }}
    .calc-btn-func:hover {{
        background: #d0d0d0;
    }}
    .calc-btn-op {{
        background: #f39c12;
        color: #fff;
    }}
    .calc-btn-op:hover {{
        background: #e67e22;
    }}
    .calc-btn-eq {{
        background: #27ae60;
        color: #fff;
    }}
    .calc-btn-eq:hover {{
        background: #229954;
    }}
    .calc-btn-wide {{
        grid-column: span 2;
    }}
</style>
<div class="calc-container">
    <div class="calc-display">
        <div class="calc-expression">{expression}&nbsp;</div>
        <div class="calc-value">{display}</div>
    </div>
    <div class="calc-keypad">
        {buttons_html}
    </div>
</div>
"""
