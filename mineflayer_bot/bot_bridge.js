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
const MC_RUNTIME_MODE = (process.env.MC_RUNTIME_MODE || "quality").toLowerCase().trim();
const PERF_MODE = MC_RUNTIME_MODE === "performance";

const AUTO_COMBAT_RANGE = Number(process.env.MC_AUTO_COMBAT_RANGE || (PERF_MODE ? "5" : "6"));
const AUTO_LOOT_RANGE = Number(process.env.MC_AUTO_LOOT_RANGE || (PERF_MODE ? "6" : "8"));
const AUTO_TICK_MS = Number(process.env.MC_AUTO_TICK_MS || (PERF_MODE ? "1700" : "1200"));
const MC_LOW_HEALTH = Number(process.env.MC_LOW_HEALTH || "8");
const MC_LOW_FOOD = Number(process.env.MC_LOW_FOOD || "12");
const MC_FLEE_DISTANCE = Number(process.env.MC_FLEE_DISTANCE || "18");
const MC_EXPLORE_HISTORY_SIZE = Number(process.env.MC_EXPLORE_HISTORY_SIZE || "8");
const MC_EXPLORE_MIN_TARGET_DISTANCE = Number(process.env.MC_EXPLORE_MIN_TARGET_DISTANCE || "30");
const MC_STUCK_MIN_MOVE = Number(process.env.MC_STUCK_MIN_MOVE || "1.2");
const MC_STUCK_TICKS = Number(process.env.MC_STUCK_TICKS || "5");
const MC_CONTEXT_INV_MAX_ITEMS = Number(process.env.MC_CONTEXT_INV_MAX_ITEMS || (PERF_MODE ? "8" : "12"));
const MC_CONTEXT_MAX_ENTITY_DISTANCE = Number(process.env.MC_CONTEXT_MAX_ENTITY_DISTANCE || (PERF_MODE ? "16" : "28"));
const MC_CONTEXT_MAX_PLAYERS = Number(process.env.MC_CONTEXT_MAX_PLAYERS || (PERF_MODE ? "3" : "4"));
const MC_CONTEXT_MAX_MOBS = Number(process.env.MC_CONTEXT_MAX_MOBS || (PERF_MODE ? "4" : "6"));
const MC_INTERACT_MAX_DISTANCE = Number(process.env.MC_INTERACT_MAX_DISTANCE || (PERF_MODE ? "10" : "12"));
const MC_MODE_STALL_MS = Number(process.env.MC_MODE_STALL_MS || "22000");
const MC_SEARCH_ROAM_RADIUS = Number(process.env.MC_SEARCH_ROAM_RADIUS || "24");
const MC_STOCK_AUTOFILL = String(process.env.MC_STOCK_AUTOFILL || "1") === "1";
const MC_STOCK_CHECK_MS = Number(process.env.MC_STOCK_CHECK_MS || "15000");
const MC_STOCK_MIN_LOGS = Number(process.env.MC_STOCK_MIN_LOGS || "4");
const MC_STOCK_MIN_PLANKS = Number(process.env.MC_STOCK_MIN_PLANKS || "12");
const MC_STOCK_MIN_STICKS = Number(process.env.MC_STOCK_MIN_STICKS || "6");
const MC_STOCK_MIN_COBBLE = Number(process.env.MC_STOCK_MIN_COBBLE || "16");
const MC_STOCK_MIN_FOOD = Number(process.env.MC_STOCK_MIN_FOOD || "4");

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
  lastGoalKey: "",
  lastMode: "idle",
  modeSinceTs: 0,
  searchMisses: 0,
  mineMisses: 0,
  lastStockCheckTs: 0,
  stockInProgress: false,
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
  state.lastMode = "idle";
  state.modeSinceTs = Date.now();
  state.followTarget = "";
  state.goto = null;
  state.biomeTarget = "";
  state.resourceTarget = "";
  state.searchMisses = 0;
  state.mineMisses = 0;
  state.miningTarget = "";
  state.miningRemaining = 0;
  state.miningInProgress = false;
  state.exploreTarget = null;
  state.exploreAssignedTs = 0;
  state.lastPos = null;
  state.stuckTicks = 0;
  state.lastGoalKey = "";
  if (bot?.pathfinder) bot.pathfinder.setGoal(null);
}

function _setGoalStable(goal, goalKey, dynamic = false) {
  if (!bot?.pathfinder) return;
  const key = String(goalKey || "");
  if (key && state.lastGoalKey === key) return;
  bot.pathfinder.setGoal(goal, dynamic);
  state.lastGoalKey = key;
}

