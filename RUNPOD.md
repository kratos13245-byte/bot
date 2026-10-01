# IARA em um Pod novo

O Pod roda somente os serviços escolhidos. Minecraft, captura da tela, microfone e avatar ficam no PC. Estes comandos não criam nem alugam instâncias automaticamente.

## Preparar uma vez por instância

Em um Pod novo, o caminho mais simples é baixar e executar o bootstrap. Ele instala Python 3.11, ferramentas do sistema, baixa o projeto sem criar `.git` no volume problemático e instala os três serviços:

```bash
curl -fsSL https://raw.githubusercontent.com/kratos13245-byte/bot/main/IARA/bootstrap_runpod.sh | bash
```

Depois envie `voz_referencia.wav` e execute `bash run_runpod_stack.sh` dentro de `/workspace/bot/IARA`.

Escolha uma imagem Ubuntu/Debian com **Python 3.10 ou 3.11 e CUDA devel** (com `nvcc`), e permissão root/sudo para instalar pacotes. Nas portas HTTP do template, coloque `8080,8092,8081` (texto, voz e visão). A GPU precisa comportar os modelos escolhidos juntos; se faltar VRAM, use modelos menores ou serviços em Pods separados.

No terminal do Pod:

```bash
cd /workspace
git -c core.filemode=false clone https://github.com/kratos13245-byte/bot.git
cd bot
bash setup_runpod.sh
```

Isso instala um ambiente exclusivo para XTTS, baixa seu modelo e compila llama.cpp com CUDA. O gerenciador XTTS pode pedir aceitação da licença: leia e responda no terminal. Texto e visão baixam seus modelos na primeira inicialização. A versão padrão do llama.cpp é `v0.5.0`; `LLAMA_CPP_REF` permite escolher outra em uma instalação nova.

`runpod.env` é criado uma vez com configuração e chave privada. Rodar o instalador novamente preserva esse arquivo e reutiliza downloads/compilação. Para personalizar antes de instalar, crie `runpod.env` ou exporte as variáveis desejadas.

**Envie sua `voz_referencia.wav` para `/workspace/iara-data/voz_referencia.wav`.** A voz não está no GitHub. `TTS_SPEAKER_WAV` permite outro caminho.

Instalação parcial, sem exigir as outras partes:

```bash
bash setup_runpod.sh --services tts
bash setup_runpod.sh --services vision
bash setup_runpod.sh --services text
```

## Iniciar tudo ou separadamente

```bash
# Texto + voz + visao; nao inicia Minecraft.
bash run_runpod_stack.sh

# Alternativas independentes:
bash run_tts_api.sh
bash run_vision_server.sh
python3 runpod.py start --services text

# Ou apenas texto e voz:
python3 runpod.py start --services text,tts
```

Espere `PRONTO` para cada serviço. TTS carrega o modelo e a voz antes de aceitar requisições. Os logs ficam em `.runpod/text.log`, `.runpod/tts.log` e `.runpod/vision.log`. Ctrl+C encerra os serviços daquela execução. Mantenha o terminal conectado ou use `tmux`, se instalado. Parar os serviços **não encerra a cobrança do Pod**.

Em outro terminal:

```bash
cd /workspace/bot
python3 runpod.py status
python3 runpod.py client-env
```

Se o ID não for detectado, use `python3 runpod.py client-env --pod-id ID_DO_POD`. Para Pods separados, exporte apenas o serviço correspondente com `--services tts`, por exemplo, e configure a mesma `IARA_API_KEY` nos Pods. Modelos locais são configuráveis com `LLAMA_MODEL_LOCAL`; visão local também precisa de `VISION_MODEL_LOCAL` e `VISION_MMPROJ`.

## Conectar o PC após recriar o Pod

Baixe o arquivo privado `client-runpod.env` do Pod para a pasta do projeto no PC. Ele contém endereços e chave de acesso; não publique o arquivo.

```powershell
.venv\Scripts\python.exe configurar_runpod.py client-runpod.env
```

A importação preserva a memória e outras configurações locais e salva um backup do `.env` anterior. Repita a exportação/importação quando o ID do Pod mudar.

**Voz e visão sem Minecraft:** abra `INICIAR-CONVERSA.cmd`. Ele desliga Minecraft e Twitch nessa sessão e ativa a visão. Digite `/mic-live` para conversar pelo microfone. O servidor de texto também é necessário para responder como personagem.

**Testes individuais, sem iniciar a personagem:**

```powershell
# Só voz: gera teste-voz.wav para abrir no reprodutor de áudio.
.venv\Scripts\python.exe testar_servico.py tts --text "Oi, porra. Voltei."

# Só visão: captura a tela deste PC e imprime a descrição.
.venv\Scripts\python.exe testar_servico.py vision
```

## Ao apagar o Pod

O armazenamento local e o volume vinculado ao Pod são apagados com ele. Um Network Volume é separado e pode sobreviver ao Pod, mas tem cobrança própria; seu uso é opcional. Sem ele, o instalador refaz o ambiente e baixa os modelos novamente. Guarde no PC a voz e uma cópia privada do `runpod.env`. A memória do Obsidian fica no PC.

Fontes: [armazenamento RunPod](https://docs.runpod.io/pods/storage/types), [portas e proxy](https://docs.runpod.io/pods/configuration/expose-ports), [compilação CUDA](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md), [XTTS](https://huggingface.co/coqui/XTTS-v2).

## Validação

Os testes verificam seleção dos serviços, configuração, autenticação e isolamento com dependências simuladas. A compilação CUDA e a inferência com os modelos precisam ser validadas em um Pod real. O proxy HTTP tem limite de duração por requisição; o cliente usa frases curtas e o servidor aquece XTTS antes da primeira chamada.
