import os
import json
import traceback
import urllib.request
import ssl
from datetime import datetime, timedelta
import pandas as pd
import akshare as ak
from log_store import add_log

# ================================================================== #
#  META 配置
# ================================================================== #
META = {
    "name": "主力多空比",
    "icon": "⚖️",
    "description": "监控期货主力合约前20大席位多空力量对比 (COT龙虎榜)",
    "tags": ["行情交易"],
    "default_size": [32, 30],
    "min_size": [24, 20],
    "max_size": [64, 48],
    "refresh_interval": 1800,  # 30分钟，通常盘后更新一次即可
    "config_fields": [
        {
            "key": "symbol",
            "label": "合约",
            "type": "symbol-cascading-select",
            "default": "CZCE.FG501",
            "placeholder": "选择合约"
        },
        {
            "key": "target_date",
            "label": "查询日期",
            "type": "text",
            "default": "",
            "placeholder": "YYYYMMDD，留空则自动获取最新"
        }
    ]
}

# ================================================================== #
#  缓存机制
# ================================================================== #
_CACHE = {}

def get_akshare_data(exchange: str, date_str: str):
    cache_key = f"{exchange}_{date_str}"
    if cache_key in _CACHE:
        return _CACHE[cache_key]
    
    data = None
    try:
        add_log(f"[sys_cot_rank] 正在请求 AKShare {exchange} 龙虎榜数据: {date_str}")
        if exchange == "CZCE":
            data = ak.get_rank_table_czce(date=date_str)
        elif exchange == "SHFE":
            data = ak.get_shfe_rank_table(date=date_str)
        elif exchange == "DCE":
            data = ak.get_dce_rank_table(date=date_str)
        elif exchange == "CFFEX":
            data = ak.get_cffex_rank_table(date=date_str)
        else:
            add_log(f"[sys_cot_rank] 不支持的交易所: {exchange}")
            return None

        # 缓存请求结果
        _CACHE[cache_key] = data
        return data
    except Exception as e:
        add_log(f"[sys_cot_rank] 获取 {exchange} 数据失败: {e}")
        return None

def fetch_latest_data(exchange: str, specific_date: str):
    if specific_date:
        data = get_akshare_data(exchange, specific_date)
        return data, specific_date
        
    dt = datetime.now()
    if dt.hour < 16:
        # 16点前，当天的结算数据肯定还没出，直接往前推一天
        dt = dt - timedelta(days=1)
        
    # 往前找，最多找 7 天
    for _ in range(7):
        if dt.weekday() < 5:  # 周一到周五
            date_str = dt.strftime("%Y%m%d")
            data = get_akshare_data(exchange, date_str)
            if data and isinstance(data, dict) and len(data) > 0:
                return data, date_str
        dt = dt - timedelta(days=1)
        
    return None, ""

def fetch_broker_history(exchange: str, contract_key: str, broker: str, latest_date: str, days: int = 5):
    try:
        dt = datetime.strptime(latest_date, "%Y%m%d")
    except:
        dt = datetime.now()
        
    history = []
    count = 0
    current_dt = dt
    
    while count < days:
        date_str = current_dt.strftime("%Y%m%d")
        if current_dt.weekday() < 5:
            d = get_akshare_data(exchange, date_str)
            if d and isinstance(d, dict) and contract_key in d:
                df = d[contract_key]
                long_pos = 0
                short_pos = 0
                for _, row in df.iterrows():
                    l_name = str(row.get('long_party_name', '')).strip()
                    s_name = str(row.get('short_party_name', '')).strip()
                    
                    if l_name == broker:
                        try: long_pos = float(str(row.get('long_open_interest', '0')).replace(',', ''))
                        except: pass
                    if s_name == broker:
                        try: short_pos = float(str(row.get('short_open_interest', '0')).replace(',', ''))
                        except: pass
                
                net_pos = long_pos - short_pos
                history.append({
                    "date": date_str,
                    "long": long_pos,
                    "short": short_pos,
                    "net": net_pos
                })
                count += 1
            elif d and isinstance(d, dict):
                count += 1
                
        current_dt -= timedelta(days=1)
        if (dt - current_dt).days > 15:
            break
            
    history.reverse()
    return history

