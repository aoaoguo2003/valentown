// Smoke test for the need-driven decision loop. Loads the real frontend code
// in a sandbox (no network, no rendering) and validates that:
//   1. every agent's deterministic wake/bed schedule fits the day window;
//   2. every destination the backend may pick is routable from every agent's
//      bed, and routable back home (mirror of backend ALLOWED_DESTINATIONS);
//   3. co-located agents resolve to the same area name, so decision-driven
//      conversations can trigger.
// Run from the repository root: node scripts/smoke_24h.js

const fs = require('fs');
const vm = require('vm');

const gameSource = fs.readFileSync('frontend/js/game.js', 'utf8');

const context = {
  console,
  Phaser: {
    AUTO: 0,
    Scale: { FIT: 'FIT', CENTER_BOTH: 'CENTER_BOTH' },
    Math: {
      Clamp(value, min, max) {
        return Math.max(min, Math.min(max, value));
      }
    },
    Game: function Game() {}
  },
  document: {
    getElementById() {
      return null;
    },
    querySelectorAll() {
      return [];
    },
    querySelector() {
      return null;
    },
    createElement() {
      return { textContent: '', innerHTML: '' };
    },
    addEventListener() {}
  },
  window: { location: { reload() {} } },
  fetch() {
    throw new Error('fetch is disabled in smoke_24h.js');
  }
};

vm.createContext(context);
vm.runInContext(`${gameSource}
globalThis.__smoke = {
  DAY_START_MINUTES,
  DAY_END_MINUTES,
  computeDefaultSchedule,
  sleepLocationByAgent,
  getAreaName,
  locationToNode,
  navNodes,
  navGraph,
  findNavPath,
  shouldUseIndoorPath
};`, context);

const api = context.__smoke;
const FULL_DAY_MINUTES = 24 * 60;

// Mirror of the backend destination catalogue (agents/agent.py). Keep in sync.
const HOME_AREAS = [
  'Ron_home', 'Ella_home', 'Arthur_home', 'Mia_home', 'Emma_home', 'Gavin_home', 'Adam_home'
];
const HOME_ROOM_LOCATIONS = [
  'Living_room', 'Kitchen', 'Dining_table', 'Dinning_room', 'Study_corner', 'Desk',
  'Bookshelf', 'Reading_chair', 'Sofa', 'Chair', 'Porch', 'Window'
];
const PUBLIC_LOCATIONS = [
  'Park.Chair', 'Park.River', 'Park.Tree', 'Park.Bench', 'Park.Flower_bed', 'Park.Playground', 'Park.Bridge',
  'Café_bar.Boss', 'Café_bar.Customer_cafe', 'Café_bar.Customer_bar', 'Café_bar.Window_seat',
  'Café_bar.Corner_table', 'Café_bar.Counter', 'Café_bar.Patio',
  'Supermarket.Boss', 'Supermarket.Customer_drink', 'Supermarket.Customer_eat', 'Supermarket.Checkout',
  'Supermarket.Fruit_shelf', 'Supermarket.Storage', 'Supermarket.Entrance_aisle',
  'Pharmacy.Boss', 'Pharmacy.Customer_left', 'Pharmacy.Customer_right', 'Pharmacy.Prescription_counter',
  'Pharmacy.Medicine_shelf', 'Pharmacy.Waiting_chair', 'Pharmacy.Consult_room'
];
const ALLOWED_DESTINATIONS = [
  ...HOME_AREAS.flatMap(home => HOME_ROOM_LOCATIONS.map(room => `${home}.${room}`)),
  ...PUBLIC_LOCATIONS
];

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function pathExists(fromLocation, toLocation) {
  const fromArea = api.getAreaName(fromLocation);
  const toArea = api.getAreaName(toLocation);
  if (
    fromArea &&
    fromArea === toArea &&
    fromArea !== 'Park' &&
    !fromLocation.endsWith('.door_in') &&
    !fromLocation.endsWith('.door_out') &&
    !toLocation.endsWith('.door_in') &&
    !toLocation.endsWith('.door_out')
  ) {
    return true;
  }

  const fromNode = api.locationToNode[fromLocation];
  const toNode = api.locationToNode[toLocation];
  if (!fromNode || !toNode) {
    return false;
  }
  return api.findNavPath(fromNode, toNode).length > 0;
}

const agentNames = Object.keys(api.sleepLocationByAgent);
const report = [];

assert(api.DAY_START_MINUTES >= 0, 'simulation day start must be inside a calendar day');
assert(api.DAY_END_MINUTES <= FULL_DAY_MINUTES, 'simulation day end must be inside a calendar day');
assert(api.DAY_START_MINUTES < api.DAY_END_MINUTES, 'simulation day start must be before day end');

// 1. Deterministic wake/bed schedules.
for (const [index, agentName] of agentNames.entries()) {
  const schedule = api.computeDefaultSchedule(index);
  assert(schedule.wakeTime >= api.DAY_START_MINUTES, `${agentName} wakes before simulation start`);
  assert(schedule.wakeTime < schedule.bedTime, `${agentName} wake time is not before bedtime`);
  assert(schedule.bedTime <= api.DAY_END_MINUTES, `${agentName} bedtime exceeds day end`);

  report.push({
    agentName,
    wakeTime: schedule.wakeTime,
    bedTime: schedule.bedTime
  });
}

// 2. Every candidate decision destination is routable from each agent's bed
//    and back, so no decision the backend emits can strand an agent.
let routesChecked = 0;
for (const agentName of agentNames) {
  const home = api.sleepLocationByAgent[agentName];
  assert(home, `${agentName} has no home sleep location`);

  for (const destination of ALLOWED_DESTINATIONS) {
    assert(api.locationToNode[destination], `destination missing from nav graph: ${destination}`);
    assert(pathExists(home, destination), `${agentName} cannot route from bed to ${destination}`);
    assert(pathExists(destination, home), `${agentName} cannot route from ${destination} back to bed`);
    routesChecked += 2;
  }
}

// 3. Conversation co-location: two agents sent to the same area resolve to the
//    same area name (the trigger condition used by the frontend).
assert(
  api.getAreaName('Park.Bench') === api.getAreaName('Park.Tree'),
  'two park anchors must resolve to the same area for conversations'
);
assert(
  api.getAreaName('Café_bar.Counter') === api.getAreaName('Café_bar.Patio'),
  'two cafe anchors must resolve to the same area for conversations'
);
assert(
  api.getAreaName('Park.Bench') !== api.getAreaName('Café_bar.Counter'),
  'different areas must not be considered co-located'
);

console.log(JSON.stringify({
  checkedAgents: report.length,
  candidateDestinations: ALLOWED_DESTINATIONS.length,
  routesChecked,
  simulatedMinutes: FULL_DAY_MINUTES,
  activeWindowMinutes: api.DAY_END_MINUTES - api.DAY_START_MINUTES,
  report
}, null, 2));
