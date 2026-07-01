'use strict';

const SSID_COLORS = {
  'grainger': { border: '#2563eb', bg: 'rgba(37,99,235,0.12)' },
  'wwg-net':  { border: '#db2777', bg: 'rgba(219,39,119,0.12)' },
};

// Fallback colors for SSIDs not in SSID_COLORS, so the UI stays correct for any
// configured SSID list rather than just the default pair.
const SSID_PALETTE = ['#2563eb', '#db2777', '#2e7d32', '#e65100', '#4a148c', '#00838f', '#827717'];
function ssidColor(ssid, idx) {
  return SSID_COLORS[ssid]?.border ?? SSID_PALETTE[idx % SSID_PALETTE.length];
}

function ssidClass(ssid) {
  return 'ssid-' + ssid.replace(/[^a-z0-9]/g, '-');
}

const HARDWARE_TAGS = {
  mist: 'Mist',
  cisco9800: 'Cisco 9800',
  cisco9800cli: 'Cisco 9800 (CLI)',
  cisco5500: 'Cisco 5500 (AireOS)',
  cisco5505: 'Cisco 5505',
};

async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status} ${url}`);
  return r.json();
}

function formatTs(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString();
}

// Just the time (e.g. "9:11:42 PM") for the per-row status column, since the
// site table only ever shows today's most recent poll.
function formatTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' });
}

// ── Data freshness ───────────────────────────────────────────────────────────
// Polls happen every 15 min. Pure function (takes an age in ms, returns a CSS
// class + label) so the thresholds are easy to reason about and test in isolation.
function freshnessFromAge(ageMs) {
  const MIN = 60 * 1000;
  if (ageMs < 15 * MIN) return { cls: 'dot-fresh', label: 'Fresh — under 15 min old' };
  if (ageMs < 120 * MIN) return { cls: 'dot-aging', label: 'Aging — under 2 hours old' };
  return { cls: 'dot-stale', label: 'Stale — over 2 hours old' };
}

function getSelectedSite() {
  return document.getElementById('site-filter').value;
}

function getDays() {
  return parseInt(document.getElementById('days-select').value, 10);
}

function renderLegend(container, ssids) {
  container.innerHTML = ssids.map((s, i) => `
    <span class="legend-item">
      <span class="legend-dot" style="background:${ssidColor(s, i)}"></span>${s}
    </span>`).join('');
}

// ── Site table ────────────────────────────────────────────────────────────────

async function loadSiteTable() {
  const wrap = document.getElementById('site-table-wrap');
  try {
    // Drive rows off the full site list so configured-but-unreported sites
    // (placeholders, or sites awaiting their first poll) still show a row.
    const [latest, sites] = await Promise.all([
      fetchJSON('/api/counts/latest'),
      fetchJSON('/api/sites'),
    ]);
    const siteFilter = getSelectedSite();

    const bySite = {};
    for (const row of latest) {
      if (!bySite[row.site_id]) bySite[row.site_id] = [];
      bySite[row.site_id].push(row);
    }

    const ssids = [...new Set(latest.map(r => r.ssid))].sort();
    renderLegend(document.getElementById('header-legend'), ssids.length ? ssids : ['grainger', 'wwg-net']);

    const nonPlaceholderSites = sites.filter(s => s.platform !== 'placeholder');
    const reportingCount = nonPlaceholderSites.filter(s => bySite[s.id]?.length).length;
    document.getElementById('site-summary').textContent =
      `${reportingCount} of ${nonPlaceholderSites.length} sites reporting`;

    const times = latest
      .filter(r => sites.find(s => s.id === r.site_id)?.platform !== 'placeholder')
      .map(r => r.polled_at).filter(Boolean).sort();
    document.getElementById('last-updated').textContent = formatTs(times[times.length - 1]);

    const visibleSites = sites.filter(s => !siteFilter || s.id === siteFilter);
    wrap.innerHTML = buildSiteTable(visibleSites, bySite, ssids);
  } catch (err) {
    wrap.innerHTML = `<p class="empty">Error loading data: ${err.message}</p>`;
  }
}

function buildSiteTable(sites, bySite, ssids) {
  if (sites.length === 0) return '<p class="empty">No sites configured yet.</p>';

  const cols = ssids.length ? ssids : ['grainger', 'wwg-net'];

  let html = '<table class="site-table"><thead><tr><th>Site</th>';
  cols.forEach((ssid, i) => {
    html += `<th class="col-num" style="color:${ssidColor(ssid, i)}">${ssid}</th>`;
  });
  html += '<th class="col-num">Total</th><th>Status</th></tr></thead><tbody>';

  for (const site of sites) {
    const rows = bySite[site.id] || [];
    const isPlaceholder = site.platform === 'placeholder';
    const hasData = rows.length > 0 && !isPlaceholder;

    const bySsid = {};
    for (const r of rows) bySsid[r.ssid] = r.client_count;
    const total = hasData ? Object.values(bySsid).reduce((a, b) => a + b, 0) : null;

    const tag = HARDWARE_TAGS[site.platform];
    const nameCell = `<div class="site-name${hasData ? '' : ' muted'}">${site.name}</div>` +
      (tag && !isPlaceholder ? `<div class="hw-tag">${tag}</div>` : '');

    const numCells = cols.map((ssid, i) => hasData && ssid in bySsid
      ? `<span class="num" style="color:${ssidColor(ssid, i)}">${bySsid[ssid].toLocaleString()}</span>`
      : '<span class="num num-empty">—</span>'
    ).map(c => `<td class="col-num">${c}</td>`).join('');

    const totalCell = hasData
      ? `<span class="num num-total">${total.toLocaleString()}</span>`
      : '<span class="num num-empty">—</span>';

    let statusHtml;
    if (!hasData) {
      const label = isPlaceholder ? 'Placeholder' : 'Not yet reporting';
      statusHtml = `<span class="status-dot dot-muted"></span><span class="status-text muted">${label}</span>`;
    } else {
      const polledAt = rows[0].polled_at;
      const f = freshnessFromAge(Date.now() - new Date(polledAt).getTime());
      statusHtml = `<span class="status-dot ${f.cls}" title="${f.label}"></span><span class="status-text">Polled ${formatTime(polledAt)}</span>`;
    }

    html += `<tr>
      <td>${nameCell}</td>
      ${numCells}
      <td class="col-num">${totalCell}</td>
      <td>${statusHtml}</td>
    </tr>`;
  }

  html += '</tbody></table>';
  return html;
}

// ── Site × date trend table ──────────────────────────────────────────────────

async function loadTable() {
  const wrap = document.getElementById('data-table-wrap');
  const legendEl = document.getElementById('table-legend');
  const days = getDays();
  const siteFilter = getSelectedSite();
  const params = new URLSearchParams({ days });
  if (siteFilter) params.set('site_id', siteFilter);
  try {
    const [sites, daily] = await Promise.all([
      fetchJSON('/api/sites'),
      fetchJSON(`/api/counts/daily?${params}`),
    ]);
    // Drop placeholder sites' stale history before anything downstream, so it
    // can't leak bogus SSIDs into the legend or values into cells.
    const placeholderIds = new Set(
      sites.filter(s => s.platform === 'placeholder').map(s => s.id));
    const liveDaily = daily.filter(r => !placeholderIds.has(r.site_id));

    // SSIDs are derived from the data — never hard-coded — so the view matches
    // whatever the deployment tracks. With no data we show a neutral empty grid.
    const ssids = [...new Set(liveDaily.map(r => r.ssid))].sort();
    legendEl.innerHTML = ssids.length
      ? ssids.map((s, i) => `<span style="color:${ssidColor(s, i)};font-weight:600">${s}</span>`)
          .join(' · ') + ' — peak clients per day'
      : 'Peak clients per day — no data in this window yet';
    const rows = sites.filter(s => !siteFilter || s.id === siteFilter);
    wrap.innerHTML = buildTable(rows, days, liveDaily, ssids);
  } catch (err) {
    wrap.innerHTML = `<p class="empty">Error loading table: ${err.message}</p>`;
  }
}

// Build a site (rows) × date (columns) table of daily peak counts. Each cell
// stacks one value per tracked SSID (color-coded). Empty cells show a dot.
function buildTable(sites, days, daily, ssids) {
  // Use UTC throughout: the backend aggregates by DATE(polled_at) in UTC, so
  // local-time columns would mismatch the data near the UTC day boundary.
  const dates = [];
  const today = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setUTCDate(today.getUTCDate() - i);
    dates.push(d);
  }
  const iso = d => `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`;
  const fmt = d => `${d.getUTCMonth() + 1}/${d.getUTCDate()}`;

  // Index the daily peaks: peaks[site_id][date][ssid] = max_count
  const peaks = {};
  for (const r of daily) {
    ((peaks[r.site_id] ??= {})[r.date] ??= {})[r.ssid] = r.max_count;
  }

  if (sites.length === 0) return '<p class="empty">No sites to show.</p>';

  const cellVal = (v, color) => v == null
    ? '<span class="cell-val cell-empty">·</span>'
    : `<span class="cell-val" style="color:${color}">${v}</span>`;

  let html = '<table class="data-table"><thead><tr><th class="site-col">Site</th>';
  for (const d of dates) html += `<th>${fmt(d)}</th>`;
  html += '</tr></thead><tbody>';
  for (const s of sites) {
    // Placeholder sites render empty even if they have stale historical rows.
    const isPlaceholder = s.platform === 'placeholder';
    html += `<tr><td class="site-col">${s.name}</td>`;
    for (const d of dates) {
      const day = isPlaceholder ? {} : (peaks[s.id]?.[iso(d)] ?? {});
      const inner = ssids.length
        ? ssids.map((ssid, i) => cellVal(day[ssid], ssidColor(ssid, i))).join('')
        : '<span class="cell-val cell-empty">·</span>';
      html += `<td>${inner}</td>`;
    }
    html += '</tr>';
  }
  html += '</tbody></table>';
  return html;
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
  await Promise.all([loadSiteTable(), loadTable()]);
}

document.getElementById('site-filter').addEventListener('change', refresh);
document.getElementById('days-select').addEventListener('change', loadTable);

populateSiteFilter().then(refresh);

// Auto-refresh every 5 minutes
setInterval(refresh, 5 * 60 * 1000);
