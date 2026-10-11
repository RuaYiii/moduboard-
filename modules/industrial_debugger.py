"""简约、主题自适应的工业通信请求模块。"""
import html
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict

from industrial_protocol.addressing import to_protocol_offset
from industrial_protocol.decoder import parse_hex_bytes
from industrial_protocol.models import FUNCTION_AREAS, AddressMode, ByteOrder, DataType, DecodeConfig, ModbusRequest, Transport
from industrial_protocol.service import SimulatorBackend

META = {"name": "工业通信请求", "icon": "⌁", "description": "Modbus / OPC 连接、功能码与地址级联调试", "tags": ["工业通信"], "default_size": [28, 25], "min_size": [22, 19], "max_size": [42, 36], "refresh_interval": 0, "config_fields": []}
DEFAULT_STATE = {"protocol_family":"modbus","transport":"modbus_tcp","operation":"3","host":"192.168.1.50","port":"502","serial_port":"COM3","baud_rate":"9600","endpoint":"opc.tcp://192.168.1.100:4840","security_mode":"None","security_policy":"None","authentication":"Anonymous","node_id":"ns=2;s=PowerSystem.Incoming01.VoltageA","opc_data_type":"Double","write_value":"220.0","subscription_name":"Critical Operations","publishing_interval":"1000","keep_alive_count":"10","lifetime_count":"60","priority":"0","sampling_interval":"1000","queue_size":"10","monitored_items":[],"unit_id":"1","address_mode":"reference_4x","address":"40001","quantity":"2","data_type":"float32","byte_order":"CDAB","raw_hex":"00 00 43 5C","result":None,"logs":[]}

def _e(v: Any) -> str: return html.escape(str(v), quote=True)
def _state(state: Dict[str, Any]) -> Dict[str, Any]:
    value = deepcopy(DEFAULT_STATE)
    if isinstance(state, dict): value.update(state)
    value["logs"] = list(value.get("logs") or [])[-4:]
    stored_items = value.get("monitored_items")
    value["monitored_items"] = deepcopy(stored_items) if isinstance(stored_items, list) else []
    return value
def _opt(v, label, current): return '<option value="%s"%s>%s</option>' % (_e(v), " selected" if v == current else "", _e(label))
def _number(v, label, low, high):
    try: result = int(str(v).strip())
    except (TypeError, ValueError) as exc: raise ValueError("%s 必须是整数" % label) from exc
    if not low <= result <= high: raise ValueError("%s 必须在 %d～%d 之间" % (label, low, high))
    return result
def _log(s, kind, text):
    s.setdefault("logs", []).append({"time":datetime.now().strftime("%H:%M:%S"),"kind":kind,"text":text}); s["logs"] = s["logs"][-4:]

def _modbus(s):
    fc = _number(s["operation"], "功能码", 1, 16)
    if fc not in FUNCTION_AREAS: raise ValueError("当前仅支持 FC01/02/03/04/05/06/0F/10")
    area = FUNCTION_AREAS[fc]; visible = _number(s["address"], "地址", 0, 65535)
    offset = to_protocol_offset(visible, AddressMode(s["address_mode"]), area)
    quantity = _number(s["quantity"], "Quantity", 1, 125)
    if fc in (5, 6) and quantity != 1: raise ValueError("FC05 / FC06 的 Quantity 必须为 1")
    if fc in (1, 2, 5, 15) and s["data_type"] not in ("bool", "bit", "hex"):
        raise ValueError("Coil / Discrete Input 仅支持 Bool、Bit 或 Raw HEX")
    req = ModbusRequest(Transport(s["transport"]), _number(s["unit_id"], "Unit ID", 0, 247), fc, offset, quantity)
    raw = parse_hex_bytes(s["raw_hex"])
    result = SimulatorBackend().execute(req, DecodeConfig(DataType(s["data_type"]), ByteOrder(s["byte_order"])), raw)
    value = ("%.8f" % result.decoded_value).rstrip("0").rstrip(".") if isinstance(result.decoded_value, float) else str(result.decoded_value)
    s["result"] = {"ok":True,"title":"模拟请求成功","value":value,"raw":" ".join("%02X" % x for x in raw),"meta":"FC%02d · %s · 协议偏移 %d · %.2f ms" % (fc, area.value, offset, result.latency_ms)}
    _log(s,"发送","站号 %d · FC%02d · 地址 %d · 数量 %d" % (req.unit_id,fc,offset,req.quantity)); _log(s,"接收",s["result"]["raw"])

