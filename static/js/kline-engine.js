/**
 * kline-engine.js — K线行情模块前端引擎
 */

(function () {
    'use strict';

    let _cdnLoaded = false;
    let _cdnLoading = false;
    const _cdnCallbacks = [];

    function ensureLightweightCharts(cb) {
        if (typeof LightweightCharts !== 'undefined') {
            _cdnLoaded = true;
            cb();
            return;
        }
        _cdnCallbacks.push(cb);
        if (_cdnLoading) return;
        _cdnLoading = true;

        const script = document.createElement('script');
        script.src = '/static/js/lightweight-charts.standalone.production.js';
        script.onload = () => {
            _cdnLoaded = true;
            _cdnCallbacks.forEach(fn => fn());
            _cdnCallbacks.length = 0;
        };
        script.onerror = (e) => {
            console.error('[KlineEngine] 无法加载 LightweightCharts CDN', e);
        };
        document.head.appendChild(script);
    }

    const _instances = new Map();

    function initKlineChart(moduleEl) {
        const moduleId = moduleEl.dataset.moduleId;
        if (!moduleId || _instances.has(moduleId)) return;

        _instances.set(moduleId, { pending: true });

        const chartArea = moduleEl.querySelector('.kline-chart-area');
        if (!chartArea) return;

        try {
            ensureLightweightCharts(() => {
                if (_instances.get(moduleId) && !_instances.get(moduleId).pending) return;

                const isDark = document.documentElement.dataset.theme === 'dark';
                
                // 主图设置
                const chart = LightweightCharts.createChart(chartArea, {
                    layout: {
                        background: { type: 'solid', color: 'transparent' },
                        textColor: isDark ? '#d1d5db' : '#374151',
                    },
                    grid: {
                        vertLines: { color: isDark ? '#374151' : '#e5e7eb', style: 1 },
                        horzLines: { color: isDark ? '#374151' : '#e5e7eb', style: 1 },
                    },
                    timeScale: { 
                        timeVisible: true, 
                        secondsVisible: false, 
                        rightOffset: 12 
                    },
                    crosshair: { mode: 0 },
                    width: chartArea.clientWidth,
                    height: chartArea.clientHeight,
                });

                // K线系列
                const candleSeries = chart.addCandlestickSeries({
                    upColor: '#ef4444',
                    downColor: '#22c55e',
                    borderVisible: false,
                    wickUpColor: '#ef4444',
                    wickDownColor: '#22c55e'
                });

                // 成交量系列 (副图效果)
                const volumeSeries = chart.addHistogramSeries({
                    color: '#26a69a',
                    priceFormat: { type: 'volume' },
                    priceScaleId: '', // 作为一个独立的比例尺
                    scaleMargins: {
                        top: 0.8, // 放在底部 20% 区域
                        bottom: 0,
                    },
                });

                // 处理窗口大小改变
                const ro = new ResizeObserver(entries => {
                    if (entries.length === 0 || entries[0].target !== chartArea) return;
                    const newRect = entries[0].contentRect;
                    chart.applyOptions({ width: newRect.width, height: newRect.height });
                });
                ro.observe(chartArea);

                _instances.set(moduleId, {
                    chart,
                    candleSeries,
                    volumeSeries,
                    ro
                });
                
                moduleEl.addEventListener('module-action-result', (e) => {
                    const detail = e.detail;
                    if (!detail || !detail.result) return;
                    
                    const res = detail.result;
                    const inst = _instances.get(moduleId);
                    if (!inst || inst.pending) return; 
                    
                    if (res.error) {
                        const statusEl = moduleEl.querySelector('.kline-status');
                        if (statusEl) statusEl.textContent = '加载失败: ' + res.error;
                        return;
                    }

                    if (res.candles && Array.isArray(res.candles)) {
                        const candleData = [];
                        const volumeData = [];
                        
                        res.candles.forEach(item => {
                            candleData.push({
                                time: item.time,
                                open: item.open,
                                high: item.high,
                                low: item.low,
                                close: item.close
                            });
                            
                            volumeData.push({
                                time: item.time,
                                value: item.volume,
                                color: item.close > item.open ? 'rgba(239, 68, 68, 0.5)' : 'rgba(34, 197, 94, 0.5)'
                            });
                        });
                        
                        inst.candleSeries.setData(candleData);
                        inst.volumeSeries.setData(volumeData);
                        inst.chart.timeScale().fitContent();
                        
                        const statusEl = moduleEl.querySelector('.kline-status');
                        if (statusEl) {
                            if (res.mock) {
                                statusEl.innerHTML = `<span style="color:red" title="${res.error_msg}">API失败，已使用模拟数据</span>`;
                            } else {
                                statusEl.textContent = '已更新: ' + new Date().toLocaleTimeString();
                            }
                        }
                        
                        const btns = moduleEl.querySelectorAll('.btn-period');
                        btns.forEach(b => b.style.background = 'transparent');
                        if (res.period) {
                            const activeBtn = moduleEl.querySelector(`.btn-period[data-payload*="${res.period}"]`);
                            if (activeBtn) activeBtn.style.background = 'var(--color-primary-light)';
                        }
                    }
                });

                // 图表引擎初始化完毕，主动触发第一次数据请求
                setTimeout(() => {
                    // 默认请求 5m 数据
                    let btn = moduleEl.querySelector('.btn-period[data-payload*="5m"]');
                    if (!btn) {
                        btn = moduleEl.querySelector('.btn-period');
                    }
                    if (btn) btn.click();
                }, 100);

            });
        } catch (e) {
            console.error('[KlineEngine] 初始化失败', e);
        }
    }


    // 监听页面变化，自动为新添加的模块初始化图表
    function scheduleScan() {
        if (!document.body) return;
        const container = document.body;
        
        // 查找所有 K线模块
        const cards = container.querySelectorAll('.module-card[data-module-type="sys_kline"]');
        cards.forEach(card => {
            if (!_instances.has(card.dataset.moduleId)) {
                if (card.querySelector('.kline-chart-area')) {
                    initKlineChart(card);
                }
            }
        });

        // 清理已删除的模块
        for (const [id, inst] of _instances.entries()) {
            if (!document.getElementById('module-' + id)) {
                if (inst.ro) inst.ro.disconnect();
                if (inst.chart) inst.chart.remove();
                _instances.delete(id);
            }
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        const observer = new MutationObserver(() => scheduleScan());
        observer.observe(document.body, { childList: true, subtree: true });
        scheduleScan();
    });
    
    // 如果由于按需加载 js，这里立即执行一次
    setTimeout(scheduleScan, 100);

})();