function _setMode(newMode) {
  const m = String(newMode || "idle").trim() || "idle";
  state.mode = m;
  state.lastMode = m;
  state.modeSinceTs = Date.now();
  state.searchMisses = 0;
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

function _inventoryCountByPredicate(predicate) {
  return _inventoryItems()
    .filter(predicate)
    .reduce((acc, it) => acc + (it.count || 0), 0);
}

function _countItemsByNameIncludes(candidates) {
  const items = _inventoryItems();
  const normalized = candidates.map((c) => normalizeText(c));
  return items
    .filter((it) => normalized.some((c) => normalizeText(it.name).includes(c)))
    .reduce((acc, it) => acc + (it.count || 0), 0);
}

function _countFoodAny() {
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
  return _countItemsByNameIncludes(foodCandidates);
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
    "tabua": "__any_planks__",
    "tabuas": "__any_planks__",
    "tábua": "__any_planks__",
    "tábuas": "__any_planks__",
    "plank": "__any_planks__",
    "planks": "__any_planks__",
    "tabua de madeira": "__any_planks__",
    "tabuas de madeira": "__any_planks__",
    "tábua de madeira": "__any_planks__",
    "tábuas de madeira": "__any_planks__",
  };

  if (aliases[t]) return aliases[t];
  if (mcData?.itemsByName?.[t]) return t;
  return null;
}

function _countLogsAny() {
  return _inventoryCountByPredicate((it) => {
    const n = String(it?.name || "");
    return n.endsWith("_log") || n.endsWith("_wood") || n.endsWith("_stem") || n.endsWith("_hyphae");
  });
}

function _countCobbleAny() {
  return _inventoryCountByPredicate((it) => {
    const n = normalizeText(it?.name || "");
    return n === "cobblestone" || n === "cobbled_deepslate";
  });
}

function _countIronAny() {
  return _inventoryCountByPredicate((it) => {
    const n = normalizeText(it?.name || "");
    return n === "iron_ingot" || n === "raw_iron" || n === "iron_ore" || n === "deepslate_iron_ore";
  });
}

function _materialPlanForItem(rawItem, count = 1) {
  const item = _resolveCraftTarget(rawItem) || normalizeText(rawItem || "");
  const qty = Math.max(1, Number(count) || 1);
  const recipes = {
    crafting_table: [{ key: "log", need: 1 * qty, resource: "log" }],
    furnace: [{ key: "cobblestone", need: 8 * qty, resource: "cobblestone" }],

    wooden_pickaxe: [{ key: "log", need: 2 * qty, resource: "log" }],
    stone_pickaxe: [{ key: "cobblestone", need: 3 * qty, resource: "cobblestone" }, { key: "log", need: 1 * qty, resource: "log" }],
    iron_pickaxe: [{ key: "iron", need: 3 * qty, resource: "iron_ore" }, { key: "log", need: 1 * qty, resource: "log" }],

    wooden_axe: [{ key: "log", need: 2 * qty, resource: "log" }],
    stone_axe: [{ key: "cobblestone", need: 3 * qty, resource: "cobblestone" }, { key: "log", need: 1 * qty, resource: "log" }],
    iron_axe: [{ key: "iron", need: 3 * qty, resource: "iron_ore" }, { key: "log", need: 1 * qty, resource: "log" }],

    wooden_shovel: [{ key: "log", need: 1 * qty, resource: "log" }],
    stone_shovel: [{ key: "cobblestone", need: 1 * qty, resource: "cobblestone" }, { key: "log", need: 1 * qty, resource: "log" }],
    iron_shovel: [{ key: "iron", need: 1 * qty, resource: "iron_ore" }, { key: "log", need: 1 * qty, resource: "log" }],

    wooden_sword: [{ key: "log", need: 1 * qty, resource: "log" }],
    stone_sword: [{ key: "cobblestone", need: 2 * qty, resource: "cobblestone" }, { key: "log", need: 1 * qty, resource: "log" }],
    iron_sword: [{ key: "iron", need: 2 * qty, resource: "iron_ore" }, { key: "log", need: 1 * qty, resource: "log" }],
  };

  const plan = recipes[item];
  if (!plan) return null;
  return { item, qty, plan };
}

function _materialCurrentStock(key) {
  switch (key) {
    case "log":
      return _countLogsAny();
    case "cobblestone":
      return _countCobbleAny();
    case "iron":
      return _countIronAny();
    default:
      return 0;
  }
}

