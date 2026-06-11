// Backend API base URL. Override by setting window.BACKEND_BASE_URL before this
// script loads (e.g. in index.html) to point at a non-local deployment.
const BACKEND_BASE_URL = (typeof window !== 'undefined' && window.BACKEND_BASE_URL) || 'http://localhost:5000';

let UNIT = 10;  // 每个单位 = 10 像素
let VIEW_W = 160 * UNIT;   // 1600px viewport
let WORLD_W = 260 * UNIT;  // 2600px scrollable map
let WORLD_H = 90 * UNIT;   // 900px

let agents = {};  // 存放所有代理

// 记录每个代理是否已展示计划并移动
let agentState = {
    'Ella Parker': { moved: false, currentDay: 1 },
    'Ron Parker': { moved: false, currentDay: 1 },
    'Adam Harris': { moved: false, currentDay: 1 },
    'Emma Harris': { moved: false, currentDay: 1 },
    'Mia Thompson': { moved: false, currentDay: 1 },
    'Gavin Harris': { moved: false, currentDay: 1 },
    'Arthur Morgan': { moved: false, currentDay: 1 }
};

let dailyPlanInProgress = false; // 标记当天的循环是否已初始化
let currentPlanDay = 1;  // 当前生活日
let conversationsInProgress = {};  // 正在播放对话的代理
let simulationStarted = false;
let simulationPaused = false;
let nightInProgress = false;
let simulationSpeed = 1;
let routesVisible = true;
let focusedRouteAgent = null;
let selectedAgentName = 'Ron Parker';
let userControlledAgentName = null;
let gameScene = null;
let activeRouteLines = [];
let agentReservations = {};
let agentSchedules = {};
let dailyScheduleLoadedByDay = {};
let agentCurrentActions = {};  // 每个代理当前正在执行的决策动作
let currentTimeMinutes = 6 * 60;
let lastProgressSyncAt = 0;
let progressLoaded = false;
let activeSpeechBubbles = {};
let activeStatusBubbles = {};
let statusBubbleTweens = {};
let sleepBubbles = {};
let sleepBubbleTweens = {};
let anchorDebugObjects = [];
let lastInternalStateSyncMinutes = {};
let restoredAgentSnapshot = null;
let walkingFrameTimers = {};
let manualControlKeys = { w: false, a: false, s: false, d: false };
let manualControlPrimaryKey = null;
let manualControlLastSyncAt = 0;

const DAY_START_MINUTES = 6 * 60;
const DAY_END_MINUTES = 23 * 60;
const SIM_MINUTES_PER_SECOND = 1;

// Need-driven loop: deterministic wake/bed window, staggered per agent so the
// town does not move in lockstep. Everything between wake and bed is decided
// one action at a time by the backend (/decide_next_action).
const DEFAULT_WAKE_MINUTES = 6 * 60 + 30;
const WAKE_STAGGER_MINUTES = 10;
const DEFAULT_BED_MINUTES = 22 * 60;
const BED_STAGGER_MINUTES = 5;
const DECISION_RETRY_MINUTES = 10;

function computeDefaultSchedule(agentIndex) {
    return {
        wakeTime: Math.min(DEFAULT_WAKE_MINUTES + (agentIndex * WAKE_STAGGER_MINUTES), DAY_END_MINUTES - 60),
        bedTime: Math.min(DEFAULT_BED_MINUTES + (agentIndex * BED_STAGGER_MINUTES), DAY_END_MINUTES)
    };
}
const CAMERA_STEP = 42 * UNIT;
const USER_CONTROL_SPEED_PIXELS_PER_SECOND = 58;
const USER_CONTROL_WALK_RADIUS = 18;
const USER_CONTROL_SYNC_INTERVAL_MS = 1500;
const MAIN_ROAD_Y = 42;
const PUBLIC_ROAD_Y = 83;
const WALKWAY_WIDTH = 2.8;
const ANCHOR_DEBUG_ROOMS = new Set([
    'Bed',
    'Toilet',
    'Kitchen',
    'Dining_table',
    'Dinning_room',
    'Living_room',
    'Sofa',
    'Chair',
    'Bookshelf',
    'Reading_chair',
    'Desk',
    'Study_corner',
    'Window'
]);

const homeAreaByAgent = {
    'Ron Parker': 'Ron_home',
    'Ella Parker': 'Ella_home',
    'Arthur Morgan': 'Arthur_home',
    'Mia Thompson': 'Mia_home',
    'Emma Harris': 'Emma_home',
    'Gavin Harris': 'Gavin_home',
    'Adam Harris': 'Adam_home'
};

let agentLocations = {
    'Ron Parker': 'Ron_home.Bed',
    'Ella Parker': 'Ella_home.Bed',
    'Arthur Morgan': 'Arthur_home.Bed',
    'Mia Thompson': 'Mia_home.Bed',
    'Emma Harris': 'Emma_home.Bed',
    'Gavin Harris': 'Gavin_home.Bed',
    'Adam Harris': 'Adam_home.Bed'
};
let agentConversations = {};
let agentPhases = Object.fromEntries(
    Object.keys(agentState).map(agentName => [agentName, 'Ready'])
);

const agentProfiles = {
    'Ron Parker': { role: 'Supermarket Owner', home: 'Ron home' },
    'Ella Parker': { role: 'Pharmacy Owner', home: 'Ella home' },
    'Emma Harris': { role: 'Mother', home: 'Emma home' },
    'Gavin Harris': { role: 'Father', home: 'Gavin home' },
    'Adam Harris': { role: 'Child', home: 'Adam home' },
    'Mia Thompson': { role: 'Family Teacher', home: 'Mia home' },
    'Arthur Morgan': { role: 'Architect', home: 'Arthur home' }
};

const agentTextureKeyByName = {
    'Ron Parker': 'ron',
    'Ella Parker': 'ella',
    'Arthur Morgan': 'arthur',
    'Mia Thompson': 'mia',
    'Emma Harris': 'emma',
    'Gavin Harris': 'gavin',
    'Adam Harris': 'adam'
};

const sleepLocationByAgent = {
    'Ron Parker': 'Ron_home.Bed',
    'Ella Parker': 'Ella_home.Bed',
    'Arthur Morgan': 'Arthur_home.Bed',
    'Mia Thompson': 'Mia_home.Bed',
    'Emma Harris': 'Emma_home.Bed',
    'Gavin Harris': 'Gavin_home.Bed',
    'Adam Harris': 'Adam_home.Bed'
};

const agentPoseSettings = {
    stand: { originX: 0.5, originY: 1, scale: 0.06, angle: 0 },
    walk1: { originX: 0.5, originY: 1, scale: 0.06, angle: -1.5 },
    walk2: { originX: 0.5, originY: 1, scale: 0.06, angle: 1.5 },
    sit: { originX: 0.5, originY: 1, scale: 0.06, angle: 0 },
    lie: { originX: 0.5, originY: 0.5, scale: 0.082, angle: 90 }
};

const sleepPoseOverrides = {
    'Ron Parker': { x: 0, y: -1.25, angle: 90 },
    'Ella Parker': { x: 0, y: -0.95, angle: -90 },
    'Arthur Morgan': { x: 0, y: -0.35, angle: 90 },
    'Mia Thompson': { x: 0, y: -0.25, angle: 90 },
    'Emma Harris': { x: 0.45, y: 1.15, angle: 90 },
    'Gavin Harris': { x: 0.65, y: 0.45, angle: 90 },
    'Adam Harris': { x: 0, y: -0.35, angle: 90 }
};

const sleepOnlyLocations = new Set(Object.values(sleepLocationByAgent));
const privateHomeRooms = new Set(['Bed', 'Toilet']);
const surfaceInteractionFallbacks = {
    Dining_table: ['Chair', 'Sofa', 'Living_room'],
    Dinning_room: ['Chair', 'Sofa', 'Living_room'],
    Bookshelf: ['Reading_chair', 'Study_corner', 'Living_room'],
    Desk: ['Chair', 'Study_corner', 'Living_room']
};

const homeConfigs = [
    { area: 'Ron_home', x: 17, y: 15, doorXOffset: -1.9 },
    { area: 'Ella_home', x: 52, y: 15, doorXOffset: -4.4 },
    { area: 'Arthur_home', x: 87, y: 15, doorXOffset: 0.3 },
    { area: 'Mia_home', x: 122, y: 15, doorXOffset: -7.1 },
    { area: 'Emma_home', x: 157, y: 15, doorXOffset: -0.3 },
    { area: 'Gavin_home', x: 192, y: 15, doorXOffset: -1 },
    { area: 'Adam_home', x: 227, y: 15, doorXOffset: -1 }
];

const publicDoorConfigs = {
    'Café_bar': { x: 105, doorXOffset: -2.9 },
    Supermarket: { x: 155, doorXOffset: -6.5 },
    Pharmacy: { x: 205, doorXOffset: -6.5 }
};

const publicDoorX = Object.fromEntries(
    Object.entries(publicDoorConfigs).map(([area, config]) => [area, config.x + config.doorXOffset])
);

const homeRoomOffsets = {
    Living_room: { x: -7, y: 5 },
    Bed: { x: 8, y: 7 },
    Toilet: { x: 8, y: -3 },
    Kitchen: { x: -4, y: -3 },
    Dining_table: { x: 3, y: 4 },
    Dinning_room: { x: 3, y: 4 },
    Study_corner: { x: -9, y: 10 },
    Desk: { x: -5, y: 10 },
    Bookshelf: { x: -10, y: 7 },
    Reading_chair: { x: -6, y: 9 },
    Sofa: { x: -5, y: 6 },
    Chair: { x: 5, y: 5 },
    Porch: { x: 0, y: 12 },
    Window: { x: -9, y: -1 }
};

const homeRoomOverrides = {
    Ron_home: {
        Living_room: { x: -7.4, y: 3 },
        Bed: { x: 9.6, y: 7.5 },
        Toilet: { x: 8.6, y: -7.4 },
        Kitchen: { x: -1.2, y: -7.5 },
        Dining_table: { x: 3.5, y: 3.2 },
        Dinning_room: { x: 3.5, y: 3.2 },
        Study_corner: { x: -6.5, y: 9.2 },
        Desk: { x: -6.5, y: 9.2 },
        Bookshelf: { x: -12.2, y: -8.1 },
        Reading_chair: { x: -7.2, y: 2.2 },
        Sofa: { x: -7.4, y: 1.2 },
        Chair: { x: 5.2, y: 3.2 },
        Porch: { x: -1.9, y: 12 },
        Window: { x: 9.8, y: -7.8 }
    },
    Ella_home: {
        Living_room: { x: -8, y: -5 },
        Bed: { x: -8.8, y: 9.4 },
        Toilet: { x: 7.2, y: 6.4 },
        Kitchen: { x: 5.4, y: -7.6 },
        Dining_table: { x: 5.5, y: -1 },
        Dinning_room: { x: 5.5, y: -1 },
        Study_corner: { x: -8.4, y: 3.5 },
        Desk: { x: -8.4, y: 3.5 },
        Bookshelf: { x: -12, y: -7.6 },
        Reading_chair: { x: -5.4, y: 3.4 },
        Sofa: { x: -7.4, y: -7.4 },
        Chair: { x: 7.8, y: -0.6 },
        Porch: { x: -4.4, y: 12 },
        Window: { x: -6.2, y: -10.6 }
    },
    Arthur_home: {
        Living_room: { x: -12.4, y: -1.7 },
        Bed: { x: -9.6, y: 6.8 },
        Toilet: { x: 8.6, y: -7.4 },
        Kitchen: { x: 1.5, y: -7.6 },
        Dining_table: { x: 2.6, y: -1.1 },
        Dinning_room: { x: 2.6, y: -1.1 },
        Study_corner: { x: 7.8, y: 6.2 },
        Desk: { x: 7.8, y: 6.2 },
        Bookshelf: { x: -12.2, y: -8.8 },
        Reading_chair: { x: -13.8, y: -1.6 },
        Sofa: { x: -13.8, y: -1.6 },
        Chair: { x: 5.8, y: 5.8 },
        Porch: { x: 0.3, y: 12 },
        Window: { x: 5.8, y: 4.1 }
    },
    Mia_home: {
        Living_room: { x: -8.8, y: 4.1 },
        Bed: { x: 4.8, y: -4.1 },
        Toilet: { x: 6.4, y: 8 },
        Kitchen: { x: -1.1, y: -7.5 },
        Dining_table: { x: -12.4, y: -0.3 },
        Dinning_room: { x: -12.4, y: -0.3 },
        Study_corner: { x: 0, y: 8 },
        Desk: { x: 0, y: 8 },
        Bookshelf: { x: -12.5, y: -8.1 },
        Reading_chair: { x: -9, y: 3.7 },
        Sofa: { x: -8.9, y: 4 },
        Chair: { x: -11.1, y: -0.2 },
        Porch: { x: -7.1, y: 12 },
        Window: { x: 6.6, y: -10.2 }
    },
    Emma_home: {
        Living_room: { x: -6.2, y: 0.2 },
        Bed: { x: -8.8, y: -9.4 },
        Toilet: { x: 10.1, y: -10.4 },
        Kitchen: { x: 3.5, y: -10.4 },
        Dining_table: { x: 5.4, y: 1 },
        Dinning_room: { x: 5.4, y: 1 },
        Study_corner: { x: -9.4, y: 8 },
        Desk: { x: -9.4, y: 8 },
        Bookshelf: { x: -11.4, y: 0.9 },
        Reading_chair: { x: -6.1, y: 1.6 },
        Sofa: { x: -6.2, y: 0.2 },
        Chair: { x: 5.5, y: 2.5 },
        Porch: { x: -0.3, y: 12 },
        Window: { x: -8.3, y: -14.1 }
    },
    Gavin_home: {
        Living_room: { x: -8, y: 5.8 },
        Bed: { x: 5.6, y: -8 },
        Toilet: { x: 9.3, y: -5 },
        Kitchen: { x: -7.6, y: -11.4 },
        Dining_table: { x: 2.8, y: 5.8 },
        Dinning_room: { x: 2.8, y: 5.8 },
        Study_corner: { x: -6.2, y: 1 },
        Desk: { x: -6.2, y: 1 },
        Bookshelf: { x: -2, y: -11.6 },
        Reading_chair: { x: -8.8, y: 4.2 },
        Sofa: { x: -8, y: 5.8 },
        Chair: { x: -4.8, y: 5.7 },
        Porch: { x: -1, y: 12 },
        Window: { x: -5.9, y: 0.8 }
    },
    Adam_home: {
        Living_room: { x: -7.8, y: 2.7 },
        Bed: { x: 8.8, y: 6.2 },
        Toilet: { x: 9.3, y: -11.2 },
        Kitchen: { x: 1.2, y: -11 },
        Dining_table: { x: 1.2, y: 2.3 },
        Dinning_room: { x: 1.2, y: 2.3 },
        Study_corner: { x: -9.4, y: 8.1 },
        Desk: { x: -9.4, y: 8.1 },
        Bookshelf: { x: -11.4, y: -2.5 },
        Reading_chair: { x: -7.9, y: 2.7 },
        Sofa: { x: -7.8, y: 2.7 },
        Chair: { x: 3.1, y: 2.4 },
        Porch: { x: -1, y: 12 },
        Window: { x: 0.5, y: -13 }
    }
};

const homeDoorOffsets = {
    door_in: { x: 0, y: 13 },
    door_out: { x: 0, y: 18 }
};

const homeDoorOverrides = {
    Emma_home: {
        door_in: { x: 0, y: 7.2 },
        door_out: { x: 0, y: 16.6 }
    },
    Gavin_home: {
        door_in: { x: 0, y: 7.2 },
        door_out: { x: 0, y: 16.6 }
    },
    Adam_home: {
        door_in: { x: 0, y: 7.2 },
        door_out: { x: 0, y: 16.6 }
    }
};

function offsetPoint(base, offset) {
    return { x: base.x + offset.x, y: base.y + offset.y };
}

function offsetDoorPoint(base, offset) {
    return { x: base.x + (base.doorXOffset || 0) + offset.x, y: base.y + offset.y };
}

function getHomeRoomOffset(homeArea, roomName) {
    return homeRoomOverrides[homeArea]?.[roomName] || homeRoomOffsets[roomName];
}

function getHomeDoorOffset(homeArea, doorName) {
    return homeDoorOverrides[homeArea]?.[doorName] || homeDoorOffsets[doorName];
}

function buildHomeLocations() {
    return Object.fromEntries(homeConfigs.map(home => [
        home.area,
        Object.fromEntries(Object.keys(homeRoomOffsets).map(roomName => [
            roomName,
            offsetPoint(home, getHomeRoomOffset(home.area, roomName))
        ]))
    ]));
}

