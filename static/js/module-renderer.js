/**
 * ModuleRenderer — 模块渲染管理器
 *
 * 负责创建模块卡片、与后端 API 交互渲染内容、处理模块内的 data-action 交互。
 */
export class ModuleRenderer {
    /**
     * @param {HTMLElement} canvas - 画布 DOM 元素
     * @param {Grid} grid - Grid 实例
     * @param {DragManager} dragManager - DragManager 实例
     * @param {Function} showToast - 显示 Toast 通知的方法
     */
    constructor(canvas, grid, dragManager, showToast) {
        this.canvas = canvas;
        this.grid = grid;
        this.dragManager = dragManager;
        this.showToast = showToast || console.log;
        
        // 存储所有模块：moduleId -> { element, type, config, state, timer, meta }
        this.modules = new Map();
        
        // 可用模块列表的元数据缓存：type -> META
        this.availableModulesMeta = {};
    }

    // ============================================================
    //  API 交互
    // ============================================================

    /**
     * 获取所有可用的模块类型和元信息
     */
    async fetchAvailableModules() {
        try {
            const res = await fetch('/api/modules');
            const data = await res.json();
            if (data.status === 'success') {
                this.availableModulesMeta = data.modules;
                return this.availableModulesMeta;
            }
            throw new Error(data.error);
        } catch (err) {
            this.showToast(`获取模块列表失败: ${err.message}`, 'error');
            return {};
        }
    }

    // ============================================================
    //  模块生命周期管理
    // ============================================================

    /**
     * 添加并渲染一个新模块
     * @param {Object} moduleData - 配置中的模块数据
     */
    async addModule(moduleData) {
        const meta = this.availableModulesMeta[moduleData.type];
        if (!meta) {
            this.showToast(`未知模块类型: ${moduleData.type}`, 'error');
            return;
        }

        // 默认值处理
        const id = moduleData.id || `mod_${moduleData.type}_${Date.now()}_${Math.floor(Math.random()*1000)}`;
        const x = moduleData.grid_x ?? 0;
        const y = moduleData.grid_y ?? 0;
        const w = moduleData.grid_w ?? meta.default_size[0];
        const h = moduleData.grid_h ?? meta.default_size[1];
        
        // 填充默认 config
        let config = moduleData.config || {};
        if (meta.config_fields) {
            for (const field of meta.config_fields) {
                if (config[field.key] === undefined) {
                    config[field.key] = field.default;
                }
            }
        }
        
        const state = moduleData.state || {};

        // 1. 创建 DOM
        const element = this._createModuleElement(id, moduleData.type, meta, x, y, w, h);
        this.canvas.appendChild(element);

        // 2. 存储数据
        this.modules.set(id, {
            id: id,
            element,
            type: moduleData.type,
            config,
            state,
            meta,
            timer: null
        });

        // 3. 初始渲染内容
        await this._renderModuleContent(id);

        // 4. 设置自动刷新定时器
        if (meta.refresh_interval && meta.refresh_interval > 0) {
            const timer = setInterval(() => {
                this._renderModuleContent(id, true); // true = 自动静默刷新
            }, meta.refresh_interval * 1000);
            this.modules.get(id).timer = timer;
        }

        return id;
    }

    /**
     * 移除一个模块
     */
    removeModule(moduleId) {
        const mod = this.modules.get(moduleId);
        if (!mod) return;

        // 触发模块销毁钩子通知内部 JS 清理定时器/Canvas/ResizeObserver
        mod.element.dispatchEvent(new CustomEvent('module-destroy', { detail: { moduleId: mod.id } }));

        // 清除定时器
        if (mod.timer) clearInterval(mod.timer);
        
        // 移除 DOM（带动画）
        mod.element.style.animation = 'moduleRemove 200ms ease-in forwards';
        setTimeout(() => {
            if (mod.element.parentNode) {
                mod.element.parentNode.removeChild(mod.element);
            }
            this.modules.delete(moduleId);
        }, 200);
    }

    /**
     * 清空所有模块
     */
    clearAll() {
        for (const [id, mod] of this.modules.entries()) {
            if (mod.timer) clearInterval(mod.timer);
            if (mod.element.parentNode) mod.element.parentNode.removeChild(mod.element);
        }
        this.modules.clear();
    }

    // ============================================================
    //  属性更新
    // ============================================================

    updateModulePosition(moduleId, gridX, gridY) {
        const mod = this.modules.get(moduleId);
        if (!mod) return;
        mod.element.dataset.gridX = gridX;
        mod.element.dataset.gridY = gridY;
    }

    updateModuleSize(moduleId, gridW, gridH) {
        const mod = this.modules.get(moduleId);
        if (!mod) return;
        mod.element.dataset.gridW = gridW;
        mod.element.dataset.gridH = gridH;
    }

