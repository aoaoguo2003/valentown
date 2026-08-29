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
  // 够用的 DOM 桩。以前 getElementById 返回 null，于是任何走到 updateUi 的
  // 测试都会炸在第一行赋值上——面板逻辑因此完全测不到。给它一个宽容的
  // 元素对象，UI 那一层就能跟着一起跑，虽然什么都渲染不出来。
  document: (() => {
    const makeElement = () => ({
      textContent: '', innerHTML: '', hidden: false, disabled: false,
      dataset: {}, style: {}, children: [],
      classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
      appendChild() {}, removeChild() {}, addEventListener() {}, removeAttribute() {},
      setAttribute() {}, focus() {}, scrollIntoView() {},
      querySelector: () => makeElement(), querySelectorAll: () => [],
      closest: () => null
    });
    return {
      getElementById: makeElement,
      querySelector: makeElement,
      querySelectorAll: () => [],
      createElement: makeElement,
      addEventListener() {}
    };
  })(),
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
  shouldUseIndoorPath,
  moveAgentAlongWaypoints,
  stopWalkingAnimation,
  showStatusEmoji,
  showAgentSpeech,
  announceMovementThen,
  setSimulationPaused,
  setSimulationSpeed,
  requestNextDecision,
  clearCurrentAction,
  activeSpeechBubbles,
  activeStatusBubbles,
  formatSleepLocation,
  agentLocations,
  agents,
  abandonMove,
  setCurrentAction,
  agentCurrentActions,
  agentReservations,
  agentState,
  agentPhases
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

// Phaser 显示对象的宽容桩：数据字段照实读写，没桩到的渲染方法当空操作。
// 少了它，任何走到 refreshAgentTints / setTexture 的逻辑都会炸在渲染调用上,
// 于是那条路径**根本测不到**——而那正是要测的东西。
function makeSprite(fields) {
  const target = Object.assign({ x: 0, y: 0, isMoving: false, isPreparingToMove: false }, fields);
  return new Proxy(target, {
    get(obj, prop) {
      if (prop in obj) return obj[prop];
      if (typeof prop === 'symbol') return undefined;
      return () => {};
    }
  });
}

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

// 2b. 目的地**两两之间**也要通。
//
// ⚠️ 上面那圈只验「床 <-> 目的地」，而居民真正的移动大多是「药房 -> 咖啡馆」
// 这种。这个洞值得堵，因为 `moveAgentOrthogonally` 找不到路时会放弃移动，
// 而动作是在移动**之前**就登记好的——一旦发生，那个居民当天就再也不决策了。
// 现在 `abandonMove` 会把动作撤掉让它自愈，但**最好的状态是这条路根本走不到**，
// 而这一圈断言就是那个保证。
for (const from of ALLOWED_DESTINATIONS) {
  for (const to of ALLOWED_DESTINATIONS) {
    if (from === to) continue;
    assert(pathExists(from, to), `no route from ${from} to ${to}`);
    routesChecked += 1;
  }
}

// 2c. 移动失败必须把已登记的动作**撤掉**。
//
// ⚠️ 这条防的是一个会静默冻结居民一整天的形状。动作是在移动**之前**登记的，
// 带着 `endsAtMinutes: null` 和 `arrived: false`；而每帧的驱动是
//
//     if (currentAction) { if (arrived && endsAtMinutes !== null) 完成; return; }
//     requestNextDecision(…)
//
// 动作还挂着又永远完不成 = 那个 `return` 每帧都走，**再也不会有新决策**，
// 一直到当晚睡觉那一支才被解开。移动链上有五个早退口（目的地不存在、
// 已在移动、开场被拒、路被堵、被玩家接管），每一个都会留下这个残局。
const stuckAgent = agentNames[0];
api.setCurrentAction(stuckAgent, {
  action: 'walk into a wall', destination: 'Park.Bench',
  durationMinutes: 30, talkTo: null, endsAtMinutes: null, source: 'llm'
});
api.agentReservations[stuckAgent] = 'Park.Bench';
assert(api.agentCurrentActions[stuckAgent], 'precondition: the action is registered before moving');