function buildHomeNavNodes() {
    const nodes = {};

    homeConfigs.forEach(home => {
        Object.keys(homeRoomOffsets).forEach(roomName => {
            nodes[`${home.area}.${roomName}`] = offsetPoint(home, getHomeRoomOffset(home.area, roomName));
        });
        Object.keys(homeDoorOffsets).forEach(doorName => {
            nodes[`${home.area}.${doorName}`] = offsetDoorPoint(home, getHomeDoorOffset(home.area, doorName));
        });
        nodes[`road.${home.area}`] = { x: home.x + (home.doorXOffset || 0), y: MAIN_ROAD_Y };
    });

    return nodes;
}

function buildHomeNavEdges() {
    const roomNames = Object.keys(homeRoomOffsets);
    const edges = [];

    homeConfigs.forEach(home => {
        roomNames.forEach(roomName => {
            edges.push([`${home.area}.${roomName}`, `${home.area}.door_in`]);
        });
        edges.push([`${home.area}.door_in`, `${home.area}.door_out`]);
        edges.push([`${home.area}.door_out`, `road.${home.area}`]);
    });

    return edges;
}

let gameConfig = {
    type: Phaser.AUTO,
    width: VIEW_W,
    height: WORLD_H,
    parent: 'game-container',
    scene: { preload, create, update },
    scale: {
        mode: Phaser.Scale.FIT,
        autoCenter: Phaser.Scale.CENTER_BOTH,
    }
};

const game = new Phaser.Game(gameConfig);

function preload() {
    // 加载所有资源
    this.load.image('background', 'assets/background.png');
    this.load.image('house1', 'assets/house1.png');
    this.load.image('house2', 'assets/house2.png');
    this.load.image('house3', 'assets/house3.png');
    this.load.image('house4', 'assets/house4.png');
    this.load.image('house5', 'assets/house5.png');
    this.load.image('house6', 'assets/house6.png');
    this.load.image('house7', 'assets/house7.png');
    this.load.image('supermarket', 'assets/supermarket.png');
    this.load.image('park', 'assets/park.png');
    this.load.image('pharmacy', 'assets/pharmacy.png');
    this.load.image('entertainment', 'assets/entertainment.png');
    this.load.image('ron', 'assets/ron.png');
    this.load.image('ella', 'assets/ella.png');
    this.load.image('arthur', 'assets/arthur.png');
    this.load.image('mia', 'assets/mia.png');
    this.load.image('emma', 'assets/emma.png');
    this.load.image('gavin', 'assets/gavin.png');
    this.load.image('adam', 'assets/adam.png');
    Object.values(agentTextureKeyByName).forEach(textureKey => {
        this.load.image(`${textureKey}_sit`, `assets/${textureKey}_sit.png?v=42`);
        this.load.image(`${textureKey}_lie`, `assets/${textureKey}_lie.png?v=42`);
        this.load.image(`${textureKey}_walk1`, `assets/${textureKey}_walk1.png?v=64`);
        this.load.image(`${textureKey}_walk2`, `assets/${textureKey}_walk2.png?v=64`);
    });
    this.load.image('lamp', 'assets/lamp.png'); 
    //this.load.image('backgroundnight', 'assets/backgroundnight.png');
    this.load.image('moon', 'assets/moon.png');
}

let locations = {
    ...buildHomeLocations(),
    "Parker_home": {
        "Living_room": { x: 10, y: 20 },
        "Bed":         { x: 26, y: 22 },
        "Ron_bed":     { x: 24, y: 22 },
        "Ella_bed":    { x: 28, y: 22 },
        "Toilet":      { x: 25, y: 12 },
        "Kitchen":     { x: 12, y: 12 },
        "Dining_table":{ x: 18, y: 18 },
        "Porch":       { x: 17, y: 26 },
        "Window":      { x: 8, y: 14 }
    },
    "Morgan_home": {
        "Bed":         { x: 8, y: 84 },
        "Arthur_bed":  { x: 10, y: 84 },
        "Living_room": { x: 8, y: 70 },
        "Dinning_room":{ x: 17, y: 73 },
        "Toilet":      { x: 20, y: 83 },
        "Study":       { x: 22, y: 70 },
        "Kitchen":     { x: 14, y: 80 },
        "Porch":       { x: 14, y: 62 }
    },
    "Thompson_home": {
        "Bed":         { x: 131, y: 22 },
        "Mia_bed":     { x: 133, y: 22 },
        "Living_room": { x: 136, y: 20 },
        "Kitchen":     { x: 140, y: 22 },
        "Desk":        { x: 128, y: 14 },
        "Bookshelf":   { x: 145, y: 14 },
        "Porch":       { x: 140, y: 27 },
        "Reading_chair": { x: 132, y: 16 }
    },
    "Harries_home": {
        "Bed":         { x: 146, y: 71 },
        "Emma_bed": { x: 144, y: 71 },
        "Gavin_bed": { x: 148, y: 76 },
        "Adam_bed": { x: 146, y: 83 },
        "Chair": { x: 126, y: 73 },
        "Sofa": { x: 134, y: 83 },
        "Kitchen": {x: 136, y: 73},
        "Dining_table": { x: 129, y: 80 },
        "Study_corner": { x: 148, y: 82 },
        "Porch": { x: 139, y: 62 },
    },
    "Park": {
        "Chair":         { x: 59, y: 69 },
        "River": { x: 45, y: 61 },
        "Tree": { x: 56, y: 64 },
        "Bench": { x: 50, y: 70 },
        "Flower_bed": { x: 62, y: 62 },
        "Playground": { x: 47, y: 67 },
        "Bridge": { x: 52, y: 63 }
    },
    "Café_bar": {
        "Boss": { x: 95, y: 55 },
        "Customer_cafe":  { x: 101, y: 61 },
        "Customer_bar":  { x: 115, y: 74 },
        "Window_seat": { x: 99, y: 64 },
        "Corner_table": { x: 115, y: 62 },
        "Counter": { x: 108, y: 72 },
        "Patio": { x: 92, y: 73 }
    },
    "Supermarket": {
        "Boss": { x: 141, y: 62 },
        "Customer_drink":  { x: 151, y: 75 },
        "Customer_eat":  { x: 165, y: 75 },
        "Checkout": { x: 160, y: 63 },
        "Fruit_shelf": { x: 145, y: 72 },
        "Storage": { x: 168, y: 66 },
        "Entrance_aisle": { x: 155, y: 61 }
    },
    "Pharmacy": {
        "Boss": { x: 196, y: 58 },
        "Customer_left":  { x: 199, y: 64 },
        "Customer_right":  { x: 219, y: 63 },
        "Prescription_counter": { x: 207, y: 59 },
        "Medicine_shelf": { x: 215, y: 68 },
        "Waiting_chair": { x: 200, y: 72 },
        "Consult_room": { x: 193, y: 70 }
    }
};

let occupiedLocations = {
    'Parker_home.Living_room': null,
    'Parker_home.Bed': null,
    'Parker_home.Ron_bed': null,
    'Parker_home.Ella_bed': null,
    'Parker_home.Toilet': null,
    'Parker_home.Kitchen': null,
    'Parker_home.Dining_table': null,
    'Parker_home.Porch': null,
    'Parker_home.Window': null,
    'Morgan_home.Living_room': null,
    'Morgan_home.Bed': null,
    'Morgan_home.Arthur_bed': null,
    'Morgan_home.Dinning_room': null,
    'Morgan_home.Toilet': null,
    'Morgan_home.Study': null,
    'Morgan_home.Kitchen': null,
    'Morgan_home.Porch': null,
    'Thompson_home.Bed': null,
    'Thompson_home.Mia_bed': null,
    'Thompson_home.Living_room': null,
    'Thompson_home.Kitchen': null,
    'Thompson_home.Desk': null,
    'Thompson_home.Bookshelf': null,
    'Thompson_home.Porch': null,
    'Thompson_home.Reading_chair': null,
    'Harries_home.Bed': null,
    'Harries_home.Emma_bed': null,
    'Harries_home.Gavin_bed': null,
    'Harries_home.Adam_bed': null,
    'Harries_home.Chair': null,
    'Harries_home.Sofa': null,
    'Harries_home.Kitchen': null,
    'Harries_home.Dining_table': null,
    'Harries_home.Study_corner': null,
    'Harries_home.Porch': null,
    'Park.Chair': null,
    'Park.River': null,
    'Park.Tree': null,
    'Park.Bench': null,
    'Park.Flower_bed': null,
    'Park.Playground': null,
    'Park.Bridge': null,
    'Café_bar.Boss': null,
    'Café_bar.Customer_cafe': null,
    'Café_bar.Customer_bar': null,
    'Café_bar.Window_seat': null,
    'Café_bar.Corner_table': null,
    'Café_bar.Counter': null,
    'Café_bar.Patio': null,
    'Supermarket.Boss': null,
    'Supermarket.Customer_drink': null,
    'Supermarket.Customer_eat': null,
    'Supermarket.Checkout': null,
    'Supermarket.Fruit_shelf': null,
    'Supermarket.Storage': null,
    'Supermarket.Entrance_aisle': null,
    'Pharmacy.Boss': null,
    'Pharmacy.Customer_left': null,
    'Pharmacy.Customer_right': null,
    'Pharmacy.Prescription_counter': null,
    'Pharmacy.Medicine_shelf': null,
    'Pharmacy.Waiting_chair': null,
    'Pharmacy.Consult_room': null
};

Object.entries(locations).forEach(([areaName, points]) => {
    Object.keys(points).forEach(pointName => {
        const locationName = `${areaName}.${pointName}`;
        if (!(locationName in occupiedLocations)) {
            occupiedLocations[locationName] = null;
        }
    });
});

let currentBackground;

const navNodes = {
    ...buildHomeNavNodes(),
    'Parker_home.Living_room': { x: 10, y: 20 },
    'Parker_home.Bed': { x: 26, y: 22 },
    'Parker_home.Ron_bed': { x: 24, y: 22 },
    'Parker_home.Ella_bed': { x: 28, y: 22 },
    'Parker_home.Toilet': { x: 25, y: 12 },
    'Parker_home.Kitchen': { x: 12, y: 12 },
    'Parker_home.Dining_table': { x: 18, y: 18 },
    'Parker_home.Porch': { x: 17, y: 26 },
    'Parker_home.Window': { x: 8, y: 14 },
    'Parker_home.door_in': { x: 17, y: 28 },
    'Parker_home.door_out': { x: 17, y: 33 },

    'Morgan_home.Bed': { x: 8, y: 84 },
    'Morgan_home.Arthur_bed': { x: 10, y: 84 },
    'Morgan_home.Living_room': { x: 8, y: 70 },
    'Morgan_home.Dinning_room': { x: 17, y: 73 },
    'Morgan_home.Toilet': { x: 20, y: 83 },
    'Morgan_home.Study': { x: 22, y: 70 },
    'Morgan_home.Kitchen': { x: 14, y: 80 },
    'Morgan_home.Porch': { x: 14, y: 62 },
    'Morgan_home.door_in': { x: 14, y: 60 },
    'Morgan_home.door_out': { x: 14, y: 55 },

    'Thompson_home.Bed': { x: 131, y: 22 },
    'Thompson_home.Mia_bed': { x: 133, y: 22 },
    'Thompson_home.Living_room': { x: 136, y: 20 },
    'Thompson_home.Kitchen': { x: 140, y: 22 },
    'Thompson_home.Desk': { x: 128, y: 14 },
    'Thompson_home.Bookshelf': { x: 145, y: 14 },
    'Thompson_home.Porch': { x: 140, y: 27 },
    'Thompson_home.Reading_chair': { x: 132, y: 16 },
    'Thompson_home.door_in': { x: 140, y: 29 },
    'Thompson_home.door_out': { x: 140, y: 31 },

    'Harries_home.Bed': { x: 146, y: 71 },
    'Harries_home.Emma_bed': { x: 144, y: 71 },
    'Harries_home.Gavin_bed': { x: 148, y: 76 },
    'Harries_home.Adam_bed': { x: 146, y: 83 },
    'Harries_home.Chair': { x: 126, y: 73 },
    'Harries_home.Sofa': { x: 134, y: 83 },
    'Harries_home.Kitchen': { x: 136, y: 73 },
    'Harries_home.Dining_table': { x: 129, y: 80 },
    'Harries_home.Study_corner': { x: 148, y: 82 },
    'Harries_home.Porch': { x: 139, y: 62 },
    'Harries_home.door_in': { x: 139, y: 64 },
    'Harries_home.door_out': { x: 139, y: 61 },

    'Café_bar.Boss': { x: 95, y: 55 },
    'Café_bar.Customer_cafe': { x: 101, y: 61 },
    'Café_bar.Customer_bar': { x: 115, y: 74 },
    'Café_bar.Window_seat': { x: 99, y: 64 },
    'Café_bar.Corner_table': { x: 115, y: 62 },
    'Café_bar.Counter': { x: 108, y: 72 },
    'Café_bar.Patio': { x: 92, y: 73 },
    'Café_bar.door_in': { x: publicDoorX['Café_bar'], y: 80 },
    'Café_bar.door_out': { x: publicDoorX['Café_bar'], y: PUBLIC_ROAD_Y },

    'Supermarket.Boss': { x: 141, y: 62 },
    'Supermarket.Customer_drink': { x: 151, y: 75 },
    'Supermarket.Customer_eat': { x: 165, y: 75 },
    'Supermarket.Checkout': { x: 160, y: 63 },
    'Supermarket.Fruit_shelf': { x: 145, y: 72 },
    'Supermarket.Storage': { x: 168, y: 66 },
    'Supermarket.Entrance_aisle': { x: 155, y: 61 },
    'Supermarket.door_in': { x: publicDoorX.Supermarket, y: 80 },
    'Supermarket.door_out': { x: publicDoorX.Supermarket, y: PUBLIC_ROAD_Y },

    'Pharmacy.Boss': { x: 196, y: 58 },
    'Pharmacy.Customer_left': { x: 199, y: 64 },
    'Pharmacy.Customer_right': { x: 219, y: 63 },
    'Pharmacy.Prescription_counter': { x: 207, y: 59 },
    'Pharmacy.Medicine_shelf': { x: 215, y: 68 },
    'Pharmacy.Waiting_chair': { x: 200, y: 72 },
    'Pharmacy.Consult_room': { x: 193, y: 70 },
    'Pharmacy.door_in': { x: publicDoorX.Pharmacy, y: 80 },
    'Pharmacy.door_out': { x: publicDoorX.Pharmacy, y: PUBLIC_ROAD_Y },

    'Park.Chair': { x: 59, y: 69 },
    'Park.River': { x: 45, y: 61 },
    'Park.Tree': { x: 56, y: 64 },
    'Park.Bench': { x: 50, y: 70 },
    'Park.Flower_bed': { x: 62, y: 62 },
    'Park.Playground': { x: 47, y: 67 },
    'Park.Bridge': { x: 52, y: 63 },

    'road.west_north': { x: 17, y: 42 },
    'road.west_south': { x: 17, y: 55 },
    'road.center_north': { x: 78, y: 42 },
    'road.center_south': { x: 78, y: 55 },
    'road.park': { x: 56, y: 45 },
    'road.park_west_corner': { x: 56, y: 42 },
    'road.park_east_corner': { x: 78, y: 45 },
    'road.north_east_corner': { x: 110, y: 42 },
    'road.south_east_corner': { x: 110, y: 55 },
    'road.east_upper': { x: 110, y: 31 },
    'road.east_mid': { x: 110, y: 45 },
    'road.east_lower': { x: 110, y: 61 },
    'road.right_lower': { x: 112, y: 61 },
    'road.Park': { x: 55, y: PUBLIC_ROAD_Y },
    'road.Café_bar': { x: publicDoorX['Café_bar'], y: PUBLIC_ROAD_Y },
    'road.Supermarket': { x: publicDoorX.Supermarket, y: PUBLIC_ROAD_Y },
    'road.Pharmacy': { x: publicDoorX.Pharmacy, y: PUBLIC_ROAD_Y },
    'road.lower_west_top': { x: 80, y: MAIN_ROAD_Y },
    'road.lower_west_bottom': { x: 80, y: PUBLIC_ROAD_Y },
    'road.lower_east_top': { x: 180, y: MAIN_ROAD_Y },
    'road.lower_east_bottom': { x: 180, y: PUBLIC_ROAD_Y }
};

const locationToNode = Object.fromEntries(
    Object.keys(navNodes)
        .filter(name => !name.startsWith('road.') && !name.endsWith('.door_in') && !name.endsWith('.door_out'))
        .map(name => [name, name])
);

