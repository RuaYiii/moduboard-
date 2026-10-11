# 🧩 ModuBoard — 模块化仪表盘

**ModuBoard** 是一个模块化的可视化仪表盘系统。用户可以在无限画布上自由拖拽、缩放各种功能模块（天气、计算器、笔记等），并支持通过编写 Python 模块来无限扩展功能。

## ✨ 核心特性

- 🧱 **模块化架构** — 每个功能都是独立的 Python 模块，即放即用
- 🔥 **热重载** — 修改模块文件后自动重新加载，无需重启服务
- 🎨 **无限画布** — 模块可以在画布上自由放置、拖动和缩放
- 💾 **配置持久化** — 工作台布局和状态可保存为 JSON 配置文件
- 🌐 **REST API** — 完整的 RESTful 接口，前后端分离设计
- 🛡️ **容错设计** — 单个模块出错不影响整个系统

---

## 🚀 快速开始

### 工业通信工作台（Windows）

1. 首次使用双击 `INSTALL.cmd` 安装运行环境。
2. 双击 `PROTOCOL_SELF_TEST.cmd`，用本机临时服务验证 Modbus TCP 与 OPC UA 协议栈；它不会访问现场设备。
3. 双击 `START_INDUSTRIAL.cmd`，打开 `http://127.0.0.1:5000/industrial`。

工作台默认是“真实设备（只读）”，只开放 Modbus FC01/02/03/04 和 OPC UA Read/Subscription。FC05/06/0F/10 仅能在“离线模拟”中演练。连接参数和点表保存在当前浏览器本机。详细现场检查表见 [FIELD_GUIDE.md](FIELD_GUIDE.md)。

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动服务

```bash
python server.py
```

服务默认运行在 `http://127.0.0.1:5000`。

> **自定义端口**：设置环境变量 `MODUBOARD_PORT=8080` 即可更改端口。服务默认只监听 `127.0.0.1`；确需局域网访问时再显式设置 `MODUBOARD_HOST`。

### 3. 打开浏览器

