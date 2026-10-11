---
name: create_moduboard_module
description: How to write and structure a ModuBoard module correctly without breaking the system
---

# ModuBoard Module Development Guidelines

When asked to create or modify a ModuBoard module, strictly follow these guidelines to ensure system stability, performance, and UI consistency.

## 1. File Location & Imports
- Modules must be placed in `d:\code\moduboard\modules\`.
- All modules run within the Flask context.
- **IMPORTANT**: If you need to log, use `from log_store import add_log`. Do NOT use `from utils.log_store import add_log` as `utils` is not a valid package in the root directory.

## 2. The `META` Dictionary
Every module **MUST** define a `META` dictionary at the module level. Without it, the module loader will reject the module.
```python
META = {
    "name": "模块名称",
    "icon": "🚀",
    "description": "模块的简短描述",
    "default_size": [32, 24], # 默认栅格大小 (width, height)
    "min_size": [16, 12],
    "max_size": [64, 48],
    "refresh_interval": 0,    # 0代表不自动刷新。如果要自动刷新，需谨慎设置（单位：秒）
    "config_fields": [
        # 可选配置项
        {"key": "symbol", "label": "交易对", "type": "searchable-text", "default": "SHFE.rb2609"},
    ]
}
```

## 3. The `render` Function
Must return the HTML structure and the state.
```python
def render(config: dict, state: dict) -> dict:
    html = f"""
    <div class="module-root" style="width: 100%; height: 100%;">
        <!-- HTML here -->
    </div>
    """
    return {
        "html": html,
        "state": state
    }
```
*Note on JS execution*: The HTML is injected via `innerHTML`. `<script>` tags inside `html` **WILL** be executed by the `module-renderer.js` engine.

## 4. The `on_action` Function
Handles user interactions (button clicks, form submits, etc.) triggered by `data-action` in the HTML.
```python
def on_action(action: str, payload: dict, config: dict, state: dict) -> dict:
    if action == "do_something":
        # Handle action...
        
        # You can return 'html' to re-render, or 'js' to execute specific client-side code
        js_code = f"""
            var el = document.querySelector('.module-scope-{{id}} .status');
            if (el) el.textContent = 'Action successful!';
        """
        return {"js": js_code, "state": state}
        
    return {"state": state}
```
**CRITICAL**: When targeting elements in `data.js`, always use `.module-scope-{{id}}` to scope your CSS/JS selectors to the current module instance. `{id}` will be dynamically replaced by the frontend.

### 4.1 IMPORTANT: `js` return field is NOT executed by frontend
Despite what the skill says above, the actual `module-renderer.js` only handles:
- `data.html` → injects via innerHTML (replaces `{id}` placeholders)
- `data.ui` → Data-Driven UI rendering
- `data.css` → scoped CSS injection
- `data.state` → update module state

The `js` field in the response is **NOT executed** by the current frontend code. To show status messages or update the UI after an action, you MUST use the **full re-render pattern**: update `state` with the result, then call `render(config, state)` to return new HTML. Example from `sys_messenger.py`:
```python
if action == "send":
    text = payload.get("text", "")
    if not text:
        state["status_msg"] = "请输入消息内容"
        state["status_type"] = "err"
        return render(config, state)
    # ... do work ...
    state["status_msg"] = "✅ 已发送"
    state["status_type"] = "ok"
    return render(config, state)
```

### 4.2 Chart / LightweightCharts Pattern
Do NOT use external engine JS files (like `kline-engine.js`) for chart initialization. The correct pattern is:
1. **Embed candle data directly into the HTML as a JSON variable**
2. **Add an inline `<script>` that polls `window.LightweightCharts` until available**, then initializes the chart:
```python
def render(config, state):
    candles_json = json.dumps(candles)
    html = f"""
    <div id="chart_{{id}}" style="width:100%;height:100%;"></div>
    <script>
    (function() {{
      var DATA = {candles_json};
      function init() {{
        var el = document.getElementById('chart_{{{{id}}}}');  // {id} replaced by renderer
        if (!el || !window.LightweightCharts) return;
        var chart = LightweightCharts.createChart(el, {{ width: el.clientWidth, height: el.clientHeight }});
        var series = chart.addCandlestickSeries();
        series.setData(DATA.map(d => ({{ time: d.time, open: d.open, high: d.high, low: d.low, close: d.close }})));
        chart.timeScale().fitContent();
      }}
      if (window.LightweightCharts) {{ init(); }}
      else {{ var t = setInterval(function(){{ if(window.LightweightCharts){{ clearInterval(t); init(); }} }}, 200); }}
    }})();
    </script>
    """
    return {"html": html, "state": state}
