// ===== UI Helper Functions =====

function showStatus(msg) {
    const el = document.getElementById('status-bar');
    el.textContent = msg;
    el.style.display = 'block';
    setTimeout(() => { el.style.display = 'none'; }, 3000);
}

function updateExcludeCount() {
    document.getElementById('exclude-count').textContent =
        `Excluded: ${excludedIds.size} segments`;
}

function buildSummary() {
    let coveredKm = 0, uncoveredKm = 0, optionalKm = 0, flaggedCount = 0;
    for (const f of MAP_DATA.network.features) {
        const p = f.properties;
        if (excludedIds.has(p.edge_id)) continue;
        const km = p.length_m / 1000;
        if (p.required === false) { optionalKm += km; continue; }
        if (p.covered) coveredKm += km;
        else uncoveredKm += km;
        if (p.review_flag && p.review_flag.length > 0) flaggedCount++;
    }
    const totalKm = coveredKm + uncoveredKm;
    const pct = totalKm > 0 ? (coveredKm / totalKm * 100) : 0;

    let html = `<b>Coverage</b><br>`;
    html += `<span style="color:${COLORS.covered}">■</span> Covered: ${coveredKm.toFixed(1)} km (${pct.toFixed(1)}%)<br>`;
    html += `<span style="color:${COLORS.uncovered}">■</span> Uncovered: ${uncoveredKm.toFixed(1)} km<br>`;
    html += `<span style="color:#aaa">■</span> Optional: ${optionalKm.toFixed(1)} km<br>`;
    html += `<span style="color:${COLORS.flagged}">■</span> Flagged: ${flaggedCount}<br>`;
    html += `<span style="color:${COLORS.excluded}">■</span> Excluded: ${excludedIds.size}`;

    if (MAP_DATA.routes && MAP_DATA.routes.features) {
        const totalRoutes = MAP_DATA.routes.features.length;
        const totalRouteDist = MAP_DATA.routes.features.reduce((s, f) => s + f.properties.distance_km, 0);
        html += `<br><br><b>Routes:</b> ${totalRoutes} (${totalRouteDist.toFixed(1)} km total)`;
    }

    document.getElementById('summary').innerHTML = html;
}

function buildTooltip(props) {
    let html = '';
    if (props.name) html += `<b>${props.name}</b><br>`;
    html += `Type: ${props.highway}<br>`;
    html += `Length: ${props.length_m.toFixed(1)}m<br>`;
    if (props.coverage_pct !== undefined && props.coverage_pct !== null) {
        html += `Coverage: ${props.coverage_pct.toFixed(1)}%<br>`;
    }
    if (props.review_flag) html += `⚑ ${props.review_flag}<br>`;
    if (props.required === false) html += `<i style="color:#aaa">Optional (connector)</i><br>`;
    if (props.reachable === false) html += `<b style="color:red">Unreachable island</b><br>`;
    if (excludedIds.has(props.edge_id)) html += `<b style="color:${COLORS.excluded}">EXCLUDED</b><br>`;
    html += `<i style="color:#999">ID: ${props.edge_id}</i>`;
    return html;
}