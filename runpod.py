"""Rebuildable RunPod setup and independent service supervisor (standard library only)."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
PORTS = {"text": "8080", "tts": "8092", "vision": "8081"}
CONFIG = ROOT / "runpod.env"

def restrict_file(path):
    """Try to protect secrets; some RunPod mounts reject chmod."""
    try:
        os.chmod(path, 0o600)
    except PermissionError:
        print(f"Aviso: o volume não permite chmod em {path}; mantenha este arquivo privado.")

def fetch_source_archive(url, destination, directory_name):
    archive = Path("/tmp") / (directory_name + ".zip")
    unpacked = Path("/tmp") / directory_name
    if unpacked.exists():
        shutil.rmtree(unpacked)
    urllib.request.urlretrieve(url, archive)
    with zipfile.ZipFile(archive) as handle:
        handle.extractall("/tmp")
    shutil.move(str(unpacked), str(destination))
    archive.unlink(missing_ok=True)

def compatible_python():
    candidates = [sys.executable, shutil.which("python3.11"), shutil.which("python3.10")]
    for candidate in candidates:
        if not candidate:
            continue
        probe = subprocess.run([candidate, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
                               capture_output=True, text=True, check=False)
        if probe.returncode == 0 and probe.stdout.strip() in {"3 10", "3 11"}:
            return candidate
    return None


def services(value):
    result = list(PORTS) if value == "all" else list(dict.fromkeys(value.split(",")))
    if not result or any(s not in PORTS for s in result):
        raise argparse.ArgumentTypeError("Use all, text, tts, vision ou uma lista: text,tts")
    return result


def config():
    data = {}
    if CONFIG.exists():
        for line in CONFIG.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                data[key.strip()] = value.strip().strip('"').strip("'")
    data.update(os.environ)
    base = data.setdefault("IARA_DATA_DIR", "/workspace/iara-data")
    data.setdefault("LLAMA_BIN", str(Path(base) / "llama.cpp/build/bin/llama-server"))
    data.setdefault("LLAMA_MODEL_HF", "RavichandranJ/Dolphin3-Cyber-8B-GGUF:Q6_K")
    data.setdefault("VISION_MODEL_HF", "ggml-org/Ministral-3-3B-Instruct-2512-GGUF:Q8_0")
    data.setdefault("XTTS_MODEL_DIR", str(Path(base) / "tts/tts_models--multilingual--multi-dataset--xtts_v2"))
    data.setdefault("TTS_SPEAKER_WAV", str(Path(base) / "voz_referencia.wav"))
    data.setdefault("LLAMA_CACHE", str(Path(base) / "llama-cache"))
    data.setdefault("IARA_SERVER_VENV", "/tmp/iara-venv-server")
    return data


def initialize_config():
    if CONFIG.exists():
        if not config().get("IARA_API_KEY"):
            with CONFIG.open("a", encoding="utf-8") as handle:
                restrict_file(CONFIG)
                handle.write(f"\nIARA_API_KEY={secrets.token_urlsafe(32)}\n")
        return
    data = config()
    fields = ["IARA_DATA_DIR", "LLAMA_MODEL_HF", "VISION_MODEL_HF", "TTS_SPEAKER_WAV"]
    with CONFIG.open("x", encoding="utf-8") as handle:
        restrict_file(CONFIG)
        handle.write("# Configuration retained when setup is rerun. Keep a private backup.\n")
        handle.write("\n".join(f"{k}={data[k]}" for k in fields))
        handle.write(f"\nIARA_API_KEY={data.get('IARA_API_KEY') or secrets.token_urlsafe(32)}\n")


def setup(selected):
    if sys.platform != "linux":
        raise RuntimeError("Execute setup dentro do Pod Linux, nao no PC Windows.")
    tts_python = compatible_python() if "tts" in selected else None
    if "tts" in selected and not tts_python:
        raise RuntimeError("XTTS requer Python 3.10/3.11. Instale python3.11 ou escolha uma imagem CUDA devel com essa versao.")
    if any(s in selected for s in ("text", "vision")) and not shutil.which("nvcc"):
        raise RuntimeError("Falta nvcc: escolha uma imagem CUDA devel (nao apenas runtime).")
    initialize_config()
    env = config()
    base = Path(env["IARA_DATA_DIR"])
    base.mkdir(parents=True, exist_ok=True)
    elevated = [] if os.geteuid() == 0 else ["sudo"]
    subprocess.run(elevated + ["apt-get", "update"], check=True)
    subprocess.run(elevated + ["apt-get", "install", "-y", "git", "cmake", "build-essential",
                              "libcurl4-openssl-dev", "libssl-dev", "ffmpeg", "libsndfile1", "python3-venv"], check=True)
    if "tts" in selected:
        venv_dir = Path(env["IARA_SERVER_VENV"])
        python = venv_dir / "bin/python"
        if not python.exists():
            subprocess.run([tts_python, "-m", "venv", str(venv_dir)], check=True)
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(ROOT / "requirements-server.txt")], check=True)
        # ModelManager handles its own license prompt; never silently accept it.
        download = "from TTS.utils.manage import ModelManager; import sys; ModelManager(output_prefix=sys.argv[1]).download_model('tts_models/multilingual/multi-dataset/xtts_v2')"
        subprocess.run([str(python), "-c", download, str(base)], env=env, check=True)
    if any(s in selected for s in ("text", "vision")):
        source = base / "llama.cpp"
        ref = env.get("LLAMA_CPP_REF", "v0.5.0")
        if not source.exists():
            try:
                subprocess.run(["git", "-c", "core.filemode=false", "clone", "--depth", "1", "--branch", ref,
                                "https://github.com/ggml-org/llama.cpp.git", str(source)], check=True)
            except subprocess.CalledProcessError:
                print("Git não funciona neste volume; baixando o código do llama.cpp em ZIP.", flush=True)
                archive_ref = ref.lstrip("v")
                fetch_source_archive(
                    f"https://github.com/ggml-org/llama.cpp/archive/refs/tags/{ref}.zip",
                    source, f"llama.cpp-{archive_ref}",
                )
        # Reuse existing checkout/build; do not silently replace custom binaries.
        subprocess.run(["cmake", "-S", str(source), "-B", str(source / "build"),
                        "-DGGML_CUDA=ON", "-DBUILD_SHARED_LIBS=OFF", "-DCMAKE_BUILD_TYPE=Release"], check=True)
        subprocess.run(["cmake", "--build", str(source / "build"), "--target", "llama-server",
                        "-j", env.get("BUILD_JOBS", "4")], check=True)
    print("Instalacao concluida. Configuracao privada: runpod.env")
    if "tts" in selected:
        print(f"Envie sua voz de referencia para: {env['TTS_SPEAKER_WAV']}")
    print("Iniciar: python3 runpod.py start --services " + ",".join(selected))


def command(service, env):
    if service == "tts":
        return [str(Path(env["IARA_SERVER_VENV"]) / "bin/python"), str(ROOT / "tts_api.py")]
    prefix = "LLAMA" if service == "text" else "VISION"
    result = [env["LLAMA_BIN"], "--host", "0.0.0.0", "--port", env.get(prefix + "_PORT", PORTS[service]),
              "-c", env.get(prefix + "_CTX", "2048"), "-ngl", env.get(prefix + "_NGL", "999"),
              "--threads", env.get(prefix + "_THREADS", "8"), "--api-key", env["IARA_API_KEY"]]
    local = env.get(prefix + "_MODEL_LOCAL", "")
    if local:
        if not Path(local).is_file():
            raise RuntimeError(f"Modelo local inexistente: {local}")
        result += ["-m", local]
        if service == "vision":
            projector = env.get("VISION_MMPROJ", "")
            if not Path(projector).is_file():
                raise RuntimeError("Modelo local de visao precisa de VISION_MMPROJ.")
            result += ["--mmproj", projector]
    else:
        result += ["-hf", env[prefix + "_MODEL_HF"]]
    return result


def port(service, env):
    key = {"text": "LLAMA_PORT", "vision": "VISION_PORT", "tts": "TTS_API_PORT"}[service]
    return env.get(key, PORTS[service])


def healthy(service, env):
    request = urllib.request.Request(f"http://127.0.0.1:{port(service, env)}/health",
                                     headers={"Authorization": "Bearer " + env.get("IARA_API_KEY", "")})
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status == 200
    except (OSError, ValueError):
        return False


def start(selected):
    env = config()
    if not env.get("IARA_API_KEY"):
        raise RuntimeError("Execute setup primeiro ou defina IARA_API_KEY no runpod.env.")
    commands = [(s, command(s, env)) for s in selected]
    for service, cmd in commands:
        if not Path(cmd[0]).is_file():
            raise RuntimeError(f"{service} nao instalado. Execute setup --services {service}.")
        if service == "tts" and not Path(env["TTS_SPEAKER_WAV"]).is_file():
            raise RuntimeError(f"Falta a voz de referencia: {env['TTS_SPEAKER_WAV']}")
        if healthy(service, env):
            raise RuntimeError(f"{service} ja esta ativo na porta {port(service, env)}.")
    env.update(TTS_PRELOAD="1", TTS_API_HOST="0.0.0.0")
    processes, logs = [], []
    log_dir = ROOT / ".runpod"
    log_dir.mkdir(exist_ok=True)
    def interrupted(*_args):
        raise KeyboardInterrupt
    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        for service, cmd in commands:
            log = (log_dir / f"{service}.log").open("a", encoding="utf-8")
            logs.append(log)
            child = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            processes.append((service, child))
        pending = set(selected)
        deadline = time.monotonic() + float(env.get("SERVICE_START_TIMEOUT_SEC", "1800"))
        print("Carregando/baixando modelos; logs em .runpod/. Ctrl+C encerra estes servicos.", flush=True)
        while True:
            for service, child in processes:
                if child.poll() is not None:
                    raise RuntimeError(f"{service} encerrou (codigo {child.returncode}); veja .runpod/{service}.log")
                if service in pending and healthy(service, env):
                    pending.remove(service)
                    print(f"PRONTO: {service} na porta {port(service, env)}", flush=True)
            if pending and time.monotonic() > deadline:
                raise RuntimeError("Tempo de inicializacao excedido: " + ", ".join(sorted(pending)))
            time.sleep(1 if pending else 3)
    except KeyboardInterrupt:
        print("Encerrando servicos desta sessao.")
    finally:
        signal.signal(signal.SIGTERM, previous)
        for _, child in processes:
            if child.poll() is None:
                child.terminate()
        for _, child in processes:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        for log in logs:
            log.close()


def client_env(selected, pod_id):
    if not pod_id or not all(c.isalnum() or c == '-' for c in pod_id):
        raise ValueError("Informe --pod-id com o ID do novo Pod.")
    env = config()
    if not env.get("IARA_API_KEY"):
        raise RuntimeError("Execute setup para gerar a chave primeiro.")
    keys = {"text": "AI_API_URL", "tts": "REMOTE_TTS_URL", "vision": "VISION_API_URL"}
    lines = [f"IARA_API_KEY={env['IARA_API_KEY']}", "ENABLE_MINECRAFT=0", "ENABLE_TWITCH=0",
             "VISION_AUTO_START=" + ("1" if "vision" in selected else "0")]
    for service in selected:
        lines.append(f"{keys[service]}=https://{pod_id}-{port(service, env)}.proxy.runpod.net")
    target = ROOT / "client-runpod.env"
    with target.open("w", encoding="utf-8") as handle:
        restrict_file(target)
        handle.write("\n".join(lines) + "\n")
    print("Configuracao privada criada: client-runpod.env. Importe no PC com configurar_runpod.py.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["setup", "start", "status", "client-env"])
    parser.add_argument("--services", type=services, default=services("all"))
    parser.add_argument("--pod-id", default=os.getenv("RUNPOD_POD_ID", ""))
    args = parser.parse_args()
    try:
        if args.action == "setup":
            setup(args.services)
        elif args.action == "start":
            start(args.services)
        elif args.action == "client-env":
            client_env(args.services, args.pod_id)
        else:
            states = {s: healthy(s, config()) for s in args.services}
            print(json.dumps(states, indent=2))
            return 0 if all(states.values()) else 1
    except (RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"ERRO: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
