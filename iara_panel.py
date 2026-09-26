"""Painel local da IARA: configuração, testes e controle do processo principal."""
from __future__ import annotations
import asyncio, json, os, secrets, subprocess, sys
from collections import deque
from pathlib import Path
from aiohttp import web

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
TOKEN = secrets.token_urlsafe(24)
SAFE_KEYS = {"AI_API_URL", "REMOTE_TTS_URL", "VISION_API_URL", "ENABLE_MINECRAFT", "ENABLE_TWITCH", "VISION_AUTO_START", "ENABLE_AVATAR", "VTS_HOST", "VTS_PORT", "AUDIO_INPUT_DEVICE", "AUDIO_OUTPUT_DEVICE"}
SECRET_KEYS = {"IARA_API_KEY"}

def read_env():
    out = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1); out[k.strip()] = v.strip().strip('"').strip("'")
    return out

def write_env(values):
    current = ENV_FILE.read_text(encoding="utf-8-sig").splitlines() if ENV_FILE.exists() else []
    keys = set(values); result = []; seen = set()
    for line in current:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in keys:
            if key not in seen: result.append(f"{key}={values[key]}"); seen.add(key)
        else: result.append(line)
    result.extend(f"{k}={v}" for k, v in values.items() if k not in seen)
    ENV_FILE.write_text("\n".join(result) + "\n", encoding="utf-8")

