import hashlib
import json
import platform
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODELS = ROOT / "models"
RUNTIME = ROOT / "runtime"
HEADERS = {"User-Agent": "voice-arena-local/0.1"}
LLM_FILE = "Qwen3-0.6B-Q4_0.gguf"
LLM_SHA = "da2572f16c06133561ce56accaa822216f2391ef4d37fba427801cd6736417d4"
VOICE_PATHS = (
    "en/en_US/lessac/medium/en_US-lessac-medium",
    "en/en_US/amy/medium/en_US-amy-medium",
    "hi/hi_IN/pratham/medium/hi_IN-pratham-medium",
    "hi/hi_IN/priyamvada/medium/hi_IN-priyamvada-medium",
)


def request(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60)


def get_json(url):
    with request(url) as response:
        return json.load(response)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url, path, expected=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and (not expected or sha256(path) == expected):
        print("Already downloaded:", path.name, flush=True)
        return
    partial = path.with_name(path.name + ".part")
    for attempt in range(3):
        try:
            print("Downloading:", path.name, flush=True)
            with request(url) as response, partial.open("wb") as output:
                total = int(response.headers.get("Content-Length", "0"))
                received = 0
                shown = 0
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    received += len(chunk)
                    if received - shown >= 50 * 1024 * 1024:
                        print(f"  {received // (1024 * 1024)} MB" + (f" / {total // (1024 * 1024)} MB" if total else ""), flush=True)
                        shown = received
                if total and received != total:
                    raise RuntimeError("Incomplete download: " + path.name)
            if expected and sha256(partial) != expected:
                raise RuntimeError("Checksum mismatch: " + path.name)
            partial.replace(path)
            return
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)


def hf_revision(repo):
    return get_json("https://huggingface.co/api/models/" + repo)["sha"]


def hf_download(repo, revision, filename, destination, expected=None):
    directory = filename.rsplit("/", 1)[0] if "/" in filename else ""
    listing = get_json("https://huggingface.co/api/models/" + repo + "/tree/" + revision + ("/" + directory if directory else ""))
    entry = next((item for item in listing if item["path"] == filename), None)
    if not entry:
        raise RuntimeError("Model file not found: " + repo + "/" + filename)
    digest = expected or entry.get("lfs", {}).get("oid")
    download("https://huggingface.co/" + repo + "/resolve/" + revision + "/" + filename, destination, digest)
    if destination.stat().st_size != entry["size"]:
        raise RuntimeError("Unexpected file size: " + filename)
    return {"repo": repo, "revision": revision, "file": filename, "sha256": sha256(destination)}


def install_llama():
    destination = RUNTIME / "llama"
    existing = list(destination.rglob("llama-server.exe")) if destination.exists() else []
    if existing:
        metadata = RUNTIME / "llama-release.json"
        if not metadata.exists():
            raise RuntimeError("Existing llama runtime has no provenance. Move it aside and rerun setup.")
        return json.loads(metadata.read_text(encoding="utf-8"))
    release = get_json("https://api.github.com/repos/ggml-org/llama.cpp/releases/latest")
    asset = next((item for item in release["assets"] if item["name"].endswith("bin-win-cpu-x64.zip")), None)
    if not asset:
        raise RuntimeError("No Windows CPU x64 binary in latest llama.cpp release.")
    digest = asset.get("digest")
    expected = digest.removeprefix("sha256:") if digest and digest.startswith("sha256:") else None
    archive = RUNTIME / asset["name"]
    download(asset["browser_download_url"], archive, expected)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        for item in zipped.infolist():
            target = (destination / item.filename).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise RuntimeError("Unsafe archive entry: " + item.filename)
        zipped.extractall(destination)
    if not list(destination.rglob("llama-server.exe")):
        raise RuntimeError("Downloaded runtime does not contain llama-server.exe.")
    metadata = {"tag": release["tag_name"], "url": asset["browser_download_url"], "sha256": sha256(archive)}
    (RUNTIME / "llama-release.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def main():
    if platform.system() != "Windows" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise RuntimeError("This setup script targets Windows x64. See README for manual alternatives.")
    MODELS.mkdir(exist_ok=True)
    RUNTIME.mkdir(exist_ok=True)
    manifest = {"llama": install_llama(), "files": []}
    repo = "ggml-org/Qwen3-0.6B-GGUF"
    revision = hf_revision(repo)
    manifest["files"].append(hf_download(repo, revision, LLM_FILE, MODELS / LLM_FILE, LLM_SHA))
    repo = "rhasspy/piper-voices"
    revision = hf_revision(repo)
    for voice in VOICE_PATHS:
        name = voice.rsplit("/", 1)[-1]
        for extension in (".onnx", ".onnx.json"):
            manifest["files"].append(hf_download(repo, revision, voice + extension, MODELS / "voices" / (name + extension)))
        card = MODELS / "voices" / (name + ".MODEL_CARD.md")
        manifest["files"].append(hf_download(repo, revision, voice.rsplit("/", 1)[0] + "/MODEL_CARD", card))
    repo = "Systran/faster-whisper-tiny"
    revision = hf_revision(repo)
    for filename in ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt", "preprocessor_config.json"):
        listing = get_json("https://huggingface.co/api/models/" + repo + "/tree/" + revision)
        if any(item["path"] == filename for item in listing):
            manifest["files"].append(hf_download(repo, revision, filename, MODELS / "whisper-tiny" / filename))
    (MODELS / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("All models saved locally. Downloads are only needed for initial setup.", flush=True)


if __name__ == "__main__":
    main()
