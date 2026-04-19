const express = require("express");
const mineflayer = require("mineflayer");
const dotenv = require("dotenv");
const { pathfinder, goals, Movements } = require("mineflayer-pathfinder");
const mcDataLoader = require("minecraft-data");

dotenv.config({ path: "../.env" });
dotenv.config();

const MC_HOST = process.env.MC_HOST || "127.0.0.1";
const MC_PORT = Number(process.env.MC_PORT || "25565");
const MC_USERNAME = process.env.MC_USERNAME || "IARA_Bot";
const MC_PASSWORD = process.env.MC_PASSWORD || undefined;
const MC_VERSION = process.env.MC_VERSION || false;
const MC_OWNER = (process.env.MC_OWNER || "").trim();

const BRIDGE_HOST = process.env.MC_BRIDGE_HOST || "127.0.0.1";
const BRIDGE_PORT = Number(process.env.MC_BRIDGE_PORT || "8095");

const AUTO_COMBAT_RANGE = Number(process.env.MC_AUTO_COMBAT_RANGE || "6");
const AUTO_LOOT_RANGE = Number(process.env.MC_AUTO_LOOT_RANGE || "8");
const AUTO_TICK_MS = Number(process.env.MC_AUTO_TICK_MS || "1200");
const MC_LOW_HEALTH = Number(process.env.MC_LOW_HEALTH || "8");
const MC_LOW_FOOD = Number(process.env.MC_LOW_FOOD || "12");
const MC_FLEE_DISTANCE = Number(process.env.MC_FLEE_DISTANCE || "18");
const MC_EXPLORE_HISTORY_SIZE = Number(process.env.MC_EXPLORE_HISTORY_SIZE || "8");
const MC_EXPLORE_MIN_TARGET_DISTANCE = Number(process.env.MC_EXPLORE_MIN_TARGET_DISTANCE || "30");
const MC_STUCK_MIN_MOVE = Number(process.env.MC_STUCK_MIN_MOVE || "1.2");
const MC_STUCK_TICKS = Number(process.env.MC_STUCK_TICKS || "5");
const MC_CONTEXT_INV_MAX_ITEMS = Number(process.env.MC_CONTEXT_INV_MAX_ITEMS || "12");

const events = [];
let eventId = 0;
let bot = null;
let connected = false;
let mcData = null;
let autoTimer = null;

const state = {
  mode: "idle", // idle | follow | goto | explore | adventure | find_biome | find_resource | mine
  followTarget: "",
  goto: null,
  biomeTarget: "",
  resourceTarget: "",
  lootEnabled: true,
  combatEnabled: true,
  survivalEnabled: true,
  lastCombatTs: 0,
  miningTarget: "",
  miningRemaining: 0,
  miningInProgress: false,
  lastEatTs: 0,
  exploreTarget: null,
  exploreAssignedTs: 0,
  exploreHistory: [],
  lastPos: null,
  stuckTicks: 0,
  basePosition: null,
};

function pushEvent(type, payload) {
  eventId += 1;
  events.push({ id: eventId, ts: Date.now(), type, payload });
  if (events.length > 2000) events.splice(0, events.length - 2000);
}

