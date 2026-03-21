/**
 * SpreadScope Dashboard — Funding Rate Monitor
 */

const API_BASE = '';
const REFRESH_INTERVAL = 15000;
let currentChartAsset = 'BTC';
let lwChart = null;
let fundingSeries = null;
let refreshTimer = null;

// ============================================================================
// Utility Functions
// ============================================================================

function formatPrice(price) {
    if (!price || price === 0) return '—';
    return '$' + parseFloat(price).toLocaleString('en-US', {
        minimumFractionDigits: 2, maximumFractionDigits: 2
    });
}

function formatPct(pct, decimals) {
    if (pct === undefined || pct === null) return '—';
    decimals = decimals || 4;
    const sign = pct >= 0 ? '+' : '';
    return sign + parseFloat(pct).toFixed(decimals) + '%';
}

function formatAPY(pct) {
    if (pct === undefined || pct === null) return '—';
    return parseFloat(pct).toFixed(1) + '%';
}

function formatUSD(amount) {
    if (amount === undefined || amount === null) return '—';
    return '$' + parseFloat(amount).toLocaleString('en-US', {
        minimumFractionDigits: 2, maximumFractionDigits: 2
    });
}

function formatAge(seconds) {
    if (!seconds || seconds === 0) return '—';
    if (seconds < 60) return Math.floor(seconds) + 's ago';
    if (seconds < 3600) return Math.floor(seconds / 60) + 'm ago';
    return Math.floor(seconds / 3600) + 'h ago';
}

function formatDuration(hours) {
    if (!hours) return '—';
    if (hours < 1) return Math.floor(hours * 60) + 'm';
    if (hours < 24) return Math.floor(hours) + 'h';
    return Math.floor(hours / 24) + 'd ' + Math.floor(hours % 24) + 'h';
}

function getAPYClass(apy) {
    if (apy > 20) return 'spread-positive';
    if (apy > 10) return 'spread-neutral';
    return 'spread-negative';
}

function getSpreadClass(pct) {
    const abs = Math.abs(pct);
    if (abs > 0.1) return 'spread-negative';
    if (abs > 0.03) return 'spread-neutral';
    return 'spread-positive';
}

function updateStatus(status, text) {
    const dot = document.getElementById('statusDot');
    const statusText = document.getElementById('statusText');
    if (dot) {
        dot.className = 'status-dot';
        if (status === 'connected') dot.classList.add('connected');
        else if (status === 'error') dot.classList.add('error');
    }
    if (statusText) statusText.textContent = text;
}

function updateTimestamp() {
    const el = document.getElementById('lastUpdated');
    if (el) el.textContent = new Date().toLocaleTimeString();
}

// ============================================================================
// API Calls
// ============================================================================

async function fetchJSON(url) {
    try {
        const response = await fetch(url);
        return await response.json();
    } catch (error) {
        console.error('Fetch failed:', url, error);
        return { status: 'error', message: error.message };
    }
}

// ============================================================================
// Rendering
// ============================================================================

function renderFundingTable(rates) {
    const tbody = document.getElementById('fundingTableBody');
    if (!tbody) return;

    if (!rates || rates.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No funding rate data. Waiting for data collection...</td></tr>';
        return;
    }

    tbody.innerHTML = rates.map(r => {
        const apyClass = getAPYClass(r.annualized_rate || 0);
        const fundingPct = r.funding_rate ? (r.funding_rate * 100).toFixed(4) + '%' : '—';
        return `<tr>
            <td><strong>${r.asset || '—'}</strong></td>
            <td>${r.venue || '—'}</td>
            <td>${fundingPct}</td>
            <td class="${apyClass}"><strong>${formatAPY(r.annualized_rate)}</strong></td>
            <td class="price">${formatPrice(r.mark_price)}</td>
            <td>${r.open_interest ? formatPrice(r.open_interest) : '—'}</td>
            <td>${formatAge(r.seconds_ago)}</td>
        </tr>`;
    }).join('');
}

function renderSignalsTable(signals) {
    const tbody = document.getElementById('signalsTableBody');
    if (!tbody) return;

    if (!signals || signals.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No active carry signals. Monitoring funding rates...</td></tr>';
        return;
    }

    tbody.innerHTML = signals.map(s => {
        const typeBadge = s.signal_type === 'entry'
            ? '<span class="badge badge-opportunity">ENTRY</span>'
            : '<span class="badge badge-closed">EXIT</span>';
        const apyClass = getAPYClass(s.expected_apy_pct || 0);
        return `<tr>
            <td>${typeBadge}</td>
            <td><strong>${s.asset || '—'}</strong></td>
            <td>${s.perp_venue || '—'}</td>
            <td class="${apyClass}"><strong>${formatAPY(s.expected_apy_pct)}</strong></td>
            <td>${formatUSD(s.suggested_size_usd)}</td>
            <td>${formatUSD(s.expected_daily_return_usd)}</td>
            <td>${formatUSD(s.estimated_fees_usd)}</td>
            <td>${formatDuration(s.breakeven_hours)}</td>
            <td>${s.created_at ? new Date(s.created_at).toLocaleString() : '—'}</td>
        </tr>`;
    }).join('');
}

