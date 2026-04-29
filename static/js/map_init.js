// ===== Map Initialization and Global State =====

const COLORS = {
    covered: '#2166ac',
    uncovered: '#d6792b',
    flagged: '#7a3a9a',
    excluded: '#888888',
    boundary: '#333333',
    reviewHighlight: '#ff00ff'
};

// Global state
let excludedIds = new Set(MAP_DATA.excluded_ids);
let segmentLayers = {};
let reviewMode = false;
let reviewList = [];
let reviewIndex = 0;
let selectedRoute = null;
let currentView = 'coverage';
let reviewHighlightLayer = null;

// Route review state
let lastSyncedActivityIds = [];
let selectedReviewRouteId = null;
let selectedReviewActivityIds = [];
let routeReviewLayer = null;
let recentTrackLayer = null;
let routeSegmentReviewLayers = {};
let selectedReviewEdgeId = null;

// Route chooser state
let routeChoiceMatches = [];
let routeChoiceActivityIds = [];
let routeChoiceSelectedIdx = null;

// Layer groups
const coverageGroup = L.layerGroup();
const reviewGroup = L.layerGroup();
const routeGroup = L.layerGroup();

// Initialize map
const map = L.map('map').setView(MAP_DATA.center, 14);
L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    attribution: '© OpenStreetMap © CARTO',
    maxZoom: 19
}).addTo(map);

// Boundary (always visible)
L.geoJSON(MAP_DATA.boundary, {
    style: { color: COLORS.boundary, weight: 2, fillOpacity: 0.03 }
}).addTo(map);

// Home marker (always visible)
L.marker(MAP_DATA.home, {
    icon: L.divIcon({
        html: '🏠',
        className: 'home-icon',
        iconSize: [24, 24],
        iconAnchor: [12, 12]
    })
}).addTo(map);