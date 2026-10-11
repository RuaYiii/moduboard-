/**
 * DragManager — 拖拽管理器
 *
 * 负责处理模块的拖拽移动和调整大小。
 * 使用 Pointer Events 确保可靠的跟踪，并自动处理画布缩放下的坐标转换。
 */
export class DragManager {
    /**
     * @param {Grid} grid - Grid 实例，用于坐标转换和吸附
     */
    constructor(grid) {
        this.grid = grid;

        // —— 状态 ——
        this._dragState = null;   // 拖拽移动状态
        this._resizeState = null; // 调整大小状态

        // —— 回调函数（由 app.js 绑定） ——
        this.onModuleMoved = null;   // (moduleId, gridX, gridY) => void
        this.onModuleResized = null; // (moduleId, gridW, gridH) => void

        this._setupEvents();
    }

    // ============================================================
    //  内部事件设置
    // ============================================================

    _setupEvents() {
        // 在 document 上监听 pointer 移动和松开，处理拖拽逻辑
        // 我们利用 setPointerCapture 确保在快速移动时不会丢失事件

        document.addEventListener('pointermove', (e) => {
            if (this._dragState) {
                this._onDrag(e);
            } else if (this._resizeState) {
                this._onResize(e);
            }
        });

        document.addEventListener('pointerup', (e) => {
            if (this._dragState) {
                this._endDrag(e);
            } else if (this._resizeState) {
                this._endResize(e);
            }
        });

        // 取消事件处理（比如切换窗口时）
        document.addEventListener('pointercancel', (e) => {
            if (this._dragState) this._endDrag(e);
            if (this._resizeState) this._endResize(e);
        });
    }

    // ============================================================
    //  拖拽移动 (Drag)
    // ============================================================

    /**
     * 开始拖拽模块
     * @param {HTMLElement} moduleEl - 模块 DOM 元素
     * @param {PointerEvent} event - 触发事件
     */
    startDrag(moduleEl, event) {
        // 如果点的是按钮之类的，不触发拖拽
        if (event.target.closest('button, input, select')) return;

        event.preventDefault();
        
        // 标记为正在拖拽
        moduleEl.classList.add('dragging');
        // 捕获指针，这样鼠标移出模块依然能接收事件
        moduleEl.setPointerCapture(event.pointerId);

        // 直接读取模块当前在画布上的真实位置（像素），避免 getBoundingClientRect 经缩放后的浮点误差
        const startCanvasPos = {
            x: parseFloat(moduleEl.style.left) || 0,
            y: parseFloat(moduleEl.style.top) || 0,
        };
        
        // 记录鼠标按下时的屏幕位置
        const startScreenPos = { x: event.clientX, y: event.clientY };

        this._dragState = {
            element: moduleEl,
            moduleId: moduleEl.dataset.moduleId,
            pointerId: event.pointerId,
            startScreenPos,
            startCanvasPos,
            currentGridX: parseInt(moduleEl.dataset.gridX),
            currentGridY: parseInt(moduleEl.dataset.gridY)
        };
    }

    _onDrag(event) {
        const state = this._dragState;
        
        // 计算屏幕上的移动距离
        const deltaScreenX = event.clientX - state.startScreenPos.x;
        const deltaScreenY = event.clientY - state.startScreenPos.y;
        
        // 转换为画布上的实际移动距离（考虑缩放）
        const deltaCanvasX = deltaScreenX / this.grid.scale;
        const deltaCanvasY = deltaScreenY / this.grid.scale;
        
        // 计算目标画布位置
        const targetCanvasX = state.startCanvasPos.x + deltaCanvasX;
        const targetCanvasY = state.startCanvasPos.y + deltaCanvasY;
        
        // 吸附到网格（像素值）
        const snappedX = this.grid.snapToGrid(targetCanvasX);
        const snappedY = this.grid.snapToGrid(targetCanvasY);
        
        // 转换为网格单位（允许自由移动，可以为负数，实现真正的无限画板）
        const gridX = this.grid.pxToGridUnits(snappedX);
        const gridY = this.grid.pxToGridUnits(snappedY);
        
        // 实时更新 DOM 位置（提供平滑反馈，我们直接修改样式）
        // 但其实更理想的是让 element.style.left 跟着未吸附的坐标走，
        // 或者显示一个虚线框来表示吸附位置。这里为了简单，直接让模块跳到吸附点。
        state.element.style.left = `${this.grid.gridUnitsToPx(gridX)}px`;
        state.element.style.top = `${this.grid.gridUnitsToPx(gridY)}px`;
        
        state.currentGridX = gridX;
        state.currentGridY = gridY;
    }

