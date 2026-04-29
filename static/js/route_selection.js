// ===== Route Table Selection and GPX Export =====

function selectRoute(routeId) {
    Object.keys(routeLayers).forEach(rid => {
        routeLayers[rid].layer.setStyle({ weight: 4, opacity: 0.8 });
    });

    document.querySelectorAll('.route-table tr').forEach(tr => tr.classList.remove('selected'));

    selectedRoute = routeId;

    if (routeLayers[routeId]) {
        routeLayers[routeId].layer.setStyle({ weight: 7, opacity: 1.0 });
        routeLayers[routeId].layer.bringToFront();
        routeLayers[routeId].layer.eachLayer(function(l) {
            map.fitBounds(l.getBounds().pad(0.1));
        });
    }

    const row = document.getElementById(`route-row-${routeId}`);
    if (row) row.classList.add('selected');

    const routeFeature = MAP_DATA.routes.features.find(f => f.properties.route_id === routeId);
    if (routeFeature) {
        const p = routeFeature.properties;
        document.getElementById('selected-route-detail').innerHTML =
            `<b>${p.route_name}</b><br>` +
            `Distance: ${p.distance_km} km<br>` +
            `New coverage: ${p.new_coverage_km} km<br>` +
            `Segments: ${p.segments_covered}`;
        document.getElementById('export-section').style.display = 'block';
    }
}

function exportSelectedGpx() {
    if (selectedRoute === null) {
        showStatus('No route selected');
        return;
    }
    window.location.href = `/api/export-gpx/${selectedRoute}`;
    showStatus('GPX downloaded');
}

async function testRouteReview() {
    if (selectedRoute === null) {
        showStatus('Select a route first');
        return;
    }

    showStatus('Finding matching activity for test...');

    try {
        const resp = await fetch('/api/review/find-test-activity', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ route_id: selectedRoute })
        });
        const data = await resp.json();

        if (data.status === 'success' && data.activity_ids && data.activity_ids.length > 0) {
            showStatus(`Found ${data.activity_ids.length} matching activities. Opening review...`);
            await openRouteReview(selectedRoute, data.activity_ids);
        } else {
            showStatus(data.message || 'No matching activities found for this route');
        }
    } catch (e) {
        showStatus('Error: ' + e.message);
    }
}