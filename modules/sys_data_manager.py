"""
ModuBoard: quant_data_hub 数据管家模块
直连 quant_data_hub 的 DuckDB 获取数据源健康状态和概况，并通过 action 触发本地 CLI 更新。
"""

import os
import subprocess
import duckdb
import logging
from typing import Any

logger = logging.getLogger(__name__)

META = {
    "name": "Data Hub Admin",
    "icon": "🗄️",
    "description": "本地交易数据仓库管理面板",
    "tags": ["系统"],
    "default_size": [60, 45],
    "min_size": [30, 30],
    "max_size": [9999, 9999],
    "refresh_interval": 0,
    "config_fields": [],
}

# 优先从环境变量读取，未配置则按相对路径推导（支持多电脑同步与自定义路径）
_DEFAULT_DB_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "quant_data_hub", "data", "quant.duckdb"
))
DB_PATH = os.environ.get("QUANT_DB_PATH") or _DEFAULT_DB_PATH

QDH_DIR = os.environ.get("QUANT_DATA_HUB_DIR") or os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "quant_data_hub"
))

def render(config: dict, state: dict) -> dict:
    error = ""
    stats_symbols = []
    stats_bars = []
    total_bars = 0
    db_size = 0
    
    if os.path.exists(DB_PATH):
        db_size = round(os.path.getsize(DB_PATH) / (1024 * 1024), 2)
        try:
            with duckdb.connect(DB_PATH, read_only=True) as con:
                # 统计 symbols 表
                stats_symbols = con.execute(
                    "SELECT asset_class, exchange, count(*), sum(is_active::int) "
                    "FROM symbols GROUP BY asset_class, exchange ORDER BY asset_class, exchange"
                ).fetchall()
                
                # 统计 bars 表
                stats_bars = con.execute(
                    "SELECT asset_class, period, count(*), min(trading_date), max(trading_date) "
                    "FROM bars GROUP BY asset_class, period ORDER BY asset_class, period"
                ).fetchall()
                
                res_total = con.execute("SELECT count(*) FROM bars").fetchone()
                if res_total:
                    total_bars = res_total[0]
        except duckdb.SerializationException as e:
            error = f"DuckDB驱动版本不匹配/后台服务未重启 (后台运行中的server.py尚未加载新版驱动): {e}。请重启 server.py 后台进程！"
        except Exception as e:
            error = f"读取 DuckDB 失败: {str(e)}"
    else:
        error = f"数据库文件未找到: {DB_PATH}"

    last_log = state.get("last_log", "尚未执行任何操作。")
    is_loading = state.get("is_loading", False)

    html = _build_html(stats_symbols, stats_bars, total_bars, db_size, error, last_log, is_loading)
    return {"html": html, "state": state}

def on_action(action: str, payload: dict, config: dict, state: dict) -> dict:
    if action == "run_cli":
        cmd_str = payload.get("cmd", "").strip()
        if not cmd_str:
            return render(config, state)
            
        args = ["python", "-m", "qdh.cli"] + cmd_str.split()
        
        try:
            state["is_loading"] = True
            logger.info(f"Executing: {' '.join(args)} in {QDH_DIR}")
            
            # 同步阻塞调用 CLI
            res = subprocess.run(
                args, cwd=QDH_DIR, capture_output=True, text=True, timeout=120
            )
            
            log = f"> {' '.join(args)}\n"
            if res.stdout:
                log += res.stdout
            if res.stderr:
                log += f"\n[STDERR]\n{res.stderr}"
                
            state["last_log"] = log
            state["is_loading"] = False
        except subprocess.TimeoutExpired:
            state["last_log"] = f"> {' '.join(args)}\n[超时] 进程执行超过 120 秒被终止。"
            state["is_loading"] = False
        except Exception as e:
            state["last_log"] = f"> {' '.join(args)}\n[出错] {str(e)}"
            state["is_loading"] = False
            
    return render(config, state)