def _opc(s):
    if s.get("transport") == "opc_da":
        raise ValueError("OPC DA 需要独立的 Windows COM/DCOM Backend，当前未启用")
    if not s["endpoint"].strip().lower().startswith("opc.tcp://"):
        raise ValueError("OPC UA Endpoint URL 必须以 opc.tcp:// 开头")
    if s["security_mode"] == "None" and s["security_policy"] != "None":
        raise ValueError("Security Mode=None 时 Security Policy 必须为 None")
    if s["security_mode"] != "None" and s["security_policy"] == "None":
        raise ValueError("Sign / SignAndEncrypt 需要非 None 的 Security Policy")
    op=s.get("operation","read")
    monitored_items = s.get("monitored_items") or []
    if op in ("browse", "read", "write") and not s["node_id"].strip():
        raise ValueError("%s 操作需要 NodeId" % op.title())
    if op == "write" and not s["write_value"].strip(): raise ValueError("Write 操作需要 Value")
    if op == "subscribe":
        _number(s["publishing_interval"], "Publishing Interval", 1, 3600000)
        keep_alive_count = _number(s["keep_alive_count"], "KeepAlive Count", 1, 10000)
        lifetime_count = _number(s["lifetime_count"], "Lifetime Count", 3, 100000)
        if lifetime_count < keep_alive_count * 3:
            raise ValueError("Lifetime Count 必须至少为 KeepAlive Count 的 3 倍")
        _number(s["priority"], "Priority", 0, 255)
        if not monitored_items:
            if not s["node_id"].strip(): raise ValueError("Subscribe 至少需要一个 MonitoredItem")
            monitored_items = [{"node_id":s["node_id"],"sampling_interval":s["sampling_interval"],"queue_size":s["queue_size"],"deadband":"0"}]
        if len(monitored_items) > 1000: raise ValueError("单个 Subscription 最多支持 1000 个 MonitoredItem")
        for index, item in enumerate(monitored_items, 1):
            if not isinstance(item, dict) or not str(item.get("node_id", "")).strip():
                raise ValueError("MonitoredItem #%d 缺少 NodeId" % index)
            _number(item.get("sampling_interval", s["sampling_interval"]), "MonitoredItem #%d Sampling Interval" % index, 0, 3600000)
            _number(item.get("queue_size", s["queue_size"]), "MonitoredItem #%d Queue Size" % index, 1, 10000)
            try: deadband = float(str(item.get("deadband", "0")).strip())
            except (TypeError, ValueError) as exc: raise ValueError("MonitoredItem #%d Deadband 必须是数字" % index) from exc
            if deadband < 0: raise ValueError("MonitoredItem #%d Deadband 不能小于 0" % index)
        s["monitored_items"] = monitored_items
    monitored_label = "MonitoredItem" if len(monitored_items) == 1 else "MonitoredItems"
    labels={"connect":("Session Ready","SecureChannel + Session 已模拟建立"),"browse":("Browse Complete","起始节点下发现 3 个 Variable"),"read":("Read Complete","Value 220.14 V · Status Good"),"write":("Write Preview","%s(%s) · 未向真实设备写入" % (s["opc_data_type"], s["write_value"])),"subscribe":("Subscription #1","%d %s · Publishing %s ms" % (len(monitored_items), monitored_label, s["publishing_interval"]))}
    title,value=labels.get(op,labels["read"]); now=datetime.now().astimezone().isoformat(timespec="milliseconds")
    if op == "subscribe":
        node_ids = [str(item["node_id"]) for item in monitored_items]
        raw = " | ".join(node_ids[:3]) + (" | …" if len(node_ids) > 3 else "")
        log_text = "SUBSCRIBE · %d items · %s" % (len(monitored_items), s.get("subscription_name") or "Subscription #1")
    else:
        raw = s["node_id"]
        log_text = "%s · %s" % (op.upper(), s["node_id"])
    s["result"]={"ok":True,"title":title,"value":value,"raw":raw,"meta":"Source / Server / Receive Timestamp · %s" % now}; _log(s,"OPC UA",log_text)

