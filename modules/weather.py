"""
ModuBoard 天气模块
使用 Open-Meteo API（无需 API Key）获取实时天气信息。
"""

import requests
import traceback
from datetime import datetime

# ------------------------------------------------------------------ #
#  模块元数据
# ------------------------------------------------------------------ #

META = {
    "name": "今日天气",
    "icon": "🌤️",
    "description": "显示指定城市的实时天气信息",
    "tags": ["实用工具"],
    "default_size": [32, 24],
    "min_size": [24, 16],
    "max_size": [9999, 9999],
    "refresh_interval": 600,
    "config_fields": [
        {"key": "city_name", "label": "城市名称", "type": "text", "default": "黄山"},
        {"key": "lat", "label": "纬度", "type": "number", "default": 29.71},
        {"key": "lon", "label": "经度", "type": "number", "default": 118.34},
    ],
}

# ------------------------------------------------------------------ #
#  WMO 天气代码映射
# ------------------------------------------------------------------ #

WEATHER_CODE_MAP: dict[int, tuple[str, str]] = {
    0:  ("☀️", "晴"),
    1:  ("⛅", "多云"),
    2:  ("⛅", "多云"),
    3:  ("⛅", "多云"),
    45: ("🌫️", "雾"),
    48: ("🌫️", "雾"),
    51: ("🌦️", "毛毛雨"),
    53: ("🌦️", "毛毛雨"),
    55: ("🌦️", "毛毛雨"),
    61: ("🌧️", "雨"),
    63: ("🌧️", "雨"),
    65: ("🌧️", "雨"),
    66: ("🌧️", "冻雨"),
    67: ("🌧️", "冻雨"),
    71: ("🌨️", "雪"),
    73: ("🌨️", "雪"),
    75: ("🌨️", "雪"),
    77: ("🌨️", "雪粒"),
    80: ("🌧️", "阵雨"),
    81: ("🌧️", "阵雨"),
    82: ("🌧️", "阵雨"),
    85: ("🌨️", "阵雪"),
    86: ("🌨️", "阵雪"),
    95: ("⛈️", "雷暴"),
    96: ("⛈️", "雷暴+冰雹"),
    99: ("⛈️", "雷暴+冰雹"),
}


def _get_weather_desc(code: int) -> tuple[str, str]:
    """根据 WMO 天气代码返回 (emoji, 中文描述)"""
    return WEATHER_CODE_MAP.get(code, ("❓", "未知"))


# ------------------------------------------------------------------ #
#  模块接口
# ------------------------------------------------------------------ #

def render(config: dict, state: dict) -> dict:
    """
    渲染天气模块。

    调用 Open-Meteo API 获取天气数据，返回包含 HTML 的字典。
    """
    city_name = config.get("city_name", "黄山")
    lat = config.get("lat", 29.71)
    lon = config.get("lon", 118.34)
    import requests
    
    # 构造 API 请求
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m&daily=temperature_2m_max,temperature_2m_min,weather_code&timezone=auto&forecast_days=1"
    try:
        session = requests.Session()
        # session.trust_env = False # 注释掉，允许通过系统代理访问外网，解决 10053 错误
        response = session.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        return {"html": f"<div class='error-msg' style='padding: 20px; text-align: center; color: var(--color-danger);'>天气数据获取失败，可能是网络环境屏蔽或 API 限制。<br><small style='font-size: 12px; margin-top: 10px; display: block;'>{str(e)}</small></div>", "state": state}
    
    # 解析当前天气
    current = data.get("current", {})
    temp = current.get("temperature_2m", "--")
    humidity = current.get("relative_humidity_2m", "--")
    weather_code = current.get("weather_code", -1)
    wind_speed = current.get("wind_speed_10m", "--")

    # 解析今日预报
    daily = data.get("daily", {})
    temp_max = daily.get("temperature_2m_max", ["--"])[0]
    temp_min = daily.get("temperature_2m_min", ["--"])[0]

    # 天气描述
    icon, desc = _get_weather_desc(weather_code)

    # 当前时间
    now_str = datetime.now().strftime("%H:%M")

    html = _build_html(city_name, temp, icon, desc, humidity, wind_speed, temp_max, temp_min, now_str)

    return {"html": html, "state": state}

    # 正常返回



