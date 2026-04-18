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
- `POST /chat`
- `POST /command`
- `GET /context` (resumo de redondeza: posicao, vida, jogadores/mobs proximos)

## 3) Rodar o `main.py`
Com `ENABLE_MINECRAFT=1`, o Python conecta no bridge e:
- escuta o chat do Minecraft
- responde com a IARA no chat do jogo

Comandos locais extras no `main.py`:
- `/mc status`
- `/mc cmd <comando>`

## 4) Fallback de "visao Minecraft"
Quando a visao geral estiver desligada, o Python pode usar o contexto do Minecraft:

```env
MC_CONTEXT_ENABLED=1
MC_CONTEXT_TTL_SEC=6
MC_CONTEXT_FALLBACK_WHEN_VISION_OFF=1
```
