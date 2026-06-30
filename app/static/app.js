'use strict';

const SSID_COLORS = {
  'grainger': { border: '#1565c0', bg: 'rgba(21,101,192,0.15)' },
  'wwg-net':  { border: '#880e4f', bg: 'rgba(136,14,79,0.15)' },
};

// Fallback colors for SSIDs not in SSID_COLORS, so the UI stays correct for any
// configured SSID list rather than just the default pair.
const SSID_PALETTE = ['#1565c0', '#880e4f', '#2e7d32', '#e65100', '#4a148c', '#00838f', '#827717'];
function ssidColor(ssid, idx) {
  return SSID_COLORS[ssid]?.border ?? SSID_PALETTE[idx % SSID_PALETTE.length];
}

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
    // Drive cards off the full site list so configured-but-unreported sites
    // (placeholders, or sites awaiting their first poll) still show a card.
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

    const visibleSites = sites.filter(s => !siteFilter || s.id === siteFilter);
    if (visibleSites.length === 0) {
      container.innerHTML = '<p class="empty">No sites configured yet.</p>';
      return;
    }

    container.innerHTML = '';
    for (const site of visibleSites) {
      const rows = bySite[site.id] || [];
      // A placeholder always shows as pending, even if it has stale historical
      // rows from before it was converted.
      const isPlaceholder = site.platform === 'placeholder';
      const card = document.createElement('div');

      if (rows.length && !isPlaceholder) {
        card.className = 'card';
        const ssidRows = rows.map(r => `
          <div class="ssid-row">
            <span class="ssid-name ${ssidClass(r.ssid)}">${r.ssid}</span>
            <span class="ssid-count">${r.client_count.toLocaleString()}</span>
          </div>`).join('');
        const polledAt = rows[0]?.polled_at ?? '';
        card.innerHTML = `
          <h3>${site.name}</h3>
          ${ssidRows}
          <div class="card-footer">${freshnessDot(polledAt)}Polled ${formatTs(polledAt)}</div>`;
      } else {
        // No poll data: placeholder, or a real site that hasn't reported yet.
        card.className = 'card card-pending';
        const label = isPlaceholder ? 'Placeholder' : 'No data yet';
        card.innerHTML = `
          <h3>${site.name}</h3>
          <div class="pending-body">${label}</div>
          <div class="card-footer">Not yet reporting</div>`;
      }
      container.appendChild(card);
    }

    // Update header timestamp (ignore placeholder sites' stale historical rows)
    const placeholderIds = new Set(
      sites.filter(s => s.platform === 'placeholder').map(s => s.id));
    const times = latest
      .filter(r => !placeholderIds.has(r.site_id))
      .map(r => r.polled_at).filter(Boolean).sort();
    const newest = times[times.length - 1];
    document.getElementById('last-updated').textContent =
      newest ? `Last updated ${formatTs(newest)}` : '';

  } catch (err) {
    container.innerHTML = `<p class="empty">Error loading data: ${err.message}</p>`;
  }
}

// ── Site × date table ────────────────────────────────────────────────────────

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
          .join(' · ') + ' peak clients per day'
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
  await Promise.all([loadCards(), loadTable()]);
}

document.getElementById('site-filter').addEventListener('change', refresh);
document.getElementById('days-select').addEventListener('change', loadTable);

populateSiteFilter().then(refresh);

// Auto-refresh every 5 minutes
setInterval(refresh, 5 * 60 * 1000);
