import os
import csv
import random
import datetime
import requests
import threading
from log_store import add_log

META = {
    "name": "交易模拟器",
    "description": "本地历史数据高频回测训练游戏",
    "tags": ["行情交易"],
    "icon": "🎮",
    "default_size": [80, 50],
    "min_size": [60, 40],
    "max_size": [9999, 9999],
    "refresh_interval": 0,
    "config_fields": [
        {"key": "symbol", "label": "交易对", "type": "select", "options": ["BTCUSDT", "ETHUSDT"], "default": "BTCUSDT"},
        {"key": "initial_capital", "label": "初始本金 ($)", "type": "number", "default": 10000},
        {"key": "leverage", "label": "杠杆倍数", "type": "number", "default": 1}
    ]
}

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "historical")
os.makedirs(DATA_DIR, exist_ok=True)

_CACHE = {}
_DOWNLOAD_TASKS = {}

def bg_download(symbol, year_month):
    task_key = f"{symbol}_{year_month}"
    _DOWNLOAD_TASKS[task_key] = "downloading"
    try:
        download_binance_data(symbol, year_month)
        _DOWNLOAD_TASKS[task_key] = "done"
    except Exception as e:
        add_log(f"后台下载异常: {e}")
        _DOWNLOAD_TASKS[task_key] = "failed"

def get_random_month():
    import glob
    files = glob.glob(os.path.join(DATA_DIR, "*_5m_*.csv"))
    available_months = []
    for f in files:
        basename = os.path.basename(f)
        # e.g. BTCUSDT_5m_2022-05.csv
        parts = basename.split('_')
        if len(parts) >= 3:
            month_part = parts[2].replace('.csv', '')
            available_months.append(month_part)
            
    if available_months:
        return random.choice(available_months)
    return "2022-05"

def download_binance_data(symbol, year_month):
    year, month = map(int, year_month.split('-'))
    start_date = datetime.datetime(year, month, 1)
    if month == 12:
        end_date = datetime.datetime(year + 1, 1, 1)
    else:
        end_date = datetime.datetime(year, month + 1, 1)

    start_ts = int(start_date.timestamp() * 1000)
    end_ts = int(end_date.timestamp() * 1000)

    file_path = os.path.join(DATA_DIR, f"{symbol}_5m_{year_month}.csv")
    if os.path.exists(file_path):
        return file_path

    add_log(f"开始下载 {symbol} {year_month} 历史数据...")

    current_ts = start_ts
    all_candles = []

    while current_ts < end_ts:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=5m&startTime={current_ts}&endTime={end_ts}&limit=1000"
        try:
            res = requests.get(url, timeout=10)
            data = res.json()
            if not data or not isinstance(data, list):
                break
            all_candles.extend(data)
            current_ts = data[-1][0] + 1
        except Exception as e:
            add_log(f"下载失败: {e}")
            break

    if all_candles:
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["time", "open", "high", "low", "close", "volume"])
            for c in all_candles:
                writer.writerow([c[0], c[1], c[2], c[3], c[4], c[5]])
        add_log(f"缓存成功: {year_month} 共 {len(all_candles)} 根 K线")
    return file_path

def get_candle(symbol, year_month, index):
    cache_key = f"{symbol}_{year_month}"

    if cache_key not in _CACHE:
        file_path = os.path.join(DATA_DIR, f"{symbol}_5m_{year_month}.csv")
        if not os.path.exists(file_path):
            return None
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = list(csv.reader(f))
            _CACHE[cache_key] = reader[1:]  # skip header

    candles = _CACHE[cache_key]
    if index < len(candles):
        return candles[index]
    return None


# ============================================================
#  渲染 — 纯数据驱动，不嵌入任何 <script>
# ============================================================

