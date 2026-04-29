// ===== View Mode Switching =====

function setView(mode) {
    currentView = mode;

    document.querySelectorAll('.view-buttons button').forEach(b => b.classList.remove('active'));
    document.getElementById('view-' + mode).classList.add('active');

    map.removeLayer(coverageGroup);
    map.removeLayer(reviewGroup);
    map.removeLayer(routeGroup);

    if (mode === 'coverage') {
        coverageGroup.addTo(map);
        document.getElementById('route-section').style.display = 'none';
        document.getElementById('btn-review-start').style.display = 'block';
    } else if (mode === 'review') {
        reviewGroup.addTo(map);
        document.getElementById('route-section').style.display = 'none';
        document.getElementById('btn-review-start').style.display = 'block';
    } else if (mode === 'routes') {
        routeGroup.addTo(map);
        document.getElementById('route-section').style.display = 'block';
        document.getElementById('btn-review-start').style.display = 'none';
    }

    buildSummary();
}

// Initialize default view
coverageGroup.addTo(map);
updateExcludeCount();
buildSummary();