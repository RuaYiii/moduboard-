/**
 * Grid — 无限画布管理器
 *
 * 负责画布的缩放、平移和网格渲染。
 * 所有模块在画布上定位，画布通过 CSS transform 实现缩放和平移。
 *
 * 交互方式：
 *   - 鼠标滚轮：缩放（以鼠标位置为中心）
 *   - 鼠标中键拖拽 / 空格+左键拖拽：平移
 *   - 工具栏按钮：缩放 +/-，重置视图
 */
export class Grid {
    /**
     * @param {HTMLElement} viewport - 视口容器（overflow: hidden）
     * @param {HTMLElement} canvas   - 画布元素（应用 CSS transform）
     */
    constructor(viewport, canvas) {
        this.viewport = viewport;
        this.canvas = canvas;

        // —— 状态 ——
        this.scale = 1;           // 当前缩放比例
        this.offsetX = 0;         // 画布平移偏移 X（屏幕像素）
        this.offsetY = 0;         // 画布平移偏移 Y（屏幕像素）
        this.gridSize = 10;       // 网格单元格大小（像素）
        this.minScale = 0.15;     // 最小缩放
        this.maxScale = 3;        // 最大缩放

        // —— 平移状态 ——
        this._isPanning = false;
        this._panStartX = 0;
        this._panStartY = 0;
        this._spaceDown = false;  // 空格键是否按下

        // —— 缩放变化回调 ——
        this.onScaleChange = null; // (scale) => void

        // 初始化
        this._setupEvents();
        this._applyTransform();
        this._updateGridBackground();
    }

    // ============================================================
    //  公共方法
    // ============================================================

    /**
     * 屏幕坐标 → 画布坐标
     * 将浏览器窗口中的鼠标位置转换为画布上的实际位置
     */
    screenToCanvas(screenX, screenY) {
        const rect = this.viewport.getBoundingClientRect();
        const viewX = screenX - rect.left;
        const viewY = screenY - rect.top;
        return {
            x: (viewX - this.offsetX) / this.scale,
            y: (viewY - this.offsetY) / this.scale,
        };
    }

    /**
     * 画布坐标 → 屏幕坐标
     */
    canvasToScreen(canvasX, canvasY) {
        const rect = this.viewport.getBoundingClientRect();
        return {
            x: canvasX * this.scale + this.offsetX + rect.left,
            y: canvasY * this.scale + this.offsetY + rect.top,
        };
    }

    /**
     * 将像素值吸附到最近的网格线
     * @param {number} value - 画布坐标值（像素）
     * @returns {number} 吸附后的值
     */
    snapToGrid(value) {
        return Math.round(value / this.gridSize) * this.gridSize;
    }

    /**
     * 将像素值转换为网格单位数
     * @param {number} px - 像素值
     * @returns {number} 网格单位数
     */
    pxToGridUnits(px) {
        return Math.round(px / this.gridSize);
    }

    /**
     * 网格单位数转换为像素值
     * @param {number} units - 网格单位数
     * @returns {number} 像素值
     */
    gridUnitsToPx(units) {
        return units * this.gridSize;
    }

    /**
     * 放大
     */
    zoomIn() {
        this._zoomAtCenter(this.scale * 1.2);
    }

    /**
     * 缩小
     */
    zoomOut() {
        this._zoomAtCenter(this.scale / 1.2);
    }

    /**
     * 重置视图（缩放 1x，居中）
     */
    resetView() {
        this.scale = 1;
        this.offsetX = 0;
        this.offsetY = 0;
        this._applyTransform();
        this._updateGridBackground();
        this._emitScaleChange();
    }

    /**
     * 设置网格大小
     * @param {number} size - 新的网格大小（像素）
     */
    setGridSize(size) {
        this.gridSize = Math.max(20, Math.min(200, size));
        this._updateGridBackground();
    }

    /**
     * 获取当前视口中心的画布坐标
     * 用于在可见区域中心放置新模块
     */
    getViewportCenter() {
        const rect = this.viewport.getBoundingClientRect();
        return this.screenToCanvas(
            rect.left + rect.width / 2,
            rect.top + rect.height / 2
        );
    }

    /**
     * 获取状态（用于保存配置）
     */
    getState() {
        return {
            scale: this.scale,
            offset_x: this.offsetX,
            offset_y: this.offsetY,
        };
    }

    /**
     * 恢复状态
     */
    setState(state) {
        if (!state) return;
        this.scale = state.scale ?? 1;
        this.offsetX = state.offset_x ?? 0;
        this.offsetY = state.offset_y ?? 0;
        this._applyTransform();
        this._updateGridBackground();
        this._emitScaleChange();
    }

    // ============================================================
    //  内部方法
    // ============================================================

    /**
     * 应用 CSS transform 到画布
     */
    _applyTransform() {
        this.canvas.style.transform =
            `translate(${this.offsetX}px, ${this.offsetY}px) scale(${this.scale})`;
        
        // 同步网格背景的平移
        this.viewport.style.backgroundPosition = `${this.offsetX}px ${this.offsetY}px`;
    }

