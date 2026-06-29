'use strict';

const SSID_COLORS = {
  'grainger': { border: '#1565c0', bg: 'rgba(21,101,192,0.15)' },
  'wwg-net':  { border: '#880e4f', bg: 'rgba(136,14,79,0.15)' },
};

function ssidClass(ssid) {
  return 'ssid-' + ssid.replace(/[^a-z0-9]/g, '-');
}

let trendChart = null;

async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status} ${url}`);
  return r.json();
}

function formatTs(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString();
}

// ── Data freshness ───────────────────────────────────────────────────────────
// Polls happen every 15 min, so anything under 20 min is healthy. Pure function
// (takes an age in ms, returns a CSS class + label) so the thresholds are easy
// to reason about and test in isolation.
function freshnessFromAge(ageMs) {
  const MIN = 60 * 1000;
  if (ageMs < 20 * MIN) return { cls: 'dot-fresh', label: 'Fresh — under 20 min old' };
  if (ageMs < 60 * MIN) return { cls: 'dot-aging', label: 'Aging — under 1 hour old' };
  return { cls: 'dot-stale', label: 'Stale — over 1 hour old' };
}

// Render a colored dot for a polled-at timestamp, or nothing if unknown.
function freshnessDot(iso) {
  if (!iso) return '';
  const f = freshnessFromAge(Date.now() - new Date(iso).getTime());
  return `<span class="dot ${f.cls}" title="${f.label}"></span>`;
}

function getSelectedSite() {
  return document.getElementById('site-filter').value;
}

function getDays() {
  return parseInt(document.getElementById('days-select').value, 10);
}

// ── Summary cards ────────────────────────────────────────────────────────────

async function loadCards() {
  const container = document.getElementById('cards');
  try {
    const latest = await fetchJSON('/api/counts/latest');
    const siteFilter = getSelectedSite();

    const bySite = {};
    for (const row of latest) {
      if (siteFilter && row.site_id !== siteFilter) continue;
      if (!bySite[row.site_id]) bySite[row.site_id] = { name: row.site_name, ssids: [] };
      bySite[row.site_id].ssids.push(row);
    }

    if (Object.keys(bySite).length === 0) {
      container.innerHTML = '<p class="empty">No data yet — waiting for first poll.</p>';
      return;
    }

    container.innerHTML = '';
    for (const [siteId, info] of Object.entries(bySite)) {
      const card = document.createElement('div');
      card.className = 'card';

      const rows = info.ssids.map(r => `
        <div class="ssid-row">
          <span class="ssid-name ${ssidClass(r.ssid)}">${r.ssid}</span>
          <span class="ssid-count">${r.client_count.toLocaleString()}</span>
        </div>`).join('');

      const polledAt = info.ssids[0]?.polled_at ?? '';
      card.innerHTML = `
        <h3>${info.name}</h3>
        ${rows}
        <div class="card-footer">${freshnessDot(polledAt)}Polled ${formatTs(polledAt)}</div>`;
      container.appendChild(card);
    }

    // Update header timestamp
    const times = latest.map(r => r.polled_at).filter(Boolean).sort();
    const newest = times[times.length - 1];
    document.getElementById('last-updated').textContent =
      newest ? `Last updated ${formatTs(newest)}` : '';

  } catch (err) {
    container.innerHTML = `<p class="empty">Error loading data: ${err.message}</p>`;
  }
}

// ── Trend chart ──────────────────────────────────────────────────────────────

async function loadChart() {
  const days = getDays();
  const siteFilter = getSelectedSite();
  const params = new URLSearchParams({ days });
  if (siteFilter) params.set('site_id', siteFilter);

  try {
    const daily = await fetchJSON(`/api/counts/daily?${params}`);
    buildChart(daily);
  } catch (err) {
    console.error('Chart load error:', err);
  }
}

function buildChart(daily) {
  // Collect all unique dates and series keys
  const dates = [...new Set(daily.map(r => r.date))].sort();

  // Group by "site_id|ssid"
  const seriesMap = {};
  for (const r of daily) {
    const key = `${r.site_name} · ${r.ssid}`;
    if (!seriesMap[key]) seriesMap[key] = { ssid: r.ssid, data: {} };
    seriesMap[key].data[r.date] = r.max_count;
  }

  const palette = [
    '#1565c0','#880e4f','#2e7d32','#e65100','#4a148c',
    '#00838f','#827717','#6a1b9a','#c62828','#00695c',
  ];
  let colorIdx = 0;

  const datasets = Object.entries(seriesMap).map(([label, info]) => {
    const color = SSID_COLORS[info.ssid]?.border ?? palette[colorIdx++ % palette.length];
    const bg    = SSID_COLORS[info.ssid]?.bg    ?? color + '26';
    return {
      label,
      data: dates.map(d => info.data[d] ?? null),
      borderColor: color,
      backgroundColor: bg,
      tension: 0.3,
      fill: false,
      spanGaps: true,
      pointRadius: dates.length <= 14 ? 4 : 2,
    };
  });

  const ctx = document.getElementById('trend-chart').getContext('2d');

  if (trendChart) trendChart.destroy();
  trendChart = new Chart(ctx, {
    type: 'line',
    data: { labels: dates, datasets },
    options: {
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { position: 'bottom' },
        tooltip: {
          callbacks: {
            label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y ?? '—'} clients`,
          },
        },
      },
      scales: {
        x: { title: { display: true, text: 'Date' } },
        y: { title: { display: true, text: 'Peak client count' }, beginAtZero: true },
      },
    },
  });
}

// ── Site filter population ───────────────────────────────────────────────────

async function populateSiteFilter() {
  try {
    const sites = await fetchJSON('/api/sites');
    const sel = document.getElementById('site-filter');
    for (const s of sites) {
      const opt = document.createElement('option');
      opt.value = s.id;
      opt.textContent = s.name;
      sel.appendChild(opt);
    }
  } catch (_) { /* ignore */ }
}

// ── Init & refresh ───────────────────────────────────────────────────────────

async function refresh() {
  await Promise.all([loadCards(), loadChart()]);
}

document.getElementById('site-filter').addEventListener('change', refresh);
document.getElementById('days-select').addEventListener('change', loadChart);

populateSiteFilter().then(refresh);

// Auto-refresh every 5 minutes
setInterval(refresh, 5 * 60 * 1000);