    _endDrag(event) {
        const state = this._dragState;
        this._dragState = null;
        
        state.element.classList.remove('dragging');
        state.element.releasePointerCapture(state.pointerId);
        
        // 触发回调更新数据模型
        if (this.onModuleMoved) {
            this.onModuleMoved(state.moduleId, state.currentGridX, state.currentGridY);
        }
    }

    // ============================================================
    //  调整大小 (Resize)
    // ============================================================

    /**
     * 开始调整模块大小
     * @param {HTMLElement} moduleEl - 模块 DOM 元素
     * @param {PointerEvent} event - 触发事件
     * @param {Object} meta - 模块的 meta 信息（用于最小最大尺寸限制）
     */
    startResize(moduleEl, event, meta) {
        event.preventDefault();
        event.stopPropagation(); // 阻止冒泡到 header 触发 drag
        
        // 添加调整大小中的样式（可选，可以使用和拖拽同样的样式或不加）
        moduleEl.classList.add('resizing');
        const handle = event.target;
        handle.setPointerCapture(event.pointerId);

        const minW = meta?.min_size?.[0] || 2;
        const minH = meta?.min_size?.[1] || 2;
        const maxW = meta?.max_size?.[0] || 9999;
        const maxH = meta?.max_size?.[1] || 9999;

        const startWidth = moduleEl.offsetWidth;
        const startHeight = moduleEl.offsetHeight;

        this._resizeState = {
            element: moduleEl,
            handle: handle,
            moduleId: moduleEl.dataset.moduleId,
            pointerId: event.pointerId,
            startScreenX: event.clientX,
            startScreenY: event.clientY,
            startWidth,
            startHeight,
            minW, minH, maxW, maxH,
            currentGridW: parseInt(moduleEl.dataset.gridW),
            currentGridH: parseInt(moduleEl.dataset.gridH)
        };
    }

    _onResize(event) {
        const state = this._resizeState;
        
        // 屏幕移动量，转化为画布实际大小变化量
        const deltaX = (event.clientX - state.startScreenX) / this.grid.scale;
        const deltaY = (event.clientY - state.startScreenY) / this.grid.scale;
        
        const rawW = state.startWidth + deltaX;
        const rawH = state.startHeight + deltaY;
        
        // 吸附并转换为网格数
        let gridW = this.grid.pxToGridUnits(rawW);
        let gridH = this.grid.pxToGridUnits(rawH);
        
        // 限制在最小值和最大值之间
        gridW = Math.max(state.minW, Math.min(state.maxW, gridW));
        gridH = Math.max(state.minH, Math.min(state.maxH, gridH));
        
        // 更新样式
        state.element.style.width = `${this.grid.gridUnitsToPx(gridW)}px`;
        state.element.style.height = `${this.grid.gridUnitsToPx(gridH)}px`;
        
        state.currentGridW = gridW;
        state.currentGridH = gridH;
    }

    _endResize(event) {
        const state = this._resizeState;
        this._resizeState = null;
        
        state.element.classList.remove('resizing');
        state.handle.releasePointerCapture(state.pointerId);
        
        // 触发回调
        if (this.onModuleResized) {
            this.onModuleResized(state.moduleId, state.currentGridW, state.currentGridH);
        }
    }
}