api.abandonMove(stuckAgent, 'Path blocked');

assert(!api.agentCurrentActions[stuckAgent],
  'a failed move must clear the registered action, or the resident never decides again');
assert(!api.agentReservations[stuckAgent],
  'a failed move must release the reserved destination');
assert(api.agentPhases[stuckAgent] === 'Path blocked',
  'the reason a move was abandoned must be visible in the UI');

// 2d. 走完最后一段时，判断姿势用的必须是**终点**，不是出发点。
//
// ⚠️ 这条防的是一个每天早上都会发生、却读代码看不出来的错位：
// `moveAgentAlongWaypoints` 走完最后一段时先调 `stopWalkingAnimation`、
// 再调 `onComplete`，而 `agentLocations` 是在 `onComplete` 里才更新的。
// 以前这里不传终点，默认参数于是取到**出发前**的位置——只要这趟是从自己
// 床边出发的（醒来第一趟必然如此），就会被判成"回到床了"，当场躺下并
// 瞬移回床，而面板显示他正在目的地做事。
{
  const walker = agentNames[0];
  const bed = api.formatSleepLocation(walker);
  const seen = [];

  // 从床边出发，走到公园
  api.agentLocations[walker] = bed;
  const sprite = makeSprite({ agentName: walker, isMoving: true });
  api.agents[walker] = sprite;

  // 只关心 stopWalkingAnimation 收到的是哪个地点。先把真函数存到 VM 里，
  // 再换成探针，用完按顺序还原——顺序错了就会把真函数还原成 undefined。
  context.__smoke.__probe = (name, finalLocation) => seen.push(finalLocation);
  vm.runInContext(`
    globalThis.__smoke.__realStop = stopWalkingAnimation;
    stopWalkingAnimation = globalThis.__smoke.__probe;
  `, context);

  api.moveAgentAlongWaypoints.call({}, sprite, [], () => {}, 'Park.Bench');

  vm.runInContext('stopWalkingAnimation = globalThis.__smoke.__realStop;', context);
  assert(typeof context.__smoke.__realStop === 'function', 'the real function must be restored');

  assert(seen.length === 1, 'the walk should end exactly once');
  assert(seen[0] === 'Park.Bench',
    `pose at the end of a walk must be decided by the destination, got ${seen[0]} `
    + `(the agent set off from ${bed}, so falling back to agentLocations lies)`);
  assert(seen[0] !== bed, 'a walk away from bed must not end in the "went to bed" branch');
}

