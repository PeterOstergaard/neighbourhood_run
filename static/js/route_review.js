// ===== Post-Run Route Review =====

async function openRouteReview(routeId, activityIds) {
    const resp = await fetch(`/api/review/route/${routeId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ activity_ids: activityIds })
    });
    const result = await resp.json();

    if (result.status !== 'success') {
        showStatus(result.message || 'Failed to open route review');
        return;
    }

    const data = result.data;
    selectedReviewRouteId = routeId;
    selectedReviewActivityIds = activityIds;
    selectedReviewEdgeId = null;

    // Clean up previous review layers
    if (routeReviewLayer) map.removeLayer(routeReviewLayer);
    if (recentTrackLayer) map.removeLayer(recentTrackLayer);
    Object.values(routeSegmentReviewLayers).forEach(l => map.removeLayer(l));
    routeSegmentReviewLayers = {};

    setView('routes');

    // Add GPS track layer (black)
    recentTrackLayer = L.geoJSON(data.recent_tracks, {
        style: { color: '#000000', weight: 4, opacity: 0.7 }
    }).addTo(map);

    // Add planned route layer (cyan) - non-interactive so clicks pass through to segments
    routeReviewLayer = L.geoJSON(data.route, {
        style: { color: '#00aaaa', weight: 5, opacity: 0.4 },
        interactive: false
    }).addTo(map);

    // Add clickable route segments (orange) - on top of route layer
    data.route_segments.features.forEach(feature => {
        const p = feature.properties;
        const layer = L.geoJSON(feature, {
            style: { color: '#ff8800', weight: 6, opacity: 0.7 },
            interactive: true
        }).addTo(map);

        layer.bindTooltip(buildTooltip(p), { sticky: true });
        layer.on('click', function() {
            selectRouteReviewSegment(p.edge_id, feature);
        });

        routeSegmentReviewLayers[p.edge_id] = layer;
    });

    // Bring segment layers to front so they're clickable
    Object.values(routeSegmentReviewLayers).forEach(layer => {
        layer.bringToFront();
    });

    // Zoom to route
    routeReviewLayer.eachLayer(function(l) {
        map.fitBounds(l.getBounds().pad(0.2));
    });

    // Zoom to route
    routeReviewLayer.eachLayer(function(l) {
        map.fitBounds(l.getBounds().pad(0.2));
    });

    // Show review panel
    document.getElementById('route-review-title').textContent = `Review: ${data.route_name}`;
    document.getElementById('route-review-subtitle').textContent =
        'Click a segment on the planned route to review it. Black line = your recorded GPS track.';
    document.getElementById('route-review-panel').style.display = 'block';
    document.getElementById('route-review-buttons').style.display = 'none';
}

function selectRouteReviewSegment(edgeId, feature) {
    selectedReviewEdgeId = edgeId;

    // Reset all segment styles
    Object.entries(routeSegmentReviewLayers).forEach(([eid, layer]) => {
        layer.setStyle({ color: '#ff8800', weight: 6, opacity: 0.7 });
    });

    // Highlight selected segment
    const layer = routeSegmentReviewLayers[edgeId];
    if (layer) {
        layer.setStyle({ color: '#ff00ff', weight: 8, opacity: 1.0 });
        layer.bringToFront();
        layer.eachLayer(function(l) {
            if (l.getBounds) map.fitBounds(l.getBounds().pad(0.5));
        });
    }

    // Show segment info
    const segmentName = feature.properties.name || 'Unnamed';
    const segmentType = feature.properties.highway || 'unknown';
    const segmentLength = feature.properties.length_m ?
        feature.properties.length_m.toFixed(1) + 'm' : '?';

    document.getElementById('route-review-title').textContent = `Segment: ${segmentName}`;
    document.getElementById('route-review-subtitle').innerHTML =
        `Type: ${segmentType} | Length: ${segmentLength} | ID: ${edgeId}<br>` +
        'Choose the runnability status for this segment:';
    document.getElementById('route-review-buttons').style.display = 'block';
}

async function setSegmentReview(status) {
    if (selectedReviewEdgeId === null) {
        showStatus("No segment selected");
        return;
    }

    const edgeId = selectedReviewEdgeId;

    const resp = await fetch(`/api/review/segment/${edgeId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status })
    });
    const data = await resp.json();

    if (data.status === 'success') {
        // Visual feedback based on status
        const layer = routeSegmentReviewLayers[edgeId];
        if (layer) {
            let color;
            if (status === 'not_runnable') color = '#cc0000';
            else if (status === 'sidewalk_present') color = '#00aa00';
            else if (status === 'runnable_no_sidewalk') color = '#00aa00';
            else color = '#999999';
            layer.setStyle({ color: color, weight: 6, opacity: 0.9 });
        }

        showStatus(`Segment ${edgeId}: ${status}`);

        // Clear selection for next segment
        selectedReviewEdgeId = null;
        document.getElementById('route-review-title').textContent = 'Click next segment to review';
        document.getElementById('route-review-subtitle').textContent =
            'Green = runnable, Red = not runnable, Grey = unsure';
        document.getElementById('route-review-buttons').style.display = 'none';
    } else {
        showStatus(data.message || 'Failed to save review');
    }
}

async function finishRouteReview() {
    if (selectedReviewRouteId === null) {
        document.getElementById('route-review-panel').style.display = 'none';
        return;
    }

    await fetch('/api/review/complete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            route_id: selectedReviewRouteId,
            activity_ids: selectedReviewActivityIds
        })
    });

    showStatus("Route review saved. Reloading...");
    document.getElementById('route-review-panel').style.display = 'none';
    setTimeout(() => window.location.reload(), 1200);
}