HTML = r'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>IARA • painel</title>
<style>:root{--bg:#10131d;--card:#191e2b;--line:#30384c;--text:#f3f5fb;--muted:#9aa4bb;--hot:#ff4f81;--ok:#46d19a}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 80% 0,#302040,var(--bg) 45%);color:var(--text);font:15px system-ui,Segoe UI,sans-serif}main{max-width:1100px;margin:auto;padding:28px 20px 60px}header{display:flex;justify-content:space-between;align-items:center;margin-bottom:22px}h1{font-size:30px;margin:0}h1 span{color:var(--hot)}h2{font-size:18px;margin:0 0 14px}.sub,.hint{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:15px}.card{background:#191e2bdd;border:1px solid var(--line);border-radius:16px;padding:18px;box-shadow:0 14px 40px #0002}.wide{grid-column:1/-1}label{display:block;color:var(--muted);font-size:12px;margin:10px 0 5px}input,select{width:100%;background:#0e121b;border:1px solid var(--line);border-radius:9px;color:var(--text);padding:10px}button{border:0;border-radius:9px;padding:10px 14px;background:var(--hot);color:white;font-weight:700;cursor:pointer;margin:5px 4px 0 0}button.alt{background:#303950}button.ok{background:#168d68}.row{display:flex;gap:8px;flex-wrap:wrap}.status{font-weight:700;margin:7px 0;color:var(--muted)}.status.ok{color:var(--ok)}pre{height:180px;overflow:auto;background:#0b0e15;border-radius:10px;padding:12px;color:#b8c3d9;white-space:pre-wrap}.chat{display:flex;gap:8px}.chat input{flex:1}.pill{display:inline-block;border-radius:99px;background:#293247;padding:4px 9px;color:var(--muted);font-size:12px}.check{display:flex;align-items:center;gap:8px;color:var(--text);margin:8px 0}.check input{width:auto}</style></head><body><main><header><div><h1>IA<span>RA</span></h1><div class="sub">painel de controle • personalidade intacta</div></div><span class="pill" id="proc">parada</span></header>
<div class="grid"><section class="card"><h2>Conexões</h2><label>URL da IA</label><input id="AI_API_URL"><label>URL do TTS</label><input id="REMOTE_TTS_URL"><label>URL da visão</label><input id="VISION_API_URL"><label>Chave IARA (fica só no .env)</label><input id="IARA_API_KEY" type="password" placeholder="••••••••"><button onclick="save()">Salvar configurações</button><div id="save" class="status"></div></section>
<section class="card"><h2>VTube Studio</h2><div class="hint">Abra o VTube Studio, ative “Start API” e deixe esta porta.</div><label>Host</label><input id="VTS_HOST"><label>Porta</label><input id="VTS_PORT"><button class="ok" onclick="vts('connect')">Conectar e autorizar</button><button class="alt" onclick="vts('model')">Ler modelo e hotkeys</button><div id="vts" class="status">ainda não testado</div></section>
<section class="card"><h2>Áudio e módulos</h2><label>Entrada (índice ou nome, vazio = padrão)</label><input id="AUDIO_INPUT_DEVICE"><label>Saída (índice ou nome, vazio = padrão)</label><input id="AUDIO_OUTPUT_DEVICE"><label class="check"><input type="checkbox" id="ENABLE_AVATAR"> avatar</label><label class="check"><input type="checkbox" id="VISION_AUTO_START"> visão automática</label><label class="check"><input type="checkbox" id="ENABLE_MINECRAFT"> Minecraft</label><label class="check"><input type="checkbox" id="ENABLE_TWITCH"> Twitch</label><button onclick="devices()" class="alt">Listar dispositivos</button><div id="devices" class="hint"></div></section>
<section class="card"><h2>Controle</h2><div class="row"><button class="ok" onclick="start()">Iniciar IARA</button><button class="alt" onclick="stop()">Parar</button><button class="alt" onclick="send('/mic')">Ouvir uma vez</button><button class="alt" onclick="send('/visao agora')">Testar visão</button></div><div id="control" class="status"></div><div class="chat"><input id="msg" placeholder="Fale com a IARA por texto…" onkeydown="if(event.key==='Enter')send()"><button onclick="send()">Enviar</button></div></section>
<section class="card wide"><h2>Terminal da IARA</h2><pre id="log">carregando…</pre></section><section class="card wide"><h2>Configuração no VTube Studio</h2><div class="hint">O painel cria os parâmetros <b>MouthOpenAI</b>, <b>EyeXAI</b>, <b>EyeYAI</b>, <b>HeadXAI</b>, <b>HeadYAI</b> e os dois olhos. No VTube Studio, abra Model Settings → <b>Parameter</b> e mapeie esses inputs para os parâmetros do seu modelo; os nomes de saída mudam entre modelos. As hotkeys de humor continuam sendo configuradas no próprio VTube Studio.</div></section></div></main>
<script>const $=id=>document.getElementById(id);let cfg={};async function api(url,opt){let r=await fetch(url,{...opt,headers:{'Content-Type':'application/json',...(opt||{}).headers}});return r.json()}async function load(){let d=await api('/api/config');cfg=d;for(const k of Object.keys(d)){if($(k))$(k).type==='checkbox'?$(k).checked=d[k]==='1':$(k).value=d[k]||''}poll()}async function save(){let d={};for(const k of [...Object.keys(cfg),...['IARA_API_KEY']])if($(k))d[k]=$(k).type==='checkbox'?($(k).checked?'1':'0'):$(k).value;let r=await api('/api/config',{method:'POST',body:JSON.stringify(d)});$('save').textContent=r.message||r.error}async function start(){let r=await api('/api/process/start',{method:'POST'});$('control').textContent=r.message||r.error}async function stop(){let r=await api('/api/process/stop',{method:'POST'});$('control').textContent=r.message||r.error}async function send(x){let m=x||$('msg').value;if(!m)return;await api('/api/process/send',{method:'POST',body:JSON.stringify({text:m})});$('msg').value=''}async function vts(action){let r=await api('/api/vts/'+action,{method:'POST'});$('vts').textContent=r.message||r.error}async function devices(){let r=await api('/api/audio/devices');$('devices').textContent=r.items?.join(' • ')||r.error}async function poll(){let r=await api('/api/process/status');$('proc').textContent=r.running?'rodando':'parada';$('proc').style.color=r.running?'#46d19a':'';$('log').textContent=(r.log||[]).join('\n');setTimeout(poll,1500)}load()</script></body></html>'''

class Panel:
    def __init__(self): self.proc=None; self.log=deque(maxlen=300)
    def config(self):
        env=read_env(); return {k:env.get(k,"") for k in SAFE_KEYS|SECRET_KEYS} | {"IARA_API_KEY": "" if not env.get("IARA_API_KEY") else "configured"}
    async def status(self,_): return web.json_response({"running":self.proc is not None and self.proc.poll() is None,"log":list(self.log)})
    async def config_get(self,_): return web.json_response(self.config())
    async def config_post(self,req):
        data=await req.json(); current=read_env(); updates={k:str(data[k]) for k in SAFE_KEYS if k in data}
        if data.get("IARA_API_KEY") and data["IARA_API_KEY"] != "configured": updates["IARA_API_KEY"]=data["IARA_API_KEY"]
        write_env({**current,**updates}); return web.json_response({"message":"Configuração salva."})
    async def start(self,_):
        if self.proc and self.proc.poll() is None:return web.json_response({"message":"A IARA já está rodando."})
        env=os.environ.copy(); env.update(read_env()); env["PYTHONUNBUFFERED"]="1"
        self.proc=subprocess.Popen([sys.executable,"main.py"],cwd=ROOT,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        asyncio.create_task(self._read()); return web.json_response({"message":"IARA iniciada."})
    async def _read(self):
        while self.proc and self.proc.stdout:
            line=await asyncio.to_thread(self.proc.stdout.readline)
            if not line:break
            self.log.append(line.rstrip())
    async def stop(self,_):
        if not self.proc or self.proc.poll() is not None:return web.json_response({"message":"A IARA já está parada."})
        try:self.proc.stdin.write('/sair\n'); self.proc.stdin.flush()
        except Exception:pass
        try: await asyncio.to_thread(self.proc.wait,5)
        except subprocess.TimeoutExpired:self.proc.terminate()
        return web.json_response({"message":"IARA parada."})
    async def send(self,req):
        if not self.proc or self.proc.poll() is not None:return web.json_response({"error":"Inicie a IARA primeiro."},status=400)
        text=(await req.json()).get("text","").strip(); self.proc.stdin.write(text+'\n'); self.proc.stdin.flush(); return web.json_response({"message":"enviado"})
    async def audio(self,_):
        try:
            import sounddevice as sd
            return web.json_response({"items":[f"{i}: {x['name']}" for i,x in enumerate(sd.query_devices())]})
        except Exception as e:return web.json_response({"error":str(e)},status=500)
    async def vts(self,req):
        action=req.match_info['action']
        try:
            from avatar import AvatarController
            a=AvatarController(); a.connect(); result="VTube Studio autorizado e parâmetros garantidos."
            if action=='model': result="Conectado. Use Model Settings para mapear os parâmetros AI ao seu modelo."
            a.parar_idle(); a.parar_piscada(); a.close(); return web.json_response({"message":result})
        except Exception as e:return web.json_response({"error":f"VTube Studio não respondeu: {e}"},status=502)

def create_app():
    p=Panel(); app=web.Application(); app.router.add_get('/',lambda _:web.Response(text=HTML,content_type='text/html'))
    app.router.add_get('/api/config',p.config_get); app.router.add_post('/api/config',p.config_post); app.router.add_get('/api/process/status',p.status); app.router.add_post('/api/process/start',p.start); app.router.add_post('/api/process/stop',p.stop); app.router.add_post('/api/process/send',p.send); app.router.add_get('/api/audio/devices',p.audio); app.router.add_post('/api/vts/{action}',p.vts); return app

if __name__=='__main__': web.run_app(create_app(),host='127.0.0.1',port=int(os.getenv('IARA_PANEL_PORT','8765')))
