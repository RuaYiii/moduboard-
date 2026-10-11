(() => {
    'use strict';

    const $ = (selector, root = document) => root.querySelector(selector);
    const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
    const viewport = $('#iw-viewport');
    const graph = $('#iw-graph');
    const canvas = $('#iw-links');
    const ctx = canvas.getContext('2d');
    const runButton = $('#iw-run');
    const runtimeMode = $('#iw-runtime-mode');
    const transport = $('#iw-transport');
    const operation = $('#iw-operation');
    const addressMode = $('#iw-address-mode');
    const address = $('#iw-address');
    const quantity = $('#iw-quantity');
    const dataType = $('#iw-data-type');
    const rawInput = $('#iw-raw');
    const nodes = Object.fromEntries($$('.iw-node').map(node => [node.dataset.node, node]));
    const defaultPositions = Object.fromEntries(Object.entries(nodes).map(([key, node]) => [key, {left: node.style.left, top: node.style.top}]));
    const edges = [['connection', 'request'], ['request', 'decoder'], ['decoder', 'output'], ['request', 'log']];
    const securePolicies = ['Aes256_Sha256_RsaPss', 'Aes128_Sha256_RsaOaep', 'Basic256Sha256', 'Basic256', 'Basic128Rsa15'];
    const registerTypes = [
        ['bool', 'Bool'], ['bit', 'Bit'], ['bitfield', 'BitField'],
        ['uint16', 'UInt16 / UBInt16'], ['int16', 'Int16 / SBInt16'],
        ['uint32', 'UInt32 / UBInt32'], ['int32', 'Int32 / SBInt32'],
        ['float32', 'Float32 / LFloat32'], ['uint64', 'UInt64'], ['int64', 'Int64'],
        ['float64', 'Float64'], ['string', 'String'], ['hex', 'Raw HEX'],
    ];
    const bitTypes = [['bool', 'Bool'], ['bit', 'Bit'], ['hex', 'Raw HEX']];
    const modbusPresets = {
        gateway0100: {transport: 'modbus_tcp', host: '215.8.24.139', port: '502', timeout: '3', retries: '0', unit_id: '15', operation: '3', address_mode: 'raw', address: '256', quantity: '1', data_type: 'uint16', byte_order: 'ABCD', scale: '1', decode_offset: '0'},
        nt_voltage_c: {transport: 'modbus_tcp', host: '215.8.5.12', port: '4002', timeout: '3', retries: '0', unit_id: '1', operation: '3', address_mode: 'raw', address: '82', quantity: '2', data_type: 'float32', byte_order: 'CDAB', scale: '1', decode_offset: '0'},
        blank: {transport: 'modbus_tcp', host: '', port: '502', timeout: '3', retries: '0', unit_id: '1', operation: '3', address_mode: 'raw', address: '0', quantity: '1', data_type: 'uint16', byte_order: 'ABCD', scale: '1', decode_offset: '0'},
    };
    let scale = 1;
    let toastTimer = null;
    let activeProtocol = 'modbus';

    const isRealMode = () => runtimeMode.value === 'real';

    function fill(select, items, preferred) {
        select.replaceChildren(...items.map(([value, label]) => {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = label;
            return option;
        }));
        if (items.some(([value]) => value === preferred)) select.value = preferred;
    }

    function syncConnection() {
        const connectionKind = ['modbus_tcp', 'rtu_over_tcp'].includes(transport.value) ? 'network' : 'modbus_rtu';
        $$('.iw-conn').forEach(element => element.classList.toggle('iw-hidden', element.dataset.conn !== connectionKind));
    }

    function updateAddressMap() {
        const visible = Number(address.value);
        let offset = visible;
        if (addressMode.value === 'one_based') offset = visible - 1;
        if (addressMode.value === 'reference_3x') offset = visible - 30001;
        if (addressMode.value === 'reference_4x') offset = visible - 40001;
        $('#iw-address-caption').textContent = `${addressMode.options[addressMode.selectedIndex]?.text || ''} ${Number.isFinite(visible) ? visible : '—'}`;
        $('#iw-offset').textContent = `Protocol Offset ${Number.isFinite(offset) ? offset : '—'}`;
    }

    function syncModbus() {
        const real = isRealMode();
        $$('option', operation).forEach(option => {
            option.disabled = real && [5, 6, 15, 16].includes(Number(option.value));
        });
        if (real && [5, 6, 15, 16].includes(Number(operation.value))) operation.value = '3';
        const fc = Number(operation.value);
        const bitArea = [1, 2, 5, 15].includes(fc);
        const write = [5, 6, 15, 16].includes(fc);
        const single = [5, 6].includes(fc);
        const previousMode = addressMode.value;
        const modes = [['raw', 'Raw / Zero Based'], ['one_based', 'One Based']];
        if ([3, 6, 16].includes(fc)) modes.push(['reference_4x', '4xxxx Reference']);
        if (fc === 4) modes.push(['reference_3x', '3xxxx Reference']);
        const fallback = 'raw';
        fill(addressMode, modes, modes.some(([value]) => value === previousMode) ? previousMode : fallback);
        if (previousMode?.startsWith('reference_') && !addressMode.value.startsWith('reference_')) address.value = '0';
        if (addressMode.value === 'reference_3x' && Number(address.value) >= 40001) address.value = '30001';
        if (addressMode.value === 'reference_4x' && Number(address.value) >= 30001 && Number(address.value) < 40001) address.value = '40001';
        quantity.disabled = single;
        if (single) quantity.value = '1';
        fill(dataType, bitArea ? bitTypes : registerTypes, dataType.value || 'uint16');
        $('#iw-order-field').classList.toggle('iw-hidden', bitArea);
        const selectedType = dataType.value;
        const engineeringType = !bitArea && !['bool', 'bit', 'bitfield', 'string', 'hex'].includes(selectedType);
        $('#iw-scale-field').classList.toggle('iw-hidden', !engineeringType);
        $('#iw-decode-offset-field').classList.toggle('iw-hidden', !engineeringType);
        $('#iw-bit-index-field').classList.toggle('iw-hidden', selectedType !== 'bit');
        $('#iw-encoding-field').classList.toggle('iw-hidden', selectedType !== 'string');
        const words = {bool: 1, bit: 1, bitfield: 1, uint16: 1, int16: 1, uint32: 2, int32: 2, float32: 2, uint64: 4, int64: 4, float64: 4}[selectedType];
        $('#iw-decode-hint').textContent = words
            ? `${dataType.options[dataType.selectedIndex]?.text || selectedType} 至少需要 ${words} 个寄存器；Scale × 原值 + Offset。`
            : 'String / Raw HEX 使用 Quantity 指定读取长度。';
        if (bitArea && ['00 00 43 5C', '43 5C 00 00'].includes(rawInput.value)) rawInput.value = '05';
        if (!bitArea && ['01', '05'].includes(rawInput.value)) rawInput.value = '00 00 43 5C';
        $('#iw-write-warning').classList.toggle('iw-hidden', !write);
        $('#iw-write-values-field').classList.toggle('iw-hidden', !write);
        $('#iw-write-warning').textContent = '写功能仅供离线模拟；真实设备模式不会发送写请求。';
        if (activeProtocol === 'modbus') runButton.textContent = write ? (isRealMode() ? '执行写入' : '模拟写入') : (isRealMode() ? '读取设备' : '模拟读取');
        updateAddressMap();
    }

    function drawArrow(x1, y1, x2, y2) {
        const color = getComputedStyle(document.documentElement).getPropertyValue('--color-primary').trim() || '#4f6ef7';
        const bend = Math.max(45, Math.abs(x2 - x1) * .45);
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.bezierCurveTo(x1 + bend, y1, x2 - bend, y2, x2, y2);
        ctx.strokeStyle = color;
        ctx.globalAlpha = .55;
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.globalAlpha = 1;
        ctx.beginPath();
        ctx.arc(x1, y1, 3, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
        ctx.beginPath();
        ctx.moveTo(x2, y2);
        ctx.lineTo(x2 - 8, y2 - 4);
        ctx.lineTo(x2 - 8, y2 + 4);
        ctx.closePath();
        ctx.fill();
    }

    function drawLinks() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        if (activeProtocol !== 'modbus') return;
        edges.forEach(([fromKey, toKey]) => {
            const from = nodes[fromKey];
            const to = nodes[toKey];
            drawArrow(from.offsetLeft + from.offsetWidth, from.offsetTop + from.offsetHeight / 2, to.offsetLeft, to.offsetTop + to.offsetHeight / 2);
        });
    }

    function setScale(next) {
        scale = Math.min(1.35, Math.max(.55, next));
        graph.style.transform = `scale(${scale})`;
        $('#iw-zoom-label').textContent = `${Math.round(scale * 100)}%`;
        drawLinks();
    }

    function fitGraph() {
        const usableWidth = Math.max(320, viewport.clientWidth - 32);
        setScale(Math.min(1, usableWidth / 1500));
        viewport.scrollTo({left: 0, top: 0, behavior: 'smooth'});
    }

    function bindDragging(node) {
        const handle = $('.iw-node-head', node);
        handle.addEventListener('pointerdown', event => {
            event.preventDefault();
            node.setPointerCapture(event.pointerId);
            const startX = event.clientX;
            const startY = event.clientY;
            const left = node.offsetLeft;
            const top = node.offsetTop;
            const move = moveEvent => {
                node.style.left = `${Math.max(10, left + (moveEvent.clientX - startX) / scale)}px`;
                node.style.top = `${Math.max(10, top + (moveEvent.clientY - startY) / scale)}px`;
                drawLinks();
            };
            const up = () => {
                node.removeEventListener('pointermove', move);
                node.removeEventListener('pointerup', up);
                node.removeEventListener('pointercancel', up);
                saveLayout();
            };
            node.addEventListener('pointermove', move);
            node.addEventListener('pointerup', up);
            node.addEventListener('pointercancel', up);
        });
        node.addEventListener('pointerdown', () => {
            $$('.iw-node').forEach(item => item.classList.remove('iw-selected'));
            node.classList.add('iw-selected');
        });
    }

    function saveLayout() {
        const positions = Object.fromEntries(Object.entries(nodes).map(([key, node]) => [key, {left: node.style.left, top: node.style.top}]));
        localStorage.setItem('industrialNodeLayout', JSON.stringify(positions));
    }

    function restoreLayout() {
        try {
            const positions = JSON.parse(localStorage.getItem('industrialNodeLayout') || '{}');
            Object.entries(positions).forEach(([key, position]) => {
                if (!nodes[key] || !position) return;
                nodes[key].style.left = position.left;
                nodes[key].style.top = position.top;
            });
        } catch (_) {
            localStorage.removeItem('industrialNodeLayout');
        }
    }

    function resetLayout() {
        Object.entries(defaultPositions).forEach(([key, position]) => {
            nodes[key].style.left = position.left;
            nodes[key].style.top = position.top;
        });
        localStorage.removeItem('industrialNodeLayout');
        drawLinks();
        fitGraph();
        showToast('Modbus 节点布局已重置');
    }

    function collectModbusPayload() {
        const payload = {};
        $$('[data-key]', graph).forEach(element => {
            const connection = element.closest('.iw-conn');
            if (!connection || !connection.classList.contains('iw-hidden')) payload[element.dataset.key] = element.value;
        });
        return payload;
    }

    function saveModbusProfile() {
        localStorage.setItem('industrialModbusProfile', JSON.stringify(collectModbusPayload()));
    }

    function applyModbusProfile(profile, notify = false) {
        if (!profile || typeof profile !== 'object') return;
        if (profile.transport) transport.value = profile.transport;
        syncConnection();
        Object.entries(profile).forEach(([key, value]) => {
            $$(`[data-key="${key}"]`, graph).forEach(element => {
                const connection = element.closest('.iw-conn');
                if (!connection || !connection.classList.contains('iw-hidden')) element.value = value;
            });
        });
        syncModbus();
        if (profile.address_mode && [...addressMode.options].some(option => option.value === profile.address_mode)) addressMode.value = profile.address_mode;
        if (profile.data_type && [...dataType.options].some(option => option.value === profile.data_type)) dataType.value = profile.data_type;
        syncModbus();
        updateAddressMap();
        saveModbusProfile();
        if (notify) showToast('Modbus 模板已载入并保存');
    }

    function restoreModbusProfile() {
        try {
            const profile = JSON.parse(localStorage.getItem('industrialModbusProfile') || 'null');
            if (profile) applyModbusProfile(profile);
        } catch (_) {
            localStorage.removeItem('industrialModbusProfile');
        }
    }

    function renderResult(result) {
        const target = $('#iw-result');
        target.className = `iw-result-value${result.ok ? '' : ' iw-result-error'}`;
        target.replaceChildren();
        const title = document.createElement('span'); title.textContent = result.title;
        const value = document.createElement('strong'); value.textContent = result.value;
        const raw = document.createElement('code'); raw.textContent = result.raw;
        const meta = document.createElement('small'); meta.textContent = result.meta;
        target.append(title, value, raw, meta);
        $('#iw-result-status').textContent = result.ok ? '正常' : '错误';
        $('#iw-result-status').style.color = result.ok ? 'var(--color-success)' : 'var(--color-danger)';
    }

    function renderLogs(logs) {
        const target = $('#iw-log');
        target.className = '';
        target.replaceChildren();
        [...(logs || [])].reverse().forEach(item => {
            const row = document.createElement('div'); row.className = 'iw-log-row';
            const time = document.createElement('time'); time.textContent = item.time;
            const kind = document.createElement('b'); kind.textContent = item.kind;
            const text = document.createElement('span'); text.textContent = item.text;
            row.append(time, kind, text); target.append(row);
        });
    }

    function showToast(message) {
        const toast = $('#iw-toast');
        toast.textContent = message;
        toast.classList.add('iw-show');
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => toast.classList.remove('iw-show'), 2200);
    }

    async function invokeDebugger(payload) {
        const response = await fetch('/api/modules/industrial_debugger/action', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action: 'execute', payload, config: {}, state: {}}),
        });
        const data = await response.json();
        if (!response.ok || data.status !== 'success') throw new Error(data.error || '请求失败');
        return data.state;
    }

    async function postJson(url, payload = {}) {
        const response = await fetch(url, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!response.ok || data.status !== 'success') {
            const error = new Error(data.error || '请求失败');
            error.category = data.category || '';
            error.details = data.details || '';
            throw error;
        }
        return data.result;
    }

    function renderRealModbus(result) {
        renderResult({
            ok: true,
            title: `${result.transport} · FC${Number(result.function_code).toString(16).toUpperCase().padStart(2, '0')}`,
            value: typeof result.decoded_value === 'object' ? JSON.stringify(result.decoded_value) : String(result.decoded_value),
            raw: result.raw_bytes || '写入响应无 Data Bytes',
            meta: `Unit ${result.unit_id} · Offset ${result.protocol_offset} · ${result.latency_ms} ms · ${result.timestamp}`,
        });
        renderLogs([
            {time: result.timestamp.slice(11, 23), kind: 'TX PDU', text: result.request_pdu},
            {time: result.timestamp.slice(11, 23), kind: 'RX PDU', text: result.response_pdu},
            {time: result.timestamp.slice(11, 23), kind: '解析', text: `Address ${result.visible_address} → Offset ${result.protocol_offset} · ${result.latency_ms} ms`},
        ]);
    }

    async function runModbusFlow() {
        const payload = collectModbusPayload();
        runButton.disabled = true;
        runButton.textContent = '运行中…';
        try {
            if (isRealMode()) {
                const result = await postJson('/api/industrial/modbus/execute', payload);
                renderRealModbus(result);
                showToast(`设备响应正常 · ${result.latency_ms} ms`);
            } else {
                const state = await invokeDebugger(payload);
                renderResult(state.result);
                renderLogs(state.logs);
                showToast(state.result.ok ? '模拟流程运行完成' : '请检查请求参数');
            }
        } catch (error) {
            renderResult({ok: false, title: error.category || '通信失败', value: error.message, raw: error.details || '未收到有效响应', meta: new Date().toLocaleString('zh-CN')});
            renderLogs([{time: new Date().toLocaleTimeString('zh-CN', {hour12: false}), kind: 'ERROR', text: `${error.category || 'Communication error'} · ${error.message}`}]);
            showToast(`运行失败：${error.message}`);
        } finally {
            runButton.disabled = false;
            syncModbus();
        }
    }

    /* OPC UA Subscription Builder */
    const opcCatalog = [
        {id: 'd1-current-a', group: '已知现场测点', name: 'D1-E-MS-STBB2-B005-P5F30 · A 相电流', nodeId: 'ns=2;s=property_407825926124554_value', dataType: 'Double', unit: 'A', base: 0, critical: true},
        {id: 'known-test-1', group: '已知现场测点', name: '测试测点 1', nodeId: 'ns=2;s=property_407825926123704_value', dataType: 'Double', unit: '', base: 0, critical: true},
        {id: 'spring-energy', group: '已知现场测点', name: '弹簧储能', nodeId: 'ns=2;s=property_407825926126189_value', dataType: 'Boolean', unit: '', base: false, critical: true},
        {id: 'known-test-2', group: '已知现场测点', name: '测试测点 2', nodeId: 'ns=2;s=property_411507327850646_value', dataType: 'Double', unit: '', base: 0, critical: true},
    ];
    let opcBrowseItems = [];
    let selectedCatalog = new Set();
    let monitoredItems = [];
    let nextItemId = 1;
    let opcConnected = false;
    let opcRunning = false;
    let opcTimer = null;
    let lastOpcSequence = 0;

    function makeElement(tag, className, text) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text !== undefined) element.textContent = text;
        return element;
    }

    function renderOpcBrowser() {
        const target = $('#opc-browser');
        const query = $('#opc-search').value.trim().toLowerCase();
        const source = isRealMode() ? opcBrowseItems : opcCatalog;
        const matches = source.filter(item => `${item.group || ''} ${item.name} ${item.nodeId}`.toLowerCase().includes(query));
        target.replaceChildren();
        let currentGroup = '';
        matches.forEach(item => {
            if (item.group && item.group !== currentGroup) {
                currentGroup = item.group;
                target.append(makeElement('div', 'iw-browser-group', currentGroup));
            }
            const label = makeElement('label', 'iw-browser-item');
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.disabled = item.nodeClass && item.nodeClass !== 'Variable';
            checkbox.checked = selectedCatalog.has(item.id);
            checkbox.addEventListener('change', () => {
                checkbox.checked ? selectedCatalog.add(item.id) : selectedCatalog.delete(item.id);
                updateSelectedCount();
            });
            const identity = document.createElement('span');
            identity.append(makeElement('strong', '', item.name), makeElement('small', '', item.nodeId));
            const kind = makeElement('em', '', item.dataType || item.nodeClass || '');
            if (item.nodeClass && item.nodeClass !== 'Variable') {
                label.classList.add('iw-browse-object');
                label.title = '双击进入此节点';
                label.addEventListener('dblclick', () => browseOpcNode(item.nodeId));
            }
            label.append(checkbox, identity, kind);
            target.append(label);
        });
        if (!matches.length) target.append(makeElement('div', 'iw-browser-empty', isRealMode() ? '连接后点击 Browse 读取 Server Address Space' : '没有匹配的 Variable'));
    }

    function updateSelectedCount() {
        $('#opc-selected-count').textContent = `${selectedCatalog.size} 已选`;
    }

    function newMonitoredItem(source) {
        return {
            id: nextItemId++,
            name: source.name,
            node_id: source.nodeId,
            data_type: source.dataType || 'Double',
            unit: source.unit || '',
            base: source.base ?? 0,
            alarm: Boolean(source.alarm),
            critical: Boolean(source.critical),
            sampling_interval: '1000',
            queue_size: '10',
            deadband: '0',
            value: '—',
            status: 'Waiting',
            source_timestamp: '—',
            server_timestamp: '—',
            receive_timestamp: '—',
        };
    }

    function addSources(sources, notify = true) {
        let added = 0;
        sources.forEach(source => {
            if (monitoredItems.some(item => item.node_id === source.nodeId)) return;
            monitoredItems.push(newMonitoredItem(source));
            added += 1;
        });
        renderOpcItems();
        if (notify) showToast(added ? `已添加 ${added} 个 MonitoredItem` : '所选测点已在 Subscription 中');
    }

    function inputFor(item, field, type = 'text') {
        const input = document.createElement('input');
        input.type = type;
        input.value = item[field];
        input.dataset.itemId = item.id;
        input.dataset.field = field;
        if (type === 'number') input.min = field === 'queue_size' ? '1' : '0';
        if (field === 'deadband') input.step = 'any';
        return input;
    }

    function renderOpcItems() {
        const body = $('#opc-item-body');
        body.replaceChildren();
        monitoredItems.forEach(item => {
            const row = document.createElement('tr');
            row.dataset.itemId = item.id;
            const criticalCell = document.createElement('td');
            const critical = makeElement('button', `iw-critical-toggle${item.critical ? ' iw-on' : ''}`, '★');
            critical.type = 'button'; critical.dataset.action = 'critical'; critical.dataset.itemId = item.id;
            critical.title = item.critical ? '取消关键测点' : '标记为关键测点';
            criticalCell.append(critical);
            const identityCell = makeElement('td', 'iw-item-identity');
            identityCell.append(makeElement('strong', '', item.name), makeElement('code', '', item.node_id));
            const typeCell = document.createElement('td');
            const typeSelect = document.createElement('select');
            const variantTypes = ['Boolean', 'SByte', 'Byte', 'Int16', 'UInt16', 'Int32', 'UInt32', 'Int64', 'UInt64', 'Float', 'Double', 'String', 'DateTime', 'ByteString', 'NodeId', 'LocalizedText', 'ExtensionObject'];
            if (item.data_type && !variantTypes.includes(item.data_type)) variantTypes.push(item.data_type);
            variantTypes.forEach(value => {
                const option = document.createElement('option'); option.value = value; option.textContent = value; typeSelect.append(option);
            });
            typeSelect.value = item.data_type; typeSelect.dataset.itemId = item.id; typeSelect.dataset.field = 'data_type'; typeCell.append(typeSelect);
            const samplingCell = document.createElement('td'); samplingCell.append(inputFor(item, 'sampling_interval', 'number'));
            const queueCell = document.createElement('td'); queueCell.append(inputFor(item, 'queue_size', 'number'));
            const deadbandCell = document.createElement('td'); deadbandCell.append(inputFor(item, 'deadband', 'number'));
            const valueCell = makeElement('td', 'iw-value-cell', item.value); valueCell.dataset.live = 'value';
            const statusCell = makeElement('td', statusClass(item.status), item.status); statusCell.dataset.live = 'status';
            const sourceTimeCell = makeElement('td', 'iw-status-wait', item.source_timestamp); sourceTimeCell.dataset.live = 'source_timestamp';
            const serverTimeCell = makeElement('td', 'iw-status-wait', item.server_timestamp); serverTimeCell.dataset.live = 'server_timestamp';
            const receiveTimeCell = makeElement('td', 'iw-status-wait', item.receive_timestamp); receiveTimeCell.dataset.live = 'receive_timestamp';
            const removeCell = document.createElement('td');
            const remove = makeElement('button', 'iw-remove-item', '×'); remove.type = 'button'; remove.dataset.action = 'remove'; remove.dataset.itemId = item.id; remove.title = '移除'; removeCell.append(remove);
            row.append(criticalCell, identityCell, typeCell, samplingCell, queueCell, deadbandCell, valueCell, statusCell, sourceTimeCell, serverTimeCell, receiveTimeCell, removeCell);
            body.append(row);
        });
        $('#opc-empty-items').classList.toggle('iw-hidden', monitoredItems.length > 0);
        updateOpcMetrics();
    }

    function statusClass(status) {
        if (String(status).startsWith('Good')) return 'iw-status-good';
        if (String(status).startsWith('Bad')) return 'iw-status-alarm';
        return 'iw-status-wait';
    }

    function updateOpcMetrics() {
        $('#opc-metric-total').textContent = monitoredItems.length;
        $('#opc-metric-good').textContent = monitoredItems.filter(item => String(item.status).startsWith('Good')).length;
        $('#opc-metric-alarm').textContent = monitoredItems.filter(item => item.alarm && item.value === 'TRUE').length;
    }

    function logOpc(message) {
        $('#opc-log').textContent = `${new Date().toLocaleTimeString('zh-CN', {hour12: false})} · ${message}`;
    }

    function opcConnectionPayload(operationName) {
        return {
            protocol_family: 'opc',
            transport: 'opc_ua',
            operation: operationName,
            endpoint: $('#opc-endpoint').value,
            securityMode: $('#opc-security-mode').value,
            securityPolicy: $('#opc-security-policy').value,
            authentication: $('#opc-authentication').value,
            username: $('#opc-username').value,
            certificate: $('#opc-certificate').value,
            privateKey: $('#opc-private-key').value,
            security_mode: $('#opc-security-mode').value,
            security_policy: $('#opc-security-policy').value,
            authentication: $('#opc-authentication').value,
            username: $('#opc-username').value,
            password: $('#opc-password').value,
            certificate: $('#opc-certificate').value,
            private_key: $('#opc-private-key').value,
            timeout: $('#opc-timeout').value,
            application_uri: $('#opc-application-uri').value,
        };
    }

    async function browseOpcNode(nodeId) {
        if (!isRealMode()) return;
        if (!opcConnected && !(await connectOpc(true))) return;
        const browseButton = $('#opc-browse');
        browseButton.disabled = true;
        try {
            const result = await postJson('/api/industrial/opc/browse', {node_id: nodeId || $('#opc-browse-nodeid').value, limit: 500});
            $('#opc-browse-nodeid').value = result.node_id;
            $('#opc-browse-location').textContent = `Current: ${result.node_id}${result.parent_id ? ` · Parent: ${result.parent_id}` : ''} · 双击 Object 进入`;
            opcBrowseItems = result.children.map(item => ({
                id: item.node_id,
                name: item.display_name || item.browse_name,
                nodeId: item.node_id,
                dataType: item.data_type,
                nodeClass: item.node_class,
                accessLevel: item.access_level,
                critical: false,
                base: 0,
            }));
            selectedCatalog = new Set(); updateSelectedCount(); renderOpcBrowser();
            logOpc(`BROWSE ${result.node_id} · ${result.children.length} references`);
        } catch (error) {
            logOpc(`BROWSE ERROR · ${error.message}`);
            showToast(`Browse 失败：${error.message}`);
        } finally {
            browseButton.disabled = false;
        }
    }

    async function connectOpc(quiet = false) {
        const button = $('#opc-connect');
        button.disabled = true;
        button.textContent = '连接中…';
        try {
            if (isRealMode()) {
                await postJson('/api/industrial/opc/connect', opcConnectionPayload('connect'));
            } else {
                const state = await invokeDebugger(opcConnectionPayload('connect'));
                if (!state.result.ok) throw new Error(state.result.value);
            }
            opcConnected = true;
            $('#opc-disconnect').disabled = false;
            const status = $('#opc-connection-status');
            status.textContent = 'Session Ready'; status.className = 'iw-status iw-status-ready';
            logOpc(`Session Ready · ${$('#opc-endpoint').value}`);
            if (!quiet) showToast(isRealMode() ? 'OPC UA Session 已连接' : 'OPC UA Session 已模拟建立');
            if (isRealMode()) await browseOpcNode($('#opc-browse-nodeid').value || 'i=85');
            return true;
        } catch (error) {
            opcConnected = false;
            $('#opc-disconnect').disabled = true;
            const status = $('#opc-connection-status');
            status.textContent = '连接失败'; status.className = 'iw-status iw-status-offline';
            logOpc(`CONNECT ERROR · ${error.message}`);
            showToast(`连接失败：${error.message}`);
            return false;
        } finally {
            button.disabled = false;
            button.textContent = opcConnected ? '重新连接' : '连接 Server';
        }
    }

    async function disconnectOpc() {
        try {
            if (isRealMode()) await postJson('/api/industrial/opc/disconnect');
        } catch (error) {
            showToast(`断开时发生错误：${error.message}`);
        }
        clearInterval(opcTimer); opcTimer = null; opcRunning = false; opcConnected = false;
        $('#opc-disconnect').disabled = true;
        $('#opc-start').disabled = false; $('#opc-start').textContent = '开始订阅'; $('#opc-stop').disabled = true;
        const status = $('#opc-connection-status'); status.textContent = '未连接'; status.className = 'iw-status iw-status-offline';
        logOpc('Session disconnected');
    }

    function collectOpcPayload() {
        const payload = opcConnectionPayload('subscribe');
        payload.subscription_name = $('#opc-subscription-name').value.trim() || 'Subscription #1';
        payload.publishing_interval = $('#opc-publishing').value;
        payload.keep_alive_count = $('#opc-keepalive').value;
        payload.lifetime_count = $('#opc-lifetime').value;
        payload.priority = $('#opc-priority').value;
        payload.node_id = monitoredItems[0]?.node_id || '';
        payload.monitored_items = monitoredItems.map(item => ({
            name: item.name,
            node_id: item.node_id,
            data_type: item.data_type,
            sampling_interval: item.sampling_interval,
            queue_size: item.queue_size,
            deadband: item.deadband,
            critical: item.critical,
        }));
        return payload;
    }

    async function startSubscription() {
        if (!monitoredItems.length) {
            showToast('请先添加至少一个 MonitoredItem');
            return;
        }
        $('#opc-start').disabled = true;
        runButton.disabled = true;
        if (!opcConnected && !(await connectOpc(true))) {
            $('#opc-start').disabled = false;
            runButton.disabled = false;
            return;
        }
        try {
            const payload = collectOpcPayload();
            let subscriptionText;
            if (isRealMode()) {
                const result = await postJson('/api/industrial/opc/subscription/start', {
                    config: {
                        name: payload.subscription_name,
                        publishing_interval: payload.publishing_interval,
                        keep_alive_count: payload.keep_alive_count,
                        lifetime_count: payload.lifetime_count,
                        priority: payload.priority,
                    },
                    items: payload.monitored_items,
                });
                subscriptionText = `Subscription #${result.subscription_id} · ${result.accepted}/${result.requested} MonitoredItems`;
            } else {
                const state = await invokeDebugger(payload);
                if (!state.result.ok) throw new Error(state.result.value);
                subscriptionText = `${state.result.title} · ${state.result.value}`;
            }
            opcRunning = true;
            clearInterval(opcTimer);
            if (isRealMode()) {
                lastOpcSequence = 0;
                await pollOpcStatus();
                opcTimer = setInterval(pollOpcStatus, 500);
            } else {
                updateOpcValues();
                opcTimer = setInterval(updateOpcValues, Math.max(100, Number($('#opc-publishing').value) || 1000));
            }
            $('#opc-start').textContent = '订阅运行中';
            $('#opc-stop').disabled = false;
            const status = $('#opc-connection-status'); status.textContent = 'Publishing'; status.className = 'iw-status iw-status-live';
            logOpc(subscriptionText);
            runButton.textContent = '停止订阅';
            showToast(`已订阅 ${monitoredItems.length} 个 MonitoredItem`);
        } catch (error) {
            logOpc(`SUBSCRIBE ERROR · ${error.message}`);
            showToast(`订阅失败：${error.message}`);
            $('#opc-start').disabled = false;
        } finally {
            runButton.disabled = false;
        }
    }

    async function stopSubscription(notify = true) {
        if (isRealMode() && opcRunning) {
            try { await postJson('/api/industrial/opc/subscription/stop'); }
            catch (error) { if (notify) showToast(`停止订阅失败：${error.message}`); }
        }
        clearInterval(opcTimer);
        opcTimer = null;
        opcRunning = false;
        $('#opc-start').disabled = false;
        $('#opc-start').textContent = '开始订阅';
        $('#opc-stop').disabled = true;
        const status = $('#opc-connection-status');
        status.textContent = opcConnected ? 'Session Ready' : '未连接';
        status.className = `iw-status ${opcConnected ? 'iw-status-ready' : 'iw-status-offline'}`;
        if (activeProtocol === 'opc') runButton.textContent = '开始订阅';
        if (notify) {
            logOpc('Subscription stopped');
            showToast('Subscription 已停止');
        }
    }

    function updateOpcValues() {
        const time = new Date();
        const stamp = time.toLocaleTimeString('zh-CN', {hour12: false});
        monitoredItems.forEach(item => {
            if (item.data_type === 'Boolean') {
                const value = item.alarm ? Math.random() < .035 : Boolean(item.base);
                item.value = value ? 'TRUE' : 'FALSE';
            } else if (['Double', 'Float', 'Int32', 'UInt32'].includes(item.data_type)) {
                const base = Number(item.base) || 0;
                const spread = Math.max(Math.abs(base) * .004, .08);
                const value = base + (Math.random() - .5) * spread;
                item.value = `${item.data_type.includes('Int') ? Math.round(value) : value.toFixed(2)}${item.unit ? ` ${item.unit}` : ''}`;
            } else {
                item.value = String(item.base ?? 'Normal');
            }
            item.status = 'Good';
            item.source_timestamp = stamp;
            item.server_timestamp = stamp;
            item.receive_timestamp = stamp;
            const row = $(`tr[data-item-id="${item.id}"]`, $('#opc-item-body'));
            if (!row) return;
            $('[data-live="value"]', row).textContent = item.value;
            const statusCell = $('[data-live="status"]', row); statusCell.textContent = item.status; statusCell.className = statusClass(item.status);
            ['source_timestamp', 'server_timestamp', 'receive_timestamp'].forEach(field => {
                const cell = $(`[data-live="${field}"]`, row); cell.textContent = item[field]; cell.className = '';
            });
        });
        $('#opc-metric-publish').textContent = stamp;
        updateOpcMetrics();
    }

    function formatOpcValue(value) {
        if (value === null || value === undefined) return '—';
        if (typeof value === 'boolean') return value ? 'TRUE' : 'FALSE';
        if (typeof value === 'object') return JSON.stringify(value);
        return String(value);
    }

    async function pollOpcStatus() {
        try {
            const response = await fetch(`/api/industrial/opc/status?since=${lastOpcSequence}`);
            const data = await response.json();
            if (!response.ok || data.status !== 'success') throw new Error(data.error || '状态读取失败');
            const snapshot = data.result;
            lastOpcSequence = snapshot.sequence;
            opcConnected = snapshot.connected;
            opcRunning = snapshot.running;
            if (snapshot.items.length) {
                snapshot.items.forEach(update => {
                    const item = monitoredItems.find(candidate => candidate.node_id === update.node_id);
                    if (!item) return;
                    item.value = formatOpcValue(update.value);
                    item.status = update.status || 'Unknown';
                    item.data_type = update.data_type || item.data_type;
                    item.source_timestamp = update.source_timestamp || '—';
                    item.server_timestamp = update.server_timestamp || '—';
                    item.receive_timestamp = update.receive_timestamp || '—';
                    const row = $(`tr[data-item-id="${item.id}"]`, $('#opc-item-body'));
                    if (!row) return;
                    $('[data-live="value"]', row).textContent = item.value;
                    const statusCell = $('[data-live="status"]', row); statusCell.textContent = item.status; statusCell.className = statusClass(item.status);
                    ['source_timestamp', 'server_timestamp', 'receive_timestamp'].forEach(field => {
                        const cell = $(`[data-live="${field}"]`, row); cell.textContent = item[field]; cell.className = '';
                    });
                });
            }
            const status = $('#opc-connection-status');
            if (!snapshot.connected) { status.textContent = snapshot.last_error ? '重连中' : '已断开'; status.className = 'iw-status iw-status-offline'; }
            else if (snapshot.running) { status.textContent = snapshot.reconnect_count ? `Publishing · R${snapshot.reconnect_count}` : 'Publishing'; status.className = 'iw-status iw-status-live'; }
            else { status.textContent = 'Session Ready'; status.className = 'iw-status iw-status-ready'; }
            const latestLog = snapshot.logs[snapshot.logs.length - 1];
            if (latestLog) $('#opc-log').textContent = `${latestLog.timestamp.slice(11, 23)} · ${latestLog.level} · ${latestLog.message}`;
            $('#opc-metric-publish').textContent = snapshot.items.some(item => item.receive_timestamp) ? new Date().toLocaleTimeString('zh-CN', {hour12: false}) : $('#opc-metric-publish').textContent;
            updateOpcMetrics();
        } catch (error) {
            logOpc(`STATUS ERROR · ${error.message}`);
        }
    }

    function saveOpcProfile() {
        const profile = {
            name: $('#opc-subscription-name').value,
            endpoint: $('#opc-endpoint').value,
            publishing: $('#opc-publishing').value,
            keepalive: $('#opc-keepalive').value,
            lifetime: $('#opc-lifetime').value,
            priority: $('#opc-priority').value,
            items: monitoredItems.map(({id, value, status, source_timestamp, server_timestamp, receive_timestamp, ...item}) => item),
        };
        localStorage.setItem('industrialOpcSubscriptionProfile', JSON.stringify(profile));
        logOpc(`Profile saved · ${profile.items.length} items`);
        showToast('Subscription 配置已保存到本机');
    }

    function restoreOpcProfile() {
        try {
            const profile = JSON.parse(localStorage.getItem('industrialOpcSubscriptionProfile') || 'null');
            if (!profile || !Array.isArray(profile.items)) return false;
            $('#opc-subscription-name').value = profile.name || 'Critical Operations';
            $('#opc-endpoint').value = profile.endpoint || $('#opc-endpoint').value;
            $('#opc-security-mode').value = profile.securityMode || 'None';
            syncOpcSecurity();
            $('#opc-security-policy').value = profile.securityPolicy || 'None';
            $('#opc-authentication').value = profile.authentication || 'Anonymous';
            $('#opc-username').value = profile.username || '';
            $('#opc-certificate').value = profile.certificate || '';
            $('#opc-private-key').value = profile.privateKey || '';
            $('#opc-publishing').value = profile.publishing || '1000';
            $('#opc-keepalive').value = profile.keepalive || '10';
            $('#opc-lifetime').value = profile.lifetime || '60';
            $('#opc-priority').value = profile.priority || '0';
            monitoredItems = profile.items.map(item => ({...newMonitoredItem({name: item.name, nodeId: item.node_id, dataType: item.data_type, unit: item.unit, base: item.base, alarm: item.alarm, critical: item.critical}), ...item, id: nextItemId++, value: '—', status: 'Waiting', source_timestamp: '—', server_timestamp: '—', receive_timestamp: '—'}));
            return true;
        } catch (_) {
            localStorage.removeItem('industrialOpcSubscriptionProfile');
            return false;
        }
    }

    function syncOpcSecurity() {
        const mode = $('#opc-security-mode').value;
        const policy = $('#opc-security-policy');
        const previous = policy.value;
        fill(policy, mode === 'None' ? [['None', 'None']] : securePolicies.map(value => [value, value]), previous);
        $$('.iw-security-file').forEach(field => field.classList.toggle('iw-hidden', mode === 'None'));
        const usernameMode = $('#opc-authentication').value === 'Username / Password';
        $$('.iw-auth-field').forEach(field => field.classList.toggle('iw-hidden', !usernameMode));
    }

    function invalidateOpcConnection() {
        if (!opcConnected) return;
        opcConnected = false;
        if (opcRunning) stopSubscription(false);
        const status = $('#opc-connection-status');
        status.textContent = '配置已更改'; status.className = 'iw-status iw-status-offline';
    }

    async function runSelfCheck(showResult = true) {
        try {
            const response = await fetch('/api/industrial/self-check');
            const data = await response.json();
            const ports = $('#iw-serial-ports');
            ports.replaceChildren(...(data.serial_ports || []).map(port => {
                const option = document.createElement('option'); option.value = port.device; option.label = port.description; return option;
            }));
            if (showResult) {
                const missing = Object.entries(data.dependencies).filter(([, item]) => !item.installed).map(([name]) => name);
                showToast(data.ready ? `现场运行库已就绪 · 检测到 ${data.serial_ports.length} 个串口` : `缺少运行库：${missing.join(', ')}`);
            }
            return data.ready;
        } catch (error) {
            if (showResult) showToast(`现场自检失败：${error.message}`);
            return false;
        }
    }

    async function syncRuntimeMode() {
        const simulation = !isRealMode();
        $('.iw-runtime-mode').classList.toggle('iw-simulation', simulation);
        if (opcConnected || opcRunning) {
            try { await postJson('/api/industrial/opc/disconnect'); } catch (_) { /* best effort */ }
            await disconnectOpc();
        }
        opcBrowseItems = [];
        selectedCatalog = new Set();
        updateSelectedCount();
        $('#opc-browse').disabled = simulation;
        $('#opc-browse-location').textContent = simulation ? '离线模拟地址空间' : 'Objects · i=85 · 连接后 Browse';
        $('#opc-connect').textContent = simulation ? '模拟连接' : '连接 Server';
        renderOpcBrowser();
        syncModbus();
        switchProtocol(activeProtocol);
    }

    function switchProtocol(protocol) {
        activeProtocol = protocol;
        const isOpc = protocol === 'opc';
        $('#iw-tab-modbus').classList.toggle('iw-active', !isOpc);
        $('#iw-tab-opc').classList.toggle('iw-active', isOpc);
        $('#iw-modbus-rail').classList.toggle('iw-hidden', isOpc);
        viewport.classList.toggle('iw-hidden', isOpc);
        $('#iw-opc-workspace').classList.toggle('iw-hidden', !isOpc);
        $('#iw-main').classList.toggle('iw-opc-mode', isOpc);
        $('#iw-graph-actions').classList.toggle('iw-hidden', isOpc);
        runButton.textContent = isOpc ? (opcRunning ? '停止订阅' : '开始订阅') : ([5, 6, 15, 16].includes(Number(operation.value)) ? (isRealMode() ? '执行写入' : '模拟写入') : (isRealMode() ? '读取设备' : '模拟读取'));
        localStorage.setItem('industrialActiveProtocol', protocol);
        if (!isOpc) requestAnimationFrame(drawLinks);
    }

    transport.addEventListener('change', () => { syncConnection(); saveModbusProfile(); });
    operation.addEventListener('change', syncModbus);
    addressMode.addEventListener('change', updateAddressMap);
    address.addEventListener('input', updateAddressMap);
    dataType.addEventListener('change', syncModbus);
    $('#iw-apply-modbus-preset').addEventListener('click', () => {
        applyModbusProfile(modbusPresets[$('#iw-modbus-preset').value], true);
    });
    graph.addEventListener('change', event => {
        if (event.target.matches('[data-key]')) saveModbusProfile();
    });
    graph.addEventListener('input', event => {
        if (event.target.matches('[data-key]')) saveModbusProfile();
    });
    runButton.addEventListener('click', () => {
        if (activeProtocol === 'modbus') runModbusFlow();
        else if (opcRunning) stopSubscription();
        else startSubscription();
    });
    $('#iw-tab-modbus').addEventListener('click', () => switchProtocol('modbus'));
    $('#iw-tab-opc').addEventListener('click', () => switchProtocol('opc'));
    $('#iw-zoom-out').addEventListener('click', () => setScale(scale - .1));
    $('#iw-zoom-in').addEventListener('click', () => setScale(scale + .1));
    $('#iw-fit').addEventListener('click', fitGraph);
    $('#iw-reset').addEventListener('click', resetLayout);
    $('#iw-self-check').addEventListener('click', () => runSelfCheck(true));
    runtimeMode.addEventListener('change', syncRuntimeMode);
    $('#iw-theme').addEventListener('click', () => {
        const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
        document.documentElement.dataset.theme = next;
        localStorage.setItem('industrialTheme', next);
        drawLinks();
    });
    $$('.iw-rail button').forEach(button => button.addEventListener('click', () => {
        const node = nodes[button.dataset.focus];
        $$('.iw-node').forEach(item => item.classList.remove('iw-selected'));
        node.classList.add('iw-selected');
        viewport.scrollTo({left: Math.max(0, node.offsetLeft * scale - 40), top: Math.max(0, node.offsetTop * scale - 40), behavior: 'smooth'});
    }));

    $('#opc-search').addEventListener('input', renderOpcBrowser);
    $('#opc-add-selected').addEventListener('click', () => {
        const source = isRealMode() ? opcBrowseItems : opcCatalog;
        addSources(source.filter(item => selectedCatalog.has(item.id) && (!item.nodeClass || item.nodeClass === 'Variable')));
        selectedCatalog = new Set(); updateSelectedCount(); renderOpcBrowser();
    });
    $('#opc-add-custom').addEventListener('click', () => {
        const name = $('#opc-custom-name').value.trim();
        const nodeId = $('#opc-custom-nodeid').value.trim();
        if (!nodeId) { showToast('请输入 NodeId'); return; }
        addSources([{name: name || nodeId, nodeId, dataType: 'Double', base: 0, critical: false}]);
        $('#opc-custom-name').value = ''; $('#opc-custom-nodeid').value = '';
    });
    $('#opc-load-critical').addEventListener('click', () => addSources(opcCatalog.filter(item => item.critical)));
    $('#opc-save-profile').addEventListener('click', saveOpcProfile);
    $('#opc-clear').addEventListener('click', () => {
        stopSubscription(false); monitoredItems = []; renderOpcItems(); logOpc('All MonitoredItems removed'); showToast('已清空测点');
    });
    $('#opc-connect').addEventListener('click', () => connectOpc());
    $('#opc-disconnect').addEventListener('click', disconnectOpc);
    $('#opc-browse').addEventListener('click', () => browseOpcNode($('#opc-browse-nodeid').value));
    $('#opc-start').addEventListener('click', startSubscription);
    $('#opc-stop').addEventListener('click', () => stopSubscription());
    $('#opc-security-mode').addEventListener('change', () => { syncOpcSecurity(); invalidateOpcConnection(); });
    $('#opc-security-policy').addEventListener('change', invalidateOpcConnection);
    $('#opc-authentication').addEventListener('change', () => { syncOpcSecurity(); invalidateOpcConnection(); });
    $('#opc-endpoint').addEventListener('input', invalidateOpcConnection);
    $('#opc-item-body').addEventListener('input', event => {
        const id = Number(event.target.dataset.itemId);
        const field = event.target.dataset.field;
        const item = monitoredItems.find(candidate => candidate.id === id);
        if (item && field) item[field] = event.target.value;
    });
    $('#opc-item-body').addEventListener('change', event => {
        const id = Number(event.target.dataset.itemId);
        const field = event.target.dataset.field;
        const item = monitoredItems.find(candidate => candidate.id === id);
        if (item && field) item[field] = event.target.value;
    });
    $('#opc-item-body').addEventListener('click', event => {
        const button = event.target.closest('button[data-action]');
        if (!button) return;
        const id = Number(button.dataset.itemId);
        const item = monitoredItems.find(candidate => candidate.id === id);
        if (button.dataset.action === 'critical' && item) item.critical = !item.critical;
        if (button.dataset.action === 'remove') monitoredItems = monitoredItems.filter(candidate => candidate.id !== id);
        renderOpcItems();
    });

    Object.values(nodes).forEach(bindDragging);
    document.documentElement.dataset.theme = localStorage.getItem('industrialTheme') || 'light';
    restoreLayout();
    syncConnection();
    syncModbus();
    restoreModbusProfile();
    syncOpcSecurity();
    if (!restoreOpcProfile()) renderOpcItems();
    else { syncOpcSecurity(); renderOpcItems(); }
    runSelfCheck(false);
    syncRuntimeMode();
    switchProtocol(localStorage.getItem('industrialActiveProtocol') === 'opc' ? 'opc' : 'modbus');
    requestAnimationFrame(() => { drawLinks(); fitGraph(); });
    window.addEventListener('resize', drawLinks);
})();
