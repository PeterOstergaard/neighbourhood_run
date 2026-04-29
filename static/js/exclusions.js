// ===== Segment Exclusion Toggle =====

async function toggleExclude(edgeId) {
    showStatus('Updating...');
    try {
        const resp = await fetch(`/api/toggle-exclude/${edgeId}`, { method: 'POST' });
        const data = await resp.json();

        if (data.status === 'excluded') excludedIds.add(edgeId);
        else excludedIds.delete(edgeId);

        updateExcludeCount();
        buildSummary();
        showStatus(`Edge ${edgeId}: ${data.status}`);
    } catch (e) {
        showStatus('Error: ' + e.message);
    }
}