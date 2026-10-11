import { Grid } from './grid.js';
import { DragManager } from './drag-manager.js';
import { ModuleRenderer } from './module-renderer.js?v=2';
import { ConfigManager } from './config-manager.js';

class App {
    constructor() {
        // DOM 元素缓存
        this.dom = {
            viewport: document.getElementById('viewport'),
            canvas: document.getElementById('canvas'),
            
            // 工具栏
            configSelect: document.getElementById('config-select'),
            btnSaveConfig: document.getElementById('btn-save-config'),
            btnNewConfig: document.getElementById('btn-new-config'),
            btnDeleteConfig: document.getElementById('btn-delete-config'),
            btnAddModule: document.getElementById('btn-add-module'),
            btnZoomIn: document.getElementById('btn-zoom-in'),
            btnZoomOut: document.getElementById('btn-zoom-out'),
            btnZoomReset: document.getElementById('btn-zoom-reset'),
            btnThemeToggle: document.getElementById('btn-theme-toggle'),
            zoomLevel: document.getElementById('zoom-level'),
            
            // 面板 & 弹窗
            modulePalette: document.getElementById('module-palette'),
            paletteList: document.getElementById('palette-list'),
            btnClosePalette: document.getElementById('btn-close-palette'),
            
            settingsModal: document.getElementById('module-settings-modal'),
            settingsBody: document.getElementById('module-settings-body'),
            btnSettingsSave: document.getElementById('btn-settings-save'),
            btnSettingsCancel: document.getElementById('btn-settings-cancel'),
            modalCloseBtns: document.querySelectorAll('.modal-close'),
            
            // Toast
            toastContainer: document.getElementById('toast-container')
        };

        // 系统实例
        this.grid = null;
        this.dragManager = null;
        this.moduleRenderer = null;
        this.configManager = null;
        
        this._settingsCurrentModuleId = null;
    }

    async init() {
        // 1. 初始化核心系统
        this.grid = new Grid(this.dom.viewport, this.dom.canvas);
        this.dragManager = new DragManager(this.grid);
        this.moduleRenderer = new ModuleRenderer(this.dom.canvas, this.grid, this.dragManager, this.showToast.bind(this));
        this.configManager = new ConfigManager(this.grid, this.moduleRenderer, this.showToast.bind(this));

        // 2. 绑定 DragManager 的回调到 Renderer
        this.dragManager.onModuleMoved = (id, gx, gy) => {
            this.moduleRenderer.updateModulePosition(id, gx, gy);
            // 这里可以触发一次自动保存
        };
        this.dragManager.onModuleResized = (id, gw, gh) => {
            this.moduleRenderer.updateModuleSize(id, gw, gh);
        };

        // 3. 监听 Grid 缩放变化以更新 UI
        this.grid.onScaleChange = (scale) => {
            this.dom.zoomLevel.textContent = `${Math.round(scale * 100)}%`;
        };

        // 4. 设置事件监听
        this._setupEvents();

        // 5. 初始化数据：获取可用模块和配置列表
        await this.moduleRenderer.fetchAvailableModules();
        await this._refreshConfigList();

        // 6. 加载初始界面
        if (this.dom.configSelect.options.length > 0) {
            // 如果有 default 配置，优先加载它
            const hasDefault = Array.from(this.dom.configSelect.options).some(opt => opt.value === 'default');
            const toLoad = hasDefault ? 'default' : this.dom.configSelect.options[0].value;
            this.dom.configSelect.value = toLoad;
            await this.configManager.loadConfig(toLoad);
        } else {
            // 没有配置，创建一个默认的
            this.showToast('欢迎来到 ModuBoard！请点击上方 "+添加模块" 开始', 'info');
            this.configManager.currentConfigName = '未命名配置';
        }

        // 7. 开启自动保存（每 30 秒）
        this.configManager.startAutoSave(30000);
    }

    // ============================================================
    //  事件绑定
    // ============================================================

    _setupEvents() {
        // —— 工具栏：缩放 ——
        this.dom.btnZoomIn.addEventListener('click', () => this.grid.zoomIn());
        this.dom.btnZoomOut.addEventListener('click', () => this.grid.zoomOut());
        this.dom.btnZoomReset.addEventListener('click', () => this.grid.resetView());

        // —— 工具栏：主题切换 ——
        this.dom.btnThemeToggle.addEventListener('click', () => {
            const html = document.documentElement;
            const current = html.dataset.theme;
            html.dataset.theme = current === 'dark' ? 'light' : 'dark';
        });

        // —— 工具栏：配置管理 ——
        this.dom.configSelect.addEventListener('change', async (e) => {
            if (e.target.value) {
                await this.configManager.loadConfig(e.target.value);
            }
        });

        this.dom.btnSaveConfig.addEventListener('click', () => {
            if (this.configManager.currentConfigName) {
                this.configManager.saveConfig(this.configManager.currentConfigName, false);
            } else {
                this.dom.btnNewConfig.click();
            }
        });

        this.dom.btnNewConfig.addEventListener('click', async () => {
            const name = prompt('请输入新工作界面名称:');
            if (name && name.trim()) {
                await this.configManager.saveConfig(name.trim(), false);
                await this._refreshConfigList();
                this.dom.configSelect.value = name.trim();
            }
        });

        this.dom.btnDeleteConfig.addEventListener('click', async () => {
            const name = this.configManager.currentConfigName;
            if (name && confirm(`确定要删除界面 "${name}" 吗？`)) {
                if (await this.configManager.deleteConfig(name)) {
                    await this._refreshConfigList();
                    if (this.dom.configSelect.options.length > 0) {
                        this.dom.configSelect.value = this.dom.configSelect.options[0].value;
                        this.configManager.loadConfig(this.dom.configSelect.value);
                    } else {
                        this.moduleRenderer.clearAll();
                        this.configManager.currentConfigName = null;
                    }
                }
            }
        });

        // —— 模块面板 ——
        this.dom.btnAddModule.addEventListener('click', () => this._togglePalette());
        this.dom.btnClosePalette.addEventListener('click', () => this._togglePalette(false));

        // —— 模块设置弹窗 ——
        document.addEventListener('open-module-settings', (e) => this._openSettingsModal(e.detail.moduleId));
        
        this.dom.modalCloseBtns.forEach(btn => btn.addEventListener('click', () => this._closeSettingsModal()));
        this.dom.btnSettingsCancel.addEventListener('click', () => this._closeSettingsModal());
        
        this.dom.btnSettingsSave.addEventListener('click', () => this._saveModuleSettings());
        
        // 点击遮罩关闭弹窗
        this.dom.settingsModal.querySelector('.modal-overlay').addEventListener('click', () => this._closeSettingsModal());
        
        // —— 全局快捷键 ——
        this._setupKeyboardShortcuts();
    }