function collectMaterialsForItem(rawItem, count = 1) {
  if (!bot || !connected || !mcData) return { ok: false, error: "bot offline" };
  const planned = _materialPlanForItem(rawItem, count);
  if (!planned) {
    return { ok: false, error: `nao tenho plano de coleta para: ${rawItem}` };
  }

  const deficits = planned.plan
    .map((req) => {
      const have = _materialCurrentStock(req.key);
      return {
        ...req,
        have,
        missing: Math.max(0, Number(req.need || 0) - Number(have || 0)),
      };
    })
    .filter((x) => x.missing > 0)
    .sort((a, b) => b.missing - a.missing);

  if (!deficits.length) {
    return {
      ok: true,
      action: "collect_for_item",
      item: planned.item,
      done: true,
      summary: `Materiais suficientes para ${planned.item}.`,
    };
  }

  const next = deficits[0];
  const out = startMining(next.resource, next.missing);
  if (!out?.ok) return out;
  return {
    ok: true,
    action: "collect_for_item",
    item: planned.item,
    done: false,
    next_resource: next.resource,
    missing: next.missing,
    summary: `Coletando ${next.resource} x${next.missing} para ${planned.item}.`,
  };
}

function _logToPlankName(logName) {
  const n = String(logName || "");
  if (n.endsWith("_log")) return n.replace(/_log$/, "_planks");
  if (n.endsWith("_wood")) return n.replace(/_wood$/, "_planks");
  if (n.endsWith("_stem")) return n.replace(/_stem$/, "_planks");
  if (n.endsWith("_hyphae")) return n.replace(/_hyphae$/, "_planks");
  return "";
}

async function _craftIntermediatesFromLogs() {
  const logs = _inventoryItems().filter((it) => {
    const n = String(it.name || "");
    return n.endsWith("_log") || n.endsWith("_wood") || n.endsWith("_stem") || n.endsWith("_hyphae");
  });

  let converted = 0;
  for (const log of logs) {
    const plankName = _logToPlankName(log.name);
    const plankDef = mcData?.itemsByName?.[plankName];
    if (!plankDef) continue;
    try {
      const recipes = bot.recipesFor(plankDef.id, null, 1, null) || [];
      if (!recipes.length) continue;
      // tenta converter o stack inteiro do tipo de tronco encontrado
      const craftCount = Math.max(1, Number(log.count || 1));
      await bot.craft(recipes[0], craftCount, null);
      converted += craftCount;
    } catch (_e) {
      // ignora falha pontual e tenta os proximos tipos de tronco
    }
  }
  return converted;
}

async function _craftIntermediatesSticks() {
  const targetSticks = Math.max(0, Number(arguments[0] || 0));
  const stickDef = mcData?.itemsByName?.stick;
  if (!stickDef) return 0;
  try {
    const recipes = bot.recipesFor(stickDef.id, null, 1, null) || [];
    if (!recipes.length) return 0;

    const currentSticks = _inventoryCountByPredicate((it) => String(it.name || "") === "stick");
    if (targetSticks <= currentSticks) return 0;

    // receita comum: 2 planks -> 4 sticks
    const missingSticks = Math.max(0, targetSticks - currentSticks);
    const craftTimes = Math.max(1, Math.ceil(missingSticks / 4));
    await bot.craft(recipes[0], craftTimes, null);
    return craftTimes * 4;
  } catch (_e) {
    return 0;
  }
}

function _estimatedSticksNeeded(targetName, qty = 1) {
  const target = String(targetName || "");
  const n = Math.max(1, Number(qty) || 1);
  if (target.includes("_pickaxe")) return 2 * n;
  if (target.includes("_axe")) return 2 * n;
  if (target.includes("_shovel")) return 2 * n;
  if (target.includes("_hoe")) return 2 * n;
  if (target.includes("_sword")) return 1 * n;
  if (target === "fishing_rod") return 3 * n;
  return 0;
}

async function _prepareBasicCraftIntermediates(targetName) {
  const target = String(targetName || "");
  const qty = Math.max(1, Number(arguments[1] || 1));
  let changed = 0;

  const beforePlanks = _inventoryCountByPredicate((it) => String(it.name || "").endsWith("_planks"));
  const beforeSticks = _inventoryCountByPredicate((it) => String(it.name || "") === "stick");

  changed += await _craftIntermediatesFromLogs();

  const sticksNeeded = _estimatedSticksNeeded(target, qty);
  if (sticksNeeded > 0) {
    changed += await _craftIntermediatesSticks(sticksNeeded);
  }

  const afterPlanks = _inventoryCountByPredicate((it) => String(it.name || "").endsWith("_planks"));
  const afterSticks = _inventoryCountByPredicate((it) => String(it.name || "") === "stick");

  const materialDelta = Math.max(0, (afterPlanks - beforePlanks)) + Math.max(0, (afterSticks - beforeSticks));
  return changed + materialDelta;
}