function renderSpreadsTable(spreads) {
    const tbody = document.getElementById('spreadsTableBody');
    if (!tbody) return;

    if (!spreads || spreads.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No spread data available.</td></tr>';
        return;
    }

    tbody.innerHTML = spreads.map(s => {
        const venueParts = (s.venue_pair || '').split(':');
        const spreadClass = getSpreadClass(s.spread_pct);
        return `<tr>
            <td><strong>${s.asset || '—'}</strong></td>
            <td>${venueParts[0] || '—'}</td>
            <td>${venueParts[1] || '—'}</td>
            <td class="price">${formatPrice(s.real_price)}</td>
            <td class="price">${formatPrice(s.synthetic_price)}</td>
            <td class="${spreadClass}"><strong>${formatPct(s.spread_pct)}</strong></td>
            <td>${formatAge(s.seconds_ago)}</td>
        </tr>`;
    }).join('');
}

function updateSummaryCards(rates, signals) {
    const capitalEl = document.getElementById('portfolioCapital');
    const activeEl = document.getElementById('activeSignals');
    const btcEl = document.getElementById('bestApyBTC');
    const ethEl = document.getElementById('bestApyETH');

    if (signals && signals.length > 0 && capitalEl) {
        capitalEl.textContent = formatUSD(signals[0].portfolio_capital_usd);
    }

    const entrySignals = (signals || []).filter(s => s.signal_type === 'entry');
    if (activeEl) {
        activeEl.textContent = entrySignals.length;
        activeEl.className = entrySignals.length > 0 ? 'card-value highlight' : 'card-value';
    }

    // Best APY from funding rates
    const btcRates = (rates || []).filter(r => r.asset === 'BTC');
    const ethRates = (rates || []).filter(r => r.asset === 'ETH');

    if (btcEl && btcRates.length > 0) {
        const best = Math.max(...btcRates.map(r => r.annualized_rate || 0));
        btcEl.textContent = formatAPY(best);
        btcEl.className = 'card-value ' + getAPYClass(best);
    }
    if (ethEl && ethRates.length > 0) {
        const best = Math.max(...ethRates.map(r => r.annualized_rate || 0));
        ethEl.textContent = formatAPY(best);
        ethEl.className = 'card-value ' + getAPYClass(best);
    }
}

// ============================================================================
// Lightweight Charts — Funding Rate History
// ============================================================================

function initLiveChart() {
    const container = document.getElementById('liveSpreadChart');
    if (!container) return;

    container.innerHTML = '';

    lwChart = LightweightCharts.createChart(container, {
        layout: {
            background: { type: 'solid', color: '#1c2128' },
            textColor: '#8b949e',
            fontFamily: "'JetBrains Mono', monospace",
        },
        grid: {
            vertLines: { color: '#21262d' },
            horzLines: { color: '#21262d' },
        },
        timeScale: {
            borderColor: '#30363d',
            timeVisible: true,
            secondsVisible: false,
        },
        rightPriceScale: {
            borderColor: '#30363d',
        },
        width: container.clientWidth,
        height: 400,
    });

    fundingSeries = lwChart.addAreaSeries({
        topColor: 'rgba(63, 185, 80, 0.4)',
        bottomColor: 'rgba(63, 185, 80, 0.0)',
        lineColor: '#3fb950',
        lineWidth: 2,
    });

    window.addEventListener('resize', () => {
        lwChart.applyOptions({ width: container.clientWidth });
    });
}

async function refreshChartData() {
    const venue = 'hyperliquid_perps';
    const data = await fetchJSON(
        `${API_BASE}/api/funding/history?asset=${currentChartAsset}&venue=${venue}&hours=72`
    );

    if (data && data.data && data.data.length > 0) {
        const chartData = data.data.map(d => ({
            time: Math.floor(new Date(d.time).getTime() / 1000),
            value: d.annualized_rate
        }));
        chartData.sort((a, b) => a.time - b.time);
        fundingSeries.setData(chartData);
    }
}

