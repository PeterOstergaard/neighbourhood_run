// ===== Flagged Segment Review Mode =====

function startReview() {
    reviewList = MAP_DATA.network.features.filter(f => {
        const rf = f.properties.review_flag;
        return rf && rf.length > 0
            && !excludedIds.has(f.properties.edge_id)
            && !f.properties.covered;
    });

    if (reviewList.length === 0) {
        showStatus('No flagged segments to review');
        return;
    }

    reviewMode = true;
    reviewIndex = 0;
    setView('review');
    document.getElementById('review-panel').style.display = 'block';
    showReviewItem();
}

function showReviewItem() {
    if (reviewIndex >= reviewList.length) {
        endReview();
        return;
    }

    if (reviewHighlightLayer) {
        map.removeLayer(reviewHighlightLayer);
        reviewHighlightLayer = null;
    }

    const f = reviewList[reviewIndex];
    const p = f.properties;

    reviewHighlightLayer = L.geoJSON(f, {
        style: { color: '#ff00ff', weight: 8, opacity: 1.0 }
    }).addTo(map);

    reviewHighlightLayer.eachLayer(function(l) {
        map.fitBounds(l.getBounds().pad(0.5));
    });

    document.getElementById('review-info').innerHTML =
        `<b>${reviewIndex + 1} / ${reviewList.length}</b><br>` +
        `${p.name || 'Unnamed'} (${p.highway})<br>` +
        `⚑ ${p.review_flag}`;
}

async function reviewAction(action) {
    if (reviewHighlightLayer) {
        map.removeLayer(reviewHighlightLayer);
        reviewHighlightLayer = null;
    }

    const p = reviewList[reviewIndex].properties;
    if (action === 'exclude') await toggleExclude(p.edge_id);
    reviewIndex++;
    showReviewItem();
}

function endReview() {
    reviewMode = false;
    document.getElementById('review-panel').style.display = 'none';

    if (reviewHighlightLayer) {
        map.removeLayer(reviewHighlightLayer);
        reviewHighlightLayer = null;
    }

    showStatus('Review complete');
}