const externalRoadSegments = [
    ['road.Ron_home', 'road.Ella_home'],
    ['road.Ella_home', 'road.lower_west_top'],
    ['road.lower_west_top', 'road.Arthur_home'],
    ['road.Arthur_home', 'road.Mia_home'],
    ['road.Mia_home', 'road.Emma_home'],
    ['road.Emma_home', 'road.lower_east_top'],
    ['road.lower_east_top', 'road.Gavin_home'],
    ['road.Gavin_home', 'road.Adam_home'],
    ['road.lower_west_top', 'road.lower_west_bottom'],
    ['road.lower_east_top', 'road.lower_east_bottom'],
    ['road.Park', 'road.lower_west_bottom'],
    ['road.lower_west_bottom', 'road.Café_bar'],
    ['road.Café_bar', 'road.Supermarket'],
    ['road.Supermarket', 'road.lower_east_bottom'],
    ['road.lower_east_bottom', 'road.Pharmacy']
];

const navEdges = [
    ...buildHomeNavEdges(),
    ['Parker_home.Living_room', 'Parker_home.door_in'],
    ['Parker_home.Bed', 'Parker_home.door_in'],
    ['Parker_home.Ron_bed', 'Parker_home.door_in'],
    ['Parker_home.Ella_bed', 'Parker_home.door_in'],
    ['Parker_home.Toilet', 'Parker_home.door_in'],
    ['Parker_home.Kitchen', 'Parker_home.door_in'],
    ['Parker_home.Dining_table', 'Parker_home.door_in'],
    ['Parker_home.Porch', 'Parker_home.door_in'],
    ['Parker_home.Window', 'Parker_home.door_in'],
    ['Parker_home.door_in', 'Parker_home.door_out'],

    ['Morgan_home.Bed', 'Morgan_home.door_in'],
    ['Morgan_home.Arthur_bed', 'Morgan_home.door_in'],
    ['Morgan_home.Living_room', 'Morgan_home.door_in'],
    ['Morgan_home.Dinning_room', 'Morgan_home.door_in'],
    ['Morgan_home.Toilet', 'Morgan_home.door_in'],
    ['Morgan_home.Study', 'Morgan_home.door_in'],
    ['Morgan_home.Kitchen', 'Morgan_home.door_in'],
    ['Morgan_home.Porch', 'Morgan_home.door_in'],
    ['Morgan_home.door_in', 'Morgan_home.door_out'],

    ['Thompson_home.Bed', 'Thompson_home.door_in'],
    ['Thompson_home.Mia_bed', 'Thompson_home.door_in'],
    ['Thompson_home.Living_room', 'Thompson_home.door_in'],
    ['Thompson_home.Kitchen', 'Thompson_home.door_in'],
    ['Thompson_home.Desk', 'Thompson_home.door_in'],
    ['Thompson_home.Bookshelf', 'Thompson_home.door_in'],
    ['Thompson_home.Porch', 'Thompson_home.door_in'],
    ['Thompson_home.Reading_chair', 'Thompson_home.door_in'],
    ['Thompson_home.door_in', 'Thompson_home.door_out'],

    ['Harries_home.Bed', 'Harries_home.door_in'],
    ['Harries_home.Emma_bed', 'Harries_home.door_in'],
    ['Harries_home.Gavin_bed', 'Harries_home.door_in'],
    ['Harries_home.Adam_bed', 'Harries_home.door_in'],
    ['Harries_home.Chair', 'Harries_home.door_in'],
    ['Harries_home.Sofa', 'Harries_home.door_in'],
    ['Harries_home.Kitchen', 'Harries_home.door_in'],
    ['Harries_home.Dining_table', 'Harries_home.door_in'],
    ['Harries_home.Study_corner', 'Harries_home.door_in'],
    ['Harries_home.Porch', 'Harries_home.door_in'],
    ['Harries_home.door_in', 'Harries_home.door_out'],

    ['Café_bar.Boss', 'Café_bar.door_in'],
    ['Café_bar.Customer_cafe', 'Café_bar.door_in'],
    ['Café_bar.Customer_bar', 'Café_bar.door_in'],
    ['Café_bar.Window_seat', 'Café_bar.door_in'],
    ['Café_bar.Corner_table', 'Café_bar.door_in'],
    ['Café_bar.Counter', 'Café_bar.door_in'],
    ['Café_bar.Patio', 'Café_bar.door_in'],
    ['Café_bar.door_in', 'Café_bar.door_out'],
    ['Café_bar.door_out', 'road.Café_bar'],

    ['Supermarket.Boss', 'Supermarket.door_in'],
    ['Supermarket.Customer_drink', 'Supermarket.door_in'],
    ['Supermarket.Customer_eat', 'Supermarket.door_in'],
    ['Supermarket.Checkout', 'Supermarket.door_in'],
    ['Supermarket.Fruit_shelf', 'Supermarket.door_in'],
    ['Supermarket.Storage', 'Supermarket.door_in'],
    ['Supermarket.Entrance_aisle', 'Supermarket.door_in'],
    ['Supermarket.door_in', 'Supermarket.door_out'],
    ['Supermarket.door_out', 'road.Supermarket'],

    ['Pharmacy.Boss', 'Pharmacy.door_in'],
    ['Pharmacy.Customer_left', 'Pharmacy.door_in'],
    ['Pharmacy.Customer_right', 'Pharmacy.door_in'],
    ['Pharmacy.Prescription_counter', 'Pharmacy.door_in'],
    ['Pharmacy.Medicine_shelf', 'Pharmacy.door_in'],
    ['Pharmacy.Waiting_chair', 'Pharmacy.door_in'],
    ['Pharmacy.Consult_room', 'Pharmacy.door_in'],
    ['Pharmacy.door_in', 'Pharmacy.door_out'],
    ['Pharmacy.door_out', 'road.Pharmacy'],

    ['Park.Chair', 'road.Park'],
    ['Park.River', 'road.Park'],
    ['Park.Tree', 'road.Park'],
    ['Park.Bench', 'road.Park'],
    ['Park.Flower_bed', 'road.Park'],
    ['Park.Playground', 'road.Park'],
    ['Park.Bridge', 'road.Park'],

    ...externalRoadSegments
];

const navGraph = buildNavGraph(navEdges);

function drawTownPaths(scene) {
    const path = scene.add.graphics().setDepth(-0.5);
    path.fillStyle(0xf3e08b, 1);

    homeConfigs.forEach(home => {
        drawWalkableSegment(path, `${home.area}.door_in`, `${home.area}.door_out`);
        drawWalkableSegment(path, `${home.area}.door_out`, `road.${home.area}`);
    });

    [
        ...externalRoadSegments,
        ['Café_bar.door_in', 'Café_bar.door_out'],
        ['Café_bar.door_out', 'road.Café_bar'],
        ['Supermarket.door_in', 'Supermarket.door_out'],
        ['Supermarket.door_out', 'road.Supermarket'],
        ['Pharmacy.door_in', 'Pharmacy.door_out'],
        ['Pharmacy.door_out', 'road.Pharmacy']
    ].forEach(([fromNode, toNode]) => drawWalkableSegment(path, fromNode, toNode));
}

function drawWalkableSegment(graphics, fromNode, toNode) {
    const from = navNodes[fromNode];
    const to = navNodes[toNode];

    if (!from || !to) {
        return;
    }

    const minX = Math.min(from.x, to.x);
    const maxX = Math.max(from.x, to.x);
    const minY = Math.min(from.y, to.y);
    const maxY = Math.max(from.y, to.y);
    const isHorizontal = Math.abs(from.y - to.y) <= 0.1;
    const widthUnits = isHorizontal ? (maxX - minX) + WALKWAY_WIDTH : WALKWAY_WIDTH;
    const heightUnits = isHorizontal ? WALKWAY_WIDTH : (maxY - minY) + WALKWAY_WIDTH;
    const centerX = (from.x + to.x) / 2;
    const centerY = (from.y + to.y) / 2;

    drawWalkableGround(graphics, centerX, centerY, widthUnits, heightUnits);
}

function drawWalkableGround(graphics, centerX, centerY, widthUnits, heightUnits) {
    graphics.fillRoundedRect(
        (centerX - (widthUnits / 2)) * UNIT,
        (centerY - (heightUnits / 2)) * UNIT,
        widthUnits * UNIT,
        heightUnits * UNIT,
        (WALKWAY_WIDTH / 2) * UNIT
    );
}

function shouldShowAnchorDebug() {
    if (typeof window === 'undefined') {
        return false;
    }

    return new URLSearchParams(window.location.search).get('anchors') === '1';
}

function getAnchorDebugPose(locationName) {
    if (getRoomName(locationName) === 'Bed') {
        return 'lie';
    }

    return isSittingLocation(locationName) ? 'sit' : 'stand';
}

function getAnchorDebugColor(pose) {
    if (pose === 'lie') return 0xe85d9e;
    if (pose === 'sit') return 0x2f80ed;
    return 0xf2a93b;
}

function getAnchorDebugLabel(locationName) {
    const areaName = getAreaName(locationName);
    const roomName = getRoomName(locationName);
    const areaLabel = areaName
        .replace('_home', '')
        .replace('Supermarket', 'Market')
        .replace('Pharmacy', 'Pharm')
        .replace('Caf茅_bar', 'Cafe')
        .slice(0, 6);
    const roomLabel = roomName
        .replace('Dining_table', 'Dining')
        .replace('Dinning_room', 'Dining')
        .replace('Living_room', 'Living')
        .replace('Reading_chair', 'ReadChair')
        .replace('Study_corner', 'Study')
        .replace('Prescription_counter', 'Rx')
        .replace('Medicine_shelf', 'Meds')
        .replace('Customer_', 'Cust ')
        .replace('_', ' ');

    return `${areaLabel}.${roomLabel}`;
}

function isAnchorDebugArea(areaName) {
    return isHomeArea(areaName) || areaName === 'Park' || Object.prototype.hasOwnProperty.call(publicDoorConfigs, areaName);
}

function getAnchorDebugEntries() {
    return Object.entries(locations).flatMap(([areaName, points]) => {
        if (!isAnchorDebugArea(areaName)) {
            return [];
        }

        return Object.entries(points)
            .filter(([roomName]) => !isHomeArea(areaName) || ANCHOR_DEBUG_ROOMS.has(roomName))
            .map(([roomName, point]) => `${areaName}.${roomName}`)
            .map(locationName => ({
                locationName,
                point: getLocationCoords(locationName),
                pose: getAnchorDebugPose(locationName)
            }))
            .filter(entry => entry.point);
    });
}

function drawInteractionAnchorDebug(scene) {
    if (!shouldShowAnchorDebug()) {
        return;
    }

    clearInteractionAnchorDebug();

    const layer = scene.add.container(0, 0).setDepth(40);
    const legendBg = scene.add.graphics();
    legendBg.fillStyle(0xffffff, 0.86);
    legendBg.lineStyle(2, 0x333333, 0.35);
    legendBg.fillRoundedRect(10, 760, 245, 88, 8);
    legendBg.strokeRoundedRect(10, 760, 245, 88, 8);
    const legend = scene.add.text(24, 772, 'Interaction anchors\norange=stand  blue=sit  pink=lie\nopen with ?anchors=1', {
        font: '13px Arial',
        fill: '#202020',
        lineSpacing: 5
    });
    layer.add([legendBg, legend]);

    getAnchorDebugEntries().forEach(({ locationName, point, pose }, index) => {
        const x = point.x * UNIT;
        const y = point.y * UNIT;
        const color = getAnchorDebugColor(pose);
        const marker = scene.add.graphics();
        marker.lineStyle(2, 0xffffff, 0.95);
        marker.fillStyle(color, 0.96);
        marker.fillCircle(x, y, 5);
        marker.strokeCircle(x, y, 6);
        marker.lineStyle(1, 0x1f1f1f, 0.6);
        marker.moveTo(x - 9, y);
        marker.lineTo(x + 9, y);
        marker.moveTo(x, y - 9);
        marker.lineTo(x, y + 9);
        marker.strokePath();

        const label = scene.add.text(x + 7, y - 10, getAnchorDebugLabel(locationName), {
            font: '10px Arial',
            fill: '#111111',
            backgroundColor: 'rgba(255,255,255,0.72)',
            padding: { x: 2, y: 1 }
        });
        label.setDepth(41 + (index % 2));
        layer.add([marker, label]);
    });

    anchorDebugObjects.push(layer);
}

function clearInteractionAnchorDebug() {
    anchorDebugObjects.forEach(item => item.destroy());
    anchorDebugObjects = [];
}

function create() {
    gameScene = this;
    setupUi();
    updateUi();

    // 背景
    currentBackground = this.add.tileSprite(0, 0, WORLD_W, WORLD_H, 'background').setOrigin(0).setDepth(-1);
    this.cameras.main.setBounds(0, 0, WORLD_W, WORLD_H);
    drawTownPaths(this);

    let wR = this.sys.game.config.width / 160;
    let hR = this.sys.game.config.height / 90;

    // 场所图标
    this.add.image(17 * wR, 15 * hR, 'house1').setScale(0.3);
    this.add.image(52 * wR, 15 * hR, 'house2').setScale(0.3);
    this.add.image(87 * wR, 15 * hR, 'house3').setScale(0.3);
    this.add.image(122 * wR, 15 * hR, 'house4').setScale(0.3);
    this.add.image(157 * wR, 15 * hR, 'house5').setScale(0.45);
    this.add.image(192 * wR, 15 * hR, 'house6').setScale(0.45);
    this.add.image(227 * wR, 15 * hR, 'house7').setScale(0.45);
    // 添加 park 图像，并设置 name
    const parkImage = this.add.image(55 * wR, 65 * hR, 'park').setScale(0.28);
    parkImage.name = 'park';  // 给 park 图像设置 name
    this.add.image(205 * wR, 65 * hR, 'pharmacy').setScale(0.28);
    // 创建 supermarket 图像，并设置 name
    const supermarketImage = this.add.image(155 * wR, 65 * hR, 'supermarket').setScale(0.28);
    supermarketImage.name = 'supermarket';  // 给 supermarket 图像设置 name
    // 创建 entertainment 图像，并设置 name
    const entertainmentImage = this.add.image(105 * wR, 65 * hR, 'entertainment').setScale(0.28);
    entertainmentImage.name = 'entertainment';  // 给 entertainment 图像设置 name
    drawInteractionAnchorDebug(this);

    // 初始化代理位置
    let ron = getLocationCoords(formatSleepLocation('Ron Parker'));
    let ella = getLocationCoords(formatSleepLocation('Ella Parker'));
    let arthur = getLocationCoords(formatSleepLocation('Arthur Morgan'));
    let mia = getLocationCoords(formatSleepLocation('Mia Thompson'));
    let emma = getLocationCoords(formatSleepLocation('Emma Harris'));
    let gavin = getLocationCoords(formatSleepLocation('Gavin Harris'));
    let adam = getLocationCoords(formatSleepLocation('Adam Harris'));

    agents['Ron Parker'] = this.add.image(ron.x * wR, ron.y * hR, getAgentTextureKey('Ron Parker', 'lie')).setOrigin(0.5, 1).setScale(0.06);
    agents['Ella Parker'] = this.add.image(ella.x * wR, ella.y * hR, getAgentTextureKey('Ella Parker', 'lie')).setOrigin(0.5, 1).setScale(0.06);
    agents['Arthur Morgan'] = this.add.image(arthur.x * wR, arthur.y * hR, getAgentTextureKey('Arthur Morgan', 'lie')).setOrigin(0.5, 1).setScale(0.06);
    agents['Mia Thompson'] = this.add.image(mia.x * wR, mia.y * hR, getAgentTextureKey('Mia Thompson', 'lie')).setOrigin(0.5, 1).setScale(0.06);
    agents['Emma Harris'] = this.add.image(emma.x * wR, emma.y * hR, getAgentTextureKey('Emma Harris', 'lie')).setOrigin(0.5, 1).setScale(0.06);
    agents['Gavin Harris'] = this.add.image(gavin.x * wR, gavin.y * hR, getAgentTextureKey('Gavin Harris', 'lie')).setOrigin(0.5, 1).setScale(0.06);
    agents['Adam Harris'] = this.add.image(adam.x * wR, adam.y * hR, getAgentTextureKey('Adam Harris', 'lie')).setOrigin(0.5, 1).setScale(0.06);

    Object.entries(agents).forEach(([agentName, sprite]) => {
        sprite.agentName = agentName;
        sprite.poseState = 'lie';
        sprite.setInteractive({ useHandCursor: true });
        sprite.on('pointerdown', () => selectAgent(agentName));
    });
    Object.keys(agents).forEach(agentName => resetAgentToSleepPosition(this, agentName));

    getSimulationConfig().then(config => {
        if (config) {
            if (Number.isInteger(config.current_life_day) && config.current_life_day > 0) {
                currentPlanDay = config.current_life_day;
            }
            if (Number.isInteger(config.current_time_minutes)) {
                currentTimeMinutes = Phaser.Math.Clamp(config.current_time_minutes, DAY_START_MINUTES, DAY_END_MINUTES);
                if (currentTimeMinutes >= DAY_END_MINUTES) {
                    currentPlanDay += 1;
                    currentTimeMinutes = DAY_START_MINUTES;
                }
            }
            applyAgentProgressSnapshot(this, config);
            Object.values(agentState).forEach(state => {
                state.currentDay = currentPlanDay;
            });
            progressLoaded = true;
            console.log(`Loaded simulation progress at lived day ${currentPlanDay}.`);
            updateUi();
        } else {
            progressLoaded = true;
            updateUi();
        }
    });
}