def render(config: dict, state: dict) -> dict:
    """
    返回纯 HTML 骨架。所有图表逻辑由前端 simulator-engine.js 驱动。
    在此直接将状态数据渲染到 HTML 中，避免前端初始的 init_check 失败导致界面一直显示 $0.00。
    """
    symbol = config.get("symbol", "BTCUSDT")
    capital = float(config.get("initial_capital", 10000))
    
    # 获取要渲染的数据
    balance = state.get("balance", capital)
    pnl = state.get("pnl", 0.0)
    equity = balance + pnl
    tick_index = state.get("tick_index", 0)
    month = state.get("month", "")
    
    title_text = f"{symbol} [{month}]" if month else "等待开始..."
    
    html = f"""
    <div class="sim-root" style="display:flex; width:100%; height:100%; position:relative; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
        <!-- 图表区 -->
        <div class="sim-chart-area" style="flex:1; min-width:0; min-height:0; overflow:hidden; position:relative;"></div>

        <!-- 控制面板 -->
        <div class="sim-panel" style="width:210px; flex-shrink:0; border-left:1px solid var(--color-border); display:flex; flex-direction:column; background:var(--color-surface-elevated); overflow-y:auto;">
            <div style="padding:12px; border-bottom:1px solid var(--color-border); text-align:center;">
                <div class="sim-title" style="font-size:13px; font-weight:bold;">{title_text}</div>
                <div style="font-size:11px; color:var(--color-text-tertiary);">进度: <span class="sim-progress">{tick_index}</span> 根 K线</div>
            </div>
            <div style="padding:12px; border-bottom:1px solid var(--color-border);">
                <div style="font-size:11px; color:var(--color-text-tertiary);">账户净值</div>
                <div class="sim-equity" style="font-size:18px; font-weight:bold; color:var(--color-primary);">${equity:.2f}</div>
            </div>
            <div style="padding:12px; border-bottom:1px solid var(--color-border);">
                <div style="font-size:11px; color:var(--color-text-tertiary);">可用余额</div>
                <div class="sim-balance" style="font-size:15px; font-weight:bold;">${balance:.2f}</div>
            </div>
            <div style="padding:12px; border-bottom:1px solid var(--color-border);">
                <div style="font-size:11px; color:var(--color-text-tertiary);">浮动盈亏</div>
                <div class="sim-pnl" style="font-size:16px; font-weight:bold; color:var(--color-text-tertiary);">{pnl:.2f}</div>
            </div>
            <div style="padding:12px; border-bottom:1px solid var(--color-border);">
                <div style="font-size:11px; color:var(--color-text-tertiary);">当前持仓</div>
                <div class="sim-position" style="font-size:12px; margin-top:4px; font-weight:bold;">空仓</div>
            </div>

            <div style="padding:12px; display:flex; flex-direction:column; gap:8px;">
                <button data-action="buy" style="background:rgba(0,184,148,0.1); color:#00b894; border:1px solid #00b894; padding:7px; border-radius:6px; cursor:pointer; font-weight:600; font-size:12px;">▲ 全仓做多</button>
                <button data-action="sell" style="background:rgba(255,118,117,0.1); color:#ff7675; border:1px solid #ff7675; padding:7px; border-radius:6px; cursor:pointer; font-weight:600; font-size:12px;">▼ 全仓做空</button>
                <button data-action="close_pos" style="background:var(--color-surface-hover); color:var(--color-text-secondary); border:1px solid var(--color-border); padding:7px; border-radius:6px; cursor:pointer; font-size:12px;">⊘ 一键平仓</button>
            </div>

            <div style="padding:12px; margin-top:auto; display:flex; flex-direction:column; gap:8px; border-top:1px solid var(--color-border);">
                <button data-action="toggle_play" class="sim-play-btn" style="background:var(--color-primary); color:#fff; border:none; padding:9px; border-radius:6px; cursor:pointer; font-weight:600; font-size:13px;">▶ 开始播放</button>
                <button data-action="restart" style="background:var(--color-surface-hover); color:var(--color-text-secondary); border:1px solid var(--color-border); padding:9px; border-radius:6px; cursor:pointer; font-size:12px;">🎲 重开一局</button>
            </div>
        </div>

        <!-- Game Over Overlay -->
        <div class="sim-overlay" style="display:none; position:absolute; top:0; left:0; right:210px; bottom:0; background:rgba(0,0,0,0.75); z-index:100; flex-direction:column; align-items:center; justify-content:center; color:white; backdrop-filter:blur(4px);">
            <div class="sim-overlay-title" style="font-size:28px; font-weight:bold; margin-bottom:12px;">GAME OVER</div>
            <div class="sim-overlay-desc" style="font-size:16px; margin-bottom:20px; opacity:0.9;"></div>
            <button data-action="restart" style="background:#4f6ef7; color:#fff; border:none; padding:10px 24px; border-radius:8px; cursor:pointer; font-size:14px; font-weight:600;">🎲 再玩一次</button>
        </div>

        <!-- 隐藏的触发器，供前端引擎调用 -->
        <button class="sim-trigger-tick" data-action="tick" style="display:none;"></button>
        <button class="sim-trigger-init_check" data-action="init_check" style="display:none;"></button>
    </div>
    """
    
    script = """
    <script>
        setTimeout(() => {
            const chartArea = document.querySelector('.sim-chart-area');
            const canvas = chartArea ? chartArea.querySelector('canvas') : null;
            let msg = "诊断信息2:\\n";
            msg += "LWCharts: " + (window.LightweightCharts ? "已加载" : "未加载") + "\\n";
            
            const scriptTag = document.querySelector('script[src*="lightweight-charts"]');
            if (scriptTag) {
                msg += "Script src: " + scriptTag.src + "\\n";
            } else {
                msg += "Script tag NOT FOUND in DOM\\n";
            }
            
            // 显示在 title 上面
            const titleEl = document.querySelector('.sim-title');
            if (titleEl) {
                const diag = document.createElement('div');
                diag.style.color = 'red';
                diag.style.fontSize = '12px';
                diag.style.fontWeight = 'bold';
                diag.innerText = msg;
                titleEl.parentElement.appendChild(diag);
            }
        }, 1500);
    </script>
    """
    return {"html": html + script, "state": state}


