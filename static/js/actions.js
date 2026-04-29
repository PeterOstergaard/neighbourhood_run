// ===== Main Action Buttons =====

async function syncStrava() {
    showStatus('Syncing from Strava... (this may take a few minutes)');
    document.getElementById('btn-strava').disabled = true;
    document.getElementById('btn-strava').textContent = '⏳ Syncing...';
    try {
        const resp = await fetch('/api/sync-strava', { method: 'POST' });
        const data = await resp.json();

        showStatus(data.message || 'Sync complete');
        lastSyncedActivityIds = data.new_activity_ids || [];

        if (lastSyncedActivityIds.length > 0) {
            const doReview = confirm("New activities were synced. Did you run one of the planned routes?");
            if (doReview) {
                await openRouteReviewChooser(lastSyncedActivityIds);
                return;
            }
        }

        setTimeout(() => window.location.reload(), 1500);
    } catch (e) {
        showStatus('Error: ' + e.message);
    } finally {
        document.getElementById('btn-strava').disabled = false;
        document.getElementById('btn-strava').textContent = '🔄 Sync Strava';
    }
}

async function generateRoutes() {
    showStatus('Generating routes... (this may take a while)');
    document.getElementById('btn-generate').disabled = true;
    try {
        const resp = await fetch('/api/generate-routes', { method: 'POST' });
        const data = await resp.json();
        showStatus(data.message || 'Routes generated');
        setTimeout(() => window.location.reload(), 1500);
    } catch (e) {
        showStatus('Error: ' + e.message);
    } finally {
        document.getElementById('btn-generate').disabled = false;
    }
}

async function rebuildCoverage() {
    showStatus('Rebuilding coverage... (this may take a few minutes)');
    document.getElementById('btn-rebuild').disabled = true;
    try {
        const resp = await fetch('/api/rebuild-coverage', { method: 'POST' });
        const data = await resp.json();
        showStatus(data.message || 'Coverage rebuilt');
        setTimeout(() => window.location.reload(), 1500);
    } catch (e) {
        showStatus('Error: ' + e.message);
    } finally {
        document.getElementById('btn-rebuild').disabled = false;
    }
}