def _build_html(stats_symbols, stats_bars, total_bars, db_size, error, last_log, is_loading: bool) -> str:
    # 构建 symbols 表格
    sym_rows = ""
    for r in stats_symbols:
        sym_rows += f"<tr><td>{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td><td>{r[3]}</td></tr>"
        
    # 构建 bars 表格
    bar_rows = ""
    for r in stats_bars:
        bar_rows += f"<tr><td>{r[0]}</td><td>{r[1]}</td><td>{r[2]:,}</td><td>{r[3]}</td><td>{r[4]}</td></tr>"

    loading_overlay = ""
    if is_loading:
        loading_overlay = '''
        <div class="qdh-loading">
            <div class="qdh-spinner"></div>
            <div>执行中，请耐心等待...</div>
        </div>
        '''

    html = f"""
    <style>
        .qdh-container {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            padding: 16px;
            color: #333;
            height: 100%;
            overflow-y: auto;
            position: relative;
        }}
        .qdh-dark .qdh-container {{ color: #e5e7eb; }}
        
        .qdh-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }}
        .qdh-card {{
            background: #fff;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            padding: 16px;
        }}
        .qdh-card h3 {{ margin-top: 0; color: #2563eb; font-size: 16px; border-bottom: 1px solid #eee; padding-bottom: 8px; }}
        
        table.qdh-table {{ width: 100%; border-collapse: collapse; font-size: 13px; text-align: left; }}
        .qdh-table th, .qdh-table td {{ padding: 6px 8px; border-bottom: 1px solid #eee; }}
        .qdh-table th {{ background: #f9fafb; font-weight: 600; color: #4b5563; }}
        
        .qdh-log {{
            background: #1e1e1e;
            color: #d4d4d4;
            padding: 12px;
            border-radius: 6px;
            font-family: 'Consolas', monospace;
            font-size: 13px;
            white-space: pre-wrap;
            max-height: 250px;
            overflow-y: auto;
        }}
        
        .qdh-actions {{ display: flex; gap: 10px; margin-bottom: 12px; align-items: center; flex-wrap: wrap; }}
        .qdh-input {{
            padding: 6px 10px;
            border: 1px solid #ccc;
            border-radius: 4px;
            width: 300px;
        }}
        .qdh-btn {{
            background: #2563eb;
            color: white;
            border: none;
            padding: 6px 12px;
            border-radius: 4px;
            cursor: pointer;
            font-weight: 500;
        }}
        .qdh-btn:hover {{ background: #1d4ed8; }}
        
        /* 模态 Loading */
        .qdh-loading {{
            position: absolute; top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(255,255,255,0.7);
            display: flex; flex-direction: column; align-items: center; justify-content: center;
            z-index: 100; font-weight: bold; color: #2563eb;
        }}
        .qdh-spinner {{
            border: 4px solid #f3f3f3; border-top: 4px solid #2563eb;
            border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite;
            margin-bottom: 10px;
        }}
        @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
    </style>
    
    <div class="qdh-container">
        {loading_overlay}
        <div style="display:flex; justify-content: space-between; align-items: baseline;">
            <h2 style="margin-top:0;">quant_data_hub 数据控制台</h2>
            <div style="font-size:14px; color:#666;">
                DB 大小: <b>{db_size} MB</b> &nbsp;|&nbsp; K线总数: <b>{total_bars:,}</b>
            </div>
        </div>
        
        {f'<div style="color:red; margin-bottom:10px;">{error}</div>' if error else ''}
        
        <div class="qdh-card" style="margin-bottom:16px;">
            <h3>执行命令 ( CLI 操作 )</h3>
            <div class="qdh-actions">
                <span>python -m qdh.cli</span>
                <input type="text" id="qdhCmdInput" class="qdh-input" placeholder="例如: update --product FG --periods D" />
                <button class="qdh-btn" onclick="qdhRunCmd()">执行</button>
                <button class="qdh-btn" style="background:#4b5563;" onclick="qdhSetCmd('stats')">快捷: 状态</button>
                <button class="qdh-btn" style="background:#4b5563;" onclick="qdhSetCmd('update --product FG --periods D')">快捷: FG日线增量</button>
            </div>
            
            <div class="qdh-log">{last_log}</div>
        </div>
        
        <div class="qdh-grid">
            <div class="qdh-card">
                <h3>品种与合约分布 (symbols)</h3>
                <table class="qdh-table">
                    <thead><tr><th>资产类型</th><th>交易所</th><th>总合约数</th><th>活跃数</th></tr></thead>
                    <tbody>{sym_rows}</tbody>
                </table>
            </div>
            
            <div class="qdh-card">
                <h3>K 线数量 Top 50</h3>
                <div style="max-height:300px; overflow-y:auto;">
                    <table class="qdh-table">
                        <thead><tr><th>合约</th><th>周期</th><th>行数</th><th>起始时间</th><th>最新时间</th></tr></thead>
                        <tbody>{bar_rows}</tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        function qdhSetCmd(cmd) {{
            document.getElementById('qdhCmdInput').value = cmd;
        }}
        
        function qdhRunCmd() {{
            const cmd = document.getElementById('qdhCmdInput').value;
            if (!cmd) return;
            // 发送 action
            ModuBoard.sendAction('run_cli', {{cmd: cmd}});
        }}
    </script>
    """
    return html