function setChartAsset(asset) {
    currentChartAsset = asset;
    document.querySelectorAll('.chart-controls .btn').forEach(b => b.classList.remove('active'));
    const btn = document.getElementById('btn' + asset);
    if (btn) btn.classList.add('active');
    refreshChartData();
}

// ============================================================================
// Dashboard Refresh Loop
// ============================================================================

async function refreshDashboard() {
    try {
        const [fundingData, signalsData, spreadsData] = await Promise.all([
            fetchJSON(API_BASE + '/api/funding/current'),
            fetchJSON(API_BASE + '/api/signals?status=active'),
            fetchJSON(API_BASE + '/api/spreads/current'),
        ]);

        if (fundingData.status === 'no_database' || spreadsData.status === 'no_database') {
            const warn = document.getElementById('dbWarning');
            if (warn) warn.style.display = 'block';
            updateStatus('error', 'No Database');
        } else {
            const warn = document.getElementById('dbWarning');
            if (warn) warn.style.display = 'none';
            updateStatus('connected', 'Connected');
        }

        renderFundingTable(fundingData.rates || []);
        renderSignalsTable(signalsData.signals || []);
        renderSpreadsTable(spreadsData.spreads || []);
        updateSummaryCards(fundingData.rates || [], signalsData.signals || []);

        await refreshChartData();
        updateTimestamp();

    } catch (error) {
        console.error('Dashboard refresh error:', error);
        updateStatus('error', 'Error: ' + error.message);
    }
}

function initDashboard() {
    console.log('Initializing SpreadScope Dashboard...');
    initLiveChart();
    refreshDashboard();
    refreshTimer = setInterval(refreshDashboard, REFRESH_INTERVAL);
}

// ============================================================================
// Pair Detail & Analytics (kept for backwards compat)
// ============================================================================

async function initPairDetail(asset, venuePair) {
    const data = await fetchJSON(
        `${API_BASE}/api/spreads/history?asset=${asset}&pair=${venuePair}&hours=24`
    );
    if (data && data.data && data.data.length > 0) {
        const latest = data.data[0];
        const el1 = document.getElementById('currentSpread');
        const el2 = document.getElementById('realPrice');
        const el3 = document.getElementById('syntheticPrice');
        if (el1) el1.textContent = formatPct(latest.spread_pct);
        if (el2) el2.textContent = formatPrice(latest.real_price);
        if (el3) el3.textContent = formatPrice(latest.synthetic_price);
    }
}

