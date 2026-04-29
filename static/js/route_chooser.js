// ===== Route Chooser Dialog =====

async function openRouteReviewChooser(activityIds) {
    const resp = await fetch('/api/review/suggest-routes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ activity_ids: activityIds })
    });
    const data = await resp.json();

    if (!data.matches || data.matches.length === 0) {
        showStatus("No likely planned route matches found.");
        setTimeout(() => window.location.reload(), 1500);
        return;
    }

    routeChoiceMatches = data.matches;
    routeChoiceActivityIds = activityIds;
    routeChoiceSelectedIdx = null;

    const listEl = document.getElementById('route-chooser-list');
    listEl.innerHTML = '';

    data.matches.forEach((m, i) => {
        const item = document.createElement('div');
        item.className = 'route-choice-item';
        item.onclick = function() { selectRouteChoice(i); };

        if (i === 0) {
            item.classList.add('selected');
            routeChoiceSelectedIdx = 0;
        }

        let overlapColor;
        if (m.overlap_pct >= 70) overlapColor = '#2e7d32';
        else if (m.overlap_pct >= 40) overlapColor = '#f57f17';
        else overlapColor = '#c62828';

        item.innerHTML = `
            <div class="route-choice-radio"></div>
            <div class="route-choice-info">
                <div class="route-choice-name">${m.route_name}</div>
                <div class="route-choice-details">${m.distance_km} km · ${m.new_coverage_km} km new coverage</div>
            </div>
            <div class="route-choice-overlap" style="color:${overlapColor}">${m.overlap_pct}%</div>
        `;

        listEl.appendChild(item);
    });

    document.getElementById('route-chooser-panel').style.display = 'block';
}

function selectRouteChoice(idx) {
    routeChoiceSelectedIdx = idx;

    const items = document.querySelectorAll('.route-choice-item');
    items.forEach((item, i) => { item.classList.toggle('selected', i === idx); });

    // Highlight on map
    const match = routeChoiceMatches[idx];
    if (match && routeLayers[match.route_id]) {
        Object.keys(routeLayers).forEach(rid => {
            routeLayers[rid].layer.setStyle({ weight: 4, opacity: 0.5 });
        });
        routeLayers[match.route_id].layer.setStyle({ weight: 7, opacity: 1.0 });
        routeLayers[match.route_id].layer.bringToFront();
        routeLayers[match.route_id].layer.eachLayer(function(l) {
            map.fitBounds(l.getBounds().pad(0.2));
        });
    }
}

async function confirmRouteChoice() {
    if (routeChoiceSelectedIdx === null) {
        showStatus('Please select a route');
        return;
    }

    const selected = routeChoiceMatches[routeChoiceSelectedIdx];
    document.getElementById('route-chooser-panel').style.display = 'none';

    await openRouteReview(selected.route_id, routeChoiceActivityIds);
}

function cancelRouteChoice() {
    document.getElementById('route-chooser-panel').style.display = 'none';
    routeChoiceMatches = [];
    routeChoiceActivityIds = [];
    routeChoiceSelectedIdx = null;
    setTimeout(() => window.location.reload(), 500);
}