    _setupKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // 排除输入框、下拉框等
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') {
                return;
            }

            const isCtrl = e.ctrlKey || e.metaKey;
            
            // Ctrl + C 复制
            if (isCtrl && e.key.toLowerCase() === 'c') {
                const activeEl = document.activeElement;
                const moduleCard = activeEl ? activeEl.closest('.module-card') : null;
                if (moduleCard) {
                    const moduleId = moduleCard.dataset.moduleId;
                    const mod = this.moduleRenderer.modules.get(moduleId);
                    if (mod) {
                        this._copiedModule = {
                            type: mod.type,
                            config: JSON.parse(JSON.stringify(mod.config)),
                            state: JSON.parse(JSON.stringify(mod.state || {}))
                        };
                        this.showToast(`已复制模块：${mod.meta.name}`, 'success');
                    }
                }
            }
            
            // Ctrl + V 粘贴
            if (isCtrl && e.key.toLowerCase() === 'v') {
                if (this._copiedModule) {
                    const type = this._copiedModule.type;
                    const meta = this.moduleRenderer.availableModulesMeta[type];
                    if (!meta) return;

                    // 计算视口中心对应的网格坐标
                    const centerPxX = this.dom.viewport.clientWidth / 2 - this.grid.offsetX;
                    const centerPxY = this.dom.viewport.clientHeight / 2 - this.grid.offsetY;
                    const gx = Math.floor(centerPxX / this.grid.scale / this.grid.gridSize);
                    const gy = Math.floor(centerPxY / this.grid.scale / this.grid.gridSize);
                    
                    const w = meta.default_size ? meta.default_size[0] : 4;
                    const h = meta.default_size ? meta.default_size[1] : 3;
                    
                    const newConfig = JSON.parse(JSON.stringify(this._copiedModule.config));
                    const newState = JSON.parse(JSON.stringify(this._copiedModule.state));
                    
                    const moduleData = {
                        type: type,
                        grid_x: gx,
                        grid_y: gy,
                        grid_w: w,
                        grid_h: h,
                        config: newConfig,
                        state: newState
                    };
                    
                    this.moduleRenderer.addModule(moduleData);
                    this.showToast(`已粘贴模块：${meta.name}`, 'success');
                }
            }
        });
    }

    // ============================================================
    //  UI 逻辑
    // ============================================================

    async _refreshConfigList() {
        const configs = await this.configManager.fetchConfigList();
        this.dom.configSelect.innerHTML = '';
        configs.forEach(name => {
            const opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name;
            this.dom.configSelect.appendChild(opt);
        });
    }

    _togglePalette(forceShow = null) {
        const isHidden = this.dom.modulePalette.classList.contains('hidden');
        const show = forceShow !== null ? forceShow : isHidden;
        
        if (show) {
            this._renderPaletteList();
            this.dom.modulePalette.classList.remove('hidden');
            // 清空搜索框并聚焦
            const searchInput = document.getElementById('palette-search-input');
            if (searchInput) {
                searchInput.value = '';
                // 绑定搜索事件（只绑一次）
                if (!searchInput._bound) {
                    searchInput.addEventListener('input', () => this._filterPaletteList(searchInput.value));
                    searchInput._bound = true;
                }
                setTimeout(() => searchInput.focus(), 100);
            }
        } else {
            this.dom.modulePalette.classList.add('hidden');
        }
    }

    /**
     * 定义标签排序顺序和图标
     */
    _getTagOrder() {
        return {
            '行情交易': { order: 0, icon: '📊' },
            '实用工具': { order: 1, icon: '🛠️' },
            '通讯工具': { order: 2, icon: '💬' },
            '系统':     { order: 3, icon: '⚙️' },
        };
    }

    _renderPaletteList() {
        this.dom.paletteList.innerHTML = '';
        const metaDict = this.moduleRenderer.availableModulesMeta;
        
        if (Object.keys(metaDict).length === 0) {
            this.dom.paletteList.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-text">未发现可用模块。<br>请在 modules/ 目录下添加 Python 脚本。</div>
                </div>`;
            return;
        }

        // 按 tag 分组
        const groups = {};
        for (const [type, meta] of Object.entries(metaDict)) {
            const tag = (meta.tags && meta.tags[0]) || '未分类';
            if (!groups[tag]) groups[tag] = [];
            groups[tag].push({ type, meta });
        }

        // 按预定义顺序排序
        const tagOrder = this._getTagOrder();
        const sortedTags = Object.keys(groups).sort((a, b) => {
            const oa = tagOrder[a] ? tagOrder[a].order : 999;
            const ob = tagOrder[b] ? tagOrder[b].order : 999;
            return oa - ob;
        });

        // 渲染每个分组
        for (const tag of sortedTags) {
            const items = groups[tag];
            const tagInfo = tagOrder[tag] || { icon: '📁' };
            
            const groupEl = document.createElement('div');
            groupEl.className = 'palette-group';
            groupEl.dataset.tag = tag;

            // 分组标题
            const header = document.createElement('div');
            header.className = 'palette-group-header';
            header.innerHTML = `
                <span class="palette-group-arrow">▼</span>
                <span class="palette-group-label">${tagInfo.icon || ''} ${tag}</span>
                <span class="palette-group-count">${items.length}</span>
            `;
            header.addEventListener('click', () => {
                groupEl.classList.toggle('collapsed');
            });

            // 分组内容
            const body = document.createElement('div');
            body.className = 'palette-group-body';

            for (const { type, meta } of items) {
                const item = document.createElement('div');
                item.className = 'palette-item';
                item.dataset.type = type;
                item.dataset.name = (meta.name || '').toLowerCase();
                item.dataset.tags = (meta.tags || []).join(',').toLowerCase();

                // 标签 badges
                const tagsHtml = (meta.tags || []).map(t =>
                    `<span class="palette-tag">${t}</span>`
                ).join('');

                item.innerHTML = `
                    <div class="palette-item-icon">${meta.icon || '📦'}</div>
                    <div class="palette-item-info">
                        <div class="palette-item-name">${meta.name}</div>
                        <div class="palette-item-desc">${meta.description || ''}</div>
                        <div class="palette-item-tags">${tagsHtml}</div>
                        <div class="palette-item-size">默认大小: ${meta.default_size.join(' × ')}</div>
                    </div>
                `;
                
                // 点击添加
                item.addEventListener('click', () => {
                    const centerCanvas = this.grid.getViewportCenter();
                    const gridX = Math.max(0, this.grid.pxToGridUnits(centerCanvas.x) - Math.floor(meta.default_size[0]/2));
                    const gridY = Math.max(0, this.grid.pxToGridUnits(centerCanvas.y) - Math.floor(meta.default_size[1]/2));
                    
                    this.moduleRenderer.addModule({
                        type: type,
                        grid_x: gridX,
                        grid_y: gridY
                    });
                    this._togglePalette(false);
                });
                
                body.appendChild(item);
            }

            groupEl.appendChild(header);
            groupEl.appendChild(body);
            this.dom.paletteList.appendChild(groupEl);
        }
    }

    /**
     * 搜索过滤面板模块列表
     */
    _filterPaletteList(query) {
        const q = query.trim().toLowerCase();
        const groups = this.dom.paletteList.querySelectorAll('.palette-group');

        for (const group of groups) {
            const items = group.querySelectorAll('.palette-item');
            const groupTag = (group.dataset.tag || '').toLowerCase();
            let visibleCount = 0;

            for (const item of items) {
                const name = item.dataset.name || '';
                const tags = item.dataset.tags || '';
                const desc = (item.querySelector('.palette-item-desc')?.textContent || '').toLowerCase();
                const match = !q || name.includes(q) || tags.includes(q) || desc.includes(q) || groupTag.includes(q);
                item.style.display = match ? '' : 'none';
                if (match) visibleCount++;
            }

            // 整个组没有匹配项则隐藏
            group.style.display = visibleCount > 0 ? '' : 'none';

            // 搜索时展开有匹配的组
            if (q && visibleCount > 0) {
                group.classList.remove('collapsed');
            }

            // 更新计数
            const countEl = group.querySelector('.palette-group-count');
            if (countEl) {
                countEl.textContent = q ? `${visibleCount}/${items.length}` : `${items.length}`;
            }
        }
    }

    // ============================================================
    //  模块设置弹窗
    // ============================================================

    _openSettingsModal(moduleId) {
        const mod = this.moduleRenderer.modules.get(moduleId);
        if (!mod || !mod.meta.config_fields || mod.meta.config_fields.length === 0) {
            this.showToast('该模块没有可配置项', 'info');
            return;
        }

        this._settingsCurrentModuleId = moduleId;
        document.getElementById('settings-modal-title').textContent = `${mod.meta.name} 设置`;
        const escapeHtml = (value) => String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
        
        // 生成表单
        let formHtml = '';
        let zIndex = 1000;
        for (const field of mod.meta.config_fields) {
            const currentVal = mod.config[field.key] !== undefined ? mod.config[field.key] : field.default;
            const safeCurrentVal = escapeHtml(currentVal);
            
            formHtml += `<div class="form-group" style="position: relative; z-index: ${zIndex--};">`;
            formHtml += `<label class="form-label">${field.label}</label>`;
            
            if (field.type === 'select' && field.options) {
                formHtml += `<select class="form-select" data-key="${field.key}">`;
                for (const opt of field.options) {
                    const selected = currentVal === opt ? 'selected' : '';
                    formHtml += `<option value="${opt}" ${selected}>${opt}</option>`;
                }
                formHtml += `</select>`;
            } else if (field.type === 'number') {
                formHtml += `<input type="number" class="form-input" data-key="${field.key}" value="${safeCurrentVal}">`;
            } else if (field.type === 'color-palette') {
                const presets = ['#c8d6e5', '#ff4d4f', '#52c41a', '#1890ff', '#faad14', '#722ed1', '#ffffff', '#000000'];
                formHtml += `<div class="color-palette-container" style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">`;
                formHtml += `<input type="color" class="form-input-color" data-key="${field.key}" value="${safeCurrentVal}" style="width:36px;height:36px;padding:0;border:none;cursor:pointer;">`;
                formHtml += `<div style="display:flex; gap:4px; flex-wrap:wrap;">`;
                presets.forEach(color => {
                    formHtml += `<div class="color-preset-dot" style="width:24px;height:24px;border-radius:50%;background:${color};border:1px solid #546e7a;cursor:pointer;" onclick="this.parentElement.previousElementSibling.value='${color}'"></div>`;
                });
                formHtml += `</div></div>`;
            } else if (field.type === 'searchable-text') {
                formHtml += `<div class="searchable-container" style="position:relative; z-index:999;">`;
                formHtml += `<input type="text" class="form-input searchable-input" data-key="${field.key}" value="${safeCurrentVal}" placeholder="输入拼音/名称搜索..." autocomplete="off">`;
                formHtml += `<ul class="searchable-dropdown" style="display:none; position:absolute; top:100%; left:0; width:100%; max-height:400px; overflow-y:auto; background:var(--color-surface-elevated); border:1px solid var(--color-border); z-index:9999; list-style:none; padding:0; margin:4px 0 0 0; box-shadow:var(--shadow-lg); border-radius:4px;"></ul>`;
                formHtml += `</div>`;
            } else if (field.type === 'searchable-tags') {
                formHtml += `<div class="searchable-tags-wrapper" style="display:flex; flex-direction:column; gap:8px;">`;
                formHtml += `<input type="hidden" class="tag-hidden-val" data-key="${field.key}" value="${safeCurrentVal}">`;
                formHtml += `<div class="tags-render-area" style="display:flex; flex-wrap:wrap; gap:6px;"></div>`;
                formHtml += `<div class="searchable-container" style="position:relative; z-index:999;">`;
                formHtml += `<input type="text" class="form-input tag-search-input" placeholder="搜索并添加..." autocomplete="off">`;
                formHtml += `<ul class="searchable-dropdown tag-search-dropdown" style="display:none; position:absolute; top:100%; left:0; width:100%; max-height:400px; overflow-y:auto; background:var(--color-surface-elevated); border:1px solid var(--color-border); z-index:9999; list-style:none; padding:0; margin:4px 0 0 0; box-shadow:var(--shadow-lg); border-radius:4px;"></ul>`;
                formHtml += `</div></div>`;
            } else if (field.type === 'dynamic-select') {
                formHtml += `<select class="form-select dynamic-select" data-key="${field.key}" data-depends="${field.depends_on}" data-endpoint="${field.endpoint}" data-current="${safeCurrentVal}">`;
                formHtml += `<option value="${safeCurrentVal}">${safeCurrentVal}</option>`;
                formHtml += `</select>`;
            } else if (field.type === 'symbol-cascading-select') {
                formHtml += `<div class="cascading-container" style="display:flex; flex-direction:column; gap:8px;">
                    <div class="cascading-loading" style="font-size:12px;color:var(--color-text-muted);">正在加载可用品种...</div>
                    <input type="hidden" class="form-input cascading-hidden" data-key="${field.key}" value="${safeCurrentVal}">
                </div>`;
            } else if (field.type === 'online-symbol-cascading-select') {
                formHtml += `<div class="online-cascading-container">
                    <div class="online-cascading-loading" role="status">正在加载在线品种目录...</div>
                    <input type="hidden" class="online-cascading-hidden" data-key="${field.key}" data-required="true" value="${safeCurrentVal}">
                </div>`;
            } else {
                formHtml += `<input type="text" class="form-input" data-key="${field.key}" value="${safeCurrentVal}">`;
            }
            
            formHtml += `</div>`;
        }
        
        this.dom.settingsBody.innerHTML = formHtml;
        this.dom.settingsModal.querySelector('.modal-content')?.classList.toggle(
            'modal-content-wide',
            mod.meta.config_fields.some(field => field.type === 'online-symbol-cascading-select')
        );
        
        // 绑定 search autocomplete 逻辑
        const searchableInputs = this.dom.settingsBody.querySelectorAll('.searchable-input');
        searchableInputs.forEach(input => {
            const dropdown = input.nextElementSibling;
            let timeout = null;
            
            input.addEventListener('input', (e) => {
                const q = e.target.value.trim();
                clearTimeout(timeout);
                if (!q) {
                    dropdown.style.display = 'none';
                    return;
                }
                timeout = setTimeout(async () => {
                    try {
                        const res = await fetch(`/api/search_symbol?q=${encodeURIComponent(q)}`);
                        const data = await res.json();
                        if (data.status === 'success' && data.results.length > 0) {
                            dropdown.innerHTML = data.results.map(item => 
                                `<li class="searchable-item" data-val="${item.value}" style="padding:10px 14px; cursor:pointer; font-size:14px; border-bottom:1px solid var(--color-border); transition:background 0.1s;">${item.label}</li>`
                            ).join('');
                            dropdown.style.display = 'block';
                            
                            // 绑定点击补全
                            dropdown.querySelectorAll('.searchable-item').forEach(li => {
                                li.addEventListener('mouseover', () => li.style.background = 'var(--bg-hover)');
                                li.addEventListener('mouseout', () => li.style.background = 'transparent');
                                li.addEventListener('click', () => {
                                    input.value = li.dataset.val;
                                    dropdown.style.display = 'none';
                                });
                            });
                        } else {
                            dropdown.style.display = 'none';
                        }
                    } catch (err) {
                        console.error('Search error:', err);
                    }
                }, 300); // 300ms 防抖
            });
            
            // 点击外部关闭下拉框
            document.addEventListener('click', (e) => {
                if (e.target !== input && e.target !== dropdown && !dropdown.contains(e.target)) {
                    dropdown.style.display = 'none';
                }
            });
        });
        
        // 绑定 searchable-tags 逻辑
        const searchableTagsWrappers = this.dom.settingsBody.querySelectorAll('.searchable-tags-wrapper');
        searchableTagsWrappers.forEach(wrapper => {
            const hiddenInput = wrapper.querySelector('.tag-hidden-val');
            const renderArea = wrapper.querySelector('.tags-render-area');
            const searchInput = wrapper.querySelector('.tag-search-input');
            const dropdown = wrapper.querySelector('.tag-search-dropdown');
            let timeout = null;
            
            const renderTags = () => {
                const valStr = hiddenInput.value.trim();
                const tags = valStr ? valStr.split(',').map(s => s.trim()).filter(s => s) : [];
                renderArea.innerHTML = tags.map((t, idx) => `
                    <div style="background:var(--color-primary-light); color:var(--color-primary); padding:4px 8px; border-radius:12px; font-size:12px; display:flex; align-items:center; gap:4px;">
                        <span>${t}</span>
                        <span class="tag-remove-btn" data-idx="${idx}" style="cursor:pointer; font-weight:bold; font-size:14px; line-height:1;">×</span>
                    </div>
                `).join('');
                
                renderArea.querySelectorAll('.tag-remove-btn').forEach(btn => {
                    btn.addEventListener('click', () => {
                        const i = parseInt(btn.dataset.idx);
                        tags.splice(i, 1);
                        hiddenInput.value = tags.join(', ');
                        renderTags();
                    });
                });
            };
            
            renderTags(); // 初始渲染
            
            searchInput.addEventListener('input', (e) => {
                const q = e.target.value.trim();
                clearTimeout(timeout);
                if (!q) {
                    dropdown.style.display = 'none';
                    return;
                }
                timeout = setTimeout(async () => {
                    try {
                        const res = await fetch(`/api/search_symbol?q=${encodeURIComponent(q)}`);
                        const data = await res.json();
                        if (data.status === 'success' && data.results.length > 0) {
                            dropdown.innerHTML = data.results.map(item => 
                                `<li class="searchable-item" data-val="${item.value}" style="padding:10px 14px; cursor:pointer; font-size:14px; border-bottom:1px solid var(--color-border); transition:background 0.1s;">${item.label}</li>`
                            ).join('');
                            dropdown.style.display = 'block';
                            
                            dropdown.querySelectorAll('.searchable-item').forEach(li => {
                                li.addEventListener('mouseover', () => li.style.background = 'var(--color-surface-hover)');
                                li.addEventListener('mouseout', () => li.style.background = 'transparent');
                                li.addEventListener('click', () => {
                                    const newVal = li.dataset.val;
                                    const currentTags = hiddenInput.value ? hiddenInput.value.split(',').map(s=>s.trim()).filter(s=>s) : [];
                                    if (!currentTags.includes(newVal)) {
                                        currentTags.push(newVal);
                                        hiddenInput.value = currentTags.join(', ');
                                        renderTags();
                                    }
                                    searchInput.value = '';
                                    dropdown.style.display = 'none';
                                });
                            });
                        } else {
                            dropdown.style.display = 'none';
                        }
                    } catch (err) {
                        console.error('Search error:', err);
                    }
                }, 300);
            });
            
            document.addEventListener('click', (e) => {
                if (e.target !== searchInput && e.target !== dropdown && !dropdown.contains(e.target)) {
                    dropdown.style.display = 'none';
                }
            });
        });

        const cascadingContainers = this.dom.settingsBody.querySelectorAll('.cascading-container');
        if (cascadingContainers.length > 0) {
            fetch('/api/symbol_tree').then(async response => {
                const data = await response.json();
                if (!response.ok || data.status !== 'success') {
                    throw new Error(data.error || `HTTP ${response.status}`);
                }
                return data;
            }).then(data => {
                const TREE = data.tree;
                const assetKeys = Object.keys(TREE).filter(ak => Object.keys(TREE[ak]?.exchanges || {}).length > 0);
                if (assetKeys.length === 0) throw new Error('本地品种库为空，请先更新数据中心');

                const normalizeCode = value => String(value || '')
                    .trim()
                    .replace(/^【[^】]*】/, '')
                    .trim()
                    .split(/\s+/)[0]
                    .toUpperCase();
                const exchangeOrder = ['SHFE', 'INE', 'DCE', 'CZCE', 'GFEX', 'CFFEX', 'SSE', 'SZSE', 'BSE'];
                const sortExchangeKeys = keys => [...keys].sort((a, b) => {
                    const ai = exchangeOrder.indexOf(a);
                    const bi = exchangeOrder.indexOf(b);
                    return (ai < 0 ? 999 : ai) - (bi < 0 ? 999 : bi) || a.localeCompare(b);
                });

                cascadingContainers.forEach(container => {
                    const hidden = container.querySelector('.cascading-hidden');
                    const currentVal = hidden.value;
                    const currentCode = normalizeCode(currentVal);

                    let matchedPath = null;
                    for (const ak of assetKeys) {
                        const exchanges = TREE[ak].exchanges || {};
                        for (const ek of Object.keys(exchanges)) {
                            const products = exchanges[ek].products || {};
                            for (const pk of Object.keys(products)) {
                                const contract = (products[pk].contracts || [])
                                    .find(c => normalizeCode(c.val) === currentCode);
                                if (contract) {
                                    matchedPath = { asset: ak, exchange: ek, product: pk, contract: contract.val };
                                    break;
                                }
                            }
                            if (matchedPath) break;
                        }
                        if (matchedPath) break;
                    }
                    
                    container.innerHTML = `
                        <div class="cascading-grid" style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;">
                            <label style="min-width:0;font-size:11px;color:var(--color-text-muted);">1. 资产类别
                                <select class="form-select cascading-a" aria-label="资产类别" style="margin-top:4px;"></select>
                            </label>
                            <label style="min-width:0;font-size:11px;color:var(--color-text-muted);">2. 交易所
                                <select class="form-select cascading-e" aria-label="交易所" style="margin-top:4px;"></select>
                            </label>
                            <label style="min-width:0;font-size:11px;color:var(--color-text-muted);">3. 品种
                                <select class="form-select cascading-p" aria-label="品种" style="margin-top:4px;"></select>
                            </label>
                            <label style="min-width:0;font-size:11px;color:var(--color-text-muted);">4. 合约
                                <select class="form-select cascading-c" aria-label="合约" style="margin-top:4px;"></select>
                            </label>
                        </div>
                        <div class="cascading-summary" role="status" style="padding:7px 9px;border-radius:4px;background:var(--color-primary-light);color:var(--color-text-secondary);font-size:12px;word-break:break-all;"></div>
                    `;
                    container.appendChild(hidden);
                    const selA = container.querySelector('.cascading-a');
                    const selE = container.querySelector('.cascading-e');
                    const selP = container.querySelector('.cascading-p');
                    const selC = container.querySelector('.cascading-c');
                    const summary = container.querySelector('.cascading-summary');

                    function setEmpty(select, text) {
                      select.innerHTML = '';
                      const option = new Option(text, '');
                      option.disabled = true;
                      option.selected = true;
                      select.appendChild(option);
                      select.disabled = true;
                    }

                    function updateSummary() {
                      if (!selC.value) {
                        hidden.value = currentVal;
                        summary.textContent = '当前层级暂无可用合约，保存时将保留原值。';
                        return;
                      }
                      hidden.value = selC.value;
                      const contractLabel = selC.options[selC.selectedIndex]?.text || selC.value;
                      summary.textContent = matchedPath
                        ? `当前：${contractLabel} · ${normalizeCode(selC.value)}`
                        : `原配置 ${currentCode || '（空）'} 不在品种库中；保存后将使用：${contractLabel} · ${normalizeCode(selC.value)}`;
                    }
                    
                    function renderA(preferred) {
                      selA.innerHTML = '';
                      assetKeys.forEach(ak => selA.appendChild(new Option(TREE[ak].label, ak)));
                      selA.disabled = assetKeys.length === 0;
                      if (preferred && assetKeys.includes(preferred)) selA.value = preferred;
                    }
                    function renderE(ak, preferred) {
                      selE.innerHTML = '';
                      const exObj = (TREE[ak] && TREE[ak].exchanges) || {};
                      const keys = sortExchangeKeys(Object.keys(exObj));
                      if (keys.length === 0) return setEmpty(selE, '暂无交易所');
                      keys.forEach(ek => selE.appendChild(new Option(exObj[ek].label, ek)));
                      selE.disabled = false;
                      if (preferred && keys.includes(preferred)) selE.value = preferred;
                    }
                    function renderP(ak, ek, preferred) {
                      selP.innerHTML = '';
                      const pObj = (TREE[ak] && TREE[ak].exchanges[ek] && TREE[ak].exchanges[ek].products) || {};
                      const keys = Object.keys(pObj).sort((a, b) => pObj[a].label.localeCompare(pObj[b].label, 'zh-CN', { numeric: true }));
                      if (keys.length === 0) return setEmpty(selP, '暂无品种');
                      keys.forEach(pk => selP.appendChild(new Option(pObj[pk].label, pk)));
                      selP.disabled = false;
                      if (preferred && keys.includes(preferred)) selP.value = preferred;
                    }
                    function renderC(ak, ek, pk, preferred) {
                      selC.innerHTML = '';
                      const contracts = [...((TREE[ak] && TREE[ak].exchanges[ek] && TREE[ak].exchanges[ek].products[pk] && TREE[ak].exchanges[ek].products[pk].contracts) || [])]
                        .sort((a, b) => Number(Boolean(b.active)) - Number(Boolean(a.active)) || a.sym.localeCompare(b.sym, undefined, { numeric: true }));
                      if (contracts.length === 0) {
                        setEmpty(selC, '暂无合约');
                        updateSummary();
                        return;
                      }
                      contracts.forEach(c => {
                        const expiredLabel = String(c.label).includes('已到期') ? c.label : `${c.label}（已到期）`;
                        const opt = new Option(c.active ? c.label : expiredLabel, c.val);
                        selC.appendChild(opt);
                      });
                      selC.disabled = false;
                      const exact = contracts.find(c => normalizeCode(c.val) === normalizeCode(preferred));
                      if (exact) selC.value = exact.val;
                      updateSummary();
                    }
                    
                    renderA(matchedPath?.asset);
                    renderE(selA.value, matchedPath?.exchange);
                    renderP(selA.value, selE.value, matchedPath?.product);
                    renderC(selA.value, selE.value, selP.value, matchedPath?.contract);
                    
                    selA.addEventListener('change', () => { renderE(selA.value); renderP(selA.value, selE.value); renderC(selA.value, selE.value, selP.value); });
                    selE.addEventListener('change', () => { renderP(selA.value, selE.value); renderC(selA.value, selE.value, selP.value); });
                    selP.addEventListener('change', () => { renderC(selA.value, selE.value, selP.value); });
                    selC.addEventListener('change', updateSummary);
                });
            }).catch(err => {
                console.error('Symbol tree load error:', err);
                cascadingContainers.forEach(container => {
                    const hidden = container.querySelector('.cascading-hidden');
                    container.innerHTML = `<div role="alert" style="padding:9px;border:1px solid #f59e0b;border-radius:4px;color:#f59e0b;font-size:12px;">品种列表加载失败：${escapeHtml(err.message)}。当前配置将保持不变。</div>`;
                    if (hidden) container.appendChild(hidden);
                });
            });
        }

        // V1 在线行情专用级联选择器：目录和合约均来自在线接口，不读取 V2 本地数据库。
        const onlineContainers = this.dom.settingsBody.querySelectorAll('.online-cascading-container');
        onlineContainers.forEach(async container => {
            const hidden = container.querySelector('.online-cascading-hidden');
            const originalValue = hidden.value;
            const normalizeCode = value => String(value || '')
                .trim()
                .replace(/^【[^】]*】/, '')
                .trim()
                .split(/\s+/)[0]
                .toUpperCase();
            const currentCode = normalizeCode(originalValue);
            const currentParts = currentCode.split('.');
            let currentExchange = currentParts.length > 1 ? currentParts[0] : '';
            let currentSymbol = currentParts.length > 1 ? currentParts.slice(1).join('.') : currentParts[0];
            const legacyStock = currentCode.match(/^(SH|SZ|BJ)(\d{6})$/);
            if (!currentExchange && legacyStock) {
                currentExchange = { SH: 'SSE', SZ: 'SZSE', BJ: 'BSE' }[legacyStock[1]];
                currentSymbol = legacyStock[2];
            } else if (!currentExchange && /^\d{6}$/.test(currentSymbol)) {
                currentExchange = /^(4|8|92)/.test(currentSymbol) ? 'BSE' : (/^[569]/.test(currentSymbol) ? 'SSE' : 'SZSE');
            }
            const currentProduct = (currentSymbol.match(/^[A-Z]+/) || [''])[0];
            const stockExchanges = new Set(['SSE', 'SZSE', 'BSE']);
            const exchangeOrder = ['SHFE', 'INE', 'DCE', 'CZCE', 'GFEX', 'CFFEX', 'SSE', 'SZSE', 'BSE'];
            let requestSerial = 0;
            let catalogMeta = '';
            let stockRows = [];
            let stockFilterTimer = null;

            const fetchJson = async url => {
                const response = await fetch(url);
                let data;
                try {
                    data = await response.json();
                } catch (_) {
                    throw new Error(`在线接口返回异常（HTTP ${response.status}）`);
                }
                if (!response.ok || data.status !== 'success') {
                    throw new Error(data.error || `HTTP ${response.status}`);
                }
                return data;
            };

            try {
                const data = await fetchJson('/api/online_symbols/catalog');
                const tree = data.tree || {};
                const assetKeys = Object.keys(tree).filter(key => Object.keys(tree[key]?.exchanges || {}).length > 0);
                if (!assetKeys.length) throw new Error('在线品种目录为空');
                catalogMeta = `目录 ${data.as_of || '今日'} · ${data.source || '在线数据源'}${data.warning ? ' · 已启用备用目录' : ''}`;
                let initialExchange = currentExchange;
                if (!stockExchanges.has(currentExchange) && currentProduct) {
                    const futuresExchanges = tree.futures_cn?.exchanges || {};
                    if (!futuresExchanges[currentExchange]?.products?.[currentProduct]) {
                        initialExchange = Object.keys(futuresExchanges)
                            .find(exchange => futuresExchanges[exchange]?.products?.[currentProduct]) || currentExchange;
                    }
                }

                container.innerHTML = `
                    <div class="online-cascade-grid">
                        <label class="online-cascade-field"><span>资产</span><select class="form-select online-cascade-a" aria-label="资产类别"></select></label>
                        <label class="online-cascade-field"><span>交易所</span><select class="form-select online-cascade-e" aria-label="交易所"></select></label>
                        <label class="online-cascade-field"><span class="online-cascade-p-label">品种</span><select class="form-select online-cascade-p" aria-label="品种"></select></label>
                        <label class="online-cascade-field online-cascade-contract-field"><span>有效合约</span><select class="form-select online-cascade-c" aria-label="有效合约"></select></label>
                    </div>
                    <input type="search" class="form-input online-symbol-filter hidden" placeholder="输入股票代码或名称筛选" autocomplete="off" aria-label="筛选股票">
                    <div class="online-cascade-status" role="status"></div>
                `;
                container.appendChild(hidden);

                const selA = container.querySelector('.online-cascade-a');
                const selE = container.querySelector('.online-cascade-e');
                const selP = container.querySelector('.online-cascade-p');
                const selC = container.querySelector('.online-cascade-c');
                const pLabel = container.querySelector('.online-cascade-p-label');
                const contractField = container.querySelector('.online-cascade-contract-field');
                const stockFilter = container.querySelector('.online-symbol-filter');
                const status = container.querySelector('.online-cascade-status');

                const setStatus = (message, kind = '') => {
                    status.className = `online-cascade-status${kind ? ` is-${kind}` : ''}`;
                    status.textContent = message;
                };
                const setPlaceholder = (select, message) => {
                    select.innerHTML = '';
                    select.appendChild(new Option(message, '', true, true));
                    select.disabled = true;
                };
                const sortedExchanges = keys => [...keys].sort((a, b) => {
                    const ai = exchangeOrder.indexOf(a);
                    const bi = exchangeOrder.indexOf(b);
                    return (ai < 0 ? 999 : ai) - (bi < 0 ? 999 : bi) || a.localeCompare(b);
                });

                const renderAssets = () => {
                    selA.innerHTML = '';
                    assetKeys.forEach(key => selA.appendChild(new Option(tree[key].label || key, key)));
                    const preferred = stockExchanges.has(currentExchange) ? 'stock_cn' : 'futures_cn';
                    if (assetKeys.includes(preferred)) selA.value = preferred;
                };
                const renderExchanges = preferred => {
                    const exchanges = tree[selA.value]?.exchanges || {};
                    const keys = sortedExchanges(Object.keys(exchanges));
                    selE.innerHTML = '';
                    keys.forEach(key => selE.appendChild(new Option(exchanges[key].label || key, key)));
                    selE.disabled = !keys.length;
                    if (preferred && keys.includes(preferred)) selE.value = preferred;
                };
                const renderProducts = preferred => {
                    const products = tree[selA.value]?.exchanges?.[selE.value]?.products || {};
                    const keys = Object.keys(products).sort((a, b) =>
                        String(products[a].label || a).localeCompare(String(products[b].label || b), 'zh-CN', { numeric: true })
                    );
                    selP.innerHTML = '';
                    keys.forEach(key => selP.appendChild(new Option(products[key].label || key, key)));
                    selP.disabled = !keys.length;
                    if (preferred && keys.includes(preferred)) selP.value = preferred;
                };

                const selectCurrentOrInvalidate = (select, rows, preferredCode, initial, noun, autoSelect = true) => {
                    const exact = rows.find(row => normalizeCode(row.val) === preferredCode);
                    if (exact) {
                        select.value = exact.val;
                        hidden.value = exact.val;
                        return true;
                    }
                    if (!initial && autoSelect && rows.length) {
                        select.value = rows[0].val;
                        hidden.value = rows[0].val;
                        return true;
                    }
                    const placeholder = initial ? `原${noun}已失效，请重新选择` : `请选择${noun}`;
                    select.insertBefore(new Option(placeholder, '', true, true), select.firstChild);
                    hidden.value = '';
                    return false;
                };

                const loadContracts = async initial => {
                    const serial = ++requestSerial;
                    hidden.value = '';
                    setPlaceholder(selC, '正在校验有效合约...');
                    setStatus(`${catalogMeta} · 正在实时校验合约`);
                    try {
                        const result = await fetchJson(`/api/online_symbols/contracts?exchange=${encodeURIComponent(selE.value)}&product=${encodeURIComponent(selP.value)}`);
                        if (serial !== requestSerial) return;
                        const rows = result.contracts || [];
                        selC.innerHTML = '';
                        rows.forEach(row => {
                            const suffix = row.continuous ? ' · 连续' : '';
                            selC.appendChild(new Option(`${row.sym} ${row.label || ''}${suffix}`.trim(), row.val));
                        });
                        selC.disabled = !rows.length;
                        if (!rows.length) throw new Error('当前没有有效挂牌合约');
                        const preferredCode = initial && currentSymbol
                            ? normalizeCode(`${selE.value}.${currentSymbol}`)
                            : currentCode;
                        const valid = selectCurrentOrInvalidate(selC, rows, preferredCode, initial, '合约');
                        const correctedExchange = valid && initial && currentExchange && selE.value !== currentExchange;
                        setStatus(
                            correctedExchange
                                ? `原交易所 ${currentExchange} 与品种不匹配；已识别为 ${preferredCode}，请确认后保存`
                                : valid
                                ? `${rows.length} 个当前挂牌合约 · ${result.as_of || '刚刚'} · ${result.source || '在线数据源'}`
                                : `${currentCode || '原配置'} 已不在当前挂牌列表中，请重新选择`,
                            valid && !correctedExchange ? '' : 'warning'
                        );
                    } catch (err) {
                        if (serial !== requestSerial) return;
                        setPlaceholder(selC, '合约加载失败');
                        hidden.value = initial ? originalValue : '';
                        setStatus(`有效合约校验失败：${err.message}`, 'error');
                    }
                };

                const renderStockOptions = (query = '', initial = false) => {
                    const q = query.trim().toLowerCase();
                    const preferredCode = normalizeCode(hidden.value) || currentCode;
                    const filtered = q
                        ? stockRows.filter(row => `${row.sym} ${row.label}`.toLowerCase().includes(q))
                        : stockRows;
                    selP.innerHTML = '';
                    filtered.forEach(row => selP.appendChild(new Option(row.label, row.val)));
                    selP.disabled = !filtered.length;
                    if (!filtered.length) {
                        setPlaceholder(selP, '没有匹配股票');
                        hidden.value = '';
                        setStatus('没有匹配的股票代码或名称', 'warning');
                        return;
                    }
                    const valid = selectCurrentOrInvalidate(selP, filtered, preferredCode, initial, '股票', !q);
                    setStatus(
                        valid
                            ? `${stockRows.length} 只在线股票 · ${catalogMeta}`
                            : (q ? `${filtered.length} 条筛选结果，请选择股票` : `${currentCode || '原配置'} 不在当前股票目录中，请重新选择`),
                        valid ? '' : 'warning'
                    );
                };

                const loadStocks = async initial => {
                    const serial = ++requestSerial;
                    hidden.value = '';
                    setPlaceholder(selP, '正在加载股票...');
                    setStatus(`${catalogMeta} · 正在加载股票目录`);
                    try {
                        const result = await fetchJson(`/api/online_symbols/stocks?exchange=${encodeURIComponent(selE.value)}`);
                        if (serial !== requestSerial) return;
                        stockRows = result.stocks || [];
                        stockFilter.value = '';
                        renderStockOptions('', initial);
                        setStatus(
                            hidden.value
                                ? `${stockRows.length} 只在线股票 · ${result.as_of || '今日'} · ${result.source || '在线数据源'}`
                                : `${currentCode || '原配置'} 不在当前股票目录中，请重新选择`,
                            hidden.value ? '' : 'warning'
                        );
                    } catch (err) {
                        if (serial !== requestSerial) return;
                        stockRows = [];
                        setPlaceholder(selP, '股票加载失败');
                        hidden.value = initial ? originalValue : '';
                        setStatus(`股票目录加载失败：${err.message}`, 'error');
                    }
                };

                const refreshMode = async initial => {
                    const isStock = selA.value === 'stock_cn';
                    pLabel.textContent = isStock ? '股票' : '品种';
                    contractField.classList.toggle('hidden', isStock);
                    stockFilter.classList.toggle('hidden', !isStock);
                    if (isStock) {
                        await loadStocks(initial);
                    } else {
                        renderProducts(initial ? currentProduct : '');
                        if (!selP.value) {
                            setPlaceholder(selC, '暂无品种');
                            hidden.value = '';
                            setStatus('该交易所暂未返回在线品种', 'warning');
                            return;
                        }
                        await loadContracts(initial);
                    }
                };

                renderAssets();
                renderExchanges(initialExchange);
                await refreshMode(true);

                selA.addEventListener('change', async () => {
                    renderExchanges('');
                    await refreshMode(false);
                });
                selE.addEventListener('change', async () => refreshMode(false));
                selP.addEventListener('change', async () => {
                    if (selA.value === 'stock_cn') {
                        hidden.value = selP.value;
                        setStatus(`${stockRows.length} 只在线股票 · 已选择 ${normalizeCode(hidden.value)}`);
                    } else {
                        await loadContracts(false);
                    }
                });
                selC.addEventListener('change', () => {
                    hidden.value = selC.value;
                    setStatus(`${selC.options[selC.selectedIndex]?.text || normalizeCode(hidden.value)} · 已通过当前挂牌列表校验`);
                });
                stockFilter.addEventListener('input', () => {
                    clearTimeout(stockFilterTimer);
                    stockFilterTimer = setTimeout(() => renderStockOptions(stockFilter.value, false), 120);
                });
            } catch (err) {
                console.error('Online symbol catalog error:', err);
                const loading = container.querySelector('.online-cascading-loading');
                const status = container.querySelector('.online-cascade-status');
                const message = `在线品种目录加载失败：${err.message}。当前配置保持不变。`;
                if (loading) {
                    loading.textContent = message;
                    loading.classList.add('is-error');
                } else if (status) {
                    status.textContent = message;
                    status.classList.add('is-error');
                }
            }
        });

        const dynamicSelects = this.dom.settingsBody.querySelectorAll('.dynamic-select');
        dynamicSelects.forEach(select => {
            const dependsKey = select.getAttribute('data-depends');
            const endpoint = select.getAttribute('data-endpoint');
            const currentVal = select.getAttribute('data-current');
            const dependsInput = this.dom.settingsBody.querySelector(`[data-key="${dependsKey}"]`);
            
            const updateOptions = () => {
                if (!dependsInput) return;
                const depVal = dependsInput.value;
                fetch(`${endpoint}?product=${depVal}`).then(r=>r.json()).then(data => {
                    if (data.status === 'success') {
                        select.innerHTML = '';
                        data.options.forEach(opt => {
                            const option = new Option(opt, opt);
                            if (opt === currentVal) option.selected = true;
                            select.appendChild(option);
                        });
                        if (select.selectedIndex === -1 && select.options.length > 0) {
                             select.selectedIndex = 0;
                        }
                    }
                });
            };
            if (dependsInput) {
                dependsInput.addEventListener('change', updateOptions);
                updateOptions();
            }
        });

        this.dom.settingsModal.classList.remove('hidden');
    }

    _closeSettingsModal() {
        this.dom.settingsModal.classList.add('hidden');
        this._settingsCurrentModuleId = null;
    }

    _saveModuleSettings() {
        if (!this._settingsCurrentModuleId) return;

        const missingRequired = [...this.dom.settingsBody.querySelectorAll('[data-required="true"]')]
            .find(el => !String(el.value || '').trim());
        if (missingRequired) {
            this.showToast('请选择一个当前有效的在线标的', 'warning');
            return;
        }
        
        const newConfig = {};
        const inputs = this.dom.settingsBody.querySelectorAll('input, select');
        
        inputs.forEach(el => {
            const key = el.dataset.key;
            if (!key) return; // 跳过没有绑定 key 的内部输入框
            
            // 简单的数据类型转换
            if (el.type === 'number') {
                newConfig[key] = parseFloat(el.value);
            } else {
                newConfig[key] = el.value;
            }
        });
        
        this.moduleRenderer.updateModuleConfig(this._settingsCurrentModuleId, newConfig);
        this._closeSettingsModal();
        this.showToast('设置已应用', 'success');
    }

    // ============================================================
    //  Toast 通知
    // ============================================================

    showToast(message, type = 'info') {
        const iconMap = {
            'success': '✅',
            'error': '❌',
            'warning': '⚠️',
            'info': 'ℹ️'
        };

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.innerHTML = `
            <span class="toast-icon">${iconMap[type]}</span>
            <span class="toast-message">${message}</span>
        `;
        
        this.dom.toastContainer.appendChild(toast);
        
        // 3秒后自动消失
        setTimeout(() => {
            toast.classList.add('toast-out');
            setTimeout(() => {
                if (toast.parentNode) toast.parentNode.removeChild(toast);
            }, 300); // 等待动画结束
        }, 3000);
    }
}

// 启动应用
const app = new App();
document.addEventListener('DOMContentLoaded', () => app.init());