// 2e. 文字气泡优先于表情气泡，**和先后顺序无关**。
//
// ⚠️ 两个气泡都浮在头顶同一位置，同时出现就互相遮住谁都读不了。话是有
// 信息量的，表情只是个状态图标——所以文字优先。对话那条路径先
// showStatusEmoji('chat') 再 showAgentSpeech，必然重叠，所以规则写在两个
// 函数里各挡一边：说话时收起表情，有话在说时不摆表情。
{
  const talker = agentNames[1];
  api.agents[talker] = makeSprite({ agentName: talker });
  api.agentState[talker] = { sleeping: false, arrived: true };
  api.agentLocations[talker] = 'Park.Bench';

  const noop = () => {};
  // Phaser 的显示对象是链式 API（setOrigin().setDepth()…），方法名一个个补
  // 太脆。用 Proxy：任何方法都返回自己，尺寸这类属性给个数。
  const stubObject = () => new Proxy({}, {
    get(target, prop) {
      if (prop === 'width') return 40;
      if (prop === 'height') return 14;
      if (prop === 'x' || prop === 'y' || prop === 'alpha') return 0;
      if (prop === Symbol.toPrimitive || prop === 'then') return undefined;
      return (...args) => (target[prop] = args, stubObject());
    }
  });
  const stubScene = {
    add: { text: stubObject, graphics: stubObject, container: stubObject },
    tweens: { add: noop },
    time: { addEvent: () => ({ remove: noop }), delayedCall: () => ({ remove: noop }) }
  };

  // ① 正在说话时，表情气泡不该被摆出来。
  //    ⚠️ 这里要传**能用的** scene 桩：传 {} 的话，摘掉守卫之后是靠
  //    `scene.add.graphics` 崩掉才"红"的，那是偶然，不是断言在起作用。
  api.activeSpeechBubbles[talker] = { pretend: 'a bubble is up' };
  api.showStatusEmoji(stubScene, talker, 'Park.Bench', 'read a book');
  assert(!api.activeStatusBubbles[talker],
    'an emoji must not be placed while a speech bubble is up — they overlap');
  delete api.activeSpeechBubbles[talker];
  delete api.activeStatusBubbles[talker];

  // ② 反过来：开始说话时，已经挂着的表情气泡要被收走。
  //    这一半才是真正修好"对话时两个气泡叠在一起"的那一半——对话路径
  //    是先 showStatusEmoji('chat') 再 showAgentSpeech。
  api.activeStatusBubbles[talker] = { destroy: noop };
  api.showAgentSpeech.call(stubScene, talker, 'hello there', noop);
  assert(!api.activeStatusBubbles[talker],
    'starting to speak must clear an emoji already on screen — text wins');

  delete api.activeSpeechBubbles[talker];

  // ③ 被打断的话，等它的**动作**必须照样被放行。
  //
  // ⚠️ 这条是跑起来才发现的：Mia 卡在 "Preparing to move" 一整天没动。
  // `announceMovementThen` 先把 isPreparingToMove 设为 true，然后**等语音
  // 气泡结束才迈步**；而 `showAgentSpeech` 遇到已有气泡时，只是把它销毁、
  // 从表里删掉——回调直接丢了。于是任何在"准备出发"期间插进来的第二句话
  // （对话就是这么来的）都让那个居民永远停在原地：isPreparingToMove 再没人
  // 清，而每帧的驱动看到 currentAction 还挂着就 return。
  //
  // 话被打断可以，等在后面的动作不能跟着一起没。
  let released = false;
  api.agents[talker].isPreparingToMove = false;
  api.agentState[talker].sleeping = false;

  api.announceMovementThen(stubScene, talker, 'Park.Bench', 'take a walk', () => { released = true; });
  assert(api.agents[talker].isPreparingToMove === true,
    'precondition: announcing a move parks the agent until the bubble ends');

  api.showAgentSpeech.call(stubScene, talker, 'someone interrupts', noop);

  assert(released,
    'a speech bubble cut short must still release whatever was waiting on it');
  assert(api.agents[talker].isPreparingToMove === false,
    'an interrupted announcement must not leave the agent parked forever');

  delete api.activeSpeechBubbles[talker];
}

