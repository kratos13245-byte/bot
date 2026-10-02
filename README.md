# IARA

Personagem VTuber em português com voz, avatar, Twitch, visão de tela e ações no Minecraft. O cliente Python coordena a personagem; um bridge Node/Mineflayer controla o jogo. As experiências são registradas em Markdown compatível com Obsidian.

## Cliente Windows

Requisitos: Python 3.11, Node.js 22 ou 24 e FFmpeg no PATH. Para usar avatar, configure o VTube Studio e as expressões/parâmetros de `avatar.py`.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-client.txt
Copy-Item .env.example .env
cd mineflayer_bot
npm ci
cd ..
```

Edite `.env` com os endereços de IA/voz, servidor Minecraft e credenciais Twitch/YouTube. Não substitua um `.env` existente sem preservar sua configuração. A voz de referência, modelos, tokens e avatar não fazem parte do repositório.

## YouTube Live

Para ativar o chat do YouTube, configure `ENABLE_YOUTUBE=1`, um `YOUTUBE_ACCESS_TOKEN` OAuth com acesso ao YouTube Data API e informe `YOUTUBE_VIDEO_ID` (ou o `YOUTUBE_LIVE_CHAT_ID` diretamente). O bridge lê mensagens e responde no mesmo chat; deixe `ENABLE_YOUTUBE=0` quando não estiver transmitindo.

Execute `INICIAR-MINECRAFT.cmd` e depois `INICIAR-IARA.cmd` a partir da pasta do projeto. Para habilitar o jogo, use `ENABLE_MINECRAFT=1`. O reconhecimento usa Whisper base, baixado na primeira execução. `XDG_CACHE_HOME` pode definir o local do cache.

## RunPod e voz

Para reconstruir uma instância e rodar texto, TTS e visão separadamente, siga [RUNPOD.md](RUNPOD.md). No PC, `INICIAR-CONVERSA.cmd` usa voz e visão com Minecraft/Twitch desligados.

O cliente usa `AI_API_URL` e `REMOTE_TTS_URL`. As dependências do servidor XTTS estão no `requirements.txt` original; os scripts `run_runpod_stack.sh` e `run_vision_server.sh` sobem os serviços após configurar modelos e llama.cpp. O cliente Windows não precisa instalar XTTS quando a voz é remota.

## Memória no Obsidian

Abra `OBSIDIAN_VAULT_DIR` como cofre. A memória é gravada em `<cofre>/<OBSIDIAN_MEMORY_BASE>/` e os procedimentos são lidos de `Procedures/` dentro dessa pasta, salvo configuração explícita em `MC_PROCEDURES_DIR`.

Ações demoradas, como minerar, caçar e navegar, são registradas como **aceitas**, não como concluídas. Elas não recebem reforço positivo automático só por terem começado. A confirmação automática do resultado final dessas ações ainda precisa ser implementada. Registros antigos não são reclassificados.

## Comandos Minecraft

O Python interpreta os comandos quando ambos os processos estão ativos. `MC_STANDALONE_COMMANDS=1` habilita o parser direto do Node para uso sem o Python; não ative os dois interpretadores juntos. A autonomia reinicia após reconexão e evita sobrepor ciclos assíncronos.

Mais comandos em [mineflayer_bot/README.md](mineflayer_bot/README.md).

## Conversa e responsividade

O modo de microfone não impõe mais os 10 segundos de espera após uma resposta. O fim da frase usa 450 ms de silêncio por padrão; ajuste `MIC_END_SILENCE_MS` se ela cortar suas pausas. A interrupção aleatória da gravação foi desativada (`MIC_RANDOM_INTERRUPTION=0`). Isso não implementa escuta simultânea enquanto a IARA fala.

A voz remota é gerada por frases: a primeira toca assim que seu WAV chega, e a próxima é preparada durante a reprodução. `TTS_PHRASE_PIPELINE=0` restaura uma única requisição por resposta. Frases separadas podem ter diferenças de entonação; compare com a voz real antes de escolher. O log `[LATENCIA]` mede o tempo até o primeiro áudio estar pronto, a partir do início da etapa de voz, sem incluir a geração do texto.

A personalidade mantém palavrões e deboche, com respostas casuais mais curtas e sem bordões obrigatórios. `AI_ALLOW_PROFANITY=0` desativa palavrões nas instruções; `AI_PROFANITY_LEVEL` controla o tom. A síntese não insere mais negativas prontas que alteravam as palavras escolhidas pela personagem. Configurações explícitas no seu `.env` prevalecem sobre os padrões.

## Testes

## Painel local e VTube Studio

No Windows, execute `ABRIR-PAINEL.cmd`. Ele abre `http://127.0.0.1:8765` para salvar endpoints, escolher dispositivos de áudio, iniciar/parar a IARA, conversar por texto e testar o VTube Studio. O painel não expõe a porta para a rede; a chave continua apenas no `.env`.

No VTube Studio, ative **Start API** em Plugin Settings antes de clicar em “Conectar e autorizar”. Na primeira conexão, aceite a permissão do plugin. Depois mapeie os parâmetros `MouthOpenAI`, `EyeXAI`, `EyeYAI`, `HeadXAI`, `HeadYAI`, `EyeBlinkLeftAI` e `EyeBlinkRightAI` em Model Settings; os parâmetros de saída variam conforme o modelo.

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
node mineflayer_bot/bridge.test.js
```

Os testes usam arquivos temporários e serviços simulados: cobrem memória concorrente, falha de gravação, resultados pendentes, busca de procedimentos, negociação, reconexão e execução de comandos. Não substituem uma sessão real com Minecraft, RunPod, Twitch e VTube Studio.
