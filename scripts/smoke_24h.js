const fs = require('fs');
const vm = require('vm');

const gameSource = fs.readFileSync('frontend/js/game.js', 'utf8');
const plans = JSON.parse(fs.readFileSync('backend/life_plans.json', 'utf8'))['1'];

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
  sleepLocationByAgent,
  parsePlanSchedule,
  getAreaName,
  locationToNode,
  navNodes,
  navGraph,
  findNavPath,
  shouldUseIndoorPath
};`, context);

const api = context.__smoke;
const FULL_DAY_MINUTES = 24 * 60;
const TIMELINE_STEP_MINUTES = 15;

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

const agentNames = Object.keys(plans).filter(name => name !== 'conversations');
const report = [];

assert(api.DAY_START_MINUTES >= 0, 'simulation day start must be inside a calendar day');
assert(api.DAY_END_MINUTES <= FULL_DAY_MINUTES, 'simulation day end must be inside a calendar day');
assert(api.DAY_START_MINUTES < api.DAY_END_MINUTES, 'simulation day start must be before day end');

for (const [index, agentName] of agentNames.entries()) {
  const [planText, destination] = plans[agentName];
  const schedule = api.parsePlanSchedule(planText, index);
  const home = api.sleepLocationByAgent[agentName];

  assert(home, `${agentName} has no home sleep location`);
  assert(api.locationToNode[destination], `${agentName} destination is not routable: ${destination}`);
  assert(pathExists(home, destination), `${agentName} cannot route from bed to destination ${destination}`);
  assert(pathExists(destination, home), `${agentName} cannot route from destination back to bed`);
  assert(schedule.wakeTime >= api.DAY_START_MINUTES, `${agentName} wakes before simulation start`);
  assert(schedule.activityTime >= schedule.wakeTime, `${agentName} activity starts before waking`);
  assert(schedule.returnTime >= schedule.activityTime, `${agentName} returns before activity`);
  assert(schedule.bedTime >= schedule.returnTime, `${agentName} sleeps before returning`);
  assert(schedule.bedTime <= api.DAY_END_MINUTES, `${agentName} bedtime exceeds day end`);

  report.push({
    agentName,
    destination,
    wakeTime: schedule.wakeTime,
    activityTime: schedule.activityTime,
    returnTime: schedule.returnTime,
    bedTime: schedule.bedTime
  });
}

for (const conversation of plans.conversations || []) {
  const initiatorDestination = plans[conversation.initiator]?.[1] || '';
  const responderDestination = plans[conversation.responder]?.[1] || '';
  assert(
    api.getAreaName(initiatorDestination) === conversation.location,
    `${conversation.initiator} is not at conversation location ${conversation.location}`
  );
  assert(
    api.getAreaName(responderDestination) === conversation.location,
    `${conversation.responder} is not at conversation location ${conversation.location}`
  );
}

const timeline = [];
for (let minute = 0; minute <= FULL_DAY_MINUTES; minute += TIMELINE_STEP_MINUTES) {
  for (const item of report) {
    if (minute < api.DAY_START_MINUTES) {
      continue;
    }
    if (minute > api.DAY_END_MINUTES) {
      continue;
    }
    if (minute === item.wakeTime) timeline.push(`${item.agentName}: wake`);
    if (minute === item.activityTime) timeline.push(`${item.agentName}: leave`);
    if (minute === item.returnTime) timeline.push(`${item.agentName}: return`);
    if (minute === item.bedTime) timeline.push(`${item.agentName}: sleep`);
  }
}

console.log(JSON.stringify({
  checkedAgents: report.length,
  checkedConversations: (plans.conversations || []).length,
  simulatedMinutes: FULL_DAY_MINUTES,
  activeWindowMinutes: api.DAY_END_MINUTES - api.DAY_START_MINUTES,
  sleepWindowMinutes: api.DAY_START_MINUTES + (FULL_DAY_MINUTES - api.DAY_END_MINUTES),
  report,
  timelineEvents: timeline.length
}, null, 2));
