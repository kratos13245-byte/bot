"""Import Pod endpoints without replacing local memory or Twitch settings."""
import argparse
from datetime import datetime
from pathlib import Path
import shutil

ALLOWED = {"AI_API_URL", "REMOTE_TTS_URL", "VISION_API_URL", "IARA_API_KEY",
           "ENABLE_MINECRAFT", "ENABLE_TWITCH", "VISION_AUTO_START"}


def import_config(source, target):
    updates = {}
    for line in Path(source).read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            if key.strip() in ALLOWED:
                updates[key.strip()] = value.strip()
    if not updates.get("IARA_API_KEY"):
        raise ValueError("Arquivo sem IARA_API_KEY. Exporte client-env no Pod.")
    target = Path(target)
    lines = target.read_text(encoding="utf-8-sig").splitlines() if target.exists() else []
    if target.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        shutil.copy2(target, target.with_name(target.name + ".backup-" + stamp))
    output, seen = [], set()
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in updates:
            if key not in seen:
                output.append(f"{key}={updates[key]}")
                seen.add(key)
        else:
            output.append(line)
    output.extend(f"{key}={value}" for key, value in updates.items() if key not in seen)
    target.write_text("\n".join(output) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    import_config(args.file, Path(__file__).resolve().parent / ".env")
    print("Pod configurado. Memoria e demais configuracoes locais preservadas.")