    updateModuleConfig(moduleId, newConfig) {
        const mod = this.modules.get(moduleId);
        if (!mod) return;
        mod.config = { ...mod.config, ...newConfig };
        this._renderModuleContent(moduleId);
    }

    /**
     * 序列化当前所有模块状态，用于保存
     */
    serializeAll() {
        const result = [];
        for (const [id, mod] of this.modules.entries()) {
            result.push({
                id,
                type: mod.type,
                grid_x: parseInt(mod.element.dataset.gridX),
                grid_y: parseInt(mod.element.dataset.gridY),
                grid_w: parseInt(mod.element.dataset.gridW),
                grid_h: parseInt(mod.element.dataset.gridH),
                config: mod.config,
                state: mod.state
            });
        }
        return result;
    }

    // ============================================================
    //  渲染逻辑与内部方法
    // ============================================================

    /**
     * 创建模块的 DOM 外壳
     */
    _createModuleElement(id, type, meta, x, y, w, h) {
        const el = document.createElement('div');
        el.className = 'module-card';
        el.id = `module-${id}`;
        el.dataset.moduleId = id;
        el.dataset.moduleType = type;
        el.dataset.gridX = x;
        el.dataset.gridY = y;
        el.dataset.gridW = w;
        el.dataset.gridH = h;
        
        // 初始位置和大小
        el.style.left = `${this.grid.gridUnitsToPx(x)}px`;
        el.style.top = `${this.grid.gridUnitsToPx(y)}px`;
        el.style.width = `${this.grid.gridUnitsToPx(w)}px`;
        el.style.height = `${this.grid.gridUnitsToPx(h)}px`;

        el.innerHTML = `
            <div class="module-header">
                <span class="module-icon">${meta.icon || '📦'}</span>
                <span class="module-title" title="${meta.name}">${meta.name}</span>
                <div class="module-actions">
                    <button class="btn-icon btn-mod-settings" title="设置">⚙️</button>
                    <button class="btn-icon btn-mod-close" title="关闭">✕</button>
                </div>
            </div>
            <div class="module-body module-scope-${id}">
                <!-- Content will be injected here -->
            </div>
            <div class="resize-handle"></div>
            <!-- Scoped CSS container -->
            <style id="style-${id}"></style>
        `;

        // 绑定拖拽事件
        const header = el.querySelector('.module-header');
        header.addEventListener('pointerdown', (e) => {
            // 设置按钮和关闭按钮不触发拖拽
            if (e.target.closest('button')) return;
            this.dragManager.startDrag(el, e);
        });

        const resizeHandle = el.querySelector('.resize-handle');
        resizeHandle.addEventListener('pointerdown', (e) => {
            this.dragManager.startResize(el, e, meta);
        });

        // 绑定卡片本身按钮事件
        el.querySelector('.btn-mod-close').addEventListener('click', () => {
            this.removeModule(id);
        });
        
        // 设置按钮的点击事件由 app.js 接管（因为弹窗在全局）
        // 这里提供一个自定义事件
        el.querySelector('.btn-mod-settings').addEventListener('click', () => {
            const event = new CustomEvent('open-module-settings', { detail: { moduleId: id } });
            document.dispatchEvent(event);
        });

        // 绑定焦点和键盘事件支持（比如给计算器提供键盘输入）
        el.tabIndex = -1; // 使元素可聚焦
        el.addEventListener('pointerdown', () => el.focus());
        el.addEventListener('keydown', (e) => {
            // 常用按键映射
            const keyMap = {
                'Enter': '=',
                'Escape': 'C',
                'Backspace': 'C',
                '*': '×',
                '/': '÷'
            };
            const key = keyMap[e.key] || e.key;
            
            // 查找带有 matching payload 的按钮并触发点击
            const buttons = el.querySelectorAll('[data-action="press"]');
            for (let btn of buttons) {
                let payloadStr = btn.dataset.payload;
                if (payloadStr) {
                    try {
                        // 有时候 JSON 里是实体编码的
                        payloadStr = payloadStr.replace(/&quot;/g, '"');
                        let payload = JSON.parse(payloadStr);
                        if (payload.key === key) {
                            btn.click();
                            e.preventDefault();
                            break;
                        }
                    } catch(err) {}
                }
            }
        });

        return el;
    }