function setupUi() {
    const startButton = document.getElementById('start-sim');
    const pauseButton = document.getElementById('pause-sim');
    const topPanelToggle = document.getElementById('top-panel-toggle');
    const panelToggle = document.getElementById('panel-toggle');
    const routeToggle = document.getElementById('route-toggle');
    const routeFocus = document.getElementById('route-focus');
    const controlAgent = document.getElementById('control-agent');
    const panLeft = document.getElementById('pan-left');
    const panRight = document.getElementById('pan-right');

    startButton.addEventListener('click', () => {
        simulationStarted = true;
        simulationPaused = false;
        syncSimulationProgress({ force: true });
        updateUi();
    });

    pauseButton.addEventListener('click', () => {
        if (!simulationStarted) return;
        simulationPaused = !simulationPaused;
        syncSimulationProgress({ force: true });
        updateUi();
    });

    topPanelToggle.addEventListener('click', event => {
        event.stopPropagation();
        toggleTopPanel();
    });

    panelToggle.addEventListener('click', event => {
        event.stopPropagation();
        toggleSidePanel();
    });

    document.addEventListener('pointerdown', event => {
        const panel = document.getElementById('side-panel');
        const topPanel = document.querySelector('.top-panel');

        if (
            panel.classList.contains('collapsed') ||
            panel.contains(event.target) ||
            topPanel.contains(event.target)
        ) {
            return;
        }

        setSidePanelCollapsed(true);
    });

    routeToggle.addEventListener('click', () => {
        routesVisible = !routesVisible;
        if (!routesVisible) {
            clearActiveRoutes();
        }
        updateRouteControls();
    });

    routeFocus.addEventListener('click', () => {
        focusedRouteAgent = focusedRouteAgent === selectedAgentName ? null : selectedAgentName;
        routesVisible = true;
        clearActiveRoutes(line => line.agentName !== focusedRouteAgent);
        updateRouteControls();
    });

    controlAgent.addEventListener('click', () => toggleUserControl(selectedAgentName));
    window.addEventListener('keydown', event => handleUserControlKey(event));
    window.addEventListener('keyup', event => handleUserControlKeyUp(event));
    window.addEventListener('blur', () => clearManualControlKeys());

    panLeft.addEventListener('click', () => panMap(-1));
    panRight.addEventListener('click', () => panMap(1));

    document.querySelectorAll('.speed-button').forEach(button => {
        button.addEventListener('click', () => {
            simulationSpeed = Number(button.dataset.speed) || 1;
            document.querySelectorAll('.speed-button').forEach(speedButton => {
                speedButton.classList.toggle('active', speedButton === button);
            });
        });
    });

    renderAgentList();
    updateRouteControls();
}

function toggleTopPanel() {
    const topPanel = document.querySelector('.top-panel');
    setTopPanelCollapsed(!topPanel.classList.contains('collapsed'));
}

function setTopPanelCollapsed(collapsed) {
    const topPanel = document.querySelector('.top-panel');
    const topPanelToggle = document.getElementById('top-panel-toggle');

    topPanel.classList.toggle('collapsed', collapsed);
    topPanelToggle.textContent = collapsed ? '+' : '−';
    topPanelToggle.setAttribute(
        'aria-label',
        collapsed ? 'Expand simulation controls' : 'Collapse simulation controls'
    );
}

function panMap(direction) {
    if (!gameScene) {
        return;
    }

    const camera = gameScene.cameras.main;
    const maxScrollX = Math.max(0, WORLD_W - VIEW_W);
    const targetX = Phaser.Math.Clamp(camera.scrollX + (direction * CAMERA_STEP), 0, maxScrollX);
    camera.pan(targetX + (VIEW_W / 2), WORLD_H / 2, 320, 'Sine.easeInOut');
}

function toggleSidePanel() {
    const panel = document.getElementById('side-panel');
    setSidePanelCollapsed(!panel.classList.contains('collapsed'));
}

function setSidePanelCollapsed(collapsed) {
    const panel = document.getElementById('side-panel');
    const panelToggle = document.getElementById('panel-toggle');

    panel.classList.toggle('collapsed', collapsed);
    panelToggle.textContent = collapsed ? 'Open' : 'Close';
    panelToggle.setAttribute('aria-label', collapsed ? 'Expand character panel' : 'Collapse character panel');
}

function renderAgentList() {
    const list = document.getElementById('agent-list');
    list.innerHTML = '';

    Object.keys(agentState).forEach(agentName => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'agent-pill';
        button.textContent = agentName;
        button.addEventListener('click', () => selectAgent(agentName));
        list.appendChild(button);
    });
}

function selectAgent(agentName) {
    selectedAgentName = agentName;
    refreshAgentTints();
    updateRouteControls();
    updateUi();
}

function refreshAgentTints() {
    Object.entries(agents).forEach(([name, sprite]) => {
        if (name === userControlledAgentName) {
            sprite.setTint(0x8ee8ff);
        } else if (name === selectedAgentName) {
            sprite.setTint(0xfff2a8);
        } else {
            sprite.clearTint();
        }
    });
}

function updateRouteControls() {
    const routeToggle = document.getElementById('route-toggle');
    const routeFocus = document.getElementById('route-focus');
    const controlAgent = document.getElementById('control-agent');
    const manualControlHint = document.getElementById('manual-control-hint');

    if (!routeToggle || !routeFocus || !controlAgent) {
        return;
    }

    routeToggle.textContent = routesVisible ? 'Hide Paths' : 'Show Paths';
    routeToggle.classList.toggle('active', routesVisible);
    routeFocus.textContent = focusedRouteAgent === selectedAgentName
        ? `All Paths`
        : `${selectedAgentName.split(' ')[0]}'s Path`;
    routeFocus.classList.toggle('active', focusedRouteAgent === selectedAgentName);
    controlAgent.textContent = userControlledAgentName === selectedAgentName ? 'Release' : 'Control';
    controlAgent.classList.toggle('active', userControlledAgentName === selectedAgentName);
    if (manualControlHint) {
        manualControlHint.hidden = userControlledAgentName !== selectedAgentName;
        manualControlHint.textContent = `Manual mode: use W/A/S/D. ${selectedAgentName.split(' ')[0]}'s auto plan is paused.`;
    }
}

function toggleUserControl(agentName) {
    if (!agents[agentName]) {
        return;
    }

    if (userControlledAgentName === agentName) {
        releaseUserControl(agentName);
        return;
    }

    enterUserControl(agentName);
}

function enterUserControl(agentName) {
    if (userControlledAgentName && userControlledAgentName !== agentName) {
        releaseUserControl(userControlledAgentName, { silent: true });
    }

    userControlledAgentName = agentName;
    const agent = agents[agentName];
    const state = agentState[agentName];

    if (state) {
        state.manualOverride = true;
        state.sleeping = false;
        state.goingToBed = false;
        state.returning = false;
        state.deciding = false;
        state.currentDay = currentPlanDay;
    }
    clearCurrentAction(agentName);

    cancelAgentMotion(agentName);
    hideStatusBubble(agentName);
    hideSleepBubble(agentName);
    hideAgentSpeech(agentName);
    setAgentPose(agentName, 'stand');
    snapUserAgentToWalkableNode(agentName);
    updateManualAgentLocation(agentName, true);
    agentPhases[agentName] = 'User controlled';
    clearManualControlKeys();
    focusGameForKeyboard();
    updateRouteControls();
    refreshAgentTints();
    updateUi();
    syncSimulationProgress({ force: true });
}

function releaseUserControl(agentName, options = {}) {
    if (userControlledAgentName !== agentName) {
        return;
    }

    const agent = agents[agentName];
    clearManualControlKeys();
    userControlledAgentName = null;

    if (agent) {
        agent.manualMoving = false;
        agent.isMoving = false;
        agent.isPreparingToMove = false;
        updateManualAgentLocation(agentName, true);
    }

    const state = agentState[agentName];
    if (state) {
        state.manualOverride = false;
    }

    reconcileAgentStateAfterManualRelease(agentName);
    applyAgentPoseForLocation(agentName, agentLocations[agentName]);

    if (!options.silent) {
        updateRouteControls();
        refreshAgentTints();
        updateUi();
        syncSimulationProgress({ force: true });
    }
}

function reconcileAgentStateAfterManualRelease(agentName) {
    const state = agentState[agentName];
    const scheduleInfo = agentSchedules[currentPlanDay]?.[agentName];

    if (!state) {
        return;
    }

    releaseReservedLocation(agentName);
    clearCurrentAction(agentName);
    state.currentDay = currentPlanDay;
    state.sleeping = false;
    state.goingToBed = false;
    state.deciding = false;
    state.nextDecisionRetryAt = null;
    state.manualOverride = false;

    if (!scheduleInfo) {
        agentPhases[agentName] = 'Ready';
        return;
    }

    const currentLocation = agentLocations[agentName] || '';
    const atHome = isOwnHomeLocation(agentName, currentLocation);
    const atSleepLocation = currentLocation === formatSleepLocation(agentName);

    state.wokeUp = true;
    state.moved = false;
    state.arrived = false;
    state.returning = false;
    state.returnedHome = atHome;

    if (currentTimeMinutes < scheduleInfo.bedTime) {
        // 白天：下一帧自动重新请求决策
        agentPhases[agentName] = 'Ready to decide next action';
        return;
    }

    state.sleeping = atSleepLocation;
    state.moved = atSleepLocation;
    agentPhases[agentName] = atSleepLocation ? 'Sleeping' : atHome ? 'Ready for bed' : 'Ready to return home';
}

function cancelAgentMotion(agentName) {
    const agent = agents[agentName];
    if (!agent) {
        return;
    }

    gameScene?.tweens?.killTweensOf(agent);
    if (walkingFrameTimers[agentName]) {
        walkingFrameTimers[agentName].remove(false);
        delete walkingFrameTimers[agentName];
    }
    clearActiveRoutes(line => line.agentName === agentName);
    agent.isMoving = false;
    agent.isPreparingToMove = false;
    agent.manualMoving = false;
    releaseReservedLocation(agentName);
}

function hideAgentSpeech(agentName) {
    const speechBubble = activeSpeechBubbles[agentName];
    if (!speechBubble) {
        return;
    }

    speechBubble.cancelled = true;
    speechBubble.typingEvent?.remove(false);
    speechBubble.fadeTimer?.remove(false);
    speechBubble.container?.destroy();
    delete activeSpeechBubbles[agentName];
}

function focusGameForKeyboard() {
    const canvas = gameScene?.game?.canvas || document.querySelector('canvas');
    if (!canvas) {
        return;
    }

    canvas.setAttribute('tabindex', '0');
    try {
        canvas.focus({ preventScroll: true });
    } catch (error) {
        canvas.focus();
    }
}

function clearManualControlKeys() {
    manualControlKeys = { w: false, a: false, s: false, d: false };
    manualControlPrimaryKey = null;
}

function handleUserControlKey(event) {
    if (!userControlledAgentName || !gameScene) {
        return;
    }

    const key = String(event.key || '').toLowerCase();
    const directions = {
        w: { x: 0, y: -1 },
        a: { x: -1, y: 0 },
        s: { x: 0, y: 1 },
        d: { x: 1, y: 0 }
    };
    const direction = directions[key];

    if (!direction) {
        return;
    }

    event.preventDefault();
    manualControlKeys[key] = true;
    manualControlPrimaryKey = key;
    focusGameForKeyboard();
}

function handleUserControlKeyUp(event) {
    if (!userControlledAgentName) {
        return;
    }

    const key = String(event.key || '').toLowerCase();
    if (!Object.prototype.hasOwnProperty.call(manualControlKeys, key)) {
        return;
    }

    event.preventDefault();
    manualControlKeys[key] = false;
    if (manualControlPrimaryKey === key) {
        manualControlPrimaryKey = Object.keys(manualControlKeys).find(candidate => manualControlKeys[candidate]) || null;
    }
}

function getManualControlDirection() {
    const directions = {
        w: { x: 0, y: -1 },
        a: { x: -1, y: 0 },
        s: { x: 0, y: 1 },
        d: { x: 1, y: 0 }
    };

    if (manualControlPrimaryKey && manualControlKeys[manualControlPrimaryKey]) {
        return directions[manualControlPrimaryKey];
    }

    const pressedKey = Object.keys(manualControlKeys).find(key => manualControlKeys[key]);
    return pressedKey ? directions[pressedKey] : null;
}

function getNodePixel(scene, nodeName) {
    const node = navNodes[nodeName];
    if (!node) {
        return null;
    }

    const wR = scene.sys.game.config.width / 160;
    const hR = scene.sys.game.config.height / 90;
    return { x: node.x * wR, y: node.y * hR };
}

function getNearestNavNodeForAgent(agentName) {
    const agent = agents[agentName];
    if (!agent) {
        return null;
    }

    const currentLocation = agentLocations[agentName];
    if (currentLocation && navNodes[currentLocation]) {
        return currentLocation;
    }

    let bestNode = null;
    let bestDistance = Infinity;
    Object.keys(navNodes).forEach(nodeName => {
        const point = getNodePixel(gameScene, nodeName);
        if (!point) {
            return;
        }

        const distance = Math.abs(agent.x - point.x) + Math.abs(agent.y - point.y);
        if (distance < bestDistance) {
            bestDistance = distance;
            bestNode = nodeName;
        }
    });

    return bestNode;
}

function getNearestNavNodeToPoint(x, y) {
    let bestNode = null;
    let bestDistance = Infinity;

    Object.keys(navNodes).forEach(nodeName => {
        const point = getNodePixel(gameScene, nodeName);
        if (!point) {
            return;
        }

        const distance = Math.abs(x - point.x) + Math.abs(y - point.y);
        if (distance < bestDistance) {
            bestDistance = distance;
            bestNode = nodeName;
        }
    });

    return { nodeName: bestNode, distance: bestDistance };
}

function getPixelDistanceToSegment(px, py, ax, ay, bx, by) {
    const dx = bx - ax;
    const dy = by - ay;
    const lengthSq = (dx * dx) + (dy * dy);
    const t = lengthSq === 0
        ? 0
        : Phaser.Math.Clamp((((px - ax) * dx) + ((py - ay) * dy)) / lengthSq, 0, 1);
    const closestX = ax + (dx * t);
    const closestY = ay + (dy * t);
    return Math.hypot(px - closestX, py - closestY);
}

function isManualWalkablePixel(x, y) {
    if (!gameScene || x < 0 || y < 0 || x > WORLD_W || y > WORLD_H) {
        return false;
    }

    return getManualWalkSegments().some(([from, to]) =>
        getPixelDistanceToSegment(x, y, from.x, from.y, to.x, to.y) <= USER_CONTROL_WALK_RADIUS
    );
}

function getManualWalkSegments() {
    const segments = [];

    navEdges.forEach(([fromNode, toNode]) => {
        const from = getNodePixel(gameScene, fromNode);
        const to = getNodePixel(gameScene, toNode);
        if (!from || !to) {
            return;
        }

        const sameX = Math.abs(from.x - to.x) <= 1;
        const sameY = Math.abs(from.y - to.y) <= 1;
        if (sameX || sameY) {
            segments.push([from, to]);
            return;
        }

        const horizontalFirstCorner = { x: to.x, y: from.y };
        const verticalFirstCorner = { x: from.x, y: to.y };
        segments.push([from, horizontalFirstCorner]);
        segments.push([horizontalFirstCorner, to]);
        segments.push([from, verticalFirstCorner]);
        segments.push([verticalFirstCorner, to]);
    });

    return segments;
}

function snapUserAgentToWalkableNode(agentName) {
    const agent = agents[agentName];
    if (!agent || isManualWalkablePixel(agent.x, agent.y)) {
        return;
    }

    const nearest = getNearestNavNodeToPoint(agent.x, agent.y);
    const point = nearest.nodeName ? getNodePixel(gameScene, nearest.nodeName) : null;
    if (!point) {
        return;
    }

    agent.x = point.x;
    agent.y = point.y;
    agentLocations[agentName] = nearest.nodeName;
}