// 2f. Pause 必须让**小镇**停下来，不只是时钟。
//
// ⚠️ 这条读代码看不出来，是在浏览器里按下暂停才发现的：`simulationPaused`
// 只让 update() 提前返回，而走路是 Phaser 的 tween、说话和对话是
// scene.time 的定时器——**两者都不经过 update()**。实测暂停 120 帧：
// 时钟推进 0 分钟，Ron Parker 走了 60 像素。世界和时钟就此对不上。
{
  const calls = [];
  const spyScene = {
    tweens: { pauseAll: () => calls.push('pauseAll'), resumeAll: () => calls.push('resumeAll'), timeScale: 1 },
    time: { paused: false, timeScale: 1 }
  };
  vm.runInContext('globalThis.__smoke.__setScene = s => { gameScene = s; };', context);
  api.__setScene(spyScene);

  api.setSimulationPaused(true);
  assert(calls.includes('pauseAll'), 'pausing must stop the tweens, or residents keep walking while paused');
  assert(spyScene.time.paused === true, 'pausing must stop the timers, or speech and conversations keep running');

  api.setSimulationPaused(false);
  assert(calls.includes('resumeAll'), 'resuming must restart the tweens');
  assert(spyScene.time.paused === false, 'resuming must restart the timers');

  // 2g. 倍速要作用在**正在飞的**动画上。
  //
  // ⚠️ 原本是创建动画的那一刻把时长除以倍速，于是切到 4x 只影响之后新建的
  // 动画。实测：60 帧内时钟推进 3.98 分钟，而已经在飞的那条腿一点没变——
  // 人在爬，表在飞。timeScale 是同一件事的正确落点。
  api.setSimulationSpeed(4);
  assert(spyScene.tweens.timeScale === 4,
    'changing speed must reach the tweens already in flight, not just the next ones');
  assert(spyScene.time.timeScale === 4,
    'changing speed must reach the timers already queued');

  api.setSimulationSpeed(1);
  assert(spyScene.tweens.timeScale === 1 && spyScene.time.timeScale === 1,
    'going back to 1x must restore the scale on both managers');

  api.__setScene(undefined);
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

// 4. 一轮决策要到动作**真正登记下来**才算结束。
//
// ⚠️ 这条是量出来的，不是想出来的。原本 `state.deciding = false` 写在
// `.then` 的第一行，而拒绝气泡的回放要花好几秒场景时间才轮到
// `startDecidedAction`。那整段窗口里：deciding 是 false、动作还没登记，
// 而每帧的驱动是
//
//     if (currentAction) { …; return; }
//     requestNextDecision(…)
//
// ——闸门大开。于是又发一次决策请求（**真花钱的 LLM 调用**），回来的第二个
// 决策撞上正在走路的自己，被判 "Already on the move" 丢掉，顺手把订好的
// 座位也退了。实况审计里那个理由真的出现过 3 次。
//
// 这里用一个"时间冻住"的 scene 桩：定时器永远不触发，于是回放停在半路，
// 正好是要检查的那一刻。
(async () => {
  const agentName = agentNames[1];
  const noop = () => {};
  const frozen = new Proxy({}, { get: () => () => frozen });
  const frozenScene = {
    add: { text: () => frozen, graphics: () => frozen, container: () => frozen },
    tweens: { add: noop },                                   // onComplete 永不触发
    time: { addEvent: () => ({ remove: noop }), delayedCall: () => ({ remove: noop }) }
  };

  context.fetch = () => Promise.resolve({
    ok: true,
    json: () => Promise.resolve({
      decision: { action: 'read a book', destination: 'Park.Bench', duration_minutes: 30, talk_to: 'nobody' },
      steps: [{ ok: false, tool: 'buy', observation: 'You are 5 short of the medicine.' }]
    })
  });

  api.agents[agentName] = makeSprite({ agentName });
  api.clearCurrentAction(agentName);
  api.agentState[agentName].deciding = false;
  api.agentState[agentName].nextDecisionRetryAt = null;

  api.requestNextDecision(frozenScene, agentName);
  for (let tick = 0; tick < 8; tick++) await Promise.resolve();   // 让 promise 链跑完

  assert(api.activeSpeechBubbles[agentName],
    'precondition: the refusal replay is on screen, so the turn is mid-flight');
  assert(!api.agentCurrentActions[agentName],
    'precondition: the action is not registered until the replay finishes');
  assert(api.agentState[agentName].deciding === true,
    'the turn must stay open until the action is registered, or the driver fires a second paid decision request');

  console.log(JSON.stringify({
  checkedAgents: report.length,
  candidateDestinations: ALLOWED_DESTINATIONS.length,
  routesChecked,
  simulatedMinutes: FULL_DAY_MINUTES,
  activeWindowMinutes: api.DAY_END_MINUTES - api.DAY_START_MINUTES,
  report
  }, null, 2));
})().catch(err => {
  console.error(err.message);
  process.exit(1);
});
