import os
import re
import json
import pandas as pd

META = {
    "name": "DataCenter (机房)",
    "icon": "🏢",
    "description": "机房资源统筹管理控制面板",
    "tags": ["机房", "资源"],
    "default_size": [64, 48],
    "min_size": [32, 24],
    "max_size": [9999, 9999],
    "refresh_interval": 0,
    "config_fields": [
        {"key": "file_path", "label": "设备清单路径", "type": "text", "default": r"C:\Users\user\Desktop\黄山弱电相关\利旧\【】【简易速查】到场设备清单.xlsx"},
        {"key": "room", "label": "监控机房", "type": "text", "default": "102"}
    ],
}

def parse_u_size(u_str):
    if pd.isna(u_str):
        return 1
    s = str(u_str).strip().upper()
    s = s.replace('U', '')
    try:
        return int(float(s))
    except:
        return 1

def load_data(file_path: str, target_room: str):
    room_data = {
        "id": f"room_{target_room}",
        "name": f"{target_room}机房",
        "modules": []
    }
    
    modules_map = {}
    for m in ['A', 'B', 'C', 'D', 'E', 'F']:
        modules_map[m] = {
            "id": f"mod_{m}",
            "name": f"模块{m}",
            "cabinets": []
        }
        for i in range(1, 29):
            cab_name = f"{m}{i:02d}"
            modules_map[m]["cabinets"].append({
                "id": cab_name,
                "name": cab_name,
                "totalU": 47,
                "equipment": []
            })
        room_data["modules"].append(modules_map[m])
        
    try:
        xls = pd.ExcelFile(file_path)
        for sheet_name in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sheet_name)
            if '部署房间' not in df.columns:
                continue
                
            for idx, row in df.iterrows():
                room_val = str(row['部署房间']).strip()
                if target_room not in room_val:
                    continue
                    
                cab = None
                for col in ['核实后-机柜', '复核后-机柜', '部署机柜', '现场放置机柜']:
                    if col in df.columns and pd.notna(row[col]):
                        cab = str(row[col]).strip().upper()
                        if cab:
                            break
                if not cab:
                    continue
                    
                m_match = re.match(r'([A-F])(\d+)', cab)
                if not m_match:
                    continue
                
                mod_letter = m_match.group(1)
                cab_num = int(m_match.group(2))
                std_cab = f"{mod_letter}{cab_num:02d}"
                
                u_slot = None
                for col in ['核实后-U位', '复核后-U位', '部署U位']:
                    if col in df.columns and pd.notna(row[col]):
                        u_val = str(row[col]).strip().upper().replace('U', '')
                        try:
                            u_slot = int(float(u_val))
                        except:
                            pass
                        if u_slot is not None:
                            break
                
                if u_slot is None:
                    continue
                    
                u_size = 1
                if '占U数' in df.columns:
                    u_size = parse_u_size(row['占U数'])
                elif 'U数' in df.columns:
                    u_size = parse_u_size(row['U数'])
                    
                sn = row.get('设备序列号', f"UNKNOWN_{idx}") if '设备序列号' in df.columns else f"UNKNOWN_{idx}"
                model = row.get('型号', '') if '型号' in df.columns else row.get('设备型号', '')
                purpose = row.get('设备用途', '') if '设备用途' in df.columns else row.get('设备类型', '')
                
                if pd.isna(sn): sn = f"UNKNOWN_{idx}"
                if pd.isna(model): model = ''
                if pd.isna(purpose): purpose = ''
                
                equip_obj = {
                    "id": str(sn),
                    "name": str(purpose) or str(model) or "Unknown Equipment",
                    "model": str(model),
                    "sizeU": u_size,
                    "startU": u_slot,
                    "purpose": str(purpose)
                }
                
                for m_obj in room_data["modules"]:
                    if m_obj["id"] == f"mod_{mod_letter}":
                        for c_obj in m_obj["cabinets"]:
                            if c_obj["id"] == std_cab:
                                c_obj["equipment"].append(equip_obj)
                                break
                        break
    except Exception as e:
        print(f"Error loading excel: {e}")
        
    return room_data

