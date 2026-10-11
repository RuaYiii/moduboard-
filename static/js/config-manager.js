/**
 * ConfigManager — 工作台配置管理器
 *
 * 负责保存/加载看板状态（模块、位置、大小、缩放等）到 JSON 文件
 */
export class ConfigManager {
    /**
     * @param {Grid} grid - Grid 实例，用于读取/设置视口状态
     * @param {ModuleRenderer} moduleRenderer - 渲染器，用于读写模块状态
     * @param {Function} showToast - Toast 通知函数
     */
    constructor(grid, moduleRenderer, showToast) {
        this.grid = grid;
        this.moduleRenderer = moduleRenderer;
        this.showToast = showToast || console.log;
        
        this.currentConfigName = null;
        this._autoSaveTimer = null;
    }

    /**
     * 获取配置列表
     */
    async fetchConfigList() {
        try {
            const res = await fetch('/api/configs');
            const data = await res.json();
            return data.configs || [];
        } catch (err) {
            this.showToast(`获取配置列表失败: ${err.message}`, 'error');
            return [];
        }
    }

    /**
     * 加载指定配置
     */
    async loadConfig(name) {
        try {
            const res = await fetch(`/api/configs/${encodeURIComponent(name)}`);
            const data = await res.json();
            
            if (data.status === 'success' && data.config) {
                await this._applyConfig(data.config);
                this.currentConfigName = name;
                this.showToast(`已加载界面: ${name}`, 'success');
                return true;
            } else {
                throw new Error(data.error || '未知错误');
            }
        } catch (err) {
            this.showToast(`加载失败: ${err.message}`, 'error');
            return false;
        }
    }

    /**
     * 保存当前状态到配置
     */
    async saveConfig(name = this.currentConfigName, isAutoSave = false) {
        if (!name) return false;

        const config = {
            name: name,
            created_at: new Date().toISOString(),
            theme: document.documentElement.dataset.theme || 'light',
            grid_size: this.grid.gridSize,
            viewport: this.grid.getState(),
            modules: this.moduleRenderer.serializeAll()
        };

        try {
            const res = await fetch(`/api/configs/${encodeURIComponent(name)}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config)
            });
            const data = await res.json();
            
            if (data.status === 'success') {
                this.currentConfigName = name;
                if (!isAutoSave) {
                    this.showToast(`已保存: ${name}`, 'success');
                }
                return true;
            } else {
                throw new Error(data.error);
            }
        } catch (err) {
            if (!isAutoSave) {
                this.showToast(`保存失败: ${err.message}`, 'error');
            }
            return false;
        }
    }

    /**
     * 删除配置
     */
    async deleteConfig(name) {
        try {
            const res = await fetch(`/api/configs/${encodeURIComponent(name)}`, {
                method: 'DELETE'
            });
            const data = await res.json();
            
            if (data.status === 'success') {
                this.showToast(`已删除: ${name}`, 'info');
                return true;
            }
            throw new Error(data.error);
        } catch (err) {
            this.showToast(`删除失败: ${err.message}`, 'error');
            return false;
        }
    }

    /**
     * 应用配置数据到界面
     */
    async _applyConfig(config) {
        // 1. 清空当前
        this.moduleRenderer.clearAll();

        // 2. 恢复主题
        if (config.theme) {
            document.documentElement.dataset.theme = config.theme;
        }

        // 3. 恢复网格和视口
        if (config.grid_size) {
            this.grid.setGridSize(config.grid_size);
        }
        if (config.viewport) {
            this.grid.setState(config.viewport);
        }

        // 4. 恢复所有模块
        if (config.modules && Array.isArray(config.modules)) {
            // 并发渲染多个模块
            const promises = config.modules.map(modData => this.moduleRenderer.addModule(modData));
            await Promise.all(promises);
        }
    }

    /**
     * 自动保存管理
     */
    startAutoSave(intervalMs = 30000) {
        if (this._autoSaveTimer) clearInterval(this._autoSaveTimer);
        this._autoSaveTimer = setInterval(() => {
            if (this.currentConfigName) {
                this.saveConfig(this.currentConfigName, true);
            }
        }, intervalMs);
    }

    stopAutoSave() {
        if (this._autoSaveTimer) {
            clearInterval(this._autoSaveTimer);
            this._autoSaveTimer = null;
        }
    }
}