def on_action(action, payload, config, state):
    s=_state(state)
    for key in DEFAULT_STATE:
        if key in payload and key not in ("result","logs"):
            s[key]=list(payload[key]) if key == "monitored_items" and isinstance(payload[key], list) else str(payload[key])
    if action == "clear_log": s["logs"]=[]; return render(config,s)
    if action != "execute": return {"error":"未知操作"}
    try: _opc(s) if s["protocol_family"] == "opc" else _modbus(s)
    except (ValueError,KeyError) as exc:
        s["result"]={"ok":False,"title":"参数有误","value":str(exc),"raw":"未发送","meta":"请检查级联选项和地址模式"}; _log(s,"错误",str(exc))
    return render(config,s)

def _result(s):
    r=s.get("result")
    if not r: return '<div class="ic-empty">填写参数后点击“模拟执行”<small>当前不会访问真实设备</small></div>'
    return '<div class="ic-result%s"><div><strong>%s</strong><span>%s</span></div><b>%s</b><code>%s</code><small>%s</small></div>' % ("" if r["ok"] else " ic-error",_e(r["title"]),"正常" if r["ok"] else "错误",_e(r["value"]),_e(r["raw"]),_e(r["meta"]))
def _logs(s):
    if not s["logs"]: return '<div class="ic-log-empty">暂无通信记录</div>'
    return "".join('<div class="ic-log-row"><time>%s</time><b>%s</b><span>%s</span></div>' % (_e(x["time"]),_e(x["kind"]),_e(x["text"])) for x in reversed(s["logs"]))