def render(config: dict, state: dict) -> dict:
    file_path = config.get("file_path", r"C:\Users\user\Desktop\黄山弱电相关\利旧\【】【简易速查】到场设备清单.xlsx")
    target_room = config.get("room", "102")
    
    last_file = state.get("last_file")
    last_room = state.get("last_room")
    
    if "room_data" not in state or last_file != file_path or last_room != target_room:
        room_data = load_data(file_path, target_room)
        state["room_data"] = room_data
        state["last_file"] = file_path
        state["last_room"] = target_room
    else:
        room_data = state["room_data"]
        
    json_data = json.dumps(room_data, ensure_ascii=False)
    
    html = """
    <div id="dcd-container" class="dcd-wrapper">
      <header class="dcd-header">
        <h1>数据中心机房资源管理 (""" + target_room + """)</h1>
      </header>
      <main class="dcd-main">
        <div class="metrics-grid" id="metrics-container"></div>
        <div id="content-container"></div>
      </main>
      
      <!-- Modal -->
      <div class="dcd-modal-overlay" id="cabinet-modal">
        <div class="modal-content">
          <div class="modal-header">
            <h2 class="modal-title" id="modal-title">机柜详情</h2>
            <button class="close-btn" id="close-modal">&times;</button>
          </div>
          <div class="modal-body">
            <div class="rack-container" id="rack-container">
            </div>
            <div class="rack-details">
              <div class="legend">
                <div class="legend-item"><div class="legend-color c-used"></div>设备占用</div>
                <div class="legend-item"><div class="legend-color c-heat"></div>预留(1U)</div>
                <div class="legend-item"><div class="legend-color c-empty"></div>空闲</div>
              </div>
              <div class="equip-info" id="equip-info">
                <h4 id="eq-name"></h4>
                <div class="info-row"><div class="info-label">型号</div><div class="info-val" id="eq-model"></div></div>
                <div class="info-row"><div class="info-label">位置</div><div class="info-val" id="eq-pos"></div></div>
                <div class="info-row"><div class="info-label">U数</div><div class="info-val" id="eq-size"></div></div>
                <div class="info-row"><div class="info-label">用途</div><div class="info-val" id="eq-purpose"></div></div>
                <div class="info-row"><div class="info-label">SN</div><div class="info-val" id="eq-sn"></div></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    
    <style>
      .dcd-wrapper {
        font-family: 'Inter', -apple-system, sans-serif;
        background-color: #0f172a;
        color: #f8fafc;
        width: 100%;
        height: 100%;
        overflow-y: auto;
        padding: 0;
        margin: 0;
        box-sizing: border-box;
      }
      .dcd-wrapper * { box-sizing: border-box; }
      .dcd-header {
        padding: 1rem 1.5rem;
        background: rgba(15, 23, 42, 0.9);
        border-bottom: 1px solid #334155;
        position: sticky;
        top: 0;
        z-index: 10;
      }
      .dcd-header h1 { margin: 0; font-size: 1.25rem; font-weight: 700; color: #fff; }
      
      .dcd-main { padding: 1.5rem; display: flex; flex-direction: column; gap: 1.5rem; }
      
      .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; }
      .metric-card {
        background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 1rem;
        transition: transform 0.2s;
      }
      .metric-card:hover { transform: translateY(-2px); }
      .metric-title { color: #94a3b8; font-size: 0.75rem; text-transform: uppercase; font-weight: 600; margin-bottom: 0.5rem; }
      .metric-value { font-size: 2rem; font-weight: 700; color: #fff; }
      
      .module-section { margin-bottom: 1.5rem; }
      .module-title { font-size: 1.1rem; font-weight: 600; padding-bottom: 0.5rem; border-bottom: 1px solid #334155; margin-bottom: 1rem; }
      .cabinets-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(70px, 1fr)); gap: 0.75rem; }
      
      .cabinet-item {
        background: #334155; border-radius: 6px; padding: 0.75rem 0.25rem; text-align: center;
        cursor: pointer; position: relative; overflow: hidden; z-index: 1; border: 1px solid transparent;
        display: flex; flex-direction: column; gap: 0.25rem;
      }
      .cabinet-item:hover { border-color: #3b82f6; box-shadow: 0 0 10px rgba(59, 130, 246, 0.3); }
      .cabinet-item.has-equip { border-bottom: 3px solid #10b981; }
      .cabinet-item.empty { border-bottom: 3px solid #94a3b8; opacity: 0.7; }
      
      .cabinet-fill { position: absolute; bottom: 0; left: 0; width: 100%; background: rgba(59, 130, 246, 0.2); z-index: -1; transition: height 0.5s; }
      .cabinet-item:hover .cabinet-fill { background: rgba(59, 130, 246, 0.4); }
      
      .cabinet-name { font-weight: 600; font-size: 0.8rem; }
      .cabinet-util { font-size: 0.7rem; color: #cbd5e1; }
      
      /* Modal */
      .dcd-modal-overlay {
        position: absolute; top: 0; left: 0; right: 0; bottom: 0;
        background: rgba(15, 23, 42, 0.85); z-index: 100;
        display: flex; justify-content: center; align-items: center;
        opacity: 0; pointer-events: none; transition: opacity 0.2s;
      }
      .dcd-modal-overlay.active { opacity: 1; pointer-events: all; }
      
      .dcd-modal-overlay .modal-content {
        background: #1e293b; border: 1px solid #334155; border-radius: 8px;
        width: 90%; max-width: 600px; height: 85%; display: flex; flex-direction: column;
        box-shadow: 0 10px 30px rgba(0,0,0,0.5);
      }
      .dcd-modal-overlay .modal-header { padding: 1rem; border-bottom: 1px solid #334155; display: flex; justify-content: space-between; align-items: center; }
      .dcd-modal-overlay .modal-title { margin: 0; font-size: 1.1rem; }
      .dcd-modal-overlay .close-btn { background: none; border: none; color: #94a3b8; font-size: 1.5rem; cursor: pointer; }
      .dcd-modal-overlay .close-btn:hover { color: #ef4444; }
      
      .dcd-modal-overlay .modal-body { padding: 1rem; flex: 1; overflow-y: auto; display: flex; align-items: flex-start; gap: 1.5rem; }
      
      .rack-container {
        width: 120px; background: #111827; border: 3px solid #374151; border-radius: 4px;
        display: flex; flex-direction: column-reverse; padding: 2px; gap: 1px; flex-shrink: 0;
      }
      .u-slot {
        height: 16px; background: rgba(30,41,59,0.8); display: flex; align-items: center;
        font-size: 0.55rem; color: rgba(255,255,255,0.3);
      }
      .u-slot.equip-slot { background: rgba(59,130,246,0.8); color: white; border: 1px solid rgba(255,255,255,0.2); cursor: pointer; }
      .u-slot.equip-slot:hover { filter: brightness(1.2); }
      .u-slot.heat-slot { background: rgba(245,158,11,0.4); color: rgba(255,255,255,0.8); }
      
      .rack-details { flex: 1; display: flex; flex-direction: column; gap: 1rem; }
      .legend { display: flex; gap: 0.75rem; font-size: 0.75rem; flex-wrap: wrap; }
      .legend-item { display: flex; align-items: center; gap: 0.25rem; }
      .legend-color { width: 12px; height: 12px; border-radius: 3px; }
      .c-used { background: rgba(59,130,246,0.8); }
      .c-heat { background: rgba(245,158,11,0.4); }
      .c-empty { background: rgba(30,41,59,0.8); }
      
      .equip-info { background: #334155; padding: 1rem; border-radius: 6px; font-size: 0.8rem; display: none; }
      .equip-info.active { display: block; }
      .equip-info h4 { margin: 0 0 0.5rem 0; color: #3b82f6; }
      .info-row { display: flex; margin-bottom: 0.25rem; }
      .info-label { width: 60px; color: #94a3b8; }
      .info-val { flex: 1; color: #f8fafc; }
    </style>
    
    <script>
      (function() {
        const roomData = """ + json_data + """;
        const container = document.getElementById('dcd-container');
        if(!container) return;
        
        const metricsContainer = container.querySelector('#metrics-container');
        const contentContainer = container.querySelector('#content-container');
        const modal = container.querySelector('#cabinet-modal');
        const closeBtn = container.querySelector('#close-modal');
        
        closeBtn.addEventListener('click', () => modal.classList.remove('active'));
        
        function calculateCabinetUsage(cabinet) {
          const totalU = cabinet.totalU || 47;
          const slots = Array(totalU + 1).fill('EMPTY');
          
          cabinet.equipment.forEach(eq => {
            let start = eq.startU; if (!start || start < 1) start = 1;
            const end = Math.min(start + eq.sizeU - 1, totalU);
            for (let i = start; i <= end; i++) slots[i] = { type: 'EQUIP', data: eq };
          });
          
          cabinet.equipment.forEach(eq => {
            let start = eq.startU; if (!start || start < 1) start = 1;
            const end = Math.min(start + eq.sizeU - 1, totalU);
            if (end + 1 <= totalU && slots[end + 1] === 'EMPTY') slots[end + 1] = 'HEAT';
          });
          
          let usedSlots = 0;
          for(let i=1; i<=totalU; i++) if(slots[i] !== 'EMPTY') usedSlots++;
          
          return { slots, usedCount: usedSlots, totalU, equipCount: cabinet.equipment.length };
        }
        
        function render() {
          let totalCabinets = 0, usedCabinets = 0, totalUs = 0, usedUs = 0;
          contentContainer.innerHTML = '';
          
          roomData.modules.forEach(m => {
            const section = document.createElement('div');
            section.className = 'module-section';
            section.innerHTML = "<div class='module-title'>" + m.name + "</div>";
            const grid = document.createElement('div');
            grid.className = 'cabinets-grid';
            
            m.cabinets.forEach(c => {
              totalCabinets++;
              const usage = calculateCabinetUsage(c);
              if (usage.equipCount > 0) usedCabinets++;
              totalUs += usage.totalU; usedUs += usage.usedCount;
              
              const utilPercent = usage.equipCount > 0 ? ((usage.usedCount / usage.totalU)*100).toFixed(0) : 0;
              const utilText = usage.equipCount > 0 ? utilPercent + '%' : '空';
              
              const cabDiv = document.createElement('div');
              cabDiv.className = 'cabinet-item ' + (usage.equipCount > 0 ? 'has-equip' : 'empty');
              cabDiv.innerHTML = "<div class='cabinet-fill' style='height: " + utilPercent + "%;'></div>" +
                                 "<div class='cabinet-name'>" + c.name + "</div>" +
                                 "<div class='cabinet-util'>" + utilText + "</div>";
              cabDiv.addEventListener('click', () => showModal(c, usage));
              grid.appendChild(cabDiv);
            });
            section.appendChild(grid);
            contentContainer.appendChild(section);
          });
          
          const mountingRate = ((usedCabinets / totalCabinets) * 100).toFixed(1);
          const spaceUtilRate = ((usedUs / totalUs) * 100).toFixed(1);
          
          metricsContainer.innerHTML = 
            "<div class='metric-card'><div class='metric-title'>上架率 (Mounting Rate)</div><div class='metric-value'>" + mountingRate + "%</div><div style='color:#94a3b8;font-size:0.75rem'>(" + usedCabinets + " / " + totalCabinets + " 机柜)</div></div>" +
            "<div class='metric-card'><div class='metric-title'>空间使用率 (Space Util)</div><div class='metric-value'>" + spaceUtilRate + "%</div><div style='color:#94a3b8;font-size:0.75rem'>(" + usedUs + "U / " + totalUs + "U) 含散热</div></div>";
        }
        
        function showModal(cabinet, usage) {
          container.querySelector('#modal-title').innerText = "机柜详情 - " + cabinet.name;
          const rackContainer = container.querySelector('#rack-container');
          rackContainer.innerHTML = '';
          const equipInfo = container.querySelector('#equip-info');
          equipInfo.classList.remove('active');
          
          for(let i = 1; i <= usage.totalU; i++) {
            const slotData = usage.slots[i];
            const uDiv = document.createElement('div');
            uDiv.className = 'u-slot';
            const label = document.createElement('span');
            label.innerText = i;
            label.style.marginRight = '4px'; label.style.width = '14px'; label.style.textAlign = 'right';
            uDiv.appendChild(label);
            
            if (slotData === 'HEAT') {
              uDiv.classList.add('heat-slot');
              const t = document.createElement('span'); t.innerText = "预留"; uDiv.appendChild(t);
            } else if (slotData !== 'EMPTY' && slotData.type === 'EQUIP') {
              uDiv.classList.add('equip-slot');
              const eq = slotData.data;
              if (i === (eq.startU || 1)) {
                const t = document.createElement('span'); t.innerText = eq.name;
                t.style.whiteSpace = 'nowrap'; t.style.overflow = 'hidden'; t.style.textOverflow = 'ellipsis';
                uDiv.appendChild(t);
              }
              uDiv.addEventListener('click', () => {
                equipInfo.classList.add('active');
                container.querySelector('#eq-name').innerText = eq.name;
                container.querySelector('#eq-model').innerText = eq.model || '-';
                container.querySelector('#eq-pos').innerText = "U" + eq.startU + " - U" + Math.min(eq.startU + eq.sizeU - 1, usage.totalU);
                container.querySelector('#eq-size').innerText = eq.sizeU + "U";
                container.querySelector('#eq-purpose').innerText = eq.purpose || '-';
                container.querySelector('#eq-sn').innerText = eq.id || '-';
              });
            }
            rackContainer.appendChild(uDiv);
          }
          modal.classList.add('active');
        }
        
        render();
      })();
    </script>
    """
    
    return {"html": html, "state": state}

def on_action(action: str, payload: dict, config: dict, state: dict) -> dict:
    return render(config, state)