# ================================================================== #
#  数据处理与渲染
# ================================================================== #
def render(config: dict, state: dict) -> dict:
    symbol_full = config.get("symbol", "CZCE.FG501").strip()
    
    # symbol-cascading-select 可能返回 "CZCE.FG501 玻璃501"，我们只需要前半部分
    symbol_full = symbol_full.split(" ")[0]
    
    target_date = config.get("target_date", "").strip()

    if "." not in symbol_full:
        return {"html": '<div style="padding:20px;">请配置有效的合约，格式: Exchange.Code (如 CZCE.FG501)</div>', "state": state}
        
    exchange, contract = symbol_full.split(".", 1)
    
    data_dict, valid_date = fetch_latest_data(exchange, target_date)
    
    if not data_dict or not isinstance(data_dict, dict):
        html = f'''
        <div style="padding:20px;display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;">
            <div style="font-size:32px;margin-bottom:10px;">📉</div>
            <div style="color:var(--color-text-secondary);font-size:var(--font-size-sm);">
                未找到 {symbol_full} 的席位龙虎榜数据<br>
                日期: {target_date if target_date else "自动最新"}
            </div>
        </div>
        '''
        return {"html": html, "state": state}
        
    # 提取品种字母前缀和数字
    import re
    match = re.match(r'^([a-zA-Z]+)(\d+)$', contract)
    keys_to_try = [contract, contract.upper(), contract.lower()]
    
    variety = contract
    if match:
        letters = match.group(1)
        digits = match.group(2)
        variety = letters.upper()
        # 处理郑商所3位数字格式 (例如 FG2610 -> FG610)
        if len(digits) == 4:
            short_digits = digits[1:]
            keys_to_try.extend([
                f"{letters}{short_digits}",
                f"{letters.upper()}{short_digits}",
                f"{letters.lower()}{short_digits}"
            ])
            
    df = None
    actual_matched_key = contract
    for k in keys_to_try:
        if k in data_dict:
            df = data_dict[k]
            actual_matched_key = k
            break
            
    # 如果精确匹配失败，智能回退到该品种的主力合约（成交量最大的合约）
    fallback_msg = ""
    if df is None or len(df) == 0:
        best_contract = None
        max_vol = -1
        for k, v_df in data_dict.items():
            if k.upper().startswith(variety) and len(v_df) > 0:
                try:
                    # 计算该合约的总成交量
                    total_vol = v_df['vol'].apply(lambda x: float(str(x).replace(',', '')) if pd.notna(x) else 0).sum()
                    if total_vol > max_vol:
                        max_vol = total_vol
                        best_contract = k
                        df = v_df
                except:
                    pass
        
        if best_contract:
            actual_matched_key = best_contract
            fallback_msg = f'<div style="font-size:11px;color:var(--color-warning);margin-top:4px;background:var(--color-warning-light);padding:2px 6px;border-radius:4px;display:inline-block;">注: {contract} 无数据，已为您展示同品种主力 {best_contract}</div>'
            
    if df is None or len(df) == 0:
        html = f'''
        <div style="padding:20px;display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;">
            <div style="font-size:32px;margin-bottom:10px;">📉</div>
            <div style="color:var(--color-text-secondary);font-size:var(--font-size-sm);">
                合约 {contract} (含 {variety} 品种) 在 {valid_date} 均无龙虎榜数据。
            </div>
        </div>
        '''
        return {"html": html, "state": state}
        
    state["valid_date"] = valid_date
    state["actual_matched_key"] = actual_matched_key

    # -- 数据清洗 --
    longs = []
    for _, row in df.iterrows():
        raw_name = row.get('long_party_name', '')
        if pd.isna(raw_name) or raw_name is None:
            continue
        name = str(raw_name).strip()
        if name and "计" not in name and name.lower() not in ["nan", "none"]:
            try:
                val = float(str(row.get('long_open_interest', '0')).replace(',', ''))
                if pd.notna(val):
                    longs.append({"name": name, "long_pos": val})
            except:
                pass
                
    shorts = []
    for _, row in df.iterrows():
        raw_name = row.get('short_party_name', '')
        if pd.isna(raw_name) or raw_name is None:
            continue
        name = str(raw_name).strip()
        if name and "计" not in name and name.lower() not in ["nan", "none"]:
            try:
                val = float(str(row.get('short_open_interest', '0')).replace(',', ''))
                if pd.notna(val):
                    shorts.append({"name": name, "short_pos": val})
            except:
                pass

    df_long = pd.DataFrame(longs)
    df_short = pd.DataFrame(shorts)
    
    if df_long.empty or df_short.empty:
        return {"html": '<div style="padding:20px;">数据列解析失败</div>', "state": state}
        
    net_df = pd.merge(df_long, df_short, on='name', how='outer').fillna(0)
    net_df['net_pos'] = net_df['long_pos'] - net_df['short_pos']
    
    total_long = net_df['long_pos'].sum()
    total_short = net_df['short_pos'].sum()
    ls_ratio = (total_long / total_short) if total_short > 0 else 1.0
    
    net_longs = net_df[net_df['net_pos'] > 0].sort_values('net_pos', ascending=False).head(10)
    net_shorts = net_df[net_df['net_pos'] < 0].sort_values('net_pos', ascending=True).head(10)
    
    max_net = max(net_df['net_pos'].abs().max(), 1)
    
    # -- 构建 HTML --
    long_html = ""
    for _, row in net_longs.iterrows():
        pct = min((row['net_pos'] / max_net) * 100, 100)
        long_html += f"""
        <div style="margin-bottom: 8px;">
            <div style="display:flex;justify-content:space-between;font-size:var(--font-size-xs);margin-bottom:2px;">
                <span data-action="select_broker" data-payload='{{"broker":"{row['name']}"}}' style="color:var(--color-text-primary);font-weight:600;cursor:pointer;text-decoration:underline dashed var(--color-border-light);text-underline-offset:3px;">{row['name']}</span>
                <span style="color:var(--color-danger);font-family:var(--font-mono);font-weight:700;">+{int(row['net_pos']):,}</span>
            </div>
            <div style="height:6px;background:var(--color-surface);border-radius:3px;overflow:hidden;display:flex;justify-content:flex-end;">
                <div style="height:100%;width:{pct}%;background:var(--color-danger);border-radius:3px;"></div>
            </div>
        </div>
        """
        
    short_html = ""
    for _, row in net_shorts.iterrows():
        pct = min((abs(row['net_pos']) / max_net) * 100, 100)
        short_html += f"""
        <div style="margin-bottom: 8px;">
            <div style="display:flex;justify-content:space-between;font-size:var(--font-size-xs);margin-bottom:2px;">
                <span style="color:var(--color-success);font-family:var(--font-mono);font-weight:700;">{int(row['net_pos']):,}</span>
                <span data-action="select_broker" data-payload='{{"broker":"{row['name']}"}}' style="color:var(--color-text-primary);font-weight:600;cursor:pointer;text-decoration:underline dashed var(--color-border-light);text-underline-offset:3px;">{row['name']}</span>
            </div>
            <div style="height:6px;background:var(--color-surface);border-radius:3px;overflow:hidden;">
                <div style="height:100%;width:{pct}%;background:var(--color-success);border-radius:3px;"></div>
            </div>
        </div>
        """

    ratio_color = "var(--color-danger)" if ls_ratio > 1 else "var(--color-success)"
    
    selected_broker = state.get("selected_broker")
    broker_history = state.get("broker_history", [])
    
    overlay_html = ""
    if selected_broker:
        rows_html = ""
        prev_net = None
        prev_long = None
        prev_short = None
        for item in broker_history:
            net = item['net']
            long_val = item['long']
            short_val = item['short']
            
            chg_html = '<span style="color:var(--color-text-tertiary);">-</span>'
            action_tag = '<span style="color:var(--color-text-tertiary);">-</span>'
            
            if prev_net is not None:
                diff = net - prev_net
                if diff > 0:
                    chg_html = f'<span style="color:var(--color-danger);font-weight:bold;font-size:12px;">▲ +{int(diff):,}</span>'
                elif diff < 0:
                    chg_html = f'<span style="color:var(--color-success);font-weight:bold;font-size:12px;">▼ {int(diff):,}</span>'
                else:
                    chg_html = f'<span style="color:var(--color-text-secondary);font-weight:bold;font-size:12px;">0</span>'
                    
                dl = long_val - prev_long
                ds = short_val - prev_short
                
                tags = []
                if dl > 0: tags.append("加多")
                elif dl < 0: tags.append("减多")
                
                if ds > 0: tags.append("加空")
                elif ds < 0: tags.append("减空")
                
                if not tags:
                    action_text = "无变动"
                    action_color = "var(--color-text-tertiary)"
                else:
                    action_text = "".join(tags)
                    if diff > 0:
                        action_color = "var(--color-danger)"
                    elif diff < 0:
                        action_color = "var(--color-success)"
                    else:
                        action_color = "var(--color-text-secondary)"
                        
                action_tag = f'<span style="color:{action_color};font-size:11px;">{action_text}</span>'
                
            prev_net = net
            prev_long = long_val
            prev_short = short_val
            
            net_color = "var(--color-danger)" if net > 0 else "var(--color-success)" if net < 0 else "var(--color-text-primary)"
            date_short = f"{item['date'][4:6]}-{item['date'][6:8]}"
            
            rows_html += f"""
            <tr>
                <td style="padding:6px 0;border-bottom:1px solid var(--color-border-light);">{date_short}</td>
                <td style="text-align:right;color:var(--color-danger);padding:6px 0;border-bottom:1px solid var(--color-border-light);">{int(item['long']):,}</td>
                <td style="text-align:right;color:var(--color-success);padding:6px 0;border-bottom:1px solid var(--color-border-light);">{int(item['short']):,}</td>
                <td style="text-align:right;font-weight:bold;color:{net_color};padding:6px 0;border-bottom:1px solid var(--color-border-light);">{int(net):,}</td>
                <td style="text-align:right;padding:6px 0;border-bottom:1px solid var(--color-border-light);">{chg_html}</td>
                <td style="text-align:right;padding:6px 0;border-bottom:1px solid var(--color-border-light);">{action_tag}</td>
            </tr>
            """
            
        overlay_html = f"""
        <div style="position:absolute;top:0;left:0;right:0;bottom:0;background:var(--color-surface);z-index:10;display:flex;flex-direction:column;">
            <div style="padding:10px 14px;border-bottom:1px solid var(--color-border);display:flex;align-items:center;gap:12px;background:var(--color-bg, #f8fafc);">
                <button data-action="close_broker" style="cursor:pointer;background:var(--color-surface);border:1px solid var(--color-border);border-radius:4px;padding:4px 8px;font-size:12px;color:var(--color-text-primary);display:flex;align-items:center;gap:4px;box-shadow:0 1px 2px rgba(0,0,0,0.05);">
                    ◀ 返回
                </button>
                <span style="font-weight:bold;font-size:14px;color:var(--color-primary);">📊 {selected_broker}</span>
            </div>
            <div style="padding:14px;overflow-y:auto;flex:1;">
                <table style="width:100%;font-size:12px;border-collapse:collapse;">
                    <thead>
                        <tr style="color:var(--color-text-tertiary);">
                            <th style="text-align:left;padding-bottom:8px;border-bottom:1px solid var(--color-border);">日期</th>
                            <th style="text-align:right;padding-bottom:8px;border-bottom:1px solid var(--color-border);">多单</th>
                            <th style="text-align:right;padding-bottom:8px;border-bottom:1px solid var(--color-border);">空单</th>
                            <th style="text-align:right;padding-bottom:8px;border-bottom:1px solid var(--color-border);">净头寸</th>
                            <th style="text-align:right;padding-bottom:8px;border-bottom:1px solid var(--color-border);">净变动</th>
                            <th style="text-align:right;padding-bottom:8px;border-bottom:1px solid var(--color-border);">动作</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows_html if rows_html else '<tr><td colspan="6" style="text-align:center;padding:10px;">暂无历史数据</td></tr>'}
                    </tbody>
                </table>
            </div>
        </div>
        """
    
    html = f"""
    <div style="display:flex;flex-direction:column;height:100%;width:100%;overflow:hidden;font-family:var(--font-family);position:relative;">
        {overlay_html}
        <div style="flex-shrink:0;padding:12px 14px;border-bottom:1px solid var(--color-border);background:var(--color-surface);">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <span style="font-size:var(--font-size-lg);font-weight:800;color:var(--color-primary);">
                    ⚔️ {actual_matched_key} <span style="font-size:var(--font-size-xs);color:var(--color-text-tertiary);font-weight:normal;">({valid_date})</span>
                </span>
                <button data-action="refresh" title="重新获取" style="cursor:pointer;background:none;border:none;font-size:16px;color:var(--color-text-secondary);">🔄</button>
            </div>
            {fallback_msg}
            
            <div style="display:flex;gap:12px;align-items:center;">
                <div style="font-size:var(--font-size-sm);color:var(--color-text-secondary);">
                    前20多空比: <span style="color:{ratio_color};font-weight:700;font-family:var(--font-mono);font-size:16px;">{ls_ratio:.2f}</span>
                </div>
                <div style="font-size:var(--font-size-xs);color:var(--color-text-tertiary);">
                    (多: {int(total_long):,} / 空: {int(total_short):,})
                </div>
            </div>
        </div>
        
        <div style="flex:1;min-height:0;overflow-y:auto;padding:14px;background:var(--color-bg, var(--color-surface));">
            <div style="display:flex;gap:20px;min-height:100px;">
                <div style="flex:1;display:flex;flex-direction:column;">
                    <div style="font-size:var(--font-size-xs);font-weight:700;color:var(--color-danger);margin-bottom:12px;display:flex;align-items:center;gap:6px;">
                        <span style="display:inline-block;width:3px;height:12px;background:var(--color-danger);border-radius:2px;"></span>
                        净多头 Top 10
                    </div>
                    <div>
                        {long_html if long_html else '<div style="color:var(--color-text-tertiary);font-size:12px;">无数据</div>'}
                    </div>
                </div>
                
                <div style="flex:1;display:flex;flex-direction:column;">
                    <div style="font-size:var(--font-size-xs);font-weight:700;color:var(--color-success);margin-bottom:12px;display:flex;align-items:center;gap:6px;justify-content:flex-end;">
                        净空头 Top 10
                        <span style="display:inline-block;width:3px;height:12px;background:var(--color-success);border-radius:2px;"></span>
                    </div>
                    <div>
                        {short_html if short_html else '<div style="color:var(--color-text-tertiary);font-size:12px;text-align:right;">无数据</div>'}
                    </div>
                </div>
            </div>
            
            <details style="margin-top:20px;border-top:1px dashed var(--color-border-light);padding-top:10px;">
                <summary style="font-size:var(--font-size-xs);color:var(--color-text-tertiary);cursor:pointer;user-select:none;font-weight:600;">
                    💡 席位分析指南
                </summary>
                <div style="padding:10px 0;font-size:12px;color:var(--color-text-secondary);line-height:1.6;">
                    • <b>净多头/净空头</b>：某席位的多单量减去空单量的绝对差值。<br>
                    • <b>多空比(L/S Ratio)</b>：前 20 大席位总多单 / 总空单。比值>1说明大资金偏向多头，比值<1偏向空头。<br>
                    • <b>注</b>：部分席位（如中信、东证）常被视为产业套保或大主力，其大幅异动具有较强前瞻性。
                </div>
            </details>
        </div>
    </div>
    """
    
    return {"html": html, "state": state}


def on_action(action: str, payload: dict, config: dict, state: dict) -> dict:
    if action == "refresh":
        global _CACHE
        _CACHE.clear()
        return render(config, state)
        
    if action == "select_broker":
        broker = payload.get("broker")
        symbol_full = config.get("symbol", "CZCE.FG501").strip().split(" ")[0]
        if "." in symbol_full:
            exchange = symbol_full.split(".")[0]
            valid_date = state.get("valid_date", "")
            actual_key = state.get("actual_matched_key", "")
            if broker and valid_date and actual_key:
                history = fetch_broker_history(exchange, actual_key, broker, valid_date, days=5)
                state["selected_broker"] = broker
                state["broker_history"] = history
        return render(config, state)
        
    if action == "close_broker":
        state.pop("selected_broker", None)
        state.pop("broker_history", None)
        return render(config, state)
        
    return {"state": state}