async function initAnalytics() {
    console.log('Initializing Analytics...');

    const [analyticsData, signalsData] = await Promise.all([
        fetchJSON(API_BASE + '/api/analytics'),
        fetchJSON(API_BASE + '/api/signals?status=all&limit=50'),
    ]);

    if (analyticsData.status === 'no_database') {
        updateStatus('error', 'No Database');
        return;
    }

    updateStatus('connected', 'Connected');
    updateTimestamp();

    const data = analyticsData.data || {};

    // Summary cards
    const overview = data.overview || {};
    const perAsset = data.per_asset || [];

    const totalEl = document.getElementById('totalReadings');
    if (totalEl) totalEl.textContent = (overview.total_snapshots || 0).toLocaleString();

    const sinceEl = document.getElementById('dataSince');
    if (sinceEl && overview.earliest) {
        sinceEl.textContent = new Date(overview.earliest).toLocaleDateString();
    }

    const btcStats = perAsset.find(r => r.asset === 'BTC');
    const ethStats = perAsset.find(r => r.asset === 'ETH');

    const btcEl = document.getElementById('avgApyBTC');
    if (btcEl && btcStats) {
        btcEl.textContent = formatAPY(btcStats.avg_apy);
        btcEl.className = 'card-value ' + getAPYClass(btcStats.avg_apy || 0);
    }
    const ethEl = document.getElementById('avgApyETH');
    if (ethEl && ethStats) {
        ethEl.textContent = formatAPY(ethStats.avg_apy);
        ethEl.className = 'card-value ' + getAPYClass(ethStats.avg_apy || 0);
    }

    // Per-asset summary table
    const tbody = document.getElementById('assetSummaryBody');
    if (tbody && perAsset.length > 0) {
        tbody.innerHTML = perAsset.map(r => `<tr>
            <td><strong>${r.asset}</strong></td>
            <td>${r.venue}</td>
            <td>${r.readings}</td>
            <td class="${getAPYClass(r.avg_apy || 0)}"><strong>${formatAPY(r.avg_apy)}</strong></td>
            <td>${formatAPY(r.min_apy)}</td>
            <td>${formatAPY(r.max_apy)}</td>
            <td>${r.avg_oi ? formatPrice(r.avg_oi) : '—'}</td>
        </tr>`).join('');
    } else if (tbody) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No funding rate data collected yet. Check back after the system has been running.</td></tr>';
    }

    // Trend chart — recent funding rates
    const recent = (data.recent || []).reverse();
    if (recent.length > 0) {
        const btcData = recent.filter(r => r.asset === 'BTC');
        const ethData = recent.filter(r => r.asset === 'ETH');

        const ctx = document.getElementById('trendChart');
        if (ctx) {
            new Chart(ctx, {
                type: 'line',
                data: {
                    datasets: [
                        {
                            label: 'BTC APY %',
                            data: btcData.map(r => ({ x: new Date(r.time), y: r.annualized_rate })),
                            borderColor: '#f7931a',
                            backgroundColor: 'rgba(247, 147, 26, 0.1)',
                            borderWidth: 2,
                            pointRadius: 1,
                            fill: true,
                        },
                        {
                            label: 'ETH APY %',
                            data: ethData.map(r => ({ x: new Date(r.time), y: r.annualized_rate })),
                            borderColor: '#627eea',
                            backgroundColor: 'rgba(98, 126, 234, 0.1)',
                            borderWidth: 2,
                            pointRadius: 1,
                            fill: true,
                        }
                    ]
                },
                options: {
                    responsive: true,
                    scales: {
                        x: { type: 'time', time: { unit: 'hour' }, ticks: { color: '#8b949e' }, grid: { color: '#21262d' } },
                        y: { ticks: { color: '#8b949e', callback: v => v.toFixed(1) + '%' }, grid: { color: '#21262d' } }
                    },
                    plugins: {
                        legend: { labels: { color: '#c9d1d9' } },
                        tooltip: { callbacks: { label: ctx => ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(2) + '%' } }
                    }
                }
            });
        }
    }

    // Hourly pattern chart
    const hourly = data.hourly || [];
    if (hourly.length > 0) {
        const hours = Array.from({length: 24}, (_, i) => i);
        const btcHourly = hours.map(h => {
            const match = hourly.find(r => r.hour_utc == h && r.asset === 'BTC');
            return match ? match.avg_apy : 0;
        });
        const ethHourly = hours.map(h => {
            const match = hourly.find(r => r.hour_utc == h && r.asset === 'ETH');
            return match ? match.avg_apy : 0;
        });

        const hCtx = document.getElementById('hourlyChart');
        if (hCtx) {
            new Chart(hCtx, {
                type: 'bar',
                data: {
                    labels: hours.map(h => h + ':00'),
                    datasets: [
                        { label: 'BTC Avg APY', data: btcHourly, backgroundColor: 'rgba(247, 147, 26, 0.6)', borderColor: '#f7931a', borderWidth: 1 },
                        { label: 'ETH Avg APY', data: ethHourly, backgroundColor: 'rgba(98, 126, 234, 0.6)', borderColor: '#627eea', borderWidth: 1 },
                    ]
                },
                options: {
                    responsive: true,
                    scales: {
                        x: { ticks: { color: '#8b949e' }, grid: { color: '#21262d' } },
                        y: { ticks: { color: '#8b949e', callback: v => v.toFixed(1) + '%' }, grid: { color: '#21262d' } }
                    },
                    plugins: { legend: { labels: { color: '#c9d1d9' } } }
                }
            });
        }
    }

    // Signal history table
    const signals = (signalsData && signalsData.signals) || [];
    const sigBody = document.getElementById('signalHistoryBody');
    if (sigBody) {
        if (signals.length === 0) {
            sigBody.innerHTML = '<tr><td colspan="7" class="empty-state">No carry signals generated yet. Signals appear when funding rates exceed the APY threshold.</td></tr>';
        } else {
            sigBody.innerHTML = signals.map(s => {
                const typeBadge = s.signal_type === 'entry'
                    ? '<span class="badge badge-opportunity">ENTRY</span>'
                    : '<span class="badge badge-closed">EXIT</span>';
                const statusClass = s.status === 'active' ? 'spread-positive' : '';
                return `<tr>
                    <td>${typeBadge}</td>
                    <td class="${statusClass}">${s.status}</td>
                    <td><strong>${s.asset || '—'}</strong></td>
                    <td>${s.perp_venue || '—'}</td>
                    <td>${formatAPY(s.expected_apy_pct)}</td>
                    <td>${formatUSD(s.suggested_size_usd)}</td>
                    <td>${s.created_at ? new Date(s.created_at).toLocaleString() : '—'}</td>
                </tr>`;
            }).join('');
        }
    }
}