def render(config, state):
    s=_state(state)
    transports=[("modbus_tcp","Modbus TCP"),("modbus_rtu","Modbus RTU"),("opc_ua","OPC UA"),("opc_da","OPC DA（后续）")]
    operations=[("1","FC01 Read Coils"),("2","FC02 Read Discrete Inputs"),("3","FC03 Read Holding Registers"),("4","FC04 Read Input Registers"),("5","FC05 Write Single Coil"),("6","FC06 Write Single Register"),("15","FC0F Write Multiple Coils"),("16","FC10 Write Multiple Registers"),("connect","Connect"),("browse","Browse"),("read","Read"),("write","Write"),("subscribe","Subscribe")]
    modes=[("raw","Raw / Zero Based"),("one_based","One Based"),("reference_3x","3xxxx Reference"),("reference_4x","4xxxx Reference")]
    types=[("bool","Bool"),("bit","Bit"),("bitfield","BitField"),("uint16","UInt16"),("int16","Int16"),("uint32","UInt32"),("int32","Int32"),("float32","Float32"),("float64","Float64"),("hex","Raw HEX")]
    t=r'''<div class="ic-root" id="ic-{id}"><style>
.ic-root{height:100%;overflow:auto;padding:10px;color:var(--color-text-primary);background:var(--color-surface);font:var(--font-size-xs)/1.45 var(--font-family)}.ic-root *{box-sizing:border-box}.ic-cascade{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;padding-bottom:9px;border-bottom:1px solid var(--color-border-light)}.ic-field{min-width:0}.ic-field label{display:block;margin:0 0 3px;color:var(--color-text-tertiary);font-size:10px}.ic-field input,.ic-field select{width:100%;height:30px;padding:0 8px;border:1px solid var(--color-border);border-radius:var(--radius-xs);outline:0;color:var(--color-text-primary);background:var(--color-surface-elevated);font:11px var(--font-family)}.ic-field input:focus,.ic-field select:focus{border-color:var(--color-primary);box-shadow:0 0 0 2px var(--color-primary-light)}.ic-field input:disabled,.ic-field select:disabled{cursor:not-allowed;color:var(--color-text-tertiary);background:var(--color-surface-hover)}.ic-section{padding:9px 0;border-bottom:1px solid var(--color-border-light)}.ic-section-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:7px;color:var(--color-text-secondary);font-weight:600}.ic-tag{padding:1px 6px;border-radius:var(--radius-full);color:var(--color-primary);background:var(--color-primary-light);font-size:10px}.ic-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}.ic-wide{grid-column:1/-1}.ic-map{display:flex;justify-content:space-between;gap:6px;margin-top:6px;padding:6px 8px;border-radius:var(--radius-xs);color:var(--color-text-secondary);background:var(--color-surface-hover);font-family:var(--font-mono)}.ic-map b{color:var(--color-primary)}.ic-warning{display:none;margin-top:6px;padding:6px 8px;border-radius:var(--radius-xs);color:var(--color-warning);background:var(--color-warning-light)}.ic-btn{width:100%;height:31px;margin:9px 0;border:1px solid var(--color-primary);border-radius:var(--radius-sm);cursor:pointer;color:var(--color-primary-text);background:var(--color-primary);font-weight:600}.ic-btn:hover{background:var(--color-primary-hover)}.ic-result,.ic-empty{min-height:84px;padding:9px;border:1px solid var(--color-border);border-radius:var(--radius-sm);background:var(--color-surface-elevated)}.ic-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--color-text-secondary)}.ic-empty small,.ic-result small{display:block;margin-top:3px;color:var(--color-text-tertiary)}.ic-result>div{display:flex;justify-content:space-between}.ic-result>div span{color:var(--color-success)}.ic-result>b{display:block;margin:7px 0 4px;font-size:18px}.ic-result code{display:block;overflow-wrap:anywhere;color:var(--color-primary)}.ic-error{border-color:var(--color-danger)}.ic-error>div span{color:var(--color-danger)}.ic-log-head{display:flex;justify-content:space-between;padding:8px 0 4px;color:var(--color-text-tertiary)}.ic-log-head button{border:0;color:var(--color-text-tertiary);background:transparent;cursor:pointer}.ic-log-row{display:grid;grid-template-columns:54px 48px 1fr;gap:5px;padding:3px 0;border-top:1px solid var(--color-border-light);font-family:var(--font-mono)}.ic-log-row time{color:var(--color-text-tertiary)}.ic-log-row b{color:var(--color-primary)}.ic-log-row span{overflow-wrap:anywhere;color:var(--color-text-secondary)}.ic-log-empty{padding:10px;text-align:center;color:var(--color-text-tertiary)}.ic-hidden{display:none!important}@media(max-width:480px){.ic-cascade,.ic-grid{grid-template-columns:1fr}.ic-wide{grid-column:auto}}</style>
<div class="ic-cascade"><div class="ic-field"><label>协议</label><select data-input="protocol_family" id="ic-family-{id}"><option value="modbus"__FM__>Modbus</option><option value="opc"__FO__>OPC</option></select></div><div class="ic-field"><label>传输方式</label><select data-input="transport" id="ic-transport-{id}" data-current="__TRANSPORT__">__TRANSPORTS__</select></div><div class="ic-field"><label>操作</label><select data-input="operation" id="ic-operation-{id}" data-current="__OPERATION__">__OPERATIONS__</select></div></div>
<section class="ic-section"><div class="ic-section-head"><span>连接参数</span><span class="ic-tag" id="ic-conn-tag-{id}">TCP</span></div><div class="ic-grid ic-conn" data-conn="modbus_tcp"><div class="ic-field"><label>Host / IP</label><input data-input="host" value="__HOST__"></div><div class="ic-field"><label>Port</label><input data-input="port" value="__PORT__"></div></div><div class="ic-grid ic-conn ic-hidden" data-conn="modbus_rtu"><div class="ic-field"><label>Serial Port</label><input data-input="serial_port" value="__SERIAL__"></div><div class="ic-field"><label>Baud Rate</label><select data-input="baud_rate">__BAUD__</select></div></div><div class="ic-grid ic-conn ic-hidden" data-conn="opc_ua"><div class="ic-field ic-wide"><label>Endpoint URL</label><input data-input="endpoint" value="__ENDPOINT__"></div><div class="ic-field"><label>Security Mode</label><select data-input="security_mode">__SECURITY__</select></div><div class="ic-field"><label>Security Policy</label><select data-input="security_policy">__POLICIES__</select></div><div class="ic-field"><label>Authentication</label><select data-input="authentication">__AUTH__</select></div></div><div class="ic-grid ic-conn ic-hidden" data-conn="opc_da"><div class="ic-field ic-wide"><label>OPC Classic / DA</label><input value="需要独立 Windows COM/DCOM Backend" disabled></div></div></section>
<section class="ic-section ic-modbus"><div class="ic-section-head"><span>Modbus Request</span><span class="ic-tag" id="ic-area-{id}">Holding Registers</span></div><div class="ic-grid"><div class="ic-field"><label>Unit ID</label><input data-input="unit_id" value="__UNIT_ID__"></div><div class="ic-field"><label>Quantity</label><input data-input="quantity" id="ic-quantity-{id}" value="__QUANTITY__"></div><div class="ic-field"><label>Address Mode</label><select data-input="address_mode" id="ic-mode-{id}" data-current="__MODE__">__MODES__</select></div><div class="ic-field"><label>Address</label><input data-input="address" id="ic-address-{id}" value="__ADDRESS__"></div><div class="ic-field"><label>Data Type</label><select data-input="data_type" id="ic-type-{id}" data-current="__DATA_TYPE__">__TYPES__</select></div><div class="ic-field ic-order"><label>Byte / Word Order</label><select data-input="byte_order">__ORDERS__</select></div><div class="ic-field ic-wide"><label id="ic-raw-label-{id}">Mock Response HEX</label><input data-input="raw_hex" id="ic-raw-{id}" value="__RAW__"></div></div><div class="ic-map"><span id="ic-visible-{id}">4xxxx Reference 40001</span><b>→</b><span id="ic-offset-{id}">Protocol Offset 0</span></div><div class="ic-warning" id="ic-warning-{id}">写操作仅做预览，不会下发到真实设备。</div></section>
<section class="ic-section ic-opc ic-hidden" id="ic-opc-request-{id}"><div class="ic-section-head"><span>OPC UA Request</span><span class="ic-tag">Value + Status + Timestamp</span></div><div class="ic-grid"><div class="ic-field ic-wide ic-node"><label id="ic-node-label-{id}">NodeId</label><input data-input="node_id" value="__NODE__"></div><div class="ic-field ic-write"><label>Variant Type</label><select data-input="opc_data_type">__OPC_TYPES__</select></div><div class="ic-field ic-write"><label>Value</label><input data-input="write_value" value="__WRITE_VALUE__"></div><div class="ic-field ic-subscription"><label>Publishing Interval (ms)</label><input data-input="publishing_interval" value="__PUBLISHING__"></div><div class="ic-field ic-subscription"><label>Sampling Interval (ms)</label><input data-input="sampling_interval" value="__SAMPLING__"></div><div class="ic-field ic-subscription"><label>Queue Size</label><input data-input="queue_size" value="__QUEUE__"></div></div><div class="ic-warning ic-opc-write" id="ic-opc-warning-{id}">OPC Write 仅做预览，不会写入真实节点。</div></section><button class="ic-btn" id="ic-execute-{id}" data-action="execute">模拟读取</button>__RESULT__<div class="ic-log-head"><span>最近记录</span><button data-action="clear_log">清空</button></div>__LOGS__
<script>(()=>{const r=document.getElementById('ic-{id}'),f=r.querySelector('#ic-family-{id}'),t=r.querySelector('#ic-transport-{id}'),o=r.querySelector('#ic-operation-{id}'),m=r.querySelector('#ic-mode-{id}'),a=r.querySelector('#ic-address-{id}'),q=r.querySelector('#ic-quantity-{id}'),dt=r.querySelector('#ic-type-{id}'),raw=r.querySelector('#ic-raw-{id}'),btn=r.querySelector('#ic-execute-{id}');const secMode=r.querySelector('[data-input="security_mode"]'),secPolicy=r.querySelector('[data-input="security_policy"]');const sets={modbus:{t:[['modbus_tcp','Modbus TCP'],['modbus_rtu','Modbus RTU']],o:[['1','FC01 Read Coils'],['2','FC02 Read Discrete Inputs'],['3','FC03 Read Holding Registers'],['4','FC04 Read Input Registers'],['5','FC05 Write Single Coil'],['6','FC06 Write Single Register'],['15','FC0F Write Multiple Coils'],['16','FC10 Write Multiple Registers']]},opc:{t:[['opc_ua','OPC UA'],['opc_da','OPC DA（后续）']],o:[['connect','Connect'],['browse','Browse'],['read','Read'],['write','Write'],['subscribe','Subscribe']]}};const regTypes=[['bool','Bool'],['bit','Bit'],['bitfield','BitField'],['uint16','UInt16'],['int16','Int16'],['uint32','UInt32'],['int32','Int32'],['float32','Float32'],['float64','Float64'],['hex','Raw HEX']],bitTypes=[['bool','Bool'],['bit','Bit'],['hex','Raw HEX']],policies=[['Basic256Sha256','Basic256Sha256'],['Aes128_Sha256_RsaOaep','Aes128_Sha256_RsaOaep'],['Aes256_Sha256_RsaPss','Aes256_Sha256_RsaPss']];const fill=(e,x,p)=>{e.innerHTML=x.map(v=>`<option value="${v[0]}">${v[1]}</option>`).join('');if(x.some(v=>v[0]===p))e.value=p};const map=()=>{const n=Number(a.value);let x=n;if(m.value==='one_based')x=n-1;if(m.value==='reference_3x')x=n-30001;if(m.value==='reference_4x')x=n-40001;r.querySelector('#ic-visible-{id}').textContent=`${m.options[m.selectedIndex]?.text||''} ${Number.isFinite(n)?n:'—'}`;r.querySelector('#ic-offset-{id}').textContent=`Protocol Offset ${Number.isFinite(x)?x:'—'}`};const req=()=>{const fc=Number(o.value),bit=[1,2,5,15].includes(fc),write=[5,6,15,16].includes(fc),single=[5,6].includes(fc),names={1:'Coils',2:'Discrete Inputs',3:'Holding Registers',4:'Input Registers',5:'Coils',6:'Holding Registers',15:'Coils',16:'Holding Registers'};r.querySelector('#ic-area-{id}').textContent=names[fc]||'';const oldMode=m.value||m.dataset.current;let ms=[['raw','Raw / Zero Based'],['one_based','One Based']];if([3,6,16].includes(fc))ms.push(['reference_4x','4xxxx Reference']);if(fc===4)ms.push(['reference_3x','3xxxx Reference']);const fallback=fc===4?'reference_3x':([3,6,16].includes(fc)?'reference_4x':'raw');fill(m,ms,ms.some(x=>x[0]===oldMode)?oldMode:fallback);if(oldMode.startsWith('reference_')&&!m.value.startsWith('reference_'))a.value='0';else if(m.value==='reference_3x'&&Number(a.value)>=40001)a.value='30001';else if(m.value==='reference_4x'&&Number(a.value)>=30001&&Number(a.value)<40001)a.value='40001';q.disabled=single;if(single)q.value='1';fill(dt,bit?bitTypes:regTypes,dt.value||dt.dataset.current);r.querySelector('.ic-order').classList.toggle('ic-hidden',bit);r.querySelector('#ic-raw-label-{id}').textContent=write?'Write Payload HEX':'Mock Response HEX';if(bit&&['00 00 43 5C','43 5C 00 00'].includes(raw.value))raw.value='01';if(!bit&&raw.value==='01')raw.value='00 00 43 5C';r.querySelector('#ic-warning-{id}').style.display=write?'block':'none';btn.textContent=write?'模拟写入':'模拟读取';map()};const opc=()=>{const op=o.value,needsNode=op!=='connect';r.querySelector('#ic-opc-request-{id}').classList.toggle('ic-hidden',!needsNode);r.querySelectorAll('.ic-node').forEach(x=>x.classList.toggle('ic-hidden',!needsNode));r.querySelectorAll('.ic-write').forEach(x=>x.classList.toggle('ic-hidden',op!=='write'));r.querySelectorAll('.ic-subscription').forEach(x=>x.classList.toggle('ic-hidden',op!=='subscribe'));r.querySelector('#ic-node-label-{id}').textContent=op==='browse'?'Start NodeId':'NodeId';r.querySelector('#ic-opc-warning-{id}').style.display=op==='write'?'block':'none';btn.textContent={connect:'模拟连接',browse:'模拟浏览',read:'模拟读取',write:'模拟写入',subscribe:'模拟订阅'}[op]||'模拟执行'};const security=()=>{const old=secPolicy.value;fill(secPolicy,secMode.value==='None'?[['None','None']]:policies,old)};const conn=()=>{r.querySelectorAll('.ic-conn').forEach(x=>x.classList.toggle('ic-hidden',x.dataset.conn!==t.value));r.querySelector('#ic-conn-tag-{id}').textContent=t.options[t.selectedIndex]?.text||'';if(t.value==='opc_ua')security()};const family=(boot=false)=>{const s=sets[f.value];fill(t,s.t,boot?t.dataset.current:t.value);fill(o,s.o,boot?o.dataset.current:o.value);r.querySelectorAll('.ic-modbus').forEach(x=>x.classList.toggle('ic-hidden',f.value!=='modbus'));r.querySelectorAll('.ic-opc').forEach(x=>x.classList.toggle('ic-hidden',f.value!=='opc'));conn();f.value==='modbus'?req():opc()};f.onchange=()=>family();t.onchange=conn;o.onchange=()=>f.value==='modbus'?req():opc();m.onchange=map;a.oninput=map;secMode.onchange=security;family(true)})();</script></div>'''
    values={"__FM__":" selected" if s["protocol_family"]=="modbus" else "","__FO__":" selected" if s["protocol_family"]=="opc" else "","__TRANSPORT__":_e(s["transport"]),"__TRANSPORTS__":"".join(_opt(v,l,s["transport"]) for v,l in transports),"__OPERATION__":_e(s["operation"]),"__OPERATIONS__":"".join(_opt(v,l,s["operation"]) for v,l in operations),"__HOST__":_e(s["host"]),"__PORT__":_e(s["port"]),"__SERIAL__":_e(s["serial_port"]),"__BAUD__":"".join(_opt(v,v,s["baud_rate"]) for v in ("1200","2400","4800","9600","19200","38400","57600","115200")),"__ENDPOINT__":_e(s["endpoint"]),"__SECURITY__":"".join(_opt(v,v,s["security_mode"]) for v in ("None","Sign","SignAndEncrypt")),"__POLICIES__":"".join(_opt(v,v,s["security_policy"]) for v in ("None","Basic256Sha256","Aes128_Sha256_RsaOaep","Aes256_Sha256_RsaPss")),"__AUTH__":"".join(_opt(v,v,s["authentication"]) for v in ("Anonymous","Username / Password","Certificate")),"__UNIT_ID__":_e(s["unit_id"]),"__QUANTITY__":_e(s["quantity"]),"__MODE__":_e(s["address_mode"]),"__MODES__":"".join(_opt(v,l,s["address_mode"]) for v,l in modes),"__ADDRESS__":_e(s["address"]),"__DATA_TYPE__":_e(s["data_type"]),"__TYPES__":"".join(_opt(v,l,s["data_type"]) for v,l in types),"__ORDERS__":"".join(_opt(v,v,s["byte_order"]) for v in ("ABCD","BADC","CDAB","DCBA")),"__RAW__":_e(s["raw_hex"]),"__NODE__":_e(s["node_id"]),"__OPC_TYPES__":"".join(_opt(v,v,s["opc_data_type"]) for v in ("Boolean","Int16","UInt16","Int32","UInt32","Int64","UInt64","Float","Double","String","DateTime")),"__WRITE_VALUE__":_e(s["write_value"]),"__PUBLISHING__":_e(s["publishing_interval"]),"__SAMPLING__":_e(s["sampling_interval"]),"__QUEUE__":_e(s["queue_size"]),"__RESULT__":_result(s),"__LOGS__":_logs(s)}
    for key,value in values.items(): t=t.replace(key,value)
    return {"html":t,"state":s}
