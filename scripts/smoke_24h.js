// 针对“需求驱动决策循环”的冒烟测试。在沙盒中加载真实的前端代码
// （不联网、不渲染），并验证以下几点：
//   1. 每个 agent 确定性的起床/睡觉时间表都落在当天的时间窗口内；
//   2. 后端可能选择的每个目的地都能从每个 agent 的床铺出发到达，
//      并能返回床铺（对应后端的 ALLOWED_DESTINATIONS，需保持同步）；
//   3. 位于同一地点的 agent 会解析为相同的区域名，从而能够触发
//      决策驱动的对话。
// 在仓库根目录下运行：node scripts/smoke_24h.js

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

// 对应后端的目的地清单（agents/agent.py）。请保持两者同步。
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

// 1. 确定性的起床/睡觉时间表。
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

// 2. 每个候选的决策目的地都能从每个 agent 的床铺到达并返回，
//    这样后端下发的任何决策都不会让 agent 被困在原地。
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

// 3. 对话的同地检测：被派往同一区域的两个 agent 会解析为相同的
//    区域名（这是前端用来判断触发对话的条件）。
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