访问 [http://127.0.0.1:5000](http://127.0.0.1:5000) 即可使用。

如果前端尚未构建，你可以直接调用 API 测试后端功能：

```bash
# 查看已加载的模块
curl http://127.0.0.1:5000/api/modules

# 渲染天气模块
curl -X POST http://127.0.0.1:5000/api/modules/weather/render \
  -H "Content-Type: application/json" \
  -d '{"config": {"city_name": "黄山", "lat": 29.71, "lon": 118.34}, "state": {}}'

# 计算器按键
curl -X POST http://127.0.0.1:5000/api/modules/calculator/action \
  -H "Content-Type: application/json" \
  -d '{"action": "press", "payload": {"key": "5"}, "config": {}, "state": {"display": "0", "expression": "", "last_result": null, "new_input": true}}'
```

---

## 🔧 模块开发教程

### 模块结构

每个模块就是一个 Python 文件，放在 `modules/` 目录下即可自动被发现和加载。

一个最小的模块需要包含以下三个部分：

```python
"""
我的自定义模块
"""

# 1. META 元数据 —— 描述模块的基本信息
META = {
    "name": "模块名称",             # 显示名称
    "icon": "📦",                   # Emoji 图标
    "description": "模块功能说明",   # 简要描述
    "default_size": [4, 3],         # 默认尺寸 [宽, 高]（网格单位）
    "min_size": [2, 2],             # 最小尺寸
    "max_size": [8, 6],             # 最大尺寸
    "refresh_interval": 0,          # 自动刷新间隔（秒），0 = 不自动刷新
    "config_fields": [              # 配置字段定义（会生成设置表单）
        {
            "key": "param_name",    # 字段键名
            "label": "参数标签",    # 显示标签
            "type": "text",         # 类型: text, number, select 等
            "default": "默认值",    # 默认值
        },
    ],
}


# 2. render() —— 渲染模块界面
def render(config: dict, state: dict) -> dict:
    """
    渲染模块 UI。
    
    Args:
        config: 用户配置（来自 META.config_fields）
        state:  模块状态（由 on_action 维护）
    
    Returns:
        {"html": "...", "state": state}
    """
    value = config.get("param_name", "默认值")
    html = f'<div class="mymod-container"><p>{value}</p></div>'
    return {"html": html, "state": state}


# 3. on_action() —— 处理用户交互
def on_action(action: str, payload: dict, config: dict, state: dict) -> dict:
    """
    处理来自前端的交互动作。
    
    HTML 中的按钮通过 data-action 和 data-payload 属性触发:
      <button data-action="do_something" data-payload='{"key":"value"}'>
    
    Args:
        action:  动作名称（对应 data-action）
        payload: 动作数据（对应 data-payload 的 JSON 解析结果）
        config:  用户配置
        state:   当前状态
    
    Returns:
        {"html": "...", "state": updated_state}  通常重新 render
    """
    if action == "do_something":
        # 修改状态
        state["counter"] = state.get("counter", 0) + 1
        return render(config, state)
    
    return {"error": f"未知动作: {action}"}
```

### 开发规范

1. **CSS 类名前缀**：使用模块名作为 CSS 类名前缀（如 `weather-`, `calc-`），避免样式冲突
2. **错误处理**：render 和 on_action 内部做好异常处理，避免未捕获异常
3. **状态管理**：所有需要持久化的数据都放在 `state` 字典中
4. **交互按钮**：使用 `data-action` 和 `data-payload` 属性
5. **热重载**：修改模块文件后，下次调用时会自动重新加载

### 内置模块

| 模块 | 文件 | 功能 |
|------|------|------|
| 🌤️ 今日天气 | `modules/weather.py` | 显示实时天气（Open-Meteo API） |
| 🧮 计算器 | `modules/calculator.py` | 四则运算计算器 |
| 👋 HelloWorld | `modules/hello_world.py` | 示例/模板模块 |
| ⌁ 工业通信请求 | `modules/industrial_debugger.py` | Modbus / OPC 级联配置、地址换算与模拟请求 |
| ≋ 工业数据解析器 | `modules/industrial_decoder.py` | 独立解释原始字节、数据类型与字节序 |

工业协议调试器的审计、能力矩阵、代码边界和增量路线见
[`INDUSTRIAL_DEBUGGER.md`](INDUSTRIAL_DEBUGGER.md)。

---

## 📡 API 参考

### 模块 API

| 方法 | 路径 | 说明 | 请求体 |
|------|------|------|--------|
| GET | `/api/modules` | 列出所有可用模块 | — |
| POST | `/api/modules/<type>/render` | 渲染模块 | `{"config": {}, "state": {}}` |
| POST | `/api/modules/<type>/action` | 调用模块动作 | `{"action": "", "payload": {}, "config": {}, "state": {}}` |

### 配置 API

| 方法 | 路径 | 说明 | 请求体 |
|------|------|------|--------|
| GET | `/api/configs` | 列出所有配置名 | — |
| GET | `/api/configs/<name>` | 获取配置 | — |
| POST | `/api/configs/<name>` | 保存配置 | 配置 JSON |
| DELETE | `/api/configs/<name>` | 删除配置 | — |

### 响应格式

所有 API 响应均为 JSON 格式：

```json
// 成功 - 模块渲染
{
  "html": "<div>...</div>",
  "state": { ... }
}

// 成功 - 配置操作
{
  "message": "配置已保存",
  "name": "default"
}

// 错误
{
  "error": "错误描述信息",
  "detail": "详细错误堆栈（仅在开发模式）"
}
```

---

## 📐 配置格式说明

配置文件存储在 `configs/` 目录下，格式为 JSON。

```json
{
  "name": "工作台名称",
  "created_at": "2026-07-12T00:00:00",
  "theme": "light",
  "grid_size": 80,
  "viewport": {
    "scale": 1.0,
    "offset_x": 0,
    "offset_y": 0
  },
  "modules": [
    {
      "id": "唯一标识",
      "type": "模块类型名（对应 .py 文件名）",
      "grid_x": 1,
      "grid_y": 1,
      "grid_w": 4,
      "grid_h": 3,
      "config": { "模块配置键值对" },
      "state": { "模块运行时状态" }
    }
  ]
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 工作台显示名称 |
| `created_at` | string | 创建时间（ISO 8601） |
| `theme` | string | 主题: `light` 或 `dark` |
| `grid_size` | number | 网格单元大小（像素） |
| `viewport.scale` | number | 画布缩放比例 |
| `viewport.offset_x/y` | number | 画布偏移量 |
| `modules[].id` | string | 模块实例唯一 ID |
| `modules[].type` | string | 模块类型（Python 文件名） |
| `modules[].grid_x/y` | number | 模块在网格上的位置 |
| `modules[].grid_w/h` | number | 模块占用的网格宽高 |
| `modules[].config` | object | 模块配置参数 |
| `modules[].state` | object | 模块运行时状态 |

---

## 📁 项目结构

```
moduboard/
├── server.py           # Flask 后端服务器（入口）
├── module_loader.py    # 模块动态加载器
├── requirements.txt    # Python 依赖
├── README.md           # 项目文档
├── modules/            # 模块目录（放入 .py 即可热加载）
│   ├── weather.py      # 天气模块
│   ├── calculator.py   # 计算器模块
│   └── hello_world.py  # 示例模块
├── configs/            # 配置文件目录
│   └── default.json    # 默认工作台配置
└── static/             # 前端静态文件
    └── index.html      # 前端主页面（待构建）
```

---

## 📝 开发计划

- [x] 后端 Flask 服务器
- [x] 模块动态加载与热重载
- [x] REST API（模块 + 配置管理）
- [x] 天气模块
- [x] 计算器模块
- [x] HelloWorld 示例模块
- [ ] 前端无限画布 UI
- [ ] 模块拖拽与缩放
- [ ] 深色主题支持
- [ ] 更多内置模块（便签、时钟、待办事项……）

---

## 📄 许可证

MIT License
