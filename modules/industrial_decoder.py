"""独立、主题自适应的工业原始数据解析模块。"""
import html
import json
from typing import Any, Dict
from industrial_protocol.decoder import decode_hex, parse_hex_bytes
from industrial_protocol.models import ByteOrder, DataType, DecodeConfig

META={"name":"工业数据解析器","icon":"≋","description":"脱离通信连接，解释寄存器原始字节","tags":["工业通信"],"default_size":[22,17],"min_size":[18,14],"max_size":[34,26],"refresh_interval":0,"config_fields":[]}
DEFAULT_STATE={"raw_hex":"00 00 43 5C","data_type":"float32","byte_order":"CDAB","bit_index":"0","scale":"1","offset":"0","unit":"V","result":None}
def _e(v:Any)->str:return html.escape(str(v),quote=True)
def _state(s:Dict[str,Any])->Dict[str,Any]:
    value=dict(DEFAULT_STATE)
    if isinstance(s,dict):value.update(s)
    return value
def _opt(v,label,current):return '<option value="%s"%s>%s</option>'%(_e(v)," selected" if v==current else "",_e(label))

def on_action(action,payload,config,state):
    s=_state(state)
    for key in DEFAULT_STATE:
        if key in payload and key!="result":s[key]=str(payload[key])
    if action!="decode":return {"error":"未知操作"}
    try:
        value=decode_hex(s["raw_hex"],DecodeConfig(DataType(s["data_type"]),ByteOrder(s["byte_order"]),int(s["bit_index"]),float(s["scale"]),float(s["offset"])))
        if isinstance(value,float):value=("%.8f"%value).rstrip("0").rstrip(".")
        elif isinstance(value,(dict,list)):value=json.dumps(value,ensure_ascii=False)
        s["result"]={"ok":True,"value":str(value),"raw":" ".join("%02X"%x for x in parse_hex_bytes(s["raw_hex"]))}
    except (ValueError,KeyError) as exc:s["result"]={"ok":False,"value":str(exc),"raw":s["raw_hex"]}
    return render(config,s)

def render(config,state):
    s=_state(state);types=[("bool","Bool"),("bit","Bit"),("bitfield","BitField"),("uint16","UInt16"),("int16","Int16"),("uint32","UInt32"),("int32","Int32"),("float32","Float32"),("uint64","UInt64"),("int64","Int64"),("float64","Float64"),("string","String"),("hex","Raw HEX")]
    r=s.get("result"); unit_types={"uint16","int16","uint32","int32","float32","uint64","int64","float64"}; show_unit=r and r["ok"] and s["data_type"] in unit_types and s["unit"].strip(); result='<div class="id-empty">输入原始字节后开始解析</div>' if not r else '<div class="id-result%s"><small>%s</small><strong>%s%s</strong><code>%s</code></div>'%("" if r["ok"] else " id-error","解析结果" if r["ok"] else "解析失败",_e(r["value"]),(" "+_e(s["unit"])) if show_unit else "",_e(r["raw"]))
    t=r'''<div class="id-root" id="id-{id}"><style>.id-root{height:100%;overflow:auto;padding:10px;color:var(--color-text-primary);background:var(--color-surface);font:var(--font-size-xs)/1.45 var(--font-family)}.id-root *{box-sizing:border-box}.id-tip{margin-bottom:9px;padding:7px 8px;border-radius:var(--radius-xs);color:var(--color-text-secondary);background:var(--color-primary-light)}.id-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.id-field{min-width:0}.id-wide{grid-column:1/-1}.id-field label{display:block;margin-bottom:3px;color:var(--color-text-tertiary);font-size:10px}.id-field input,.id-field select{width:100%;height:30px;padding:0 8px;border:1px solid var(--color-border);border-radius:var(--radius-xs);outline:0;color:var(--color-text-primary);background:var(--color-surface-elevated);font:11px var(--font-family)}.id-field input:focus,.id-field select:focus{border-color:var(--color-primary);box-shadow:0 0 0 2px var(--color-primary-light)}.id-btn{width:100%;height:31px;margin:9px 0;border:1px solid var(--color-primary);border-radius:var(--radius-sm);cursor:pointer;color:var(--color-primary-text);background:var(--color-primary);font-weight:600}.id-btn:hover{background:var(--color-primary-hover)}.id-result,.id-empty{min-height:75px;padding:10px;border:1px solid var(--color-border);border-radius:var(--radius-sm);background:var(--color-surface-elevated)}.id-empty{display:grid;place-items:center;color:var(--color-text-tertiary)}.id-result small{display:block;color:var(--color-text-tertiary)}.id-result strong{display:block;margin:4px 0;font-size:22px;overflow-wrap:anywhere}.id-result code{display:block;color:var(--color-primary);overflow-wrap:anywhere}.id-error{border-color:var(--color-danger)}.id-error strong{color:var(--color-danger)}.id-hidden{display:none!important}@media(max-width:360px){.id-grid{grid-template-columns:1fr}.id-wide{grid-column:auto}}</style><div class="id-tip">仅解释数据，不连接设备，也不会发送指令。</div><div class="id-grid"><div class="id-field id-wide"><label>Raw HEX Bytes</label><input data-input="raw_hex" value="__RAW__"></div><div class="id-field"><label>Data Type</label><select data-input="data_type" id="id-type-{id}">__TYPES__</select></div><div class="id-field id-order"><label>Byte / Word Order</label><select data-input="byte_order">__ORDERS__</select></div><div class="id-field id-numeric"><label>Scale</label><input data-input="scale" value="__SCALE__"></div><div class="id-field id-numeric"><label>Offset</label><input data-input="offset" value="__OFFSET__"></div><div class="id-field id-bit"><label>Bit Index</label><input data-input="bit_index" value="__BIT__"></div><div class="id-field id-numeric"><label>Unit</label><input data-input="unit" value="__UNIT__"></div></div><button class="id-btn" data-action="decode">解析数据</button>__RESULT__<script>(()=>{const r=document.getElementById('id-{id}'),t=r.querySelector('#id-type-{id}');const sync=()=>{const v=t.value,n=['uint16','int16','uint32','int32','float32','uint64','int64','float64'].includes(v);r.querySelectorAll('.id-numeric').forEach(x=>x.classList.toggle('id-hidden',!n));r.querySelector('.id-bit').classList.toggle('id-hidden',v!=='bit');r.querySelector('.id-order').classList.toggle('id-hidden',['bool','bit','bitfield','hex'].includes(v))};t.onchange=sync;sync()})();</script></div>'''
    values={"__RAW__":_e(s["raw_hex"]),"__TYPES__":"".join(_opt(v,l,s["data_type"]) for v,l in types),"__ORDERS__":"".join(_opt(v,v,s["byte_order"]) for v in ("ABCD","BADC","CDAB","DCBA")),"__SCALE__":_e(s["scale"]),"__OFFSET__":_e(s["offset"]),"__BIT__":_e(s["bit_index"]),"__UNIT__":_e(s["unit"]),"__RESULT__":result}
    for key,value in values.items():t=t.replace(key,value)
    return {"html":t,"state":s}