    /**
     * 更新网格背景（随缩放调整点阵大小和位置）
     */
    _updateGridBackground() {
        const scaledGrid = this.gridSize * this.scale;
        // 网格点阵背景 —— 点的大小随缩放微调
        const dotSize = Math.max(0.8, Math.min(1.5, this.scale));
        
        this.viewport.style.backgroundSize = `${scaledGrid}px ${scaledGrid}px`;
        this.viewport.style.backgroundImage =
            `radial-gradient(circle, var(--grid-dot-color) ${dotSize}px, transparent ${dotSize}px)`;
    }

    /**
     * 以视口中心为基准缩放
     */
    _zoomAtCenter(newScale) {
        const rect = this.viewport.getBoundingClientRect();
        const centerX = rect.width / 2;
        const centerY = rect.height / 2;
        this._zoomAt(centerX, centerY, newScale);
    }

    /**
     * 以指定屏幕位置为中心缩放
     * 核心公式: offset = mousePos - (mousePos - offset) * (newScale / oldScale)
     */
    _zoomAt(viewX, viewY, newScale) {
        // 限制缩放范围
        newScale = Math.max(this.minScale, Math.min(this.maxScale, newScale));
        if (newScale === this.scale) return;

        const ratio = newScale / this.scale;
        this.offsetX = viewX - (viewX - this.offsetX) * ratio;
        this.offsetY = viewY - (viewY - this.offsetY) * ratio;
        this.scale = newScale;

        this._applyTransform();
        this._updateGridBackground();
        this._emitScaleChange();
    }

    /**
     * 触发缩放变化回调
     */
    _emitScaleChange() {
        if (this.onScaleChange) {
            this.onScaleChange(this.scale);
        }
    }

    /**
     * 设置所有交互事件
     */
    _setupEvents() {
        // —— 鼠标滚轮缩放 ——
        this.viewport.addEventListener('wheel', (e) => {
            // 如果鼠标悬停在 .module-body 上且该内容可滚动，不按下 ctrl 键时允许默认的滚动行为
            const moduleBody = e.target.closest('.module-body');
            if (moduleBody && !e.ctrlKey) {
                // 判断元素是否在内容高度上大于容器高度（有垂直滚动条）或水平滚动条
                const canScrollY = moduleBody.scrollHeight > moduleBody.clientHeight;
                const canScrollX = moduleBody.scrollWidth > moduleBody.clientWidth;
                if (canScrollY || canScrollX) {
                    return; // 允许原生滚动
                }
            }

            e.preventDefault();
            const rect = this.viewport.getBoundingClientRect();
            const viewX = e.clientX - rect.left;
            const viewY = e.clientY - rect.top;

            // 根据滚动方向决定缩放因子
            const zoomFactor = e.deltaY < 0 ? 1.08 : 1 / 1.08;
            this._zoomAt(viewX, viewY, this.scale * zoomFactor);
        }, { passive: false });

        // —— 鼠标中键平移 / 空格+左键平移 ——
        this.viewport.addEventListener('pointerdown', (e) => {
            // 中键（button === 1）或 空格+左键
            const shouldPan = e.button === 1 || (e.button === 0 && this._spaceDown);
            if (!shouldPan) return;

            this._isPanning = true;
            this._panStartX = e.clientX - this.offsetX;
            this._panStartY = e.clientY - this.offsetY;
            this.viewport.setPointerCapture(e.pointerId);
            this.viewport.classList.add('panning');
            e.preventDefault();
        });

        this.viewport.addEventListener('pointermove', (e) => {
            if (!this._isPanning) return;
            this.offsetX = e.clientX - this._panStartX;
            this.offsetY = e.clientY - this._panStartY;
            this._applyTransform();
        });

        this.viewport.addEventListener('pointerup', (e) => {
            if (!this._isPanning) return;
            this._isPanning = false;
            this.viewport.classList.remove('panning');
        });

        // —— 空格键状态跟踪 ——
        document.addEventListener('keydown', (e) => {
            if (e.code === 'Space' && !e.repeat && e.target === document.body) {
                this._spaceDown = true;
                this.viewport.classList.add('panning');
                e.preventDefault();
            }
        });

        document.addEventListener('keyup', (e) => {
            if (e.code === 'Space') {
                this._spaceDown = false;
                if (!this._isPanning) {
                    this.viewport.classList.remove('panning');
                }
            }
        });

        // —— 键盘快捷键 ——
        document.addEventListener('keydown', (e) => {
            // Ctrl++ / Ctrl+= : 放大
            if (e.ctrlKey && (e.key === '+' || e.key === '=')) {
                e.preventDefault();
                this.zoomIn();
            }
            // Ctrl+- : 缩小
            if (e.ctrlKey && e.key === '-') {
                e.preventDefault();
                this.zoomOut();
            }
            // Ctrl+0 : 重置
            if (e.ctrlKey && e.key === '0') {
                e.preventDefault();
                this.resetView();
            }
        });
    }
}