function _findNearbyCraftingTable(maxDistance = 8) {
  const tableId = mcData?.blocksByName?.crafting_table?.id;
  if (!tableId || !bot?.findBlock) return null;
  return bot.findBlock({ matching: tableId, maxDistance }) || null;
}

function _resolveBlockTarget(rawName) {
  const t = normalizeText(rawName || "").replace(/^(?:um|uma|uns|umas|o|a|os|as)\s+/, "").trim();
  if (!t) return null;
  const aliases = {
    "fornalha": "furnace",
    "mesa de trabalho": "crafting_table",
    "mesa de craft": "crafting_table",
    "crafting table": "crafting_table",
    "crafting_table": "crafting_table",
    "bancada": "crafting_table",
    "mesa": "crafting_table",
    "bau": "chest",
    "bau duplo": "chest",
    "bau grande": "chest",
    "cofre": "chest",
    "forja": "smithing_table",
    "bigorna": "anvil",
    "anvil": "anvil",
  };
  return aliases[t] || t;
}

function _findNearestBlockByName(blockName, maxDistance = MC_INTERACT_MAX_DISTANCE) {
  if (!mcData?.blocksByName || !bot?.findBlock) return null;
  const b = mcData.blocksByName[blockName];
  if (!b) return null;
  return bot.findBlock({ matching: b.id, maxDistance }) || null;
}

async function _waitUntil(fn, timeoutMs = 9000, intervalMs = 180) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      if (fn()) return true;
    } catch (_e) {}
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  return false;
}

async function interactBlock(rawBlock, maxDistance = MC_INTERACT_MAX_DISTANCE) {
  if (!bot || !connected || !mcData) return { ok: false, error: "bot offline" };
  const blockName = _resolveBlockTarget(rawBlock);
  if (!blockName) return { ok: false, error: "bloco alvo vazio" };

  const block = _findNearestBlockByName(blockName, Number(maxDistance) || MC_INTERACT_MAX_DISTANCE);
  if (!block) return { ok: false, error: `bloco nao encontrado por perto: ${blockName}` };

  const targetPos = block.position;
  let dist = bot.entity.position.distanceTo(targetPos);
  if (dist > 4.8) {
    if (!bot.pathfinder) return { ok: false, error: "pathfinder offline" };
    bot.pathfinder.setGoal(new goals.GoalNear(targetPos.x, targetPos.y, targetPos.z, 2));
    const reached = await _waitUntil(
      () => bot.entity.position.distanceTo(targetPos) <= 4.8,
      12000,
      200,
    );
    if (!reached) return { ok: false, error: `nao consegui aproximar do bloco: ${blockName}` };
    dist = bot.entity.position.distanceTo(targetPos);
  }

  try {
    await bot.lookAt(targetPos.offset(0.5, 0.5, 0.5), true);
    await bot.activateBlock(block);
    pushEvent("interact_done", {
      block: block.name,
      distance: Number(dist.toFixed(2)),
      pos: { x: targetPos.x, y: targetPos.y, z: targetPos.z },
    });
    return { ok: true, action: "interact_block", block: block.name, distance: Number(dist.toFixed(2)) };
  } catch (e) {
    return { ok: false, error: `falha ao interagir com bloco: ${e.message}` };
  }
}

