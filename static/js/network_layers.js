// ===== Network Layer Construction =====

function getSegmentColor(props) {
    if (excludedIds.has(props.edge_id)) return COLORS.excluded;
    if (props.required === false) return '#aaaaaa';
    if (props.covered) return COLORS.covered;
    return COLORS.uncovered;
}

function getReviewColor(props) {
    if (excludedIds.has(props.edge_id)) return COLORS.excluded;
    if (props.review_flag && props.review_flag.length > 0) return COLORS.flagged;
    return '#dddddd';
}

// Coverage view layer
L.geoJSON(MAP_DATA.network, {
    style: function(feature) {
        const p = feature.properties;
        if (excludedIds.has(p.edge_id)) {
            return { color: '#888888', weight: 3, opacity: 0.6, dashArray: '6 4' };
        }
        return {
            color: getSegmentColor(p),
            weight: p.required === false ? 1 : (p.covered ? 2 : 3),
            opacity: p.covered ? 0.6 : 0.8,
            dashArray: null
        };
    },
    onEachFeature: function(feature, layer) {
        const p = feature.properties;
        segmentLayers[p.edge_id] = layer;
        layer.bindTooltip(buildTooltip(p), { sticky: true });
        layer.on('click', function() {
            if (!reviewMode) toggleExclude(p.edge_id);
        });
    }
}).addTo(coverageGroup);

// Wide hit area for coverage
L.geoJSON(MAP_DATA.network, {
    style: { weight: 20, opacity: 0 },
    onEachFeature: function(feature, layer) {
        layer.on('click', function() {
            if (!reviewMode) toggleExclude(feature.properties.edge_id);
        });
    }
}).addTo(coverageGroup);

// Review view: background context
L.geoJSON(MAP_DATA.network, {
    style: function(feature) {
        const p = feature.properties;
        if (excludedIds.has(p.edge_id)) {
            return { color: COLORS.excluded, weight: 1, opacity: 0.3, dashArray: '4 4' };
        }
        if (p.required === false) return { color: '#cccccc', weight: 1, opacity: 0.2 };
        if (p.covered) return { color: COLORS.covered, weight: 2, opacity: 0.3 };
        return { color: COLORS.uncovered, weight: 2, opacity: 0.3 };
    }
}).addTo(reviewGroup);

// Review view: flagged segments on top
L.geoJSON(MAP_DATA.network, {
    style: function(feature) {
        const p = feature.properties;
        if (p.review_flag && p.review_flag.length > 0 && !excludedIds.has(p.edge_id)) {
            return { color: COLORS.flagged, weight: 4, opacity: 0.9 };
        }
        return { weight: 0, opacity: 0 };
    },
    onEachFeature: function(feature, layer) {
        const p = feature.properties;
        layer.bindTooltip(buildTooltip(p), { sticky: true });
        layer.on('click', function() {
            if (!reviewMode) toggleExclude(p.edge_id);
        });
    }
}).addTo(reviewGroup);

// Review view: wide hit area
L.geoJSON(MAP_DATA.network, {
    style: { weight: 20, opacity: 0 },
    onEachFeature: function(feature, layer) {
        layer.on('click', function() {
            if (!reviewMode) toggleExclude(feature.properties.edge_id);
        });
    }
}).addTo(reviewGroup);

// Routes view: planned routes
const routeLayers = {};

if (MAP_DATA.routes && MAP_DATA.routes.features && MAP_DATA.routes.features.length > 0) {
    MAP_DATA.routes.features.forEach(function(feature) {
        const p = feature.properties;
        const color = p.color || '#ff0000';

        const routeLayer = L.geoJSON(feature, {
            style: { color: color, weight: 4, opacity: 0.8 }
        });

        routeLayer.bindTooltip(
            `<b>${p.route_name}</b><br>` +
            `Distance: ${p.distance_km} km<br>` +
            `New coverage: ${p.new_coverage_km} km`,
            { sticky: true }
        );

        routeLayer.on('click', function() { selectRoute(p.route_id); });

        routeLayer.addTo(routeGroup);
        routeLayers[p.route_id] = { layer: routeLayer, color: color };
    });

    // Build route table
    const tbody = document.getElementById('route-table-body');
    MAP_DATA.routes.features.forEach(function(feature) {
        const p = feature.properties;
        const tr = document.createElement('tr');
        tr.id = `route-row-${p.route_id}`;
        tr.onclick = function() { selectRoute(p.route_id); };
        tr.innerHTML =
            `<td><span class="route-color-dot" style="background:${p.color}"></span>${p.route_name}</td>` +
            `<td>${p.distance_km} km</td>` +
            `<td>${p.new_coverage_km} km</td>`;
        tbody.appendChild(tr);
    });
}