/**
 * globalScaleFix.js — 全局缩放坐标修正补丁（唯一来源）
 *
 * 所有图表模块共享此补丁。通过 <script src="/static/js/globalScaleFix.js"> 在页面
 * 加载早期引入（早于任何 LightweightCharts 实例化），确保 EventTarget.prototype
 * .addEventListener 被安全地猴子补丁一次。
 *
 * 问题背景：
 *   ModuBoard 的画布 (#canvas) 使用 CSS transform: translate(ox, oy) scale(s) 实现
 *   无限缩放画布。LightweightCharts (LW) 内部通过 getBoundingClientRect() 获取容器
 *   位置，再用 e.clientX - rect.left 计算鼠标在图表中的 CSS 像素坐标。
 *   但 getBoundingClientRect() 返回的是缩放后的屏幕像素尺寸，而 LW 认为容器宽高
 *   是 offsetWidth/offsetHeight（CSS 像素），两者在 scale ≠ 1 时不一致，导致
 *   十字准线 / tooltip 偏移。
 *
 * 修正原理：
 *   拦截所有 addEventListener('mousemove', ...) 等调用，在真正的 handler 执行前，
 *   将 event.clientX/Y 修正为"如果没有缩放时的等效坐标"，使 LW 内部的
 *   (correctedClientX - rect.left) 刚好等于真实的 CSS 像素偏移量。
 *
 *   公式: correctedX = chartRect.left + (e.clientX - chartRect.left) / scale
 *   其中 scale 从 #canvas 元素的 getBoundingClientRect().width / offsetWidth 获取，
 *   chartRect 取事件目标所在 .module-card 内的具体图表容器元素。
 *
 * 重要约束（供未来模块开发者参考）：
 *   1. 此文件是 scaleFix 的唯一实现，各模块 .py 中不应再内联 installGlobalScaleFix。
 *   2. 新增图表模块时，给图表容器 div 加一个约定的 CSS 类名（如 .my-chart），
 *      并在下方 CHART_SELECTORS 数组中注册。
 *   3. 此补丁必须在 LightweightCharts.js 加载前生效（因为 LW 在 import 阶段
 *      可能就注册了事件）。在 index.html 中，<script src="globalScaleFix.js"> 应
 *      出现在 LW 之前。
 *   4. 缩放比从 #canvas 元素统一获取（因为所有图表都在 #canvas 的 CSS transform
 *      下），确保全局一致。
 */
(function installGlobalScaleFix() {
    if (window.__scaleFixInstalled) return;
    window.__scaleFixInstalled = true;

    /**
     * 注册所有图表容器的 CSS 类选择器。
     * 新增图表模块时在此添加对应的 class。
     */
    var CHART_SELECTORS = [
        '.klv2-chart',
        '.spread-chart',
        '.kline-chart',
        '.dt-kline-chart',
    ];
    var CHART_SELECTOR_STRING = CHART_SELECTORS.join(',');

    function getCanvasScale() {
        var cvs = document.getElementById('canvas');
        if (!cvs) return 1;
        var r = cvs.getBoundingClientRect();
        return cvs.offsetWidth > 0 ? (r.width / cvs.offsetWidth) : 1;
    }

    function fixEvent(e) {
        if (!e || e.__scaleFixed) return e;
        var scale = getCanvasScale();
        if (!scale || Math.abs(scale - 1) < 0.001) return e;

        var target = e.target;
        if (!target || typeof target.closest !== 'function') return e;
        var card = target.closest('.module-card');
        if (!card) return e;

        var chartEl = card.querySelector(CHART_SELECTOR_STRING);
        if (!chartEl) return e;

        var rect = chartEl.getBoundingClientRect();
        var unscaledX = rect.left + (e.clientX - rect.left) / scale;
        var unscaledY = rect.top  + (e.clientY - rect.top)  / scale;

        return new Proxy(e, {
            get: function(obj, prop) {
                if (prop === '__scaleFixed') return true;
                if (prop === 'clientX') return unscaledX;
                if (prop === 'clientY') return unscaledY;
                if (prop === 'pageX') return unscaledX + (window.scrollX || 0);
                if (prop === 'pageY') return unscaledY + (window.scrollY || 0);
                var val = obj[prop];
                return typeof val === 'function' ? val.bind(obj) : val;
            }
        });
    }

    var origAdd = EventTarget.prototype.addEventListener;
    EventTarget.prototype.addEventListener = function(type, listener, options) {
        if (['mousemove', 'pointermove', 'mousedown', 'pointerdown',
             'mouseup', 'pointerup', 'click', 'dblclick', 'wheel'].indexOf(type) !== -1) {
            var wrapped = function(e) {
                return listener.call(this, fixEvent(e));
            };
            wrapped.__orig = listener;
            return origAdd.call(this, type, wrapped, options);
        }
        return origAdd.call(this, type, listener, options);
    };
})();
