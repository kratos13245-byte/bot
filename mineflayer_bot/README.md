# Mineflayer Bridge (IARA)

## 1) Configurar `.env`
Use no projeto (`/workspace/bot/.env` ou local):

```env
ENABLE_MINECRAFT=1
MC_BRIDGE_URL=http://127.0.0.1:8095

MC_HOST=127.0.0.1
MC_PORT=25565
MC_USERNAME=IARA_Bot
MC_PASSWORD=
MC_VERSION=

MC_BRIDGE_HOST=127.0.0.1
MC_BRIDGE_PORT=8095
```

## 2) Instalar e iniciar o bridge Node

```bash
cd mineflayer_bot
npm install
npm start
```

Endpoints principais:
- `GET /health`
- `GET /events`
- `GET /inventory`
- `POST /chat`
- `POST /command`
- `GET /context` (resumo de redondeza: posicao, vida, jogadores/mobs proximos)
- `POST /action` (controle autonomo: follow, goto, explore, stop, find_biome, find_resource)

## 3) Rodar o `main.py`
Com `ENABLE_MINECRAFT=1`, o Python conecta no bridge e:
- escuta o chat do Minecraft
- responde com a IARA no chat do jogo

Comandos locais extras no `main.py`:
- `/mc status`
- `/mc cmd <comando>`

## 4) Fase 1 de autonomia
Comandos naturais no chat do Minecraft:
- `siga-me`
- `siga <nick>`
- `pare`
- `va para <x> <y> <z>`
- `explorar`
- `va ate bioma <nome> e procura <recurso>`
- `mine <recurso> [quantidade]`
- `combate on|off`
- `loot on|off`
- `sobrevivencia on|off`

Por padrao, quando detectar comando, o bot executa e responde com feedback curto no chat.

## 5) Fallback de "visao Minecraft"
Quando a visao geral estiver desligada, o Python pode usar o contexto do Minecraft:

```env
MC_CONTEXT_ENABLED=1
MC_CONTEXT_TTL_SEC=6
MC_CONTEXT_FALLBACK_WHEN_VISION_OFF=1
MC_SKIP_AI_ON_COMMAND=1
MC_OWNER=
MC_AUTO_COMBAT_RANGE=6
MC_AUTO_LOOT_RANGE=8
MC_AUTO_TICK_MS=1200
MC_LOW_HEALTH=8
MC_LOW_FOOD=12
MC_FLEE_DISTANCE=18
MC_EXPLORE_HISTORY_SIZE=8
MC_EXPLORE_MIN_TARGET_DISTANCE=30
MC_STUCK_MIN_MOVE=1.2
MC_STUCK_TICKS=5
MC_CONTEXT_INV_MAX_ITEMS=12
MC_CONTEXT_MAX_ENTITY_DISTANCE=28
MC_CONTEXT_MAX_PLAYERS=4
MC_CONTEXT_MAX_MOBS=6
MC_AI_ACTION_PLANNER=1
MC_NARRATION_ENABLED=1
MC_NARRATION_INTERVAL_SEC=5
MC_NARRATION_COOLDOWN_SEC=28
MC_NARRATION_TO_CHAT=1
MC_NARRATION_TO_TTS=0
```

## 6) Fase 3 (autonomia avancada)
Novos comandos naturais (chat Minecraft ou via IA):
- `modo aventura` / `modo aventura on|off`
- `marcar base`
- `voltar base`

O que muda:
- exploracao anti-loop (evita ficar reciclando pontos muito proximos)
- deteccao de travamento (se ficar "patinando", troca alvo automaticamente)
- memoria curta de alvos recentes de exploracao
- suporte a base (salvar posicao atual e retornar depois)
- resumo de inventario disponivel via API/acao
- crafting de ferramentas/itens simples por comando natural

Comandos extras:
- `inventario` / `mochila`
- `craft <item> [quantidade]` (ex.: `craft picareta de pedra`)
- `coloca <bloco> [quantidade] [no chao|na frente|aqui]`
- `largar <item> [quantidade]`

## 7) Planner IA + narracao de arredores
- Planner: quando o parser fixo nao identificar, a IA tenta converter a ordem em acao estruturada segura (whitelist).
- Narracao: loop que comenta mudancas relevantes dos arredores com cooldown para evitar flood.

Comandos locais:
- `/mc ai <ordem>`
- `/mc narracao on`
- `/mc narracao off`
