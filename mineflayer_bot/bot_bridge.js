const express = require("express");
const mineflayer = require("mineflayer");
const dotenv = require("dotenv");

dotenv.config({ path: "../.env" });
dotenv.config();

const MC_HOST = process.env.MC_HOST || "127.0.0.1";
const MC_PORT = Number(process.env.MC_PORT || "25565");
const MC_USERNAME = process.env.MC_USERNAME || "IARA_Bot";
const MC_PASSWORD = process.env.MC_PASSWORD || undefined;
const MC_VERSION = process.env.MC_VERSION || false;

const BRIDGE_HOST = process.env.MC_BRIDGE_HOST || "127.0.0.1";
const BRIDGE_PORT = Number(process.env.MC_BRIDGE_PORT || "8095");

const events = [];
let eventId = 0;
let bot = null;
let connected = false;

function _toFixed(n) {
  return Number.isFinite(n) ? Number(n.toFixed(1)) : n;
}

function buildMinecraftContext() {
  if (!bot || !connected || !bot.entity) {
    return {
      ok: false,
      connected,
      summary: "",
      data: {},
    };
  }

  const p = bot.entity.position;
  const health = bot.health ?? null;
  const food = bot.food ?? null;
  const yaw = bot.entity.yaw ?? 0;
  const pitch = bot.entity.pitch ?? 0;

  const selfPos = { x: _toFixed(p.x), y: _toFixed(p.y), z: _toFixed(p.z) };

  const entities = Object.values(bot.entities || {})
    .filter((e) => e && e.position && e !== bot.entity)
    .map((e) => {
      const dist = p.distanceTo(e.position);
      return {
        name: e.username || e.name || e.displayName || "entity",
        type: e.type || "unknown",
        kind: e.name || e.type || "unknown",
        distance: _toFixed(dist),
      };
    })
    .filter((e) => Number.isFinite(e.distance))
    .sort((a, b) => a.distance - b.distance);

  const playersNear = entities.filter((e) => e.type === "player").slice(0, 5);
  const mobsNear = entities.filter((e) => e.type === "mob").slice(0, 8);

  let blockBelow = null;
  try {
    const b = bot.blockAt(p.offset(0, -1, 0));
    blockBelow = b?.name || null;
  } catch (_e) {
    blockBelow = null;
  }

  const playersTxt = playersNear.length
    ? playersNear.map((x) => `${x.name}(${x.distance}m)`).join(", ")
    : "nenhum";

  const mobsTxt = mobsNear.length
    ? mobsNear.map((x) => `${x.kind}(${x.distance}m)`).join(", ")
    : "nenhum";

  const summary =
    `Posicao: x=${selfPos.x}, y=${selfPos.y}, z=${selfPos.z}. ` +
    `Vida=${health}, Fome=${food}. Bloco abaixo=${blockBelow || "desconhecido"}. ` +
    `Jogadores proximos: ${playersTxt}. Mobs proximos: ${mobsTxt}. ` +
    `Orientacao yaw=${_toFixed(yaw)}, pitch=${_toFixed(pitch)}.`;

  return {
    ok: true,
    connected,
    summary,
    data: {
      position: selfPos,
      health,
      food,
      block_below: blockBelow,
      players_near: playersNear,
      mobs_near: mobsNear,
      yaw: _toFixed(yaw),
      pitch: _toFixed(pitch),
    },
  };
}

function pushEvent(type, payload) {
  eventId += 1;
  events.push({
    id: eventId,
    ts: Date.now(),
    type,
    payload,
  });

  if (events.length > 2000) {
    events.splice(0, events.length - 2000);
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
    console.log("[MC] Bot conectado e spawnado.");
    pushEvent("spawn", { username: MC_USERNAME });
  });

  bot.on("chat", (username, message) => {
    if (username === bot.username) return;
    console.log(`[MC CHAT] ${username}: ${message}`);
    pushEvent("chat", { username, message });
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
  });
});

app.get("/events", (req, res) => {
  const cursor = Number(req.query.cursor || 0);
  const out = events.filter((e) => e.id > cursor);
  res.json({ cursor: eventId, events: out });
});

app.post("/chat", (req, res) => {
  const text = String(req.body?.text || "").trim();
  if (!text) return res.status(400).json({ ok: false, error: "text vazio" });
  if (!bot || !connected) return res.status(503).json({ ok: false, error: "bot offline" });

  bot.chat(text);
  pushEvent("bot_chat", { text });
  res.json({ ok: true });
});

app.post("/command", (req, res) => {
  const command = String(req.body?.command || "").trim();
  if (!command) return res.status(400).json({ ok: false, error: "command vazio" });
  if (!bot || !connected) return res.status(503).json({ ok: false, error: "bot offline" });

  bot.chat(command.startsWith("/") ? command : `/${command}`);
  pushEvent("bot_command", { command });
  res.json({ ok: true });
});

app.get("/context", (_req, res) => {
  const context = buildMinecraftContext();
  if (!context.connected) {
    return res.status(503).json(context);
  }
  res.json(context);
});

app.listen(BRIDGE_PORT, BRIDGE_HOST, () => {
  console.log(`[MC BRIDGE] API em http://${BRIDGE_HOST}:${BRIDGE_PORT}`);
});

createBot();
