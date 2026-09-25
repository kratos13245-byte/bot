const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { EventEmitter } = require('node:events');

function harness(env = {}) {
  const routes = {};
  const intervals = new Set();
  const timeouts = [];
  const bots = [];
  const app = { use() {}, get(path, fn) { routes[path] = fn; }, post(path, fn) { routes[path] = fn; }, listen() {} };
  const express = () => app;
  express.json = () => () => {};
  const deps = {
    express, dotenv: { config() {} },
    mineflayer: { createBot() {
      const bot = new EventEmitter();
      Object.assign(bot, { username: 'IARA', version: 'test', loadPlugin() {}, pathfinder: { setMovements() {} } });
      bots.push(bot);
      return bot;
    } },
    'mineflayer-pathfinder': { pathfinder() {}, goals: {}, Movements: class {} },
    'minecraft-data': () => ({}),
  };
  const context = vm.createContext({ require: name => deps[name], console, process: { env },
    setInterval(fn) { intervals.add(fn); return fn; }, clearInterval(fn) { intervals.delete(fn); },
    setTimeout(fn) { timeouts.push(fn); } });
  vm.runInContext(fs.readFileSync(__dirname + '/bot_bridge.js', 'utf8'), context);
  return { context, routes, intervals, timeouts, bots };
}

test('autonomy restarts after reconnect and never overlaps ticks', async () => {
  const h = harness();
  h.bots[0].emit('spawn');
  assert.equal(h.intervals.size, 1);
  let calls = 0, finish;
  h.context.runAutonomyTick = () => { calls++; return new Promise(resolve => { finish = resolve; }); };
  const tick = [...h.intervals][0];
  tick(); tick();
  assert.equal(calls, 1);
  finish();
  await new Promise(resolve => setImmediate(resolve));
  tick();
  assert.equal(calls, 2);
  finish();
  h.bots[0].emit('end');
  assert.equal(h.intervals.size, 0);
  h.timeouts[0]();
  h.bots[1].emit('spawn');
  assert.equal(h.intervals.size, 1);
});

test('chat executes locally only in explicit standalone mode', () => {
  for (const standalone of [false, true]) {
    const h = harness(standalone ? { MC_STANDALONE_COMMANDS: '1' } : {});
    let calls = 0;
    h.context.maybeHandleIngameCommand = () => calls++;
    h.bots[0].emit('chat', 'renato', 'mine stone');
    assert.equal(calls, standalone ? 1 : 0);
  }
});

test('action exceptions return JSON failure instead of hanging the request', async () => {
  const h = harness();
  h.bots[0].emit('spawn');
  h.context.craftItem = async () => { throw new Error('craft failed'); };
  const response = { code: 200, status(code) { this.code = code; return this; }, json(body) { this.body = body; return this; } };
  await h.routes['/action']({ body: { action: 'craft_tool', payload: { item: 'stick' } } }, response);
  assert.equal(response.code, 500);
  assert.equal(response.body.ok, false);
  assert.equal(response.body.error, 'craft failed');
});