def on_action(action: str, payload: dict, config: dict, state: dict) -> dict:
    """
    处理天气模块的动作。

    目前支持:
    - refresh: 重新渲染（触发 API 调用）
    """
    if action == "refresh":
        return render(config, state)

    return {"error": f"未知动作: {action}"}


# ------------------------------------------------------------------ #
#  HTML 模板构建
# ------------------------------------------------------------------ #

def _build_html(
    city: str,
    temp: float,
    icon: str,
    desc: str,
    humidity: float,
    wind: float,
    high: float,
    low: float,
    time_str: str,
) -> str:
    """构建天气模块的 HTML"""
    return f"""
<style>
    .weather-container {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        padding: 16px;
        height: 100%;
        box-sizing: border-box;
        display: flex;
        flex-direction: column;
        gap: 10px;
        color: #333;
    }}
    .weather-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
    }}
    .weather-city {{
        font-size: 1.1em;
        font-weight: 600;
        color: #444;
    }}
    .weather-time {{
        font-size: 0.85em;
        color: #999;
    }}
    .weather-main {{
        display: flex;
        align-items: center;
        gap: 12px;
        flex: 1;
    }}
    .weather-icon {{
        font-size: 3em;
        line-height: 1;
    }}
    .weather-temp {{
        font-size: 2.5em;
        font-weight: 300;
        line-height: 1;
    }}
    .weather-temp-unit {{
        font-size: 0.4em;
        vertical-align: super;
        color: #999;
    }}
    .weather-desc {{
        font-size: 1em;
        color: #666;
        margin-left: 4px;
    }}
    .weather-details {{
        display: flex;
        gap: 16px;
        font-size: 0.85em;
        color: #666;
        flex-wrap: wrap;
    }}
    .weather-detail-item {{
        display: flex;
        align-items: center;
        gap: 4px;
    }}
    .weather-footer {{
        display: flex;
        justify-content: space-between;
        align-items: center;
    }}
    .weather-range {{
        font-size: 0.85em;
        color: #888;
    }}
    .weather-refresh-btn {{
        background: none;
        border: 1px solid #ddd;
        border-radius: 6px;
        padding: 4px 10px;
        cursor: pointer;
        font-size: 0.85em;
        color: #666;
        transition: all 0.2s;
    }}
    .weather-refresh-btn:hover {{
        background: #f0f0f0;
        border-color: #ccc;
    }}
</style>
<div class="weather-container">
    <div class="weather-header">
        <span class="weather-city">📍 {city}</span>
        <span class="weather-time">更新于 {time_str}</span>
    </div>
    <div class="weather-main">
        <span class="weather-icon">{icon}</span>
        <div>
            <span class="weather-temp">{temp}<span class="weather-temp-unit">°C</span></span>
            <div class="weather-desc">{desc}</div>
        </div>
    </div>
    <div class="weather-details">
        <span class="weather-detail-item">💧 湿度 {humidity}%</span>
        <span class="weather-detail-item">💨 风速 {wind} km/h</span>
    </div>
    <div class="weather-footer">
        <span class="weather-range">🌡️ {low}° / {high}°</span>
        <button class="weather-refresh-btn" data-action="refresh">🔄 刷新</button>
    </div>
</div>
"""


def _build_error_html(city: str, error: str) -> str:
    """构建错误状态的 HTML"""
    return f"""
<style>
    .weather-container {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        padding: 16px;
        height: 100%;
        box-sizing: border-box;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 12px;
        color: #333;
    }}
    .weather-error-icon {{
        font-size: 2.5em;
    }}
    .weather-error-msg {{
        font-size: 0.9em;
        color: #e74c3c;
        text-align: center;
        word-break: break-all;
    }}
    .weather-refresh-btn {{
        background: none;
        border: 1px solid #ddd;
        border-radius: 6px;
        padding: 4px 10px;
        cursor: pointer;
        font-size: 0.85em;
        color: #666;
        transition: all 0.2s;
    }}
    .weather-refresh-btn:hover {{
        background: #f0f0f0;
        border-color: #ccc;
    }}
</style>
<div class="weather-container">
    <span class="weather-error-icon">⚠️</span>
    <span class="weather-city">📍 {city}</span>
    <span class="weather-error-msg">天气数据获取失败</span>
    <button class="weather-refresh-btn" data-action="refresh">🔄 重试</button>
</div>
"""