function pickManualNeighbor(currentNode, direction) {
    const current = navNodes[currentNode];
    if (!current) {
        return null;
    }

    let best = null;
    let bestScore = 0;
    (navGraph[currentNode] || []).forEach(candidateName => {
        const candidate = navNodes[candidateName];
        if (!candidate) {
            return;
        }

        const dx = candidate.x - current.x;
        const dy = candidate.y - current.y;
        const major = (direction.x * dx) + (direction.y * dy);
        const sideways = direction.x ? Math.abs(dy) : Math.abs(dx);
        const score = major - (sideways * 0.35);

        if (major > 0.1 && score > bestScore) {
            best = candidateName;
            bestScore = score;
        }
    });

    return best;
}

function updateManualControl(delta) {
    if (!userControlledAgentName || !gameScene) {
        return;
    }

    const direction = getManualControlDirection();
    if (!direction) {
        stopUserControlledAgent();
        return;
    }

    moveUserControlledAgent(direction, delta);
}

function stopUserControlledAgent() {
    const agentName = userControlledAgentName;
    const agent = agents[agentName];
    if (!agent || !agent.manualMoving) {
        return;
    }

    agent.manualMoving = false;
    agent.isMoving = false;
    updateManualAgentLocation(agentName);
    setAgentPose(agentName, 'stand');
    agentPhases[agentName] = 'User controlled';
    updateUi();
    syncSimulationProgress({ force: true });
}

function updateManualAgentLocation(agentName, force = false) {
    const agent = agents[agentName];
    if (!agent) {
        return;
    }

    const nearest = getNearestNavNodeToPoint(agent.x, agent.y);
    if (nearest.nodeName && (force || nearest.distance <= USER_CONTROL_WALK_RADIUS + 8)) {
        agentLocations[agentName] = nearest.nodeName;
    }
}

function moveUserControlledAgent(direction, delta) {
    const agentName = userControlledAgentName;
    const agent = agents[agentName];

    if (!agent || agent.isPreparingToMove) {
        return;
    }

    snapUserAgentToWalkableNode(agentName);
    const seconds = Math.max(0.001, (delta || 16.67) / 1000);
    const distance = USER_CONTROL_SPEED_PIXELS_PER_SECOND * seconds;
    const nextX = clampNumber(agent.x + (direction.x * distance), 0, WORLD_W);
    const nextY = clampNumber(agent.y + (direction.y * distance), 0, WORLD_H);

    if (!isManualWalkablePixel(nextX, nextY)) {
        if (agent.manualMoving) {
            agent.manualMoving = false;
            agent.isMoving = false;
            setAgentPose(agentName, 'stand');
            syncSimulationProgress({ force: true });
        }
        agentPhases[agentName] = 'Manual path blocked';
        updateUi();
        return;
    }

    hideStatusBubble(agentName);
    hideSleepBubble(agentName);
    if (!agent.manualMoving) {
        startWalkingAnimation(agentName);
    }

    agent.x = nextX;
    agent.y = nextY;
    agent.manualMoving = true;
    agent.isMoving = true;
    agentPhases[agentName] = 'User controlled';
    updateManualAgentLocation(agentName);

    const now = Date.now();
    if (now - manualControlLastSyncAt >= USER_CONTROL_SYNC_INTERVAL_MS) {
        manualControlLastSyncAt = now;
        updateUi();
        syncSimulationProgress({ force: true });
    }
}

function setCurrentAction(agentName, actionInfo) {
    agentCurrentActions[agentName] = actionInfo;
    if (selectedAgentName === agentName) {
        updateUi();
    }
}

function clearCurrentAction(agentName) {
    delete agentCurrentActions[agentName];
    if (selectedAgentName === agentName) {
        updateUi();
    }
}

function updateUi() {
    const statusText = simulationPaused
        ? 'Paused'
        : simulationStarted
            ? 'Running'
            : 'Ready';

    document.getElementById('day-label').textContent = 'Valentown';
    document.getElementById('status-label').textContent = statusText;
    document.getElementById('start-sim').disabled = !progressLoaded || (simulationStarted && !simulationPaused);
    document.getElementById('pause-sim').disabled = !simulationStarted;
    document.getElementById('pause-sim').textContent = simulationPaused ? 'Resume' : 'Pause';
    updateClockUi();

    document.querySelectorAll('.agent-pill').forEach(button => {
        button.classList.toggle('active', button.textContent === selectedAgentName);
        button.classList.toggle('controlled', button.textContent === userControlledAgentName);
    });

    refreshAgentTints();
    updateRouteControls();
    updateAgentPanel();
}

function updateAgentPanel() {
    const profile = agentProfiles[selectedAgentName] || {};
    const displayDay = currentPlanDay;
    const currentAction = agentCurrentActions[selectedAgentName] || {};
    const conversations = agentConversations[selectedAgentName]?.[displayDay] || [];

    document.getElementById('agent-name').textContent = selectedAgentName;
    document.getElementById('agent-role').textContent = profile.role || 'Resident';
    document.getElementById('agent-location').textContent = formatLocation(agentLocations[selectedAgentName] || profile.home || 'Unknown');
    document.getElementById('agent-state').textContent = agentPhases[selectedAgentName] || 'Ready';
    document.getElementById('agent-plan').textContent = currentAction.action || 'Deciding what to do next.';
    document.getElementById('agent-destination').textContent = currentAction.destination ? formatLocation(currentAction.destination) : 'Waiting for simulation';
    document.getElementById('agent-schedule').textContent = formatAgentSchedule(selectedAgentName, displayDay);

    const conversationList = document.getElementById('conversation-list');
    conversationList.innerHTML = '';

    if (!conversations.length) {
        const empty = document.createElement('li');
        empty.className = 'empty-message';
        empty.textContent = 'No conversations recorded for this day yet.';
        conversationList.appendChild(empty);
        return;
    }

    conversations.forEach(item => {
        const li = document.createElement('li');
        li.innerHTML = `<strong>${escapeHtml(item.with)}</strong><span>${escapeHtml(item.text)}</span>`;
        conversationList.appendChild(li);
    });
}

function updateClockUi() {
    const timeLabel = document.getElementById('time-label');
    const clockPhase = document.getElementById('clock-phase');
    const progressBar = document.getElementById('time-progress-bar');

    if (!timeLabel || !clockPhase || !progressBar) {
        return;
    }

    timeLabel.textContent = formatSimTime(currentTimeMinutes);
    clockPhase.textContent = getDayPhase(currentTimeMinutes);

    const dayProgress = Phaser.Math.Clamp(
        (currentTimeMinutes - DAY_START_MINUTES) / (DAY_END_MINUTES - DAY_START_MINUTES),
        0,
        1
    );
    progressBar.style.width = `${Math.round(dayProgress * 100)}%`;
}

function formatAgentSchedule(agentName, day) {
    const schedule = agentSchedules[day]?.[agentName];
    if (!schedule) {
        return 'Waiting for day to start';
    }

    return `Wake ${formatSimTime(schedule.wakeTime)} | Bed ${formatSimTime(schedule.bedTime)}`;
}

function reserveDestination(agentName, requestedLocation) {
    releaseReservedLocation(agentName);

    const normalizedLocation = normalizeRequestedLocation(agentName, requestedLocation);
    const assignedLocation = findAvailableLocation(normalizedLocation, agentName);
    if (!assignedLocation) {
        return normalizedLocation;
    }

    occupiedLocations[assignedLocation] = agentName;
    agentReservations[agentName] = assignedLocation;
    return assignedLocation;
}

function normalizeRequestedLocation(agentName, requestedLocation) {
    const [areaName, pointName] = String(requestedLocation || '').split('.');
    const legacyHomeMap = {
        Parker_home: agentName === 'Ella Parker' ? 'Ella_home' : 'Ron_home',
        Morgan_home: 'Arthur_home',
        Thompson_home: 'Mia_home',
        Harries_home: homeAreaByAgent[agentName] || 'Emma_home'
    };
    const mappedArea = legacyHomeMap[areaName];

    if (!mappedArea || !pointName) {
        return normalizePlayableDestination(agentName, requestedLocation);
    }

    const mappedLocation = `${mappedArea}.${pointName}`;
    if (locationToNode[mappedLocation]) {
        return normalizePlayableDestination(agentName, mappedLocation);
    }

    return normalizePlayableDestination(agentName, `${mappedArea}.Living_room`);
}

function normalizePlayableDestination(agentName, requestedLocation) {
    const locationName = String(requestedLocation || '');
    const [areaName, roomName] = locationName.split('.');

    if (!areaName || !roomName || !locationToNode[locationName]) {
        return locationName;
    }

    if (isPrivateVisitorLocation(agentName, locationName)) {
        return findFirstExistingLocation([
            `${areaName}.Living_room`,
            `${areaName}.Sofa`,
            `${areaName}.Chair`,
            `${areaName}.Porch`
        ]) || locationName;
    }

    return resolveSurfaceInteractionLocation(locationName);
}

function isHomeArea(areaName) {
    return Object.values(homeAreaByAgent).includes(areaName);
}

function isPrivateVisitorLocation(agentName, locationName) {
    const [areaName, roomName] = String(locationName || '').split('.');
    return isHomeArea(areaName) && privateHomeRooms.has(roomName) && homeAreaByAgent[agentName] !== areaName;
}

function isSurfaceLocation(locationName) {
    const roomName = String(locationName || '').split('.')[1];
    return Boolean(surfaceInteractionFallbacks[roomName]);
}

function resolveSurfaceInteractionLocation(locationName) {
    const [areaName, roomName] = String(locationName || '').split('.');
    const fallbacks = surfaceInteractionFallbacks[roomName];

    if (!fallbacks) {
        return locationName;
    }

    return findFirstExistingLocation(fallbacks.map(fallbackRoom => `${areaName}.${fallbackRoom}`)) || locationName;
}

function findFirstExistingLocation(locationNames) {
    return locationNames.find(locationName => locationToNode[locationName]);
}

function releaseReservedLocation(agentName) {
    const reservedLocation = agentReservations[agentName];
    if (!reservedLocation) {
        return;
    }

    if (occupiedLocations[reservedLocation] === agentName) {
        occupiedLocations[reservedLocation] = null;
    }
    delete agentReservations[agentName];
}

function findAvailableLocation(requestedLocation, agentName) {
    const candidates = getSameAreaLocations(requestedLocation, agentName);

    return candidates.find(locationName => !isLocationOccupied(locationName, agentName)) || null;
}

function getSameAreaLocations(locationName, agentName) {
    const areaName = getAreaName(locationName);
    const sameArea = Object.keys(locationToNode).filter(candidate =>
        getAreaName(candidate) === areaName &&
        !sleepOnlyLocations.has(candidate) &&
        !isPrivateVisitorLocation(agentName, candidate) &&
        !isSurfaceLocation(candidate)
    );

    return [
        locationName,
        ...sameArea.filter(candidate => candidate !== locationName)
    ];
}

function isLocationOccupied(locationName, agentName) {
    const occupant = occupiedLocations[locationName];
    if (occupant && occupant !== agentName) {
        return true;
    }

    const point = navNodes[locationName];
    if (!point) {
        return true;
    }

    return Object.entries(agentReservations).some(([reservedAgent, reservedLocation]) => {
        if (reservedAgent === agentName) {
            return false;
        }

        const reservedPoint = navNodes[reservedLocation];
        return reservedPoint && reservedPoint.x === point.x && reservedPoint.y === point.y;
    });
}

function getAreaName(locationName) {
    return locationName.split('.')[0];
}

function rememberConversation(day, conversation) {
    [
        { name: conversation.initiator, with: conversation.responder, text: conversation.question },
        { name: conversation.responder, with: conversation.initiator, text: conversation.answer }
    ].forEach(entry => {
        if (!agentConversations[entry.name]) {
            agentConversations[entry.name] = {};
        }
        if (!agentConversations[entry.name][day]) {
            agentConversations[entry.name][day] = [];
        }
        agentConversations[entry.name][day].push({
            with: entry.with,
            text: entry.text
        });
    });

    updateUi();
}

function formatLocation(location) {
    return location.replaceAll('_', ' ').replace('.', ' / ');
}

function getRoomName(locationName) {
    return String(locationName || '').split('.').pop() || '';
}

function formatRoomName(locationName) {
    const roomName = getRoomName(locationName);
    const roomLabels = {
        Kitchen: 'kitchen',
        Dining_table: 'dining table',
        Dinning_room: 'dining room',
        Living_room: 'living room',
        Sofa: 'sofa',
        Chair: 'chair',
        Bed: 'bedroom',
        Toilet: 'bathroom',
        Bookshelf: 'bookshelf',
        Reading_chair: 'reading chair',
        Desk: 'desk',
        Study_corner: 'study corner',
        Window: 'window',
        Porch: 'front door'
    };

    return roomLabels[roomName] || formatLocation(roomName);
}

function isOwnHomeLocation(agentName, locationName) {
    return getAreaName(locationName || '') === homeAreaByAgent[agentName];
}

function formatMovementDestination(agentName, targetLocation) {
    if (isOwnHomeLocation(agentName, targetLocation)) {
        return formatRoomName(targetLocation);
    }

    return formatLocation(targetLocation);
}

function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = value || '';
    return div.innerHTML;
}

function getDestinationArea(locationName) {
    return formatLocation(getAreaName(locationName || 'Unknown'));
}

function buildMovementSpeech(agentName, targetLocation, actionText = 'do an activity') {
    const taskText = String(actionText || 'do an activity').trim() || 'do an activity';
    return `I am going to ${formatMovementDestination(agentName, targetLocation)} to ${taskText}.`;
}

function getCurrentActionText(agentName, fallbackAction = 'do an activity') {
    const action = agentCurrentActions[agentName]?.action;
    return action ? String(action).trim() : fallbackAction;
}

function announceMovementThen(scene, agentName, targetLocation, actionText, onReady) {
    const agent = agents[agentName];
    if (!agent || agentName === userControlledAgentName || agent.isMoving || agent.isPreparingToMove) {
        return false;
    }

    agent.isPreparingToMove = true;
    agentPhases[agentName] = 'Preparing to move';
    hideStatusBubble(agentName);
    updateUi();

    showAgentSpeech.call(scene, agentName, buildMovementSpeech(agentName, targetLocation, actionText), () => {
        const currentAgent = agents[agentName];
        if (!currentAgent || agentName === userControlledAgentName) {
            if (currentAgent) {
                currentAgent.isPreparingToMove = false;
            }
            return;
        }

        currentAgent.isPreparingToMove = false;
        onReady();
    });

    return true;
}

function buildTomorrowThought(agentName) {
    return 'Time to sleep. I will decide what to do tomorrow after I wake up.';
}

function formatSimTime(minutes) {
    const normalized = Math.max(0, Math.round(minutes));
    const hours24 = Math.floor(normalized / 60) % 24;
    const mins = normalized % 60;
    const period = hours24 >= 12 ? 'PM' : 'AM';
    const hours12 = hours24 % 12 || 12;

    return `${hours12}:${String(mins).padStart(2, '0')} ${period}`;
}

function getDayPhase(minutes) {
    if (minutes < 9 * 60) return 'Morning';
    if (minutes < 12 * 60) return 'Late Morning';
    if (minutes < 17 * 60) return 'Afternoon';
    if (minutes < 21 * 60) return 'Evening';
    return 'Night';
}

function scaledDuration(duration) {
    return duration / simulationSpeed;
}

function schedule(scene, delay, callback) {
    return scene.time.delayedCall(scaledDuration(delay), callback);
}

function resetInternalStateClock(agentName) {
    lastInternalStateSyncMinutes[agentName] = currentTimeMinutes;
}

function syncAgentActionState(agentName, locationName, actionText = '', options = {}) {
    const previousMinutes = lastInternalStateSyncMinutes[agentName] ?? currentTimeMinutes;
    const elapsedGameMinutes = Math.max(0, Math.round(currentTimeMinutes - previousMinutes));
    lastInternalStateSyncMinutes[agentName] = currentTimeMinutes;

    return fetch(`${BACKEND_BASE_URL}/complete_agent_action`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            agent_name: agentName,
            location: locationName,
            action: actionText,
            elapsed_game_minutes: elapsedGameMinutes,
            day: currentPlanDay,
            time: formatSimTime(currentTimeMinutes),
            sleeping: Boolean(options.sleeping),
            social_contact: Boolean(options.social_contact)
        })
    })
        .then(response => response.ok ? response.json() : null)
        .then(data => {
            if (data?.triggers?.length) {
                console.log(`${agentName} internal triggers:`, data.triggers);
            }
            return data;
        })
        .catch(error => {
            console.warn(`Could not sync internal state for ${agentName}:`, error);
            return null;
        });
}

function getAgentLocationSnapshot() {
    return { ...agentLocations };
}

function getAgentPositionSnapshot() {
    return Object.fromEntries(
        Object.entries(agents).map(([agentName, agent]) => [
            agentName,
            {
                x: Math.round(agent.x * 100) / 100,
                y: Math.round(agent.y * 100) / 100
            }
        ])
    );
}

function getAgentPoseSnapshot() {
    return Object.fromEntries(
        Object.entries(agents).map(([agentName, agent]) => [
            agentName,
            agent.poseState || 'stand'
        ])
    );
}