    /**
     * 调用后端 render 接口更新模块内容
     */
    async _renderModuleContent(moduleId, silent = false) {
        const mod = this.modules.get(moduleId);
        if (!mod) return;

        const body = mod.element.querySelector('.module-body');
        if (!silent) body.classList.add('loading');

        try {
            const res = await fetch(`/api/modules/${mod.type}/render`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ config: mod.config, state: mod.state })
            });
            const data = await res.json();
            
            if (data.status === 'success') {
                this._applyRenderResult(mod, data);
            } else {
                body.innerHTML = `<div class="error-msg">渲染失败: ${data.error}</div>`;
            }
        } catch (err) {
            body.innerHTML = `<div class="error-msg">请求失败: ${err.message}</div>`;
        } finally {
            body.classList.remove('loading');
        }
    }

    /**
     * 处理交互 action
     */
    async _handleAction(moduleId, action, payload) {
        const mod = this.modules.get(moduleId);
        if (!mod) {
            this.showToast(`找不到模块实例 ${moduleId}`, 'error');
            return;
        }

        const body = mod.element.querySelector('.module-body');

        try {
            // 收集当前模块内的所有输入框的值，合并到 payload 中
            const inputs = {};
            mod.element.querySelectorAll('[data-input]').forEach(el => {
                inputs[el.dataset.input] = el.value;
            });
            const finalPayload = { ...payload, ...inputs };
            
            const res = await fetch(`/api/modules/${mod.type}/action`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    action,
                    payload: finalPayload,
                    config: mod.config,
                    state: mod.state
                })
            });
            
            const data = await res.json();
            
            if (data.status === 'success') {
                this._applyRenderResult(mod, data);
                // 触发自定义事件，供模块内部注入的复杂 JS 脚本监听
                const event = new CustomEvent('module-action-result', { 
                    detail: { action, payload: finalPayload, result: data } 
                });
                mod.element.dispatchEvent(event);
            } else {
                this.showToast(`操作失败: ${data.error}`, 'error');
            }
        } catch (err) {
            this.showToast(`请求失败: ${err.message}`, 'error');
        }
    }

    /**
     * 应用渲染结果（HTML、CSS、State 或 Data-Driven UI）
     */
    _applyRenderResult(mod, data) {
        // 更新状态
        if (data.state) mod.state = data.state;
        // 交互动作（例如切换 K 线周期）可以显式返回配置变更，确保保存工作台时不丢失。
        if (data.config) mod.config = { ...mod.config, ...data.config };
        
        const body = mod.element.querySelector('.module-body');

        // 如果后端返回了纯数据协议 (Data-Driven UI)
        if (data.ui) {
            body.innerHTML = '';
            body.appendChild(this._buildUIComponent(data.ui, mod.id));
            this._bindDynamicActions(mod.element, mod.id);
            return;
        }

        // 回退逻辑：传统 HTML 渲染
        if (data.html) {
            // 自动替换 {id} 占位符为实际的模块 ID，方便模块后端生成唯一 DOM ID
            const processedHtml = data.html.replace(/\{id\}/g, mod.id);
            
            // 性能优化：如果新 HTML 与当前 DOM 完全相同，跳过 DOM 重建与 script 重新解析
            if (body.innerHTML === processedHtml) {
                this._bindDynamicActions(mod.element, mod.id);
                return;
            }

            // 触发旧 DOM 销毁钩子，清理已挂载的图表/监听器
            mod.element.dispatchEvent(new CustomEvent('module-destroy', { detail: { moduleId: mod.id } }));
            body.innerHTML = processedHtml;
            
            // 浏览器 innerHTML 不会执行 script 标签，需要手动提取并重新插入
            const scripts = body.querySelectorAll('script');
            scripts.forEach(oldScript => {
                const newScript = document.createElement('script');
                Array.from(oldScript.attributes).forEach(attr => newScript.setAttribute(attr.name, attr.value));
                if (oldScript.src) {
                    newScript.src = oldScript.src;
                } else {
                    newScript.appendChild(document.createTextNode(oldScript.innerHTML));
                }
                oldScript.parentNode.replaceChild(newScript, oldScript);
            });
            
            this._bindDynamicActions(mod.element, mod.id);
        }
        
        // 更新 CSS，并且加上作用域限定
        if (data.css) {
            const styleTag = mod.element.querySelector(`#style-${mod.id}`);
            if (styleTag) {
                // 简单的作用域限制：在所有的选择器前面加上 .module-scope-{id}
                const scopedCSS = data.css.replace(/(^|})([^{]+){/g, (match, p1, p2) => {
                    if (p2.trim().startsWith('@')) return match;
                    const selectors = p2.split(',').map(s => `.module-scope-${mod.id} ${s.trim()}`).join(', ');
                    return `${p1}${selectors} {`;
                });
                styleTag.textContent = scopedCSS;
            }
        }
    }

    /**
     * 数据驱动渲染器工厂：将 JSON 转换为 DOM
     */
    _buildUIComponent(uiConfig, moduleId) {
        const container = document.createElement('div');
        container.style.width = '100%';
        container.style.height = '100%';
        container.style.display = 'flex';
        container.style.flexDirection = 'column';
        container.style.boxSizing = 'border-box';
        container.style.padding = '12px';
        container.style.overflow = 'auto';

        if (uiConfig.type === 'text') {
            const textEl = document.createElement('div');
            textEl.textContent = uiConfig.content || '';
            
            // 默认精美排版
            textEl.style.flex = '1';
            textEl.style.display = 'flex';
            textEl.style.alignItems = 'center';
            textEl.style.justifyContent = uiConfig.align || 'center';
            textEl.style.textAlign = uiConfig.align || 'center';
            textEl.style.color = uiConfig.color || 'var(--color-text)';
            textEl.style.fontFamily = uiConfig.fontFamily || '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
            
            // 尺寸预设
            if (uiConfig.size === 'small') textEl.style.fontSize = '1em';
            else if (uiConfig.size === 'large') textEl.style.fontSize = '3em';
            else if (uiConfig.size === 'xlarge') {
                textEl.style.fontSize = '4.5em';
                textEl.style.fontWeight = '300';
            }
            else textEl.style.fontSize = '2em'; // default
            
            if (uiConfig.weight) textEl.style.fontWeight = uiConfig.weight;

            container.appendChild(textEl);
        } else if (uiConfig.type === 'table') {
            const tableEl = document.createElement('table');
            tableEl.style.width = '100%';
            tableEl.style.borderCollapse = 'collapse';
            tableEl.style.fontSize = '0.9em';
            tableEl.style.fontFamily = uiConfig.fontFamily || '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
            tableEl.style.textAlign = 'left';

            // 表头
            if (uiConfig.columns && uiConfig.columns.length > 0) {
                const thead = document.createElement('thead');
                const tr = document.createElement('tr');
                uiConfig.columns.forEach(col => {
                    const th = document.createElement('th');
                    th.textContent = col;
                    th.style.padding = '8px 12px';
                    th.style.borderBottom = '1px solid var(--color-border)';
                    th.style.color = 'var(--color-text-muted)';
                    th.style.fontWeight = '600';
                    th.style.position = 'sticky';
                    th.style.top = '0';
                    th.style.backgroundColor = 'var(--color-bg)';
                    th.style.zIndex = '1';
                    tr.appendChild(th);
                });
                thead.appendChild(tr);
                tableEl.appendChild(thead);
            }

            // 数据
            const tbody = document.createElement('tbody');
            if (uiConfig.data && uiConfig.data.length > 0) {
                uiConfig.data.forEach((row, index) => {
                    const tr = document.createElement('tr');
                    // 斑马纹或鼠标悬停背景效果可以在 JS 里简单实现，或者靠 CSS。这里用简单的底边框。
                    tr.style.borderBottom = '1px solid var(--color-border)';
                    
                    row.forEach(cellText => {
                        const td = document.createElement('td');
                        td.textContent = cellText;
                        td.style.padding = '8px 12px';
                        td.style.color = 'var(--color-text)';
                        tr.appendChild(td);
                    });
                    
                    // hover 效果
                    tr.addEventListener('mouseenter', () => tr.style.backgroundColor = 'var(--color-hover)');
                    tr.addEventListener('mouseleave', () => tr.style.backgroundColor = 'transparent');
                    
                    tbody.appendChild(tr);
                });
            } else {
                const tr = document.createElement('tr');
                const td = document.createElement('td');
                td.textContent = '暂无数据';
                td.colSpan = uiConfig.columns ? uiConfig.columns.length : 1;
                td.style.padding = '20px';
                td.style.textAlign = 'center';
                td.style.color = 'var(--color-text-muted)';
                tr.appendChild(td);
                tbody.appendChild(tr);
            }
            
            tableEl.appendChild(tbody);
            container.appendChild(tableEl);
        } else {
            container.innerHTML = `<div style="color:red; text-align:center;">暂不支持的 UI 类型: ${uiConfig.type}</div>`;
        }

        return container;
    }

    /**
     * 绑定动态生成的 HTML 中的 data-action
     */
    _bindDynamicActions(container, moduleId) {
        // 解绑旧事件（由于我们是直接替换 innerHTML，旧 DOM 节点会被丢弃）
        const actionElements = container.querySelectorAll('.module-body [data-action]');
        
        actionElements.forEach(el => {
            el.addEventListener('click', (e) => {
                e.preventDefault();
                const action = el.dataset.action;
                let payload = {};
                if (el.dataset.payload) {
                    try { 
                        // 非常激进的转义处理，防止各种奇怪的 JSON 字符串情况
                        let payloadStr = el.dataset.payload
                            .replace(/&quot;/g, '"')
                            .replace(/&apos;/g, "'");
                        payload = JSON.parse(payloadStr); 
                    } catch(err) { 
                        console.error("Invalid payload JSON:", el.dataset.payload); 
                    }
                }
                
                this._handleAction(moduleId, action, payload);
            });
        });
    }
}