function normalizeText(t) {
  return String(t || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
}

function _toFixed(n) {
  return Number.isFinite(n) ? Number(n.toFixed(1)) : n;
}

function isHostileMob(entity) {
  if (!entity || entity.type !== "mob") return false;
  const name = normalizeText(entity.name || entity.displayName || "");
  const hostile = [
    "zombie",
    "skeleton",
    "creeper",
    "spider",
    "enderman",
    "witch",
    "drowned",
    "phantom",
    "slime",
    "guardian",
    "hoglin",
    "piglin_brute",
  ];
  return hostile.some((h) => name.includes(h));
}

function _setModeIdle() {
  state.mode = "idle";
  state.followTarget = "";
  state.goto = null;
  state.biomeTarget = "";
  state.resourceTarget = "";
  state.miningTarget = "";
  state.miningRemaining = 0;
  state.miningInProgress = false;
  state.exploreTarget = null;
  state.exploreAssignedTs = 0;
  state.lastPos = null;
  state.stuckTicks = 0;
  if (bot?.pathfinder) bot.pathfinder.setGoal(null);
}

function _distance3(a, b) {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  const dz = a.z - b.z;
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

function _registerExploreTarget(target) {
  if (!target) return;
  state.exploreHistory.push({ x: target.x, y: target.y, z: target.z, ts: Date.now() });
  if (state.exploreHistory.length > MC_EXPLORE_HISTORY_SIZE) {
    state.exploreHistory.splice(0, state.exploreHistory.length - MC_EXPLORE_HISTORY_SIZE);
  }
}

function _isFarFromRecent(target) {
  if (!state.exploreHistory.length) return true;
  return state.exploreHistory.every((h) => _distance3(h, target) >= MC_EXPLORE_MIN_TARGET_DISTANCE);
}

function _inventoryItems() {
  try {
    return bot.inventory?.items?.() || [];
  } catch (_e) {
    return [];
  }
}

function _findItemByNameIncludes(candidates) {
  const items = _inventoryItems();
  for (const c of candidates) {
    const found = items.find((it) => normalizeText(it.name).includes(normalizeText(c)));
    if (found) return found;
  }
  return null;
}

function _findItemsByNameIncludes(candidates) {
  const items = _inventoryItems();
  return items.filter((it) => candidates.some((c) => normalizeText(it.name).includes(normalizeText(c))));
}

function _countItemsByNameIncludes(candidates) {
  const items = _inventoryItems();
  const normalized = candidates.map((c) => normalizeText(c));
  return items
    .filter((it) => normalized.some((c) => normalizeText(it.name).includes(c)))
    .reduce((acc, it) => acc + (it.count || 0), 0);
}

function _inventorySummary(maxItems = MC_CONTEXT_INV_MAX_ITEMS) {
  const items = _inventoryItems();
  const grouped = new Map();
  for (const it of items) {
    const key = it.name || "unknown";
    grouped.set(key, (grouped.get(key) || 0) + (it.count || 0));
  }

  const list = [...grouped.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))
    .slice(0, maxItems);

  const summary = list.length
    ? list.map((x) => `${x.name} x${x.count}`).join(", ")
    : "vazio";

  return { summary, items: list, total_types: grouped.size };
}

async function _equipBestWeapon() {
  const weapon = _findItemByNameIncludes([
    "netherite_sword",
    "diamond_sword",
    "iron_sword",
    "stone_sword",
    "wooden_sword",
    "_sword",
    "_axe",
  ]);
  if (!weapon) return false;
  try {
    await bot.equip(weapon, "hand");
    return true;
  } catch (_e) {
    return false;
  }
}

function _toolCandidatesForResource(resource) {
  const r = normalizeText(resource || "");
  if (r.includes("log") || r.includes("wood") || r.includes("madeira")) return ["_axe", "axe"];
  if (r.includes("dirt") || r.includes("sand") || r.includes("gravel") || r.includes("terra")) return ["_shovel", "shovel"];
  return ["_pickaxe", "pickaxe"];
}

async function _equipToolForResource(resource) {
  const tool = _findItemByNameIncludes(_toolCandidatesForResource(resource));
  if (!tool) return false;
  try {
    await bot.equip(tool, "hand");
    return true;
  } catch (_e) {
    return false;
  }
}

function _resolveCraftTarget(rawName) {
  let t = normalizeText(rawName || "");
  t = t.replace(/^(?:um|uma|uns|umas|o|a|os|as)\s+/, "").trim();
  if (!t) return null;

  const aliases = {
    "picareta de madeira": "wooden_pickaxe",
    "picareta madeira": "wooden_pickaxe",
    "picareta de pedra": "stone_pickaxe",
    "picareta pedra": "stone_pickaxe",
    "picareta de ferro": "iron_pickaxe",
    "picareta ferro": "iron_pickaxe",
    "picareta de diamante": "diamond_pickaxe",
    "picareta diamante": "diamond_pickaxe",
    "machado de madeira": "wooden_axe",
    "machado madeira": "wooden_axe",
    "machado de pedra": "stone_axe",
    "machado pedra": "stone_axe",
    "machado de ferro": "iron_axe",
    "machado ferro": "iron_axe",
    "pa de madeira": "wooden_shovel",
    "pa madeira": "wooden_shovel",
    "pa de pedra": "stone_shovel",
    "pa pedra": "stone_shovel",
    "pa de ferro": "iron_shovel",
    "pa ferro": "iron_shovel",
    "espada de madeira": "wooden_sword",
    "espada madeira": "wooden_sword",
    "espada de pedra": "stone_sword",
    "espada pedra": "stone_sword",
    "espada de ferro": "iron_sword",
    "espada ferro": "iron_sword",
    "mesa de trabalho": "crafting_table",
    "mesa de craft": "crafting_table",
    "crafting table": "crafting_table",
    "crafting_table": "crafting_table",
    "craftingtable": "crafting_table",
    "bancada": "crafting_table",
    "mesa": "crafting_table",
    "fornalha": "furnace",
  };

  if (aliases[t]) return aliases[t];
  if (mcData?.itemsByName?.[t]) return t;
  return null;
}

function _findNearbyCraftingTable(maxDistance = 8) {
  const tableId = mcData?.blocksByName?.crafting_table?.id;
  if (!tableId || !bot?.findBlock) return null;
  return bot.findBlock({ matching: tableId, maxDistance }) || null;
}

async function craftItem(rawItem, count = 1) {
  if (!bot || !connected || !mcData) return { ok: false, error: "bot offline" };
  const itemName = _resolveCraftTarget(rawItem);
  if (!itemName) return { ok: false, error: `item desconhecido: ${rawItem}` };

  const itemDef = mcData.itemsByName[itemName];
  if (!itemDef) return { ok: false, error: `item sem definicao: ${itemName}` };

  const qty = Math.max(1, Number(count) || 1);
  let tableBlock = null;
  let recipes = bot.recipesFor(itemDef.id, null, qty, null) || [];

  if (!recipes.length) {
    tableBlock = _findNearbyCraftingTable(8);
    if (tableBlock) recipes = bot.recipesFor(itemDef.id, null, qty, tableBlock) || [];
  }

  if (!recipes.length) {
    return { ok: false, error: `sem receita/materiais para ${itemName}` };
  }

  const before = _countItemsByNameIncludes([itemName]);
  try {
    await bot.craft(recipes[0], qty, tableBlock);
    const after = _countItemsByNameIncludes([itemName]);
    const crafted = Math.max(0, after - before);
    pushEvent("craft_done", { item: itemName, requested: qty, crafted });
    return { ok: true, action: "craft", item: itemName, requested: qty, crafted };
  } catch (e) {
    return { ok: false, error: `falha no craft: ${e.message}` };
  }
}

async function dropItem(rawItem, count = 1) {
  if (!bot || !connected || !mcData) return { ok: false, error: "bot offline" };
  let query = normalizeText(rawItem || "");
  query = query.replace(/^(?:um|uma|uns|umas|o|a|os|as)\s+/, "").trim();
  if (!query) return { ok: false, error: "item vazio" };

  const itemName = _resolveCraftTarget(query) || query;
  const matched = _findItemsByNameIncludes([itemName, query]);
  if (!matched.length) return { ok: false, error: `item nao encontrado no inventario: ${query}` };

  const qtyRequested = Math.max(1, Number(count) || 1);
  const target = matched.sort((a, b) => (b.count || 0) - (a.count || 0))[0];
  const qty = Math.min(qtyRequested, Number(target.count || 1));
  try {
    await bot.toss(target.type, null, qty);
    pushEvent("drop_done", { item: target.name, requested: qtyRequested, dropped: qty });
    return { ok: true, action: "drop_item", item: target.name, requested: qtyRequested, dropped: qty };
  } catch (e) {
    return { ok: false, error: `falha ao largar item: ${e.message}` };
  }
}

function _nearestHostileInRange(range) {
  return Object.values(bot.entities || {})
    .filter((e) => e && isHostileMob(e))
    .map((e) => ({ e, d: bot.entity.position.distanceTo(e.position) }))
    .filter((x) => x.d <= range)
    .sort((a, b) => a.d - b.d)[0];
}

function _tryFleeIfLowHealth() {
  if (!state.survivalEnabled) return false;
  if (Number(bot.health || 0) > MC_LOW_HEALTH) return false;

  const nearestHostile = _nearestHostileInRange(16);
  if (!nearestHostile) return false;

  const p = bot.entity.position;
  const h = nearestHostile.e.position;
  const dx = p.x - h.x;
  const dz = p.z - h.z;
  const len = Math.max(0.001, Math.sqrt(dx * dx + dz * dz));
  const nx = dx / len;
  const nz = dz / len;
  const tx = p.x + nx * MC_FLEE_DISTANCE;
  const tz = p.z + nz * MC_FLEE_DISTANCE;
  bot.pathfinder.setGoal(new goals.GoalNear(tx, p.y, tz, 2));
  return true;
}

async function _tryEatIfNeeded() {
  if (!state.survivalEnabled) return false;
  const now = Date.now();
  if (now - state.lastEatTs < 2500) return false;
  if (Number(bot.food || 20) > MC_LOW_FOOD) return false;

  const foodCandidates = [
    "cooked_beef",
    "steak",
    "cooked_porkchop",
    "cooked_mutton",
    "cooked_chicken",
    "baked_potato",
    "bread",
    "carrot",
    "potato",
    "beetroot",
  ];
  const item = _findItemByNameIncludes(foodCandidates);
  if (!item) return false;

  try {
    await bot.equip(item, "hand");
    await bot.consume();
    state.lastEatTs = now;
    pushEvent("survival_eat", { item: item.name });
    return true;
  } catch (_e) {
    return false;
  }
}

function followPlayer(playerName) {
  if (!bot?.pathfinder) return { ok: false, error: "pathfinder offline" };
  const target = String(playerName || "").trim();
  if (!target) return { ok: false, error: "player vazio" };
  state.mode = "follow";
  state.followTarget = target;
  state.goto = null;
  state.biomeTarget = "";
  state.resourceTarget = "";
  return { ok: true, action: "follow_player", target };
}

function gotoPosition(x, y, z, range = 2) {
  if (!bot?.pathfinder) return { ok: false, error: "pathfinder offline" };
  const gx = Number(x);
  const gy = Number(y);
  const gz = Number(z);
  if (!Number.isFinite(gx) || !Number.isFinite(gy) || !Number.isFinite(gz)) {
    return { ok: false, error: "coordenadas invalidas" };
  }
  state.mode = "goto";
  state.goto = { x: gx, y: gy, z: gz, range: Number(range) || 2 };
  state.followTarget = "";
  state.biomeTarget = "";
  state.resourceTarget = "";
  return { ok: true, action: "goto", target: state.goto };
}

function setExplore(enabled = true) {
  if (!bot?.pathfinder) return { ok: false, error: "pathfinder offline" };
  if (enabled) {
    state.mode = "explore";
    state.exploreTarget = null;
    state.exploreAssignedTs = 0;
  }
  else if (state.mode === "explore") _setModeIdle();
  return { ok: true, action: "explore", enabled: !!enabled };
}

function _pickExploreTarget(origin = null) {
  const p = origin || bot.entity.position;
  const minR = Number(process.env.MC_EXPLORE_MIN_RADIUS || "55");
  const maxR = Number(process.env.MC_EXPLORE_MAX_RADIUS || "140");

  let chosen = null;
  for (let i = 0; i < 10; i += 1) {
    const radius = minR + Math.random() * Math.max(1, maxR - minR);
    const angle = Math.random() * Math.PI * 2;
    const x = p.x + Math.cos(angle) * radius;
    const z = p.z + Math.sin(angle) * radius;
    const y = p.y;
    const target = { x, y, z, range: 3 };
    if (_isFarFromRecent(target)) {
      chosen = target;
      break;
    }
    if (!chosen) chosen = target;
  }

  state.exploreTarget = chosen;
  state.exploreAssignedTs = Date.now();
  _registerExploreTarget(state.exploreTarget);
}

function setAdventure(enabled = true) {
  if (!bot?.pathfinder) return { ok: false, error: "pathfinder offline" };
  if (enabled) {
    state.mode = "adventure";
    state.exploreTarget = null;
    state.exploreAssignedTs = 0;
    state.stuckTicks = 0;
  } else if (state.mode === "adventure") {
    _setModeIdle();
  }
  return { ok: true, action: "adventure", enabled: !!enabled };
}

function setBaseHere() {
  if (!bot?.entity) return { ok: false, error: "bot sem posicao" };
  const p = bot.entity.position;
  state.basePosition = { x: p.x, y: p.y, z: p.z };
  return { ok: true, action: "set_base_here", base: state.basePosition };
}

function goBase() {
  if (!state.basePosition) return { ok: false, error: "base nao definida" };
  state.mode = "goto";
  state.goto = { ...state.basePosition, range: 3 };
  return { ok: true, action: "go_base", target: state.goto };
}

function setCombat(enabled = true) {
  state.combatEnabled = !!enabled;
  return { ok: true, action: "combat", enabled: state.combatEnabled };
}

function setLoot(enabled = true) {
  state.lootEnabled = !!enabled;
  return { ok: true, action: "loot", enabled: state.lootEnabled };
}

function setSurvival(enabled = true) {
  state.survivalEnabled = !!enabled;
  return { ok: true, action: "survival", enabled: state.survivalEnabled };
}

function stopAll() {
  _setModeIdle();
  return { ok: true, action: "stop" };
}

function _findBiomeAnchor(biomeQuery) {
  if (!bot?.findBlocks || !mcData || !biomeQuery) return null;
  const target = normalizeText(biomeQuery);
  const blocks = bot.findBlocks({
    maxDistance: 256,
    count: 256,
    matching: (b) => {
      try {
        const biome = mcData.biomes[b.biome.id];
        return normalizeText(biome?.name || "").includes(target);
      } catch (_e) {
        return false;
      }
    },
  });
  return blocks?.length ? blocks[0] : null;
}

function _findResourceBlock(resourceQuery) {
  if (!bot?.findBlocks || !resourceQuery) return null;
  const target = normalizeText(resourceQuery);
  const blocks = bot.findBlocks({
    maxDistance: 96,
    count: 64,
    matching: (b) => normalizeText(b?.name || "").includes(target),
  });
  return blocks?.length ? blocks[0] : null;
}

function findBiome(biome, resource = "") {
  if (!bot?.pathfinder) return { ok: false, error: "pathfinder offline" };
  const b = String(biome || "").trim();
  if (!b) return { ok: false, error: "biome vazio" };
  state.mode = "find_biome";
  state.biomeTarget = b;
  state.resourceTarget = String(resource || "").trim();
  state.followTarget = "";
  state.goto = null;
  return { ok: true, action: "find_biome", biome: state.biomeTarget, resource: state.resourceTarget };
}

function findResource(resource) {
  if (!bot?.pathfinder) return { ok: false, error: "pathfinder offline" };
  const r = String(resource || "").trim();
  if (!r) return { ok: false, error: "resource vazio" };
  state.mode = "find_resource";
  state.resourceTarget = r;
  state.followTarget = "";
  state.goto = null;
  state.biomeTarget = "";
  return { ok: true, action: "find_resource", resource: state.resourceTarget };
}

function startMining(resource, count = 1) {
  if (!bot?.pathfinder) return { ok: false, error: "pathfinder offline" };
  const r = String(resource || "").trim();
  const n = Number(count);
  if (!r) return { ok: false, error: "resource vazio" };
  if (!Number.isFinite(n) || n <= 0) return { ok: false, error: "count invalido" };
  state.mode = "mine";
  state.miningTarget = r;
  state.miningRemaining = Math.floor(n);
  state.miningInProgress = false;
  state.followTarget = "";
  state.goto = null;
  state.biomeTarget = "";
  state.resourceTarget = "";
  return { ok: true, action: "mine", resource: r, remaining: state.miningRemaining };
}

function buildMinecraftContext() {
  if (!bot || !connected || !bot.entity) return { ok: false, connected, summary: "", data: {} };

  const p = bot.entity.position;
  const entities = Object.values(bot.entities || {})
    .filter((e) => e && e.position && e !== bot.entity)
    .map((e) => ({
      name: e.username || e.name || e.displayName || "entity",
      type: e.type || "unknown",
      kind: e.name || e.type || "unknown",
      distance: _toFixed(p.distanceTo(e.position)),
    }))
    .filter((e) => Number.isFinite(e.distance))
    .sort((a, b) => a.distance - b.distance);

  const playersNear = entities.filter((e) => e.type === "player").slice(0, 5);
  const mobsNear = entities.filter((e) => e.type === "mob").slice(0, 8);
  const inv = _inventorySummary();

  let blockBelow = null;
  try {
    blockBelow = bot.blockAt(p.offset(0, -1, 0))?.name || null;
  } catch (_e) {}

  const summary =
    `Posicao: x=${_toFixed(p.x)}, y=${_toFixed(p.y)}, z=${_toFixed(p.z)}. ` +
    `Vida=${bot.health ?? null}, Fome=${bot.food ?? null}. Bloco abaixo=${blockBelow || "desconhecido"}. ` +
    `Inventario: ${inv.summary}. ` +
    `Jogadores proximos: ${playersNear.length ? playersNear.map((x) => `${x.name}(${x.distance}m)`).join(", ") : "nenhum"}. ` +
    `Mobs proximos: ${mobsNear.length ? mobsNear.map((x) => `${x.kind}(${x.distance}m)`).join(", ") : "nenhum"}.`;

  return {
    ok: true,
    connected,
    summary,
    data: {
      position: { x: _toFixed(p.x), y: _toFixed(p.y), z: _toFixed(p.z) },
      health: bot.health ?? null,
      food: bot.food ?? null,
      block_below: blockBelow,
      inventory_summary: inv.summary,
      inventory_items: inv.items,
      players_near: playersNear,
      mobs_near: mobsNear,
      state,
    },
  };
}

async function runAutonomyTick() {
  if (!bot || !connected || !bot.entity || !bot.pathfinder) return;

  if (_tryFleeIfLowHealth()) return;
  await _tryEatIfNeeded();

  if (state.combatEnabled) {
    const now = Date.now();
    const nearestHostile = _nearestHostileInRange(AUTO_COMBAT_RANGE);
    if (nearestHostile && now - state.lastCombatTs > 900) {
      try {
        await _equipBestWeapon();
        bot.attack(nearestHostile.e);
        state.lastCombatTs = now;
      } catch (_e) {}
    }
  }

  if (state.lootEnabled && state.mode === "idle") {
    const nearestDrop = Object.values(bot.entities || {})
      .filter((e) => e && e.name === "item" && e.position)
      .map((e) => ({ e, d: bot.entity.position.distanceTo(e.position) }))
      .filter((x) => x.d <= AUTO_LOOT_RANGE)
      .sort((a, b) => a.d - b.d)[0];
    if (nearestDrop) {
      bot.pathfinder.setGoal(new goals.GoalNear(nearestDrop.e.position.x, nearestDrop.e.position.y, nearestDrop.e.position.z, 1));
      return;
    }
  }

  if (state.mode === "follow" && state.followTarget) {
    const targetEntity = bot.players[state.followTarget]?.entity;
    if (targetEntity) bot.pathfinder.setGoal(new goals.GoalFollow(targetEntity, 2), true);
    return;
  }

  if (state.mode === "goto" && state.goto) {
    bot.pathfinder.setGoal(new goals.GoalNear(state.goto.x, state.goto.y, state.goto.z, state.goto.range || 2));
    return;
  }

  if (state.mode === "explore" || state.mode === "adventure") {
    const now = Date.now();
    const maxAgeMs = Number(process.env.MC_EXPLORE_REPATH_MS || "18000");
    const target = state.exploreTarget;
    const origin = state.mode === "adventure" && state.basePosition ? state.basePosition : null;

    if (state.lastPos) {
      const moved = _distance3(state.lastPos, bot.entity.position);
      if (moved < MC_STUCK_MIN_MOVE) state.stuckTicks += 1;
      else state.stuckTicks = 0;
    } else {
      state.stuckTicks = 0;
    }
    state.lastPos = { x: bot.entity.position.x, y: bot.entity.position.y, z: bot.entity.position.z };

    let needNewTarget = false;
    if (!target) {
      needNewTarget = true;
    } else {
      const dx = bot.entity.position.x - target.x;
      const dy = bot.entity.position.y - target.y;
      const dz = bot.entity.position.z - target.z;
      const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
      const age = now - (state.exploreAssignedTs || 0);
      const noPath = !bot.pathfinder.isMoving() && age > 2500;
      const stuck = state.stuckTicks >= MC_STUCK_TICKS;
      if (dist <= (target.range || 3) || age > maxAgeMs || noPath || stuck) {
        needNewTarget = true;
      }
    }

    if (needNewTarget) _pickExploreTarget(origin);

    if (state.exploreTarget) {
      bot.pathfinder.setGoal(
        new goals.GoalNear(
          state.exploreTarget.x,
          state.exploreTarget.y,
          state.exploreTarget.z,
          state.exploreTarget.range || 3
        )
      );
    }
    return;
  }

  if (state.mode === "find_biome" && state.biomeTarget) {
    const anchor = _findBiomeAnchor(state.biomeTarget);
    if (anchor) {
      bot.pathfinder.setGoal(new goals.GoalNear(anchor.x, anchor.y, anchor.z, 3));
      if (state.resourceTarget) {
        const rb = _findResourceBlock(state.resourceTarget);
        if (rb) bot.pathfinder.setGoal(new goals.GoalNear(rb.x, rb.y, rb.z, 2));
      }
    }
    return;
  }

  if (state.mode === "find_resource" && state.resourceTarget) {
    const rb = _findResourceBlock(state.resourceTarget);
    if (rb) bot.pathfinder.setGoal(new goals.GoalNear(rb.x, rb.y, rb.z, 2));
    return;
  }

  if (state.mode === "mine" && state.miningTarget) {
    if (state.miningRemaining <= 0) {
      _setModeIdle();
      return;
    }
    if (state.miningInProgress) return;

    const pos = _findResourceBlock(state.miningTarget);
    if (!pos) {
      const p = bot.entity.position;
      bot.pathfinder.setGoal(new goals.GoalNear(p.x + (Math.random() * 20 - 10), p.y, p.z + (Math.random() * 20 - 10), 2));
      return;
    }

    const block = bot.blockAt(pos);
    if (!block) return;
    const dist = bot.entity.position.distanceTo(block.position);
    if (dist > 4.5) {
      bot.pathfinder.setGoal(new goals.GoalNear(block.position.x, block.position.y, block.position.z, 2));
      return;
    }

    try {
      state.miningInProgress = true;
      await _equipToolForResource(state.miningTarget);
      if (bot.canDigBlock(block)) {
        await bot.dig(block, true);
        state.miningRemaining = Math.max(0, state.miningRemaining - 1);
        pushEvent("mine_progress", {
          target: state.miningTarget,
          remaining: state.miningRemaining,
          pos: { x: block.position.x, y: block.position.y, z: block.position.z },
        });
      }
    } catch (_e) {
      // retry on next tick
    } finally {
      state.miningInProgress = false;
    }
    return;
  }
}

function startAutonomyLoop() {
  if (autoTimer) clearInterval(autoTimer);
  autoTimer = setInterval(() => {
    runAutonomyTick().catch(() => {});
  }, AUTO_TICK_MS);
}

function stopAutonomyLoop() {
  if (!autoTimer) return;
  clearInterval(autoTimer);
  autoTimer = null;
}

function maybeHandleIngameCommand(username, rawMessage) {
  const msg = normalizeText(rawMessage);
  if (!msg) return;
  if (MC_OWNER && normalizeText(username) !== normalizeText(MC_OWNER)) return;

  if (msg.includes("siga-me") || msg.includes("siga me")) {
    followPlayer(username);
    bot.chat(`Ok ${username}, vou te seguir.`);
    return;
  }
  const followOther = msg.match(/^siga\s+([a-z0-9_]{3,20})$/i);
  if (followOther) {
    followPlayer(followOther[1]);
    bot.chat(`Fechado, seguindo ${followOther[1]}.`);
    return;
  }
  if (msg === "pare" || msg === "parar") {
    stopAll();
    bot.chat("Parei.");
    return;
  }
  if (msg === "modo aventura on" || msg === "aventura on" || msg === "aventura") {
    setAdventure(true);
    bot.chat("Modo aventura ligado.");
    return;
  }
  if (msg === "modo aventura off" || msg === "aventura off") {
    setAdventure(false);
    bot.chat("Modo aventura desligado.");
    return;
  }
  if (msg === "marcar base" || msg === "set base") {
    const out = setBaseHere();
    if (out.ok) bot.chat("Base marcada.");
    return;
  }
  if (msg === "voltar base" || msg === "ir base") {
    const out = goBase();
    if (out.ok) bot.chat("Voltando pra base.");
    return;
  }
  if (msg === "inventario" || msg === "mochila") {
    const inv = _inventorySummary(16);
    bot.chat(`Inventario: ${inv.summary}`);
    return;
  }
  const craftCmd = msg.match(/^(?:craft|faca|faz|cria|monta)\s+([a-z0-9_\-\s]+?)(?:\s+(\d+))?$/i);
  if (craftCmd) {
    const item = (craftCmd[1] || "").trim();
    const count = Number(craftCmd[2] || "1");
    craftItem(item, count)
      .then((out) => {
        if (out.ok) bot.chat(`Craft concluido: ${out.item} x${out.crafted || out.requested}.`);
        else bot.chat(`Nao consegui craftar: ${out.error}`);
      })
      .catch((e) => bot.chat(`Erro no craft: ${e.message}`));
    return;
  }
  const dropCmd = msg.match(/^(?:largar|larga|dropa|dropar|joga fora|descarta)\s+([a-z0-9_\-\s]+?)(?:\s+(\d+))?$/i);
  if (dropCmd) {
    const item = (dropCmd[1] || "").trim();
    const count = Number(dropCmd[2] || "1");
    dropItem(item, count)
      .then((out) => {
        if (out.ok) bot.chat(`Larguei ${out.item} x${out.dropped}.`);
        else bot.chat(`Nao consegui largar: ${out.error}`);
      })
      .catch((e) => bot.chat(`Erro ao largar item: ${e.message}`));
    return;
  }
  const mineCmd = msg.match(/^mine\s+([a-z0-9_\-\s]+?)(?:\s+(\d+))?$/i);
  if (mineCmd) {
    const resource = (mineCmd[1] || "").trim();
    const count = Number(mineCmd[2] || "1");
    const out = startMining(resource, count);
    if (out.ok) bot.chat(`Beleza, vou minerar ${resource} x${count}.`);
  }
}

function createBot() {
  console.log(`[MC] Conectando em ${MC_HOST}:${MC_PORT} como ${MC_USERNAME}...`);
  bot = mineflayer.createBot({
    host: MC_HOST,
    port: MC_PORT,
    username: MC_USERNAME,
    password: MC_PASSWORD,
    version: MC_VERSION || undefined,
  });

  bot.on("spawn", () => {
    connected = true;
    mcData = mcDataLoader(bot.version);
    bot.loadPlugin(pathfinder);
    const move = new Movements(bot, mcData);
    bot.pathfinder.setMovements(move);
    console.log("[MC] Bot conectado e spawnado.");
    pushEvent("spawn", { username: MC_USERNAME });
  });

  bot.on("chat", (username, message) => {
    if (username === bot.username) return;
    console.log(`[MC CHAT] ${username}: ${message}`);
    pushEvent("chat", { username, message });
    maybeHandleIngameCommand(username, message);
  });

  bot.on("message", (jsonMsg) => {
    pushEvent("raw_message", { text: jsonMsg.toString() });
  });

  bot.on("kicked", (reason) => {
    connected = false;
    console.log("[MC] Kicked:", reason);
    pushEvent("kicked", { reason: String(reason) });
  });

  bot.on("error", (err) => {
    connected = false;
    console.log("[MC] Erro:", err.message);
    pushEvent("error", { message: err.message });
  });

  bot.on("end", () => {
    connected = false;
    console.log("[MC] Conexao encerrada. Tentando reconectar em 5s...");
    pushEvent("end", {});
    stopAutonomyLoop();
    setTimeout(createBot, 5000);
  });
}

const app = express();
app.use(express.json({ limit: "2mb" }));

app.get("/health", (_req, res) => {
  res.json({
    ok: true,
    connected,
    username: bot?.username || MC_USERNAME,
    event_id: eventId,
    state,
  });
});

app.get("/events", (req, res) => {
  const cursor = Number(req.query.cursor || 0);
  const out = events.filter((e) => e.id > cursor);
  res.json({ cursor: eventId, events: out });
});

app.get("/inventory", (_req, res) => {
  if (!bot || !connected) return res.status(503).json({ ok: false, error: "bot offline" });
  const inv = _inventorySummary(40);
  return res.json({ ok: true, connected, ...inv });
});

app.post("/chat", (req, res) => {
  const text = String(req.body?.text || "").trim();
  if (!text) return res.status(400).json({ ok: false, error: "text vazio" });
  if (!bot || !connected) return res.status(503).json({ ok: false, error: "bot offline" });
  bot.chat(text);
  pushEvent("bot_chat", { text });
  return res.json({ ok: true });
});

app.post("/command", (req, res) => {
  const command = String(req.body?.command || "").trim();
  if (!command) return res.status(400).json({ ok: false, error: "command vazio" });
  if (!bot || !connected) return res.status(503).json({ ok: false, error: "bot offline" });
  bot.chat(command.startsWith("/") ? command : `/${command}`);
  pushEvent("bot_command", { command });
  return res.json({ ok: true });
});

app.post("/action", async (req, res) => {
  const action = String(req.body?.action || "").trim();
  const payload = req.body?.payload || {};
  if (!action) return res.status(400).json({ ok: false, error: "action vazia" });
  if (!bot || !connected) return res.status(503).json({ ok: false, error: "bot offline" });

  let out = null;
  switch (action) {
    case "follow_player":
      out = followPlayer(String(payload.player || "").trim());
      break;
    case "goto":
      out = gotoPosition(payload.x, payload.y, payload.z, payload.range || 2);
      break;
    case "explore":
      out = setExplore(payload.enabled !== false);
      break;
    case "set_adventure":
      out = setAdventure(payload.enabled !== false);
      break;
    case "set_base_here":
      out = setBaseHere();
      break;
    case "go_base":
      out = goBase();
      break;
    case "inventory_summary":
      out = { ok: true, action: "inventory_summary", ..._inventorySummary(20) };
      break;
    case "craft_tool":
      out = await craftItem(String(payload.item || ""), Number(payload.count || 1));
      break;
    case "drop_item":
      out = await dropItem(String(payload.item || ""), Number(payload.count || 1));
      break;
    case "stop":
      out = stopAll();
      break;
    case "set_combat":
      out = setCombat(payload.enabled !== false);
      break;
    case "set_loot":
      out = setLoot(payload.enabled !== false);
      break;
    case "set_survival":
      out = setSurvival(payload.enabled !== false);
      break;
    case "find_biome":
      out = findBiome(String(payload.biome || ""), String(payload.resource || ""));
      break;
    case "find_resource":
      out = findResource(String(payload.resource || ""));
      break;
    case "mine":
      out = startMining(String(payload.resource || ""), Number(payload.count || 1));
      break;
    default:
      out = { ok: false, error: `action desconhecida: ${action}` };
  }

  pushEvent("action", { action, payload, result: out });
  if (!out?.ok) return res.status(400).json(out);
  return res.json(out);
});

app.get("/context", (_req, res) => {
  const context = buildMinecraftContext();
  if (!context.connected) return res.status(503).json(context);
  return res.json(context);
});

app.listen(BRIDGE_PORT, BRIDGE_HOST, () => {
  console.log(`[MC BRIDGE] API em http://${BRIDGE_HOST}:${BRIDGE_PORT}`);
});

createBot();
startAutonomyLoop();