function hasAgentSnapshot(config) {
    return Boolean(
        config &&
        (
            Object.keys(config.agent_locations || {}).length ||
            Object.keys(config.agent_positions || {}).length
        )
    );
}

function applyAgentProgressSnapshot(scene, config) {
    if (!hasAgentSnapshot(config)) {
        return false;
    }

    const savedLocations = config.agent_locations || {};
    const savedPositions = config.agent_positions || {};
    const savedPoses = config.agent_pose_states || {};

    Object.keys(agents).forEach(agentName => {
        const agent = agents[agentName];
        const savedLocation = savedLocations[agentName];
        const savedPosition = savedPositions[agentName];

        if (savedLocation && getLocationCoords(savedLocation)) {
            agentLocations[agentName] = savedLocation;
        }

        if (
            savedPosition &&
            Number.isFinite(Number(savedPosition.x)) &&
            Number.isFinite(Number(savedPosition.y))
        ) {
            agent.x = Number(savedPosition.x);
            agent.y = Number(savedPosition.y);
        } else {
            const coords = getLocationCoords(agentLocations[agentName]);
            if (coords) {
                const wR = scene.sys.game.config.width / 160;
                const hR = scene.sys.game.config.height / 90;
                agent.x = coords.x * wR;
                agent.y = coords.y * hR;
            }
        }

        const pose = savedPoses[agentName] || (agentLocations[agentName] === formatSleepLocation(agentName) ? 'lie' : 'stand');
        setAgentPose(agentName, pose);
        if (pose === 'lie') {
            positionAgentForSleep(scene, agentName);
            showSleepBubble(scene, agentName);
        } else {
            hideSleepBubble(agentName);
            applyAgentPoseForLocation(agentName, agentLocations[agentName]);
        }
    });

    restoredAgentSnapshot = {
        day: config.current_life_day,
        time: config.current_time_minutes,
        agent_locations: savedLocations,
        agent_positions: savedPositions,
        agent_pose_states: savedPoses
    };
    updateUi();
    return true;
}

function syncSimulationProgress(options = {}) {
    if (!progressLoaded) {
        return;
    }

    const now = Date.now();
    if (!options.force && now - lastProgressSyncAt < 10000) {
        return;
    }
    lastProgressSyncAt = now;

    fetch(`${BACKEND_BASE_URL}/update_simulation_progress`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            current_life_day: currentPlanDay,
            current_time_minutes: Math.round(currentTimeMinutes),
            status: simulationStarted && !simulationPaused ? 'running' : simulationPaused ? 'paused' : 'ready',
            agent_locations: getAgentLocationSnapshot(),
            agent_positions: getAgentPositionSnapshot(),
            agent_pose_states: getAgentPoseSnapshot()
        })
    }).catch(error => {
        console.warn('Could not sync simulation progress:', error);
    });
}

function getSimulationConfig() {
    return fetch(`${BACKEND_BASE_URL}/get_config`)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .catch(error => {
            console.warn("Could not fetch simulation config, using frontend defaults:", error);
            return null;
        });
}

// 从后端获取代理的每日计划
// 请求后端为代理决定下一步动作（需求驱动决策）
function fetchNextDecision(agentName, lastAction = null) {
    return fetch(`${BACKEND_BASE_URL}/decide_next_action`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            agent_name: agentName,
            day: currentPlanDay,
            time: formatSimTime(currentTimeMinutes),
            current_location: agentLocations[agentName] || null,
            last_action: lastAction
        })
    })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        });
}

// 请求后端为两位同区域的代理生成一段对话
function fetchConversation(initiatorName, responderName, location) {
    return fetch(`${BACKEND_BASE_URL}/generate_conversation`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            initiator: initiatorName,
            responder: responderName,
            location: location,
            day: currentPlanDay
        })
    })
        .then(response => response.ok ? response.json() : null)
        .catch(error => {
            console.warn('Conversation generation failed:', error);
            return null;
        });
}

// 通知后端进入新的一天（触发反思与进度持久化）
function notifyNewDay(lifeDay) {
    return fetch(`${BACKEND_BASE_URL}/start_new_day`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ life_day: lifeDay })
    })
        .then(response => response.ok ? response.json() : null)
        .catch(error => {
            console.warn('Failed to notify backend of new day:', error);
            return null;
        });
}

// 从后端获取当天的所有对话记录
function getDailyConversations(day, location = null) {
    // 构建请求URL
    let url = `${BACKEND_BASE_URL}/get_conversations?life_day=${day}`;
    if (location) {
        url += `&location=${encodeURIComponent(location)}`;
    }

    return fetch(url)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            // 验证数据结构
            if (!data || !Array.isArray(data.conversations)) {
                console.error("Invalid conversation data structure:", data);
                return [];
            }
            
            return data.conversations;
        })
        .catch(error => {
            console.error("Error fetching conversations:", error);
            return []; // 返回空数组保持前端稳定性
        });
}

// 显示代理的说话气泡
function clampNumber(value, min, max) {
    if (min > max) {
        return (min + max) / 2;
    }

    return Phaser.Math.Clamp(value, min, max);
}

function getCameraWorldView(scene, margin = 8) {
    const camera = scene?.cameras?.main || gameScene?.cameras?.main;
    const left = camera?.worldView?.x ?? camera?.scrollX ?? 0;
    const top = camera?.worldView?.y ?? camera?.scrollY ?? 0;
    const width = camera?.worldView?.width ?? camera?.width ?? VIEW_W;
    const height = camera?.worldView?.height ?? camera?.height ?? WORLD_H;

    return {
        left: left + margin,
        top: top + margin,
        right: left + width - margin,
        bottom: top + height - margin
    };
}

function getFloatingBubblePosition(scene, agent, localBounds, aboveOffset, belowOffset, floatPadding = 0) {
    const view = getCameraWorldView(scene, 10);
    const minX = view.left - localBounds.left;
    const maxX = view.right - localBounds.right;
    const minY = view.top - localBounds.top + floatPadding;
    const maxY = view.bottom - localBounds.bottom;
    const aboveY = agent.y - aboveOffset;
    const belowY = agent.y + belowOffset;
    const preferredY = aboveY + localBounds.top - floatPadding < view.top ? belowY : aboveY;

    return {
        x: clampNumber(agent.x, minX, maxX),
        y: clampNumber(preferredY, minY, maxY)
    };
}

function showAgentSpeech(agentName, speechContent, onComplete) {
    const agent = agents[agentName];
    if (!agent) return;

    const previousBubble = activeSpeechBubbles[agentName];
    if (previousBubble) {
        previousBubble.cancelled = true;
        previousBubble.typingEvent?.remove(false);
        previousBubble.fadeTimer?.remove(false);
        previousBubble.container?.destroy();
        delete activeSpeechBubbles[agentName];
    }

    // 先用临时文本测量实际尺寸
    const tempText = this.add.text(0, 0, speechContent, {
        font: '12px Arial',
        fill: '#000',
        wordWrap: { width: 150, useAdvancedWrap: true },
    }).setVisible(false);
    
    const padding = 6;
    const textWidth = tempText.width;
    const textHeight = tempText.height;
    tempText.destroy();

    // 计算气泡位置
    const rectW = textWidth + padding * 2;
    const rectH = textHeight + padding * 2;
    const radius = 8;
    const tailWidth = 8;
    const tailHeight = 6;
    const view = getCameraWorldView(this, 10);
    const x = agent.x;
    const rectX = clampNumber(x - (rectW / 2), view.left, view.right - rectW);
    const aboveRectY = agent.y - 56 - rectH;
    const belowRectY = agent.y + 28;
    const fitsAbove = aboveRectY >= view.top;
    const fitsBelow = belowRectY + rectH + tailHeight <= view.bottom;
    const placeBelow = !fitsAbove && fitsBelow;
    const rectY = placeBelow
        ? belowRectY
        : clampNumber(aboveRectY, view.top, view.bottom - rectH - tailHeight);
    const tailX = clampNumber(
        x,
        rectX + radius + (tailWidth / 2),
        rectX + rectW - radius - (tailWidth / 2)
    );

    // 创建气泡背景
    const bubbleBg = this.add.graphics();
    bubbleBg.fillStyle(0xffffff, 0.9);
    bubbleBg.lineStyle(2, 0xaaaaaa, 1);
    bubbleBg.fillRoundedRect(rectX, rectY, rectW, rectH, radius);
    bubbleBg.strokeRoundedRect(rectX, rectY, rectW, rectH, radius);

    // 创建对话尾部
    if (placeBelow) {
        bubbleBg.fillTriangle(
            tailX - tailWidth / 2, rectY,
            tailX + tailWidth / 2, rectY,
            tailX, rectY - tailHeight
        );
        bubbleBg.strokeTriangle(
            tailX - tailWidth / 2, rectY,
            tailX + tailWidth / 2, rectY,
            tailX, rectY - tailHeight
        );
    } else {
        bubbleBg.fillTriangle(
            tailX - tailWidth / 2, rectY + rectH,
            tailX + tailWidth / 2, rectY + rectH,
            tailX, rectY + rectH + tailHeight
        );
        bubbleBg.strokeTriangle(
            tailX - tailWidth / 2, rectY + rectH,
            tailX + tailWidth / 2, rectY + rectH,
            tailX, rectY + rectH + tailHeight
        );
    }

    // 创建实际显示文本（初始为空）
    const bubbleText = this.add.text(
        rectX + padding,
        rectY + padding,
        '',  // 初始为空文本
        {
            font: '12px Arial',
            fill: '#000',
            wordWrap: { width: 150, useAdvancedWrap: true }
        }
    );

    const container = this.add.container(0, 0, [bubbleBg, bubbleText]);
    container.alpha = 0;
    const speechBubble = { container, cancelled: false, typingEvent: null, fadeTimer: null };
    activeSpeechBubbles[agentName] = speechBubble;
    
    // 淡入动画
    this.tweens.add({ 
        targets: container,
        alpha: 1,
        duration: 200
    });

    // 逐字显示逻辑
    let currentLength = 0;
    const charDelay = 45; // 每个字符间隔（毫秒）
    speechBubble.typingEvent = this.time.addEvent({
        delay: scaledDuration(charDelay),
        repeat: speechContent.length - 1,
        callback: () => {
            if (speechBubble.cancelled) {
                return;
            }
            currentLength++;
            bubbleText.setText(speechContent.substr(0, currentLength));
        }
    });

    // 完整显示4秒后淡出（总等待时间 = 文字显示时间 + 4秒）
    const totalTypingTime = speechContent.length * charDelay;
    speechBubble.fadeTimer = schedule(this, totalTypingTime + 3000, () => {
        if (speechBubble.cancelled || activeSpeechBubbles[agentName] !== speechBubble) {
            return;
        }

        this.tweens.add({
            targets: container,
            alpha: 0,
            duration: scaledDuration(200),
            onComplete: () => {
                if (speechBubble.cancelled || activeSpeechBubbles[agentName] !== speechBubble) {
                    return;
                }

                container.destroy();
                delete activeSpeechBubbles[agentName];
                if (typeof onComplete === 'function') {
                    onComplete();
                }
            }
        });
    });
}

function showSleepBubble(scene, agentName) {
    hideSleepBubble(agentName);

    const agent = agents[agentName];
    if (!agent) {
        return;
    }

    const position = getFloatingBubblePosition(
        scene,
        agent,
        { left: -28, right: 31, top: -17, bottom: 32 },
        76,
        34,
        6
    );
    const x = position.x;
    const y = position.y;
    const bubbleBg = scene.add.graphics();
    bubbleBg.fillStyle(0xf8fbff, 0.95);
    bubbleBg.lineStyle(2, 0x8da0b1, 1);
    bubbleBg.fillRoundedRect(-28, -17, 56, 32, 13);
    bubbleBg.strokeRoundedRect(-28, -17, 56, 32, 13);
    bubbleBg.fillStyle(0xf8fbff, 0.95);
    bubbleBg.fillCircle(18, 20, 5);
    bubbleBg.fillCircle(28, 29, 3);

    const bubbleText = scene.add.text(0, -1, 'zZz', {
        font: '15px Arial',
        fill: '#24384d',
        fontStyle: 'bold'
    }).setOrigin(0.5);

    const moon = scene.add.text(-16, -1, '•', {
        font: '18px Arial',
        fill: '#f5d86d'
    }).setOrigin(0.5);

    const container = scene.add.container(x, y, [bubbleBg, moon, bubbleText]).setDepth(8);
    container.alpha = 0;
    sleepBubbles[agentName] = container;
    sleepBubbleTweens[agentName] = [
        scene.tweens.add({
            targets: container,
            y: y - 6,
            duration: scaledDuration(900),
            yoyo: true,
            repeat: -1,
            ease: 'Sine.easeInOut'
        }),
        scene.tweens.add({
            targets: bubbleText,
            scale: 1.15,
            alpha: 0.72,
            duration: scaledDuration(700),
            yoyo: true,
            repeat: -1,
            ease: 'Sine.easeInOut'
        }),
        scene.tweens.add({
            targets: container,
            alpha: 1,
            duration: scaledDuration(250)
        })
    ];
}

function hideSleepBubble(agentName) {
    if (!sleepBubbles[agentName]) {
        return;
    }

    (sleepBubbleTweens[agentName] || []).forEach(tween => tween.stop());
    delete sleepBubbleTweens[agentName];
    sleepBubbles[agentName].destroy();
    delete sleepBubbles[agentName];
}

function getStatusEmoji(locationName, actionText = '') {
    const source = `${locationName || ''} ${actionText || ''}`.toLowerCase();
    const rules = [
        { tokens: ['chat', 'talk', 'conversation', 'greet'], emoji: '💬' },
        { tokens: ['coffee', 'café', 'cafe', 'bar'], emoji: '☕' },
        { tokens: ['tv', 'television', 'watch', 'living_room', 'sofa', '客厅'], emoji: '📺' },
        { tokens: ['kitchen', 'cook', 'cooking', 'meal', '厨房'], emoji: '🍳' },
        { tokens: ['dining', 'dinning', 'eat', 'lunch', 'dinner', 'breakfast', '餐'], emoji: '🍽️' },
        { tokens: ['bookshelf', 'read', 'reading', 'book', '书'], emoji: '📖' },
        { tokens: ['desk', 'study', 'teach', 'teacher', 'homework', 'work', '学习'], emoji: '✏️' },
        { tokens: ['pharmacy', 'medicine', 'prescription', 'consult', '药'], emoji: '💊' },
        { tokens: ['supermarket', 'shop', 'checkout', 'fruit', 'shelf', 'restock', 'storage', '超市'], emoji: '🛒' },
        { tokens: ['park', 'bench', 'tree', 'flower', 'playground', 'river', 'bridge', 'walk', '公园'], emoji: '🌳' },
        { tokens: ['toilet', 'bathroom', '厕所'], emoji: '🚿' },
        { tokens: ['bed', 'rest', 'sleep', '床'], emoji: '🛏️' },
        { tokens: ['window'], emoji: '🪟' },
        { tokens: ['chair', 'seat', 'sit'], emoji: '🪑' },
        { tokens: ['home', '回家', '在家'], emoji: '🏠' }
    ];
    const matches = [];

    rules.forEach(rule => {
        if (rule.tokens.some(token => source.includes(token)) && !matches.includes(rule.emoji)) {
            matches.push(rule.emoji);
        }
    });

    return (matches.length ? matches : ['🙂']).slice(0, 2).join('');
}

function showStatusEmoji(scene, agentName, locationName, actionText = '') {
    hideStatusBubble(agentName);

    const agent = agents[agentName];
    if (!agent || agentState[agentName]?.sleeping) {
        return;
    }

    const emoji = getStatusEmoji(locationName, actionText);
    const position = getFloatingBubblePosition(
        scene,
        agent,
        { left: -28, right: 30, top: -18, bottom: 32 },
        84,
        38,
        5
    );
    const x = position.x;
    const y = position.y;
    const bubbleBg = scene.add.graphics();
    bubbleBg.fillStyle(0xffffff, 0.92);
    bubbleBg.lineStyle(2, 0x9fb2c6, 1);
    bubbleBg.fillRoundedRect(-28, -18, 56, 36, 14);
    bubbleBg.strokeRoundedRect(-28, -18, 56, 36, 14);
    bubbleBg.fillStyle(0xffffff, 0.92);
    bubbleBg.fillCircle(17, 21, 5);
    bubbleBg.fillCircle(27, 29, 3);

    const bubbleText = scene.add.text(0, -1, emoji, {
        font: '22px "Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji", Arial',
        align: 'center'
    }).setOrigin(0.5);

    const container = scene.add.container(x, y, [bubbleBg, bubbleText]).setDepth(9);
    container.alpha = 0;
    activeStatusBubbles[agentName] = container;
    statusBubbleTweens[agentName] = [
        scene.tweens.add({
            targets: container,
            y: y - 5,
            duration: scaledDuration(1100),
            yoyo: true,
            repeat: -1,
            ease: 'Sine.easeInOut'
        }),
        scene.tweens.add({
            targets: bubbleText,
            scale: 1.12,
            duration: scaledDuration(900),
            yoyo: true,
            repeat: -1,
            ease: 'Sine.easeInOut'
        }),
        scene.tweens.add({
            targets: container,
            alpha: 1,
            duration: scaledDuration(220)
        })
    ];
}