```
When the user switches periods, `on_action` calls the API, gets new data, builds new HTML with new data embedded, and returns it — the `module-renderer.js` reinjects HTML and reruns the script automatically.

### 4.3 Collecting input values in actions
The frontend's `_handleAction` automatically collects all `[data-input]` elements and merges them into `payload`. Use `data-input="fieldname"` on textareas/inputs:
```html
<textarea data-input="text" ...></textarea>
```
The value will appear in `payload["text"]` when the action fires.

## 5. Network & Proxy (this machine)
- **Clash proxy**: `127.0.0.1:7897` (HTTP)
- Both Telegram API and U聊 API require going through the proxy on this machine
- Direct connection (no proxy) to U聊 causes `[WinError 10053]` — connection reset by Clash
- Use `urllib.request.ProxyHandler` + `HTTPSHandler` with SSL cert verification disabled:
```python
def _build_opener():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ph = urllib.request.ProxyHandler({"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"})
    https_h = urllib.request.HTTPSHandler(context=ctx)
    return urllib.request.build_opener(ph, https_h)
```

## 6. Performance Constraints (GIL & Event Loop)
- **Do NOT block the Python GIL**: Synchronous network requests or heavy Pandas computations (e.g., using `akshare`) will block the single-threaded Flask server, causing the entire dashboard (including clock and calculator) to lag.
- If you must fetch data, use a caching mechanism or keep `refresh_interval` large (e.g., >= 15 seconds) for heavy operations.
- Avoid attaching global `window` or `document` event listeners in module scripts unless absolutely necessary, and ensure they are cleaned up, as modules can be created and destroyed dynamically.

## 7. Type Hints
Python 3.9 on this machine. Do NOT use `X | Y` union syntax (3.10+). Use `Optional[X]` or omit return type hints for union types.

## 8. Example Skeleton
```python
import json
from log_store import add_log

META = {
    "name": "Demo",
    "icon": "💡",
    "description": "Demo module",
    "default_size": [16, 12],
    "config_fields": []
}

def render(config: dict, state: dict) -> dict:
    return {
        "html": "<div>Hello World</div>",
        "state": state
    }

def on_action(action: str, payload: dict, config: dict, state: dict) -> dict:
    return {"state": state}
```

## 9. UI & Layout Best Practices (Grid Constraints)
Because modules run within constrained grid items in ModuBoard, you MUST handle overflow correctly:
- **Root Container**: Use `display: flex; flex-direction: column; overflow: hidden; height: 100%; width: 100%;` on the top-level div so it doesn't break the grid.
- **Fixed Headers**: For toolbars or headers, use `flex-shrink: 0;`.
- **Scrollable Body**: For the main content area, use `flex: 1; min-height: 0; overflow-y: auto;`. The `min-height: 0` is critical for Flexbox to allow scrolling instead of expanding the parent.
- **Information Hierarchy**: Prioritize critical numbers. For secondary explanations or raw data tables, use native HTML5 `<details>` and `<summary>` to collapse them by default. This saves precious screen real estate without requiring any JavaScript state management.

## 10. Python F-String & HTML Rendering Gotchas
When generating HTML strings in Python using f-strings (e.g., `f"""..."""`), beware of the following recurring bugs:
- **Bracket Escaping**: Any literal curly braces in your inline CSS or JS (e.g., `function() { ... }` or `chart_{id}`) MUST be escaped as `{{` and `}}` (e.g., `function() {{ ... }}` or `chart_{{id}}`).
- **Quote Collisions**: If your HTML/JS contains triple single quotes `'''`, do NOT use `f'''` for the Python string. Prefer `f"""` (triple double quotes) for large HTML blocks to minimize collision with JS string literals.
- **IndentationErrors**: If a multi-line f-string is accidentally left unclosed, the Python compiler may throw a confusing `IndentationError` or `SyntaxError` on subsequent lines. ALWAYS triple-check your string terminations when refactoring HTML blocks.

## 11. Grouping and Symbol Selection
- **Module Grouping**: Always include a `tags` array in the `META` dictionary (e.g., `"tags": ["行情交易"]`). Without this, your module will not be grouped correctly in the ModuBoard module gallery.
- **Symbol Inputs**: When requiring a user to select a trading symbol, prefer setting the config field type to `"symbol-cascading-select"` instead of `"searchable-text"`. This provides a guided 4-level cascaded dropdown (Category -> Exchange -> Product -> Contract) populated from the system's symbol tree, preventing the user from entering invalid or non-existent contracts like `FG2610`. 
*Note*: The frontend will return a string like `"CZCE.FG501 玻璃501"`. Your backend `render` function should split by space and take the first part (`symbol.split(" ")[0]`) to get the actual code.