# ============================================================
#  交易引擎
# ============================================================

def calculate_pnl(state, current_price):
    if not state.get("position") or state.get("amount", 0) == 0:
        return 0.0
    amount = state["amount"]
    entry = state["entry_price"]
    if state["position"] == "LONG":
        return (current_price - entry) * amount
    else:
        return (entry - current_price) * amount

def check_liquidation(state, pnl):
    return (state["balance"] + pnl) <= 0

def on_action(action: str, payload: dict, config: dict, state: dict) -> dict:
    symbol = config.get("symbol", "BTCUSDT")
    capital = float(config.get("initial_capital", 10000))
    leverage = float(config.get("leverage", 1))

    if action == "init_check":
        if state.get("download_status") == "downloading":
            task_key = f"{state['symbol']}_{state['month']}"
            status = _DOWNLOAD_TASKS.get(task_key)
            if status == "done":
                state["download_status"] = "done"
                idx = state.get("tick_index", 50)
                initial = []
                for i in range(idx):
                    c = get_candle(state["symbol"], state["month"], i)
                    if c: initial.append(c)
                return {"state": state, "initial_candles": initial}
            elif status == "failed":
                state["download_status"] = "failed"
                state["month"] = ""
                return {"state": state, "error": "下载失败"}
            else:
                return {"state": state}
                
        if not state.get("month"):
            # 不自动下载，返回空闲状态，让用户手动点 restart
            state = {
                "symbol": symbol,
                "month": "",
                "tick_index": 0,
                "balance": capital,
                "position": None,
                "entry_price": 0.0,
                "amount": 0.0,
                "pnl": 0.0,
                "is_playing": False,
                "download_status": "idle"
            }
            return {"state": state}
        else:
            # 恢复已有的图表数据
            idx = state.get("tick_index", 50)
            month = state["month"]
            # 如果本地没有文件，说明数据丢了，重置
            file_path = os.path.join(DATA_DIR, f"{symbol}_5m_{month}.csv")
            if not os.path.exists(file_path):
                state["month"] = ""
                state["tick_index"] = 0
                return {"state": state}
                
            initial = []
            for i in range(idx):
                c = get_candle(symbol, month, i)
                if c:
                    initial.append(c)
            return {"state": state, "initial_candles": initial}

    if action == "restart":
        month = get_random_month()
        
        state = {
            "symbol": symbol,
            "month": month,
            "tick_index": 50,
            "balance": capital,
            "position": None,
            "entry_price": 0.0,
            "amount": 0.0,
            "pnl": 0.0,
            "is_playing": False,
            "download_status": "downloading"
        }
        
        threading.Thread(target=bg_download, args=(symbol, month)).start()
        
        return {"state": state}

    if action == "toggle_play":
        state["is_playing"] = not state.get("is_playing", False)
        return {"state": state}

    if action == "tick":
        if not state.get("is_playing"):
            return {"state": state}

        idx = state.get("tick_index", 50)
        c = get_candle(state["symbol"], state["month"], idx)

        if not c:
            state["is_playing"] = False
            final_equity = state['balance'] + state['pnl']
            return {
                "state": state,
                "game_over": True,
                "game_over_title": "当月结束",
                "game_over_color": "#00b894",
                "game_over_desc": f"最终净值: ${final_equity:.2f}"
            }

        current_price = float(c[4])
        pnl = calculate_pnl(state, current_price)
        state["pnl"] = pnl

        if check_liquidation(state, pnl):
            state["is_playing"] = False
            state["balance"] = 0
            state["pnl"] = 0
            state["position"] = None
            return {
                "state": state,
                "new_candle": c,
                "game_over": True,
                "game_over_title": "💥 爆仓",
                "game_over_color": "#ff7675",
                "game_over_desc": "亏损超过本金，您已破产"
            }

        state["tick_index"] = idx + 1
        return {"state": state, "new_candle": c}

    # Trading Actions
    if action in ["buy", "sell", "close_pos"]:
        idx = state.get("tick_index", 50)
        c = get_candle(state["symbol"], state["month"], idx - 1)
        if not c:
            return {"state": state}

        current_price = float(c[4])

        if state.get("position"):
            pnl = calculate_pnl(state, current_price)
            state["balance"] += pnl
            state["position"] = None
            state["entry_price"] = 0.0
            state["amount"] = 0.0
            state["pnl"] = 0.0
            add_log(f"平仓完成, PnL: {pnl:.2f}, Balance: {state['balance']:.2f}")

        if action == "close_pos":
            return {"state": state}

        equity = state["balance"]
        if equity <= 0:
            return {"state": state}

        amount = (equity * leverage) / current_price

        state["position"] = "LONG" if action == "buy" else "SHORT"
        state["entry_price"] = current_price
        state["amount"] = amount
        state["pnl"] = 0.0

        add_log(f"开仓 {state['position']} 价格 {current_price:.2f} 数量 {amount:.4f}")

    return {"state": state}