function hideStatusBubble(agentName) {
    if (!activeStatusBubbles[agentName]) {
        return;
    }

    (statusBubbleTweens[agentName] || []).forEach(tween => tween.stop());
    delete statusBubbleTweens[agentName];
    activeStatusBubbles[agentName].destroy();
    delete activeStatusBubbles[agentName];
}

function getAgentTextureKey(agentName, pose = 'stand') {
    const baseKey = agentTextureKeyByName[agentName];
    if (!baseKey || pose === 'stand') {
        return baseKey;
    }

    return `${baseKey}_${pose}`;
}

function setAgentPose(agentName, pose) {
    const agent = agents[agentName];
    const textureKey = getAgentTextureKey(agentName, pose);
    const settings = agentPoseSettings[pose] || agentPoseSettings.stand;
    const sleepSettings = pose === 'lie' ? sleepPoseOverrides[agentName] || {} : {};

    if (!agent || !textureKey) {
        return;
    }

    if (!String(pose).startsWith('walk') && walkingFrameTimers[agentName]) {
        walkingFrameTimers[agentName].remove(false);
        delete walkingFrameTimers[agentName];
    }

    if (agent.texture?.key !== textureKey) {
        agent.setTexture(textureKey);
    }
    agent.setOrigin(settings.originX, settings.originY);
    agent.setScale(settings.scale);
    agent.setAngle(sleepSettings.angle ?? settings.angle);
    agent.poseState = pose;
}

function startWalkingAnimation(agentName) {
    const agent = agents[agentName];
    if (!agent || walkingFrameTimers[agentName]) {
        return;
    }

    let frameIndex = 0;
    setAgentPose(agentName, 'walk1');
    walkingFrameTimers[agentName] = gameScene.time.addEvent({
        delay: scaledDuration(105),
        loop: true,
        callback: () => {
            if (!agents[agentName]) {
                stopWalkingAnimation(agentName);
                return;
            }

            frameIndex = (frameIndex + 1) % 2;
            const framePose = frameIndex === 0 ? 'walk1' : 'walk2';
            setAgentPose(agentName, framePose);
        }
    });
}

function stopWalkingAnimation(agentName, finalLocation = agentLocations[agentName]) {
    if (walkingFrameTimers[agentName]) {
        walkingFrameTimers[agentName].remove(false);
        delete walkingFrameTimers[agentName];
    }

    const agent = agents[agentName];
    if (!agent) {
        return;
    }

    if (agentState[agentName]?.sleeping || (!agentState[agentName]?.manualOverride && finalLocation === formatSleepLocation(agentName))) {
        setAgentPose(agentName, 'lie');
        positionAgentForSleep(gameScene, agentName);
        return;
    }

    applyAgentPoseForLocation(agentName, finalLocation);
}

function getSleepPoseCoords(scene, agentName) {
    const sleepLocation = formatSleepLocation(agentName);
    const coords = getLocationCoords(sleepLocation);

    if (!coords) {
        return null;
    }

    const offset = sleepPoseOverrides[agentName] || {};
    const wR = scene.sys.game.config.width / 160;
    const hR = scene.sys.game.config.height / 90;

    return {
        x: (coords.x + (offset.x || 0)) * wR,
        y: (coords.y + (offset.y || 0)) * hR
    };
}

function positionAgentForSleep(scene, agentName) {
    const agent = agents[agentName];
    const sleepCoords = getSleepPoseCoords(scene, agentName);

    if (!agent || !sleepCoords) {
        return;
    }

    agent.x = sleepCoords.x;
    agent.y = sleepCoords.y;
}

function isSittingLocation(locationName) {
    if (!locationName) {
        return false;
    }

    return [
        'Chair',
        'Bench',
        'Sofa',
        'Dining_table',
        'Dinning_room',
        'Reading_chair',
        'Window_seat',
        'Corner_table',
        'Customer_cafe',
        'Customer_bar',
        'Patio'
    ].some(token => locationName.includes(token));
}

function applyAgentPoseForLocation(agentName, locationName) {
    if (agentState[agentName]?.sleeping) {
        setAgentPose(agentName, 'lie');
        return;
    }

    setAgentPose(agentName, isSittingLocation(locationName) ? 'sit' : 'stand');
}

function moveAgentToInitialPosition(agentName, targetLocation) {
    const homeLocation = formatInitialLocation(agentName);
    const initialLocation = getLocationCoords(homeLocation);
    if (!initialLocation) {
        console.error(`Error: No initial location defined for ${agentName}`);
        return;
    }
    if (!agents[agentName] || agents[agentName].isMoving || agents[agentName].isPreparingToMove) {
        return;
    }

    const wR = this.sys.game.config.width / 160;
    const hR = this.sys.game.config.height / 90;
    const tx = initialLocation.x * wR;
    const ty = initialLocation.y * hR;

    setAgentPose(agentName, 'stand');

    announceMovementThen(this, agentName, homeLocation, 'rest', () => {
        if (!agents[agentName]) {
            return;
        }

        setAgentPose(agentName, 'stand');
        agents[agentName].isMoving = true;
        agentPhases[agentName] = 'Returning home';
        updateUi();

        moveAgentOrthogonally.call(this, agentName, agents[agentName], tx, ty, homeLocation, () => {
            agents[agentName].isMoving = false;
            agentState[agentName].currentDay = currentPlanDay;
            agentState[agentName].arrived = false;
            agentState[agentName].returning = false;
            agentState[agentName].returnedHome = true;
            agentLocations[agentName] = homeLocation;
            agentPhases[agentName] = 'At home';
            applyAgentPoseForLocation(agentName, homeLocation);
            showStatusEmoji(this, agentName, homeLocation, 'rest');
            syncAgentActionState(agentName, homeLocation, 'rest');
            updateUi();
            syncSimulationProgress({ force: true });

            // 使用标准位置格式清除占用
            if (targetLocation) {
                console.log(`Releasing ${targetLocation} for ${agentName}`);
                releaseReservedLocation(agentName);
            }
        });
    });
}

function formatInitialLocation(agentName) {
    return sleepLocationByAgent[agentName] || agentLocations[agentName] || 'Unknown';
}

function formatSleepLocation(agentName) {
    return sleepLocationByAgent[agentName] || formatInitialLocation(agentName);
}

function moveAgentToSleepPosition(scene, agentName) {
    const sleepLocation = formatSleepLocation(agentName);
    const coords = getLocationCoords(sleepLocation);
    const state = agentState[agentName];
    const agent = agents[agentName];

    if (!coords || !state || !agent || agent.isMoving || agent.isPreparingToMove) {
        return;
    }

    const wR = scene.sys.game.config.width / 160;
    const hR = scene.sys.game.config.height / 90;

    state.goingToBed = true;
    setAgentPose(agentName, 'stand');

    announceMovementThen(scene, agentName, sleepLocation, 'sleep', () => {
        if (!agents[agentName]) {
            return;
        }

        const movingAgent = agents[agentName];
        setAgentPose(agentName, 'stand');
        movingAgent.isMoving = true;
        agentPhases[agentName] = 'Going to bed';
        updateUi();

        moveAgentOrthogonally.call(scene, agentName, movingAgent, coords.x * wR, coords.y * hR, sleepLocation, () => {
            movingAgent.isMoving = false;
            state.goingToBed = false;
            state.sleeping = true;
            state.moved = true;
            agentLocations[agentName] = sleepLocation;
            agentPhases[agentName] = 'Sleeping';
            hideStatusBubble(agentName);
            setAgentPose(agentName, 'lie');
            positionAgentForSleep(scene, agentName);
            showSleepBubble(scene, agentName);
            syncAgentActionState(agentName, sleepLocation, 'sleep', { sleeping: true });
            updateUi();
            syncSimulationProgress({ force: true });
        });
    });
}

function resetAgentToSleepPosition(scene, agentName) {
    const sleepLocation = formatSleepLocation(agentName);
    const coords = getLocationCoords(sleepLocation);
    const agent = agents[agentName];

    if (!coords || !agent) {
        return;
    }

    const wR = scene.sys.game.config.width / 160;
    const hR = scene.sys.game.config.height / 90;
    agent.x = coords.x * wR;
    agent.y = coords.y * hR;
    agent.isMoving = false;
    agent.isPreparingToMove = false;
    agentLocations[agentName] = sleepLocation;
    hideStatusBubble(agentName);
    setAgentPose(agentName, 'lie');
    positionAgentForSleep(scene, agentName);
}


// 路径规划函数
function getDefaultHomeActivityLocation(agentName) {
    const homeArea = homeAreaByAgent[agentName];
    const preferredRooms = ['Living_room', 'Kitchen', 'Dining_table', 'Dinning_room', 'Sofa', 'Desk'];
    const match = preferredRooms
        .map(roomName => `${homeArea}.${roomName}`)
        .find(locationName => getLocationCoords(locationName));

    return match || formatSleepLocation(agentName);
}

function placeAgentAtLocation(scene, agentName, locationName, pose = null) {
    const coords = getLocationCoords(locationName);
    const agent = agents[agentName];

    if (!coords || !agent) {
        return;
    }

    const wR = scene.sys.game.config.width / 160;
    const hR = scene.sys.game.config.height / 90;
    agent.x = coords.x * wR;
    agent.y = coords.y * hR;
    agent.isMoving = false;
    agent.isPreparingToMove = false;
    agentLocations[agentName] = locationName;

    if (pose === 'lie' || locationName === formatSleepLocation(agentName)) {
        hideStatusBubble(agentName);
        setAgentPose(agentName, 'lie');
        positionAgentForSleep(scene, agentName);
        showSleepBubble(scene, agentName);
        return;
    }

    hideSleepBubble(agentName);
    if (pose) {
        setAgentPose(agentName, pose);
    } else {
        applyAgentPoseForLocation(agentName, locationName);
    }
}

// 向后端请求下一步决策，并执行返回的动作
function requestNextDecision(scene, agentName) {
    const state = agentState[agentName];
    if (!state || state.deciding) {
        return;
    }
    if (state.nextDecisionRetryAt && currentTimeMinutes < state.nextDecisionRetryAt) {
        return;
    }

    state.deciding = true;
    agentPhases[agentName] = 'Deciding what to do next';
    updateUi();

    fetchNextDecision(agentName, state.lastCompletedAction || null)
        .then(data => {
            state.deciding = false;
            const decision = data?.decision;
            if (!decision || !decision.destination) {
                throw new Error('Empty decision');
            }

            state.nextDecisionRetryAt = null;
            startDecidedAction(scene, agentName, decision);
        })
        .catch(error => {
            console.warn(`Decision request failed for ${agentName}:`, error);
            state.deciding = false;
            state.nextDecisionRetryAt = currentTimeMinutes + DECISION_RETRY_MINUTES;
            agentPhases[agentName] = 'Waiting to retry decision';
            updateUi();
        });
}

// 执行一条决策：预约目的地并移动过去
function startDecidedAction(scene, agentName, decision) {
    const state = agentState[agentName];
    const assignedDestination = reserveDestination(agentName, decision.destination);

    setCurrentAction(agentName, {
        action: decision.action,
        destination: assignedDestination,
        durationMinutes: decision.duration_minutes,
        talkTo: decision.talk_to && decision.talk_to !== 'nobody' ? decision.talk_to : null,
        endsAtMinutes: null,
        source: decision.source || 'llm'
    });
    state.arrived = false;

    if (assignedDestination === agentLocations[agentName]) {
        // 已在目的地：直接开始动作
        beginActionAtDestination(scene, agentName, assignedDestination);
        return;
    }

    moveAgent.call(scene, agentName, assignedDestination, currentPlanDay);
}

// 到达目的地后：起算动作时长、上报状态、尝试触发对话
function beginActionAtDestination(scene, agentName, targetLocation) {
    const state = agentState[agentName];
    const currentAction = agentCurrentActions[agentName];
    const actionText = getCurrentActionText(agentName);

    state.arrived = true;
    if (currentAction) {
        currentAction.endsAtMinutes = currentTimeMinutes + (currentAction.durationMinutes || 60);
    }

    agentPhases[agentName] = `Doing: ${actionText}`;
    applyAgentPoseForLocation(agentName, targetLocation);
    showStatusEmoji(scene, agentName, targetLocation, actionText);
    syncAgentActionState(agentName, targetLocation, actionText);
    updateUi();
    syncSimulationProgress({ force: true });
    maybeStartDecisionConversation(scene, agentName);
}

// 移动执行函数
function moveAgent(agentName, targetLocation, day) {
    const keys = targetLocation.split('.');
    let coords = locations;

    for (const k of keys) {
        if (!coords[k]) {
            console.error(`Error: Location ${targetLocation} not defined`);
            return;
        }
        coords = coords[k];
    }

    const wR = this.sys.game.config.width / 160;
    const hR = this.sys.game.config.height / 90;
    const tx = coords.x * wR;
    const ty = coords.y * hR;

    if (!agents[agentName]) {
        console.error(`Error: Agent ${agentName} not defined`);
        return;
    }
    if (agents[agentName].isMoving || agents[agentName].isPreparingToMove) {
        return;
    }

    const actionText = getCurrentActionText(agentName);

    announceMovementThen(this, agentName, targetLocation, actionText, () => {
        if (!agents[agentName]) {
            return;
        }

        setAgentPose(agentName, 'stand');
        agents[agentName].isMoving = true;
        agentPhases[agentName] = 'Moving';
        updateUi();

        moveAgentOrthogonally.call(this, agentName, agents[agentName], tx, ty, targetLocation, () => {
            agents[agentName].isMoving = false;
            agentLocations[agentName] = targetLocation;
            beginActionAtDestination(this, agentName, targetLocation);
        });
    });
}

// 当前动作结束：上报完成、写入历史，下一帧重新决策
function completeCurrentAction(scene, agentName) {
    const state = agentState[agentName];
    const currentAction = agentCurrentActions[agentName];
    if (!currentAction) {
        return;
    }

    const actionText = getCurrentActionText(agentName);
    state.lastCompletedAction = `${actionText} (at ${formatLocation(currentAction.destination)})`;
    state.arrived = false;
    clearCurrentAction(agentName);
    hideStatusBubble(agentName);
    agentPhases[agentName] = 'Finished activity';
    updateUi();
}

function hydrateTimedDayState(scene, useRestoredPositions = false) {
    const schedules = agentSchedules[currentPlanDay] || {};

    Object.keys(agentState).forEach(agentName => {
        const scheduleInfo = schedules[agentName];
        const state = agentState[agentName];
        if (!scheduleInfo || !state) {
            return;
        }

        const currentLocation = agentLocations[agentName] || formatSleepLocation(agentName);
        const sleepLocation = formatSleepLocation(agentName);
        const atSleepLocation = currentLocation === sleepLocation;
        let inferredLocation = currentLocation;
        let inferredPose = null;

        state.currentDay = currentPlanDay;
        state.arrived = false;
        state.returning = false;
        state.returnedHome = false;
        state.moved = false;
        state.goingToBed = false;
        state.deciding = false;
        state.nextDecisionRetryAt = null;
        state.bedtimeThoughtShown = false;

        if (currentTimeMinutes < scheduleInfo.wakeTime) {
            state.wokeUp = false;
            state.sleeping = true;
            inferredLocation = sleepLocation;
            inferredPose = 'lie';
            agentPhases[agentName] = `Sleeping until ${formatSimTime(scheduleInfo.wakeTime)}`;
        } else if (currentTimeMinutes < scheduleInfo.bedTime) {
            // 醒着：从当前位置（恢复的或家中）继续，下一帧会重新请求决策
            state.wokeUp = true;
            state.sleeping = false;
            inferredLocation = useRestoredPositions ? currentLocation : getDefaultHomeActivityLocation(agentName);
            agentPhases[agentName] = 'Ready to decide next action';
        } else {
            state.wokeUp = true;
            state.sleeping = useRestoredPositions ? atSleepLocation : true;
            state.moved = state.sleeping;
            inferredLocation = sleepLocation;
            inferredPose = 'lie';
            agentPhases[agentName] = state.sleeping ? 'Sleeping' : 'Ready for bed';
        }

        if (!useRestoredPositions) {
            placeAgentAtLocation(scene, agentName, inferredLocation, inferredPose);
        } else if (state.sleeping) {
            hideStatusBubble(agentName);
            setAgentPose(agentName, 'lie');
            positionAgentForSleep(scene, agentName);
            showSleepBubble(scene, agentName);
        } else {
            hideSleepBubble(agentName);
            applyAgentPoseForLocation(agentName, currentLocation);
        }
    });
}

