# ModuBoard 开发者文档 (开发者必读)

ModuBoard 提供了一套革命性的“数据驱动渲染 (Data-Driven UI)”架构。
作为模块开发者，你的核心任务是**处理业务逻辑，输出数据对象**，剩下的所有前端展示（排版、适配、CSS、交互）都交由看板底层的 UI 工厂自动完成。

---

## 1. 模块的基本结构

每一个 Python 模块文件都需要存放在 `modules/` 目录下，并且必须包含以下三部分：
1. `META`: 模块的元数据字典。
2. `render(config, state)`: 返回初始界面的函数。
3. `on_action(action, payload, config, state)`: 处理前端交互动作的函数。

---

## 2. 数据驱动渲染协议 (Data-Driven UI)

在过去的架构中，开发者需要在 `render` 中返回拼凑好的 `html` 字符串。现在，你只需要返回一个包含 `ui` 属性的字典。

### 2.1 文本组件 (Text)

如果你的模块仅仅需要展示动态的文本（如时间、温湿度、数字指标），可以直接使用 `text` 类型的渲染器。

**Python 示例：**
```python
def render(config, state):
    # 你的业务逻辑
    value = get_my_data()
    
    return {
        "ui": {
            "type": "text",
            "content": str(value),         # 需要展示的文本内容
            "align": "center",             # 对齐方式: left, center, right
            "size": "large",               # 预设尺寸: small, default(中), large, xlarge
            "color": "var(--color-text)",  # 文字颜色（支持 CSS 变量，便于主题切换）
            "weight": "bold",              # 字体粗细: normal, bold, 300等
            "fontFamily": "monospace"      # 字体风格
        },
        "state": state
    }
```

### 2.2 兼容传统 HTML (回退机制)

如果你需要极其定制化的界面，依然可以使用旧版的 `html` 字段。
只要返回的数据中不包含 `ui` 字段，且包含 `html` 字段，前端将自动回退到传统的 HTML 直出模式。

**Python 示例：**
```python
def render(config, state):
    return {
        "html": "<div style='color:red;'>我是定制界面的模块</div>",
        "state": state
    }
```

---

## 3. 后续扩展蓝图 (开发中)

为了让 ModuBoard 成为最强大的数据面板，我们正在前端的 UI 工厂中陆续增加以下渲染组件：

- **表格 (Table)**: 只需要返回 `{"type": "table", "columns": [...], "data": [[...]]}`，前端将自动生成带有表头锁定、分页、排序的高级表格。
- **K线图/折线图 (Chart)**: 返回 `{"type": "chart", "series": [...]}`，前端将自动调用 ECharts 或 Chart.js 生成可缩放的图表。
- **表单 (Form)**: 返回 `{"type": "form", "fields": [...]}`，前端将自动生成输入框及提交按钮，并且自动绑定后端的 `on_action`。

使用数据驱动的模块将自动享有**未来的所有前端 UI 升级与主题适配**，无需开发者修改任何一行 Python 代码。