async function craftItem(rawItem, count = 1) {
  if (!bot || !connected || !mcData) return { ok: false, error: "bot offline" };
  const itemName = _resolveCraftTarget(rawItem);
  if (!itemName) return { ok: false, error: `item desconhecido: ${rawItem}` };

  if (itemName === "__any_planks__") {
    const before = _inventoryCountByPredicate((it) => String(it.name || "").endsWith("_planks"));
    const converted = await _craftIntermediatesFromLogs();
    const after = _inventoryCountByPredicate((it) => String(it.name || "").endsWith("_planks"));
    const crafted = Math.max(0, after - before);
    if (crafted <= 0 && converted <= 0) {
      return { ok: false, error: "sem logs para converter em tabuas" };
    }
    pushEvent("craft_done", { item: "planks", requested: count, crafted });
    return { ok: true, action: "craft", item: "planks", requested: Number(count || 1), crafted };
  }

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
    // tenta preparar materiais intermediarios (ex.: tronco -> tabua -> graveto)
    await _prepareBasicCraftIntermediates(itemName, qty);

    recipes = bot.recipesFor(itemDef.id, null, qty, null) || [];
    if (!recipes.length) {
      tableBlock = _findNearbyCraftingTable(8);
      if (tableBlock) recipes = bot.recipesFor(itemDef.id, null, qty, tableBlock) || [];
    }
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

function _isPlaceableTargetBlock(block) {
  if (!block) return true;
  const name = String(block.name || "").toLowerCase();
  if (["air", "cave_air", "void_air"].includes(name)) return true;
  return block.boundingBox === "empty";
}

function _findPlacementSpot(positionMode = "front") {
  if (!bot?.entity) return null;
  const feet = bot.entity.position.floored();
  const mode = String(positionMode || "front").toLowerCase().trim();
  const yaw = bot.entity.yaw || 0;
  const fdx = Math.round(-Math.sin(yaw));
  const fdz = Math.round(-Math.cos(yaw));

  // "here/aqui/no chao" significa "perto de mim no chao", nao literalmente embaixo do bot.
  const around = [
    [fdx, 0, fdz],
    [1, 0, 0],
    [-1, 0, 0],
    [0, 0, 1],
    [0, 0, -1],
    [fdx + 1, 0, fdz],
    [fdx - 1, 0, fdz],
    [fdx, 0, fdz + 1],
    [fdx, 0, fdz - 1],
    [fdx * 2, 0, fdz * 2],
  ];

  const inFront = [
    [fdx, 0, fdz],
    [fdx * 2, 0, fdz * 2],
    [fdx + 1, 0, fdz],
    [fdx - 1, 0, fdz],
    [fdx, 0, fdz + 1],
    [fdx, 0, fdz - 1],
    [1, 0, 0],
    [-1, 0, 0],
    [0, 0, 1],
    [0, 0, -1],
  ];

  const underMode = mode === "under" || mode === "embaixo";
  const hereMode = mode === "here" || mode === "aqui";
  const offsets = underMode ? [[0, -1, 0], ...around] : (hereMode ? around : inFront);
  const targets = offsets.map(([dx, dy, dz]) => feet.offset(dx, dy, dz));

  for (const target of targets) {
    const targetBlock = bot.blockAt(target);
    if (!_isPlaceableTargetBlock(targetBlock)) continue;

    const refs = [
      target.offset(0, -1, 0),
      target.offset(1, 0, 0),
      target.offset(-1, 0, 0),
      target.offset(0, 0, 1),
      target.offset(0, 0, -1),
      target.offset(0, 1, 0),
    ];

    for (const pos of refs) {
      const ref = bot.blockAt(pos);
      if (!ref || ref.boundingBox === "empty") continue;
      const faceVector = target.minus(ref.position);
      if (Math.abs(faceVector.x) + Math.abs(faceVector.y) + Math.abs(faceVector.z) !== 1) continue;
      return { ok: true, target, ref, faceVector };
    }
  }

  return { ok: false, error: "nao achei espaco valido por perto para colocar bloco" };
}

async function placeBlock(rawItem, count = 1, position = "front") {
  if (!bot || !connected || !mcData) return { ok: false, error: "bot offline" };
  let query = normalizeText(rawItem || "");
  query = query.replace(/^(?:um|uma|uns|umas|o|a|os|as)\s+/, "").trim();
  if (!query) return { ok: false, error: "item vazio" };

  const resolved = _resolveCraftTarget(query) || query;
  const matched = _findItemsByNameIncludes([resolved, query]).filter((it) => it && it.type != null);
  if (!matched.length) return { ok: false, error: `item nao encontrado no inventario: ${query}` };

  const qtyRequested = Math.max(1, Number(count) || 1);
  const qty = Math.min(qtyRequested, matched.reduce((acc, it) => acc + (it.count || 0), 0));
  if (qty <= 0) return { ok: false, error: "quantidade invalida" };

  const spot = _findPlacementSpot(position);
  if (!spot?.ok) return { ok: false, error: spot?.error || "nao achei local para posicionar" };

  let placed = 0;
  try {
    const item = matched.sort((a, b) => (b.count || 0) - (a.count || 0))[0];
    await bot.equip(item, "hand");
    for (let i = 0; i < qty; i += 1) {
      await bot.placeBlock(spot.ref, spot.faceVector);
      placed += 1;
      if (i + 1 < qty) {
        // para pilha, tenta reposicionar no mesmo local somente se ainda houver espaco
        const blockNow = bot.blockAt(spot.target);
        if (!_isPlaceableTargetBlock(blockNow)) break;
      }
    }
    pushEvent("place_done", {
      item: item.name,
      requested: qtyRequested,
      placed,
      position,
      target: { x: spot.target.x, y: spot.target.y, z: spot.target.z },
    });
    return {
      ok: true,
      action: "place_block",
      item: item.name,
      requested: qtyRequested,
      placed,
      position,
    };
  } catch (e) {
    return { ok: false, error: `falha ao colocar bloco: ${e.message}` };
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

async function _tryMaintainSurvivalStock() {
  if (!state.survivalEnabled || !MC_STOCK_AUTOFILL) return false;
  if (!bot || !connected || !mcData) return false;

  const now = Date.now();
  if (now - (state.lastStockCheckTs || 0) < MC_STOCK_CHECK_MS) return false;
  state.lastStockCheckTs = now;

  if (state.stockInProgress) return false;
  state.stockInProgress = true;
  try {
    const logs = _countLogsAny();
    const planks = _inventoryCountByPredicate((it) => String(it.name || "").endsWith("_planks"));
    const sticks = _inventoryCountByPredicate((it) => String(it.name || "") === "stick");
    const cobble = _countCobbleAny();
    const food = _countFoodAny();

    // 1) Converter logs em tabuas quando faltar base de craft
    if (planks < MC_STOCK_MIN_PLANKS && logs > 0) {
      const before = planks;
      await _craftIntermediatesFromLogs();
      const after = _inventoryCountByPredicate((it) => String(it.name || "").endsWith("_planks"));
      if (after > before) {
        pushEvent("stock_restock", { kind: "planks", before, after, min: MC_STOCK_MIN_PLANKS });
        return true;
      }
    }

    // 2) Craftar apenas o minimo de sticks necessario
    if (sticks < MC_STOCK_MIN_STICKS) {
      const crafted = await _craftIntermediatesSticks(MC_STOCK_MIN_STICKS);
      if (crafted > 0) {
        pushEvent("stock_restock", { kind: "sticks", crafted, min: MC_STOCK_MIN_STICKS });
        return true;
      }
    }

    // 3) Se estiver em aventura, sair pra coletar base quando faltar muito
    if (state.mode === "adventure") {
      if (logs < MC_STOCK_MIN_LOGS) {
        const miss = Math.max(1, MC_STOCK_MIN_LOGS - logs);
        const out = startMining("log", miss);
        if (out?.ok) {
          pushEvent("stock_collect", { kind: "log", missing: miss, min: MC_STOCK_MIN_LOGS });
          return true;
        }
      }
      if (cobble < MC_STOCK_MIN_COBBLE) {
        const miss = Math.max(1, MC_STOCK_MIN_COBBLE - cobble);
        const out = startMining("cobblestone", miss);
        if (out?.ok) {
          pushEvent("stock_collect", { kind: "cobblestone", missing: miss, min: MC_STOCK_MIN_COBBLE });
          return true;
        }
      }
      // Heuristica simples: se comida esta baixa, tenta procurar recurso alimentar.
      if (food < MC_STOCK_MIN_FOOD) {
        const out = findResource("wheat");
        if (out?.ok) {
          pushEvent("stock_collect", { kind: "food_hint_wheat", have: food, min: MC_STOCK_MIN_FOOD });
          return true;
        }
      }
    }
  } finally {
    state.stockInProgress = false;
  }
  return false;
}

function followPlayer(playerName) {
  if (!bot?.pathfinder) return { ok: false, error: "pathfinder offline" };
  const target = String(playerName || "").trim();
  if (!target) return { ok: false, error: "player vazio" };
  _setMode("follow");
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
  _setMode("goto");
  state.goto = { x: gx, y: gy, z: gz, range: Number(range) || 2 };
  state.followTarget = "";
  state.biomeTarget = "";
  state.resourceTarget = "";
  return { ok: true, action: "goto", target: state.goto };
}

function setExplore(enabled = true) {
  if (!bot?.pathfinder) return { ok: false, error: "pathfinder offline" };
  if (enabled) {
    _setMode("explore");
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
    _setMode("adventure");
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
  _setMode("find_biome");
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
  _setMode("find_resource");
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
  _setMode("mine");
  state.miningTarget = r;
  state.miningRemaining = Math.floor(n);
  state.miningInProgress = false;
  state.mineMisses = 0;
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
    .filter((e) => Number.isFinite(e.distance) && e.distance <= MC_CONTEXT_MAX_ENTITY_DISTANCE)
    .sort((a, b) => a.distance - b.distance);

  const playersNear = entities.filter((e) => e.type === "player").slice(0, MC_CONTEXT_MAX_PLAYERS);
  const mobsNear = entities.filter((e) => e.type === "mob").slice(0, MC_CONTEXT_MAX_MOBS);
  const inv = _inventorySummary();

  let blockBelow = null;
  try {
    blockBelow = bot.blockAt(p.offset(0, -1, 0))?.name || null;
  } catch (_e) {}

  const summary =
    `Posicao: x=${_toFixed(p.x)}, y=${_toFixed(p.y)}, z=${_toFixed(p.z)}. ` +
    `Vida=${bot.health ?? null}, Fome=${bot.food ?? null}. Bloco abaixo=${blockBelow || "desconhecido"}. ` +
    `Inventario: ${inv.summary}. ` +
    `Raio de contexto=${MC_CONTEXT_MAX_ENTITY_DISTANCE} blocos. ` +
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

  if (state.mode !== state.lastMode) {
    state.lastMode = state.mode;
    state.modeSinceTs = Date.now();
    state.searchMisses = 0;
  }

  if (
    state.mode !== "idle" &&
    !state.miningInProgress &&
    Date.now() - Number(state.modeSinceTs || 0) > MC_MODE_STALL_MS &&
    !bot.pathfinder.isMoving()
  ) {
    pushEvent("mode_stall_reset", { mode: state.mode, ms: Date.now() - Number(state.modeSinceTs || 0) });
    _setModeIdle();
    return;
  }

  if (_tryFleeIfLowHealth()) return;
  await _tryEatIfNeeded();
  if (await _tryMaintainSurvivalStock()) return;

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
    if (targetEntity) {
      const p = targetEntity.position;
      const key = `follow:${state.followTarget}:${Math.round(p.x)}:${Math.round(p.y)}:${Math.round(p.z)}`;
      _setGoalStable(new goals.GoalFollow(targetEntity, 2), key, true);
    }
    return;
  }

  if (state.mode === "goto" && state.goto) {
    const key = `goto:${Math.round(state.goto.x)}:${Math.round(state.goto.y)}:${Math.round(state.goto.z)}:${state.goto.range || 2}`;
    _setGoalStable(new goals.GoalNear(state.goto.x, state.goto.y, state.goto.z, state.goto.range || 2), key, false);
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
      const ex = state.exploreTarget;
      const key = `explore:${Math.round(ex.x)}:${Math.round(ex.y)}:${Math.round(ex.z)}:${ex.range || 3}`;
      _setGoalStable(
        new goals.GoalNear(
          ex.x,
          ex.y,
          ex.z,
          ex.range || 3
        ),
        key,
        false
      );
    }
    return;
  }

  if (state.mode === "find_biome" && state.biomeTarget) {
    const anchor = _findBiomeAnchor(state.biomeTarget);
    if (anchor) {
      state.searchMisses = 0;
      _setGoalStable(new goals.GoalNear(anchor.x, anchor.y, anchor.z, 3), `biome:${anchor.x}:${anchor.y}:${anchor.z}`, false);
      if (state.resourceTarget) {
        const rb = _findResourceBlock(state.resourceTarget);
        if (rb) _setGoalStable(new goals.GoalNear(rb.x, rb.y, rb.z, 2), `biome_resource:${rb.x}:${rb.y}:${rb.z}`, false);
      }
    } else {
      state.searchMisses += 1;
      const p = bot.entity.position;
      const tx = p.x + (Math.random() * MC_SEARCH_ROAM_RADIUS * 2 - MC_SEARCH_ROAM_RADIUS);
      const tz = p.z + (Math.random() * MC_SEARCH_ROAM_RADIUS * 2 - MC_SEARCH_ROAM_RADIUS);
      _setGoalStable(new goals.GoalNear(tx, p.y, tz, 3), `biome_roam:${Math.round(tx)}:${Math.round(p.y)}:${Math.round(tz)}`, false);
      if (state.searchMisses > 12) {
        pushEvent("search_timeout", { mode: "find_biome", biome: state.biomeTarget });
        _setMode("explore");
      }
    }
    return;
  }

  if (state.mode === "find_resource" && state.resourceTarget) {
    const rb = _findResourceBlock(state.resourceTarget);
    if (rb) {
      state.searchMisses = 0;
      _setGoalStable(new goals.GoalNear(rb.x, rb.y, rb.z, 2), `resource:${rb.x}:${rb.y}:${rb.z}`, false);
    } else {
      state.searchMisses += 1;
      const p = bot.entity.position;
      const tx = p.x + (Math.random() * MC_SEARCH_ROAM_RADIUS * 2 - MC_SEARCH_ROAM_RADIUS);
      const tz = p.z + (Math.random() * MC_SEARCH_ROAM_RADIUS * 2 - MC_SEARCH_ROAM_RADIUS);
      _setGoalStable(new goals.GoalNear(tx, p.y, tz, 3), `resource_roam:${Math.round(tx)}:${Math.round(p.y)}:${Math.round(tz)}`, false);
      if (state.searchMisses > 10) {
        pushEvent("search_timeout", { mode: "find_resource", resource: state.resourceTarget });
        _setMode("explore");
      }
    }
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
      state.mineMisses += 1;
      const p = bot.entity.position;
      const isWood = normalizeText(state.miningTarget).includes("log") || normalizeText(state.miningTarget).includes("wood");
      const roam = isWood ? Math.max(30, MC_SEARCH_ROAM_RADIUS * 2) : 16;
      const tx = p.x + (Math.random() * roam * 2 - roam);
      const tz = p.z + (Math.random() * roam * 2 - roam);
      _setGoalStable(new goals.GoalNear(tx, p.y, tz, 3), `mine_roam:${Math.round(tx)}:${Math.round(p.y)}:${Math.round(tz)}`, false);

      if (state.mineMisses > 14 && isWood) {
        pushEvent("mine_timeout", { target: state.miningTarget, misses: state.mineMisses, fallback: "explore" });
        _setMode("explore");
        return;
      }
      if (state.mineMisses > 20) {
        pushEvent("mine_timeout", { target: state.miningTarget, misses: state.mineMisses, fallback: "idle" });
        _setModeIdle();
        return;
      }
      return;
    }
    state.mineMisses = 0;

    const block = bot.blockAt(pos);
    if (!block) return;
    const dist = bot.entity.position.distanceTo(block.position);
    if (dist > 4.5) {
      _setGoalStable(
        new goals.GoalNear(block.position.x, block.position.y, block.position.z, 2),
        `mine_target:${block.position.x}:${block.position.y}:${block.position.z}`,
        false,
      );
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
  const placeCmd = msg.match(
    /^(?:coloca|coloque|por|poe|põe|posiciona)\s+([a-z0-9_\-\s]+?)(?:\s+(?:x|por)?\s*(\d+))?(?:\s+(?:no chao|na frente|aqui))?$/i
  );
  if (placeCmd) {
    const item = (placeCmd[1] || "").trim();
    const count = Number(placeCmd[2] || "1");
    const pos = msg.includes("no chao") || msg.includes("aqui") ? "here" : "front";
    placeBlock(item, count, pos)
      .then((out) => {
        if (out.ok) bot.chat(`Coloquei ${out.item} x${out.placed}.`);
        else bot.chat(`Nao consegui colocar bloco: ${out.error}`);
      })
      .catch((e) => bot.chat(`Erro ao colocar bloco: ${e.message}`));
    return;
  }
  const interactCmd = msg.match(/^(?:interage|interagir|usa|use|abre|abrir)\s+(?:o|a)?\s*([a-z0-9_\-\s]+)$/i);
  if (interactCmd) {
    const block = (interactCmd[1] || "").trim();
    interactBlock(block)
      .then((out) => {
        if (out.ok) bot.chat(`Interagi com ${out.block}.`);
        else bot.chat(`Nao consegui interagir: ${out.error}`);
      })
      .catch((e) => bot.chat(`Erro ao interagir: ${e.message}`));
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
    case "place_block":
      out = await placeBlock(
        String(payload.item || ""),
        Number(payload.count || 1),
        String(payload.position || "front"),
      );
      break;
    case "interact_block":
      out = await interactBlock(
        String(payload.block || ""),
        Number(payload.max_distance || MC_INTERACT_MAX_DISTANCE),
      );
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
    case "collect_for_item":
      out = collectMaterialsForItem(String(payload.item || ""), Number(payload.count || 1));
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
  console.log(`[MC BRIDGE] runtime mode: ${PERF_MODE ? "performance" : "quality"}`);
});

createBot();
startAutonomyLoop();