function prepareTimedDay(scene) {
    const restoredTimeMinutes = currentTimeMinutes;
    dailyPlanInProgress = true;
    agentSchedules[currentPlanDay] = {};
    currentTimeMinutes = Phaser.Math.Clamp(restoredTimeMinutes, DAY_START_MINUTES, DAY_END_MINUTES);
    agentReservations = {};
    agentCurrentActions = {};

    Object.keys(occupiedLocations).forEach(key => {
        occupiedLocations[key] = null;
    });

    const agentNames = Object.keys(agentState);
    const useRestoredPositions = Boolean(
        restoredAgentSnapshot &&
        Number(restoredAgentSnapshot.day) === Number(currentPlanDay) &&
        restoredTimeMinutes > DAY_START_MINUTES
    );
    const shouldResumeDay = restoredTimeMinutes > DAY_START_MINUTES;

    agentNames.forEach((agentName, index) => {
        hideStatusBubble(agentName);
        if (!shouldResumeDay) {
            resetAgentToSleepPosition(scene, agentName);
        }
        resetInternalStateClock(agentName);
        agentState[agentName] = {
            ...agentState[agentName],
            moved: false,
            currentDay: currentPlanDay,
            arrived: false,
            returning: false,
            returnedHome: false,
            wokeUp: false,
            sleeping: true,
            bedtimeThoughtShown: false,
            goingToBed: false,
            deciding: false,
            nextDecisionRetryAt: null,
            lastCompletedAction: null
        };

        // 起居时间为确定性规则：不依赖 LLM，仿真永远可以推进
        agentSchedules[currentPlanDay][agentName] = computeDefaultSchedule(index);
        agentPhases[agentName] = `Sleeping until ${formatSimTime(agentSchedules[currentPlanDay][agentName].wakeTime)}`;
        if (!shouldResumeDay) {
            showSleepBubble(scene, agentName);
        }
    });

    dailyScheduleLoadedByDay[currentPlanDay] = true;
    hydrateTimedDayState(scene, useRestoredPositions);
    updateUi();
    if (shouldResumeDay) {
        syncSimulationProgress({ force: true });
        // 恢复进度时回填当天已发生的对话记录
        getDailyConversations(currentPlanDay).then(conversations => {
            conversations.forEach(conversation => rememberConversation(currentPlanDay, conversation));
            updateUi();
        });
    }
}

function advanceSimulationClock(delta) {
    if (!dailyScheduleLoadedByDay[currentPlanDay]) {
        return;
    }

    const deltaSeconds = (delta || 16.67) / 1000;
    currentTimeMinutes = Math.min(
        DAY_END_MINUTES,
        currentTimeMinutes + (deltaSeconds * SIM_MINUTES_PER_SECOND * simulationSpeed)
    );
}

function runTimedDayActions(scene) {
    const schedules = agentSchedules[currentPlanDay] || {};

    Object.keys(agentState).forEach(agentName => {
        const scheduleInfo = schedules[agentName];
        const state = agentState[agentName];

        if (agentName === userControlledAgentName) {
            return;
        }

        if (!scheduleInfo || state.currentDay !== currentPlanDay || state.moved) {
            return;
        }

        const agentSprite = agents[agentName];
        const busyMoving = agentSprite?.isMoving || agentSprite?.isPreparingToMove;

        // 1. 起床
        if (!state.wokeUp && currentTimeMinutes >= scheduleInfo.wakeTime) {
            state.wokeUp = true;
            state.sleeping = false;
            syncAgentActionState(agentName, agentLocations[agentName], 'wake up', { sleeping: true });
            hideSleepBubble(agentName);
            hideStatusBubble(agentName);
            setAgentPose(agentName, 'stand');
            agentPhases[agentName] = 'Awake';
            updateUi();
            return;
        }

        if (!state.wokeUp || state.sleeping) {
            return;
        }

        const currentAction = agentCurrentActions[agentName];
        const pastBedtime = currentTimeMinutes >= scheduleInfo.bedTime;

        // 2. 睡前流程：到点后不再开新动作，回家上床
        if (pastBedtime) {
            if (busyMoving || conversationsInProgress[agentName]) {
                return;
            }
            if (currentAction) {
                completeCurrentAction(scene, agentName);
                return;
            }
            if (!state.returnedHome && !state.returning) {
                state.returning = true;
                moveAgentToInitialPosition.call(scene, agentName, agentLocations[agentName]);
                return;
            }
            if (state.returnedHome && !state.bedtimeThoughtShown) {
                state.bedtimeThoughtShown = true;
                showAgentSpeech.call(scene, agentName, buildTomorrowThought(agentName));
            }
            if (state.returnedHome && !state.goingToBed) {
                moveAgentToSleepPosition(scene, agentName);
            }
            return;
        }

        // 3. 白天循环：动作结束 → 完成上报 → 请求下一条决策
        if (busyMoving || state.deciding || conversationsInProgress[agentName]) {
            return;
        }

        if (currentAction) {
            if (
                state.arrived &&
                currentAction.endsAtMinutes !== null &&
                currentTimeMinutes >= currentAction.endsAtMinutes
            ) {
                completeCurrentAction(scene, agentName);
            }
            return;
        }

        requestNextDecision(scene, agentName);
    });
}

function getLocationCoords(locationName) {
    const keys = locationName.split('.');
    let coords = locations;

    for (const key of keys) {
        if (!coords[key]) {
            return null;
        }
        coords = coords[key];
    }

    return coords;
}

// 决策中带 talk_to 且对方就在同一区域时，请求一段对话并播放
function maybeStartDecisionConversation(scene, agentName) {
    const currentAction = agentCurrentActions[agentName];
    const targetName = currentAction?.talkTo;
    if (!targetName || !agentState[targetName]) {
        return;
    }
    if (conversationsInProgress[agentName] || conversationsInProgress[targetName]) {
        return;
    }

    const myArea = getAreaName(agentLocations[agentName] || '');
    const targetArea = getAreaName(agentLocations[targetName] || '');
    const targetState = agentState[targetName];
    if (!myArea || myArea !== targetArea || targetState.sleeping) {
        return;
    }

    conversationsInProgress[agentName] = true;
    conversationsInProgress[targetName] = true;

    fetchConversation(agentName, targetName, myArea).then(data => {
        const convo = data?.conversation;
        if (!convo) {
            conversationsInProgress[agentName] = false;
            conversationsInProgress[targetName] = false;
            return;
        }

        rememberConversation(currentPlanDay, convo);
        showStatusEmoji(scene, convo.initiator, agentLocations[convo.initiator], 'chat');
        syncAgentActionState(convo.initiator, agentLocations[convo.initiator], 'chat', { social_contact: true });
        showAgentSpeech.call(scene, convo.initiator, convo.question);
        schedule(scene, 2200, () => {
            showStatusEmoji(scene, convo.responder, agentLocations[convo.responder], 'chat');
            syncAgentActionState(convo.responder, agentLocations[convo.responder], 'chat', { social_contact: true });
            showAgentSpeech.call(scene, convo.responder, convo.answer, () => {
                conversationsInProgress[agentName] = false;
                conversationsInProgress[targetName] = false;
            });
        });
        updateUi();
    });
}

function moveAgentOrthogonally(agentName, agent, targetX, targetY, targetLocation, onComplete) {
    if (agentName === userControlledAgentName) {
        agent.isMoving = false;
        agent.isPreparingToMove = false;
        return;
    }

    const sourceLocation = agentLocations[agentName];
    const waypoints = normalizeOrthogonalWaypoints(
        agent.x,
        agent.y,
        findWalkablePath(agent.x, agent.y, targetX, targetY, sourceLocation, targetLocation)
    );
    if (!waypoints) {
        console.warn(`Path blocked for ${agentName}. Movement cancelled to avoid walking through walls.`);
        agent.isMoving = false;
        agentPhases[agentName] = 'Path blocked';
        releaseReservedLocation(agentName);
        updateUi();
        return;
    }

    const routeLine = shouldDrawRoute(agentName) ? drawRoute.call(this, agent, waypoints) : null;

    moveAgentAlongWaypoints.call(this, agent, [...waypoints], () => {
        fadeRoute.call(this, routeLine);
        onComplete();
    });
}

function normalizeOrthogonalWaypoints(startX, startY, waypoints) {
    if (!waypoints) {
        return null;
    }

    const normalized = [];
    let currentX = startX;
    let currentY = startY;

    waypoints.forEach(point => {
        const sameX = Math.abs(currentX - point.x) <= 1;
        const sameY = Math.abs(currentY - point.y) <= 1;

        if (!sameX && !sameY) {
            normalized.push({ x: point.x, y: currentY });
        }

        normalized.push(point);
        currentX = point.x;
        currentY = point.y;
    });

    return normalized;
}

function shouldDrawRoute(agentName) {
    return routesVisible && (!focusedRouteAgent || focusedRouteAgent === agentName);
}

function moveAgentAlongWaypoints(agent, waypoints, onComplete) {
    if (agent.agentName === userControlledAgentName) {
        agent.isMoving = false;
        agent.isPreparingToMove = false;
        return;
    }

    if (!waypoints.length) {
        stopWalkingAnimation(agent.agentName);
        onComplete();
        return;
    }

    startWalkingAnimation(agent.agentName);
    const next = waypoints.shift();
    const distance = Math.abs(agent.x - next.x) + Math.abs(agent.y - next.y);
    const pixelsPerSecond = 52;
    const minLegDuration = 250;
    const duration = scaledDuration(Math.max(minLegDuration, (distance / pixelsPerSecond) * 1000));

    const tweenConfig = {
        targets: agent,
        duration,
        ease: 'Linear',
        onComplete: () => {
            if (agent.agentName === userControlledAgentName) {
                agent.isMoving = false;
                agent.isPreparingToMove = false;
                return;
            }
            syncSimulationProgress({ force: true });
            moveAgentAlongWaypoints.call(this, agent, waypoints, onComplete);
        }
    };

    if (Math.abs(agent.x - next.x) > 1) {
        tweenConfig.x = next.x;
    }
    if (Math.abs(agent.y - next.y) > 1) {
        tweenConfig.y = next.y;
    }

    this.tweens.add(tweenConfig);
}

function drawRoute(agent, waypoints) {
    if (!waypoints.length) {
        return null;
    }

    const line = this.add.graphics();
    line.setDepth(4);
    line.agentName = agent.agentName;
    line.lineStyle(4, 0xf5d86d, 0.72);
    line.beginPath();
    line.moveTo(agent.x, agent.y - 4);
    waypoints.forEach(point => line.lineTo(point.x, point.y - 4));
    line.strokePath();

    waypoints.forEach(point => {
        line.fillStyle(0xffffff, 0.88);
        line.fillCircle(point.x, point.y - 4, 3);
    });

    activeRouteLines.push(line);
    return line;
}

function fadeRoute(routeLine) {
    if (!routeLine) {
        return;
    }

    this.tweens.add({
        targets: routeLine,
        alpha: 0,
        duration: scaledDuration(600),
        onComplete: () => {
            activeRouteLines = activeRouteLines.filter(line => line !== routeLine);
            routeLine.destroy();
        }
    });
}

function clearActiveRoutes(predicate = () => true) {
    activeRouteLines = activeRouteLines.filter(line => {
        if (!predicate(line)) {
            return true;
        }

        line.destroy();
        return false;
    });
}

function startUnifiedNight(scene) {
    if (nightInProgress) {
        return;
    }

    nightInProgress = true;
    dailyPlanInProgress = true;
    Object.keys(agentPhases).forEach(agentName => {
        hideStatusBubble(agentName);
        agentPhases[agentName] = 'Sleeping';
        agentLocations[agentName] = formatSleepLocation(agentName);
        setAgentPose(agentName, 'lie');
        positionAgentForSleep(scene, agentName);
    });
    updateUi();
    syncSimulationProgress({ force: true });

    schedule(scene, 8000, () => {
        Object.keys(occupiedLocations).forEach(key => {
            occupiedLocations[key] = null;
        });
        agentReservations = {};

        currentPlanDay++;
        currentTimeMinutes = DAY_START_MINUTES;
        agentCurrentActions = {};
        conversationsInProgress = {};
        Object.values(agentState).forEach(state => {
            state.moved = false;
            state.currentDay = currentPlanDay;
            state.arrived = false;
            state.returning = false;
            state.returnedHome = false;
            state.wokeUp = false;
            state.sleeping = false;
            state.goingToBed = false;
            state.deciding = false;
            state.nextDecisionRetryAt = null;
            state.lastCompletedAction = null;
        });
        Object.keys(agentPhases).forEach(agentName => {
            agentPhases[agentName] = 'Ready';
        });

        nightInProgress = false;
        dailyPlanInProgress = false;
        dailyScheduleLoadedByDay[currentPlanDay] = false;
        // 通知后端进入新一天：持久化进度并触发每位代理的反思
        notifyNewDay(currentPlanDay);
        syncSimulationProgress({ force: true });
        updateUi();
    });
}

function findWalkablePath(startX, startY, targetX, targetY, sourceLocation, targetLocation) {
    const wR = gameScene.sys.game.config.width / 160;
    const hR = gameScene.sys.game.config.height / 90;
    const sourceNode = locationToNode[sourceLocation] || (navNodes[sourceLocation] ? sourceLocation : null);
    const targetNode = locationToNode[targetLocation] || (navNodes[targetLocation] ? targetLocation : null);

    if (!sourceNode || !targetNode) {
        console.warn(`Missing nav node for ${sourceLocation} -> ${targetLocation}`);
        return null;
    }

    if (shouldUseIndoorPath(sourceLocation, targetLocation)) {
        return [{ x: targetX, y: targetY }];
    }

    const nodePath = findNavPath(sourceNode, targetNode);
    if (!nodePath.length) {
        console.warn(`No navigation path for ${sourceLocation} -> ${targetLocation}`);
        return null;
    }

    const waypointNodes = nodePath.slice(1).map(nodeName => navNodes[nodeName]);
    return waypointNodes.map(point => ({
        x: point.x * wR,
        y: point.y * hR
    }));
}

function shouldUseIndoorPath(sourceLocation, targetLocation) {
    const sourceArea = getAreaName(sourceLocation || '');
    const targetArea = getAreaName(targetLocation || '');

    return (
        sourceArea &&
        sourceArea === targetArea &&
        sourceArea !== 'Park' &&
        !sourceLocation.endsWith('.door_in') &&
        !sourceLocation.endsWith('.door_out') &&
        !targetLocation.endsWith('.door_in') &&
        !targetLocation.endsWith('.door_out')
    );
}

function buildNavGraph(edges) {
    const graph = {};

    Object.keys(navNodes).forEach(nodeName => {
        graph[nodeName] = [];
    });

    edges.forEach(([from, to]) => {
        if (!graph[from] || !graph[to]) {
            console.warn(`Invalid nav edge: ${from} -> ${to}`);
            return;
        }

        graph[from].push(to);
        graph[to].push(from);
    });

    return graph;
}

function findNavPath(sourceNode, targetNode) {
    if (sourceNode === targetNode) {
        return [sourceNode];
    }

    const queue = [sourceNode];
    const visited = new Set([sourceNode]);
    const cameFrom = {};

    while (queue.length) {
        const current = queue.shift();

        for (const next of navGraph[current] || []) {
            if (visited.has(next)) {
                continue;
            }

            visited.add(next);
            cameFrom[next] = current;

            if (next === targetNode) {
                return reconstructNavPath(cameFrom, sourceNode, targetNode);
            }

            queue.push(next);
        }
    }

    return [];
}

function reconstructNavPath(cameFrom, sourceNode, targetNode) {
    const path = [targetNode];
    let current = targetNode;

    while (current !== sourceNode) {
        current = cameFrom[current];
        if (!current) {
            return [];
        }
        path.unshift(current);
    }

    return path;
}

// 每日更新逻辑
function update(time, delta) {
    updateManualControl(delta);

    if (!simulationStarted || simulationPaused) {
        return;
    }

    if (!dailyPlanInProgress && !nightInProgress) {
        prepareTimedDay(this);
        return;
    }

    if (!dailyScheduleLoadedByDay[currentPlanDay]) {
        return;
    }

    advanceSimulationClock(delta);
    runTimedDayActions(this);
    updateClockUi();
    syncSimulationProgress();

    if (userControlledAgentName) {
        return;
    }

    const allAgentsReady = Object.values(agentState).every(state =>
        state.moved &&
        state.currentDay === currentPlanDay
    );

    if (allAgentsReady && !nightInProgress) {
        startUnifiedNight(this);
        return;
    }
}


