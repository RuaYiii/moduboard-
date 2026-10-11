/**
 * simulator-engine.js — 交易模拟器前端引擎
 *
 * 通过事件委托检测模拟器模块的出现，初始化 Lightweight Charts。
 * 使用极轻量的检测方式，不会干扰页面其他功能。
 */

(function () {
    'use strict';

    // ======== 诊断浮窗 ========
    const debugContainer = document.createElement('div');
    debugContainer.style.cssText = 'position:fixed;bottom:10px;right:10px;z-index:99999;display:flex;flex-direction:column;align-items:flex-end;gap:5px;pointer-events:none;';
    
    const toggleBtn = document.createElement('button');
    toggleBtn.textContent = '🐛 引擎日志';
    toggleBtn.style.cssText = 'pointer-events:auto;padding:6px 12px;background:var(--color-surface, #fff);border:1px solid var(--color-border, #ddd);border-radius:6px;cursor:pointer;font-size:12px;box-shadow:0 2px 8px rgba(0,0,0,0.15);color:var(--color-text, #333);font-weight:bold;transition:all 0.2s;';
    
    const debugOverlay = document.createElement('div');
    debugOverlay.style.cssText = 'display:none;pointer-events:auto;background:rgba(15,15,15,0.95);color:#33ff33;padding:16px;font-family:"Consolas", monospace;font-size:14px;line-height:1.4;user-select:text;white-space:pre-wrap;width:600px;max-width:90vw;height:450px;max-height:80vh;overflow-y:auto;border:1px solid #444;box-shadow:0 8px 24px rgba(0,0,0,0.6);border-radius:8px;backdrop-filter:blur(4px);';
    
    toggleBtn.onclick = () => {
        if (debugOverlay.style.display === 'none') {
            debugOverlay.style.display = 'block';
            toggleBtn.style.background = 'var(--color-primary, #1890ff)';
            toggleBtn.style.color = '#fff';
            toggleBtn.style.borderColor = 'transparent';
        } else {
            debugOverlay.style.display = 'none';
            toggleBtn.style.background = 'var(--color-surface, #fff)';
            toggleBtn.style.color = 'var(--color-text, #333)';
            toggleBtn.style.borderColor = 'var(--color-border, #ddd)';
        }
    };
    
    debugContainer.appendChild(toggleBtn);
    debugContainer.appendChild(debugOverlay);

    function mountDebug() {
        if (document.body) document.body.appendChild(debugContainer);
        else document.addEventListener('DOMContentLoaded', () => document.body.appendChild(debugContainer));
    }
    mountDebug();

    function debugLog(msg) {
        debugOverlay.textContent = '[SimEngine] ' + msg + '\n' + debugOverlay.textContent;
        if (debugOverlay.textContent.length > 5000) {
            debugOverlay.textContent = debugOverlay.textContent.substring(0, 5000);
        }
        console.log('[SimEngine]', msg);
    }

    debugLog("v6 loaded");

    // CDN
    let _cdnLoaded = false;
    let _cdnLoading = false;
    const _cdnCallbacks = [];

    function ensureLightweightCharts(cb) {
        debugLog("ensureLightweightCharts called");
        if (typeof LightweightCharts !== 'undefined') {
            debugLog("LightweightCharts is already defined");
            _cdnLoaded = true;
            cb();
            return;
        }
        _cdnCallbacks.push(cb);
        if (_cdnLoading) {
            debugLog("_cdnLoading is already true, waiting...");
            return;
        }
        _cdnLoading = true;

        debugLog("Injecting script tag to document.head...");
        const script = document.createElement('script');
        script.src = '/static/js/lightweight-charts.standalone.production.js';
        script.onload = () => {
            debugLog("script tag ONLOAD fired!");
            _cdnLoaded = true;
            _cdnCallbacks.forEach(fn => fn());
            _cdnCallbacks.length = 0;
        };
        script.onerror = (e) => {
            debugLog("script tag ONERROR fired: " + e);
        };
        document.head.appendChild(script);
        debugLog("Script tag appended to DOM.");
    }

    // 已初始化的模块 ID 集合
    const _instances = new Map();

    function initSimulator(moduleEl) {
        const moduleId = moduleEl.dataset.moduleId;
        if (!moduleId || _instances.has(moduleId)) return;

        // 先标记为"正在初始化"，防止重复触发
        _instances.set(moduleId, { pending: true });

        const chartArea = moduleEl.querySelector('.sim-chart-area');
        if (!chartArea) return;

        try {
            ensureLightweightCharts(() => {
                try {
                    if (_instances.get(moduleId) && !_instances.get(moduleId).pending) return;

                    const isDark = document.documentElement.dataset.theme === 'dark';
                    const chart = LightweightCharts.createChart(chartArea, {
                        layout: {
                            background: { type: 'solid', color: 'transparent' },
                            textColor: isDark ? '#d1d5db' : '#374151',
                        },
                        grid: {
                            vertLines: { color: isDark ? '#374151' : '#e5e7eb', style: 1 },
                            horzLines: { color: isDark ? '#374151' : '#e5e7eb', style: 1 },
                        },
                        timeScale: { timeVisible: true, secondsVisible: false, rightOffset: 12 },
                        crosshair: { mode: 0 },
                        width: chartArea.clientWidth,
                        height: chartArea.clientHeight,
                    });

                    const series = chart.addCandlestickSeries({
                        upColor: '#00b894', downColor: '#ff7675', borderVisible: false,
                        wickUpColor: '#00b894', wickDownColor: '#ff7675',
                    });

                    // 防抖的 resize
                    let resizeTimer = null;
                    const ro = new ResizeObserver(() => {
                        clearTimeout(resizeTimer);
                        resizeTimer = setTimeout(() => {
                            chart.applyOptions({ width: chartArea.clientWidth, height: chartArea.clientHeight });
                        }, 50);
                    });
                    ro.observe(chartArea);

                    const inst = { chart, series, interval: null, ro, pending: false };
                    _instances.set(moduleId, inst);

                    // 监听 action 结果
                    moduleEl.addEventListener('module-action-result', (e) => {
                        handleActionResult(moduleEl, moduleId, e.detail);
                    });

                    // 监听点击事件，给“重开一局”添加立即的 UI 反馈
                    moduleEl.addEventListener('click', (e) => {
                        const restartBtn = e.target.closest('button[data-action="restart"]');
                        if (restartBtn) {
                            const titleEl = moduleEl.querySelector('.sim-title');
                            if (titleEl) titleEl.innerHTML = '<span style="color:#f59e0b;">📥 正在从币安下载数据，请稍候...</span>';
                            const progEl = moduleEl.querySelector('.sim-progress');
                            if (progEl) progEl.textContent = '--';
                        }
                    });

                    console.log('[SimEngine] Initialized for', moduleId);

                    // 触发初始化 action
                    triggerAction(moduleEl, 'init_check');
                } catch (innerErr) {
                    const titleEl = moduleEl.querySelector('.sim-title');
                    if (titleEl) titleEl.innerHTML = `<span style="color:red">Init Error: ${innerErr.message}</span>`;
                    console.error('[SimEngine] Inner Init Error:', innerErr);
                }
            });
        } catch (err) {
            const titleEl = moduleEl.querySelector('.sim-title');
            if (titleEl) titleEl.innerHTML = `<span style="color:red">Outer Init Error: ${err.message}</span>`;
            console.error('[SimEngine] Outer Init Error:', err);
        }
    }

    /**
     * 通过模拟按钮点击触发 action
     */
    function triggerAction(moduleEl, actionName) {
        let btn = moduleEl.querySelector(`.sim-trigger-${actionName}`);
        if (!btn) {
            btn = document.createElement('button');
            btn.className = `sim-trigger-${actionName}`;
            btn.dataset.action = actionName;
            btn.style.display = 'none';
            const body = moduleEl.querySelector('.module-body');
            if (body) body.appendChild(btn);
        }
        btn.click();
    }

    function handleActionResult(moduleEl, moduleId, detail) {
        const res = detail.result;
        const state = res.state || {};
        const inst = _instances.get(moduleId);
        
        const q = (sel) => moduleEl.querySelector(sel);

        // ALWAYS update UI panels
        if (state.download_status === 'downloading') {
            const el = q('.sim-title');
            if (el) el.innerHTML = '<span style="color:#f59e0b;">📥 正在从币安下载数据，请稍候...</span>';
            setTimeout(() => triggerAction(moduleEl, 'init_check'), 1000);
            return;
        } else if (state.download_status === 'failed') {
            const el = q('.sim-title');
            if (el) el.innerHTML = `<span style="color:#ff7675;">❌ 下载失败 (可能需要代理)</span>`;
            return;
        } else if (state.month && state.symbol) {
            const el = q('.sim-title');
            if (el) el.textContent = `${state.symbol} [${state.month}]`;
        }
        const progEl = q('.sim-progress');
        if (progEl && state.tick_index !== undefined) progEl.textContent = state.tick_index;

        if (state.balance !== undefined) {
            const balEl = q('.sim-balance');
            if (balEl) balEl.textContent = '$' + state.balance.toFixed(2);
            const equity = state.balance + (state.pnl || 0);
            const eqEl = q('.sim-equity');
            if (eqEl) eqEl.textContent = '$' + equity.toFixed(2);
        }

        const pnlEl = q('.sim-pnl');
        if (pnlEl && state.pnl !== undefined) {
            pnlEl.textContent = state.pnl > 0 ? '+$' + state.pnl.toFixed(2) : '$' + state.pnl.toFixed(2);
            pnlEl.style.color = state.pnl > 0 ? '#00b894' : (state.pnl < 0 ? '#ff7675' : 'var(--color-text-tertiary)');
        }

        const posEl = q('.sim-position');
        if (posEl) {
            if (state.position === 'LONG') {
                posEl.innerHTML = '<span style="color:#00b894;background:rgba(0,184,148,0.1);padding:2px 6px;border-radius:4px;font-size:11px;">多 ' +
                    parseFloat(state.amount).toFixed(4) + ' @ ' + parseFloat(state.entry_price).toFixed(2) + '</span>';
            } else if (state.position === 'SHORT') {
                posEl.innerHTML = '<span style="color:#ff7675;background:rgba(255,118,117,0.1);padding:2px 6px;border-radius:4px;font-size:11px;">空 ' +
                    parseFloat(state.amount).toFixed(4) + ' @ ' + parseFloat(state.entry_price).toFixed(2) + '</span>';
            } else {
                posEl.textContent = '空仓';
            }
        }

        // ---- 播放/暂停 ----
        const playBtn = q('.sim-play-btn');
        if (playBtn) {
            if (state.is_playing && !res.game_over) {
                playBtn.textContent = '⏸ 暂停播放';
                playBtn.style.background = '#fdcb6e';
                playBtn.style.color = '#2d3436';
                if (inst && !inst.interval) {
                    inst.interval = setInterval(() => triggerAction(moduleEl, 'tick'), 1000);
                }
            } else {
                playBtn.textContent = '▶ 继续播放';
                playBtn.style.background = 'var(--color-primary)';
                playBtn.style.color = '#fff';
                if (inst && inst.interval) { clearInterval(inst.interval); inst.interval = null; }
            }
        }

        // ---- Game Over ----
        const overlay = q('.sim-overlay');
        if (overlay) {
            if (res.game_over) {
                overlay.style.display = 'flex';
                const t = q('.sim-overlay-title');
                if (t) { t.textContent = res.game_over_title || 'GAME OVER'; t.style.color = res.game_over_color || '#ff7675'; }
                const d = q('.sim-overlay-desc');
                if (d) d.textContent = res.game_over_desc || '';
            } else {
                overlay.style.display = 'none';
            }
        }

        // If chart is not ready, we can't update chart data
        if (!inst || inst.pending) return;

        // ---- 图表 ----
        try {
            if (res.initial_candles && res.initial_candles.length) {
                inst.series.setData(res.initial_candles.map(c => ({
                    time: parseInt(c[0]) / 1000,
                    open: parseFloat(c[1]), high: parseFloat(c[2]),
                    low: parseFloat(c[3]), close: parseFloat(c[4]),
                })));
            }
            if (res.new_candle) {
                const c = res.new_candle;
                inst.series.update({
                    time: parseInt(c[0]) / 1000,
                    open: parseFloat(c[1]), high: parseFloat(c[2]),
                    low: parseFloat(c[3]), close: parseFloat(c[4]),
                });
            }
        } catch (e) {
            console.error('[SimEngine] Chart update error:', e);
        }
    }

    // ============================================================
    //  检测方式：只在 #canvas 上监听，且用 requestIdleCallback 防卡
    // ============================================================

    let _scanScheduled = false;

    function scheduleScan() {
        if (_scanScheduled) return;
        _scanScheduled = true;
        requestAnimationFrame(() => {
            _scanScheduled = false;
            const container = document.getElementById('canvas');
            if (!container) {
                debugLog("scheduleScan: #canvas container missing!");
                return;
            }
            const cards = container.querySelectorAll('.module-card[data-module-type="sys_simulator"]');
            if (cards.length > 0) debugLog(`scheduleScan: found ${cards.length} sys_simulator card(s)`);
            cards.forEach(card => {
                if (!_instances.has(card.dataset.moduleId)) {
                    if (card.querySelector('.sim-root')) {
                        debugLog(`Initializing card ID: ${card.dataset.moduleId}`);
                        initSimulator(card);
                    } else {
                        debugLog(`Card ${card.dataset.moduleId} missing .sim-root`);
                    }
                }
            });
        });
    }

    function startObserving() {
        const container = document.getElementById('canvas');
        if (!container) {
            debugLog("startObserving: #canvas NOT FOUND, retrying in 200ms");
            setTimeout(startObserving, 200);
            return;
        }
        debugLog("startObserving: #canvas FOUND, attaching observer");
        const observer = new MutationObserver(() => scheduleScan());
        observer.observe(container, { childList: true, subtree: true });
        scheduleScan();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', startObserving);
    } else {
        startObserving();
    }

})();
