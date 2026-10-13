import asyncio
import argparse
import getpass
import os
import json
from pathlib import Path
from urllib.parse import urlparse

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web

from cloud_engine import SarvamEngine
from room import Room

ROOT = Path(__file__).resolve().parent
MAX_AUDIO = 16000 * 4 * 21
LLM_URL = "http://127.0.0.1:8081"

def allowed_request(request):
    host = request.host.split(":")[0]
    if host not in ("127.0.0.1", "localhost"):
        return False
    origin = request.headers.get("Origin")
    if origin:
        parsed = urlparse(origin)
        return parsed.scheme == "http" and parsed.netloc == request.host
    return True


async def websocket(request):
    if not allowed_request(request):
        raise web.HTTPForbidden(text="Local same-origin clients only.")
    if request.app["busy"]:
        raise web.HTTPConflict(text="One local room is already open. Close its tab first.")
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=8000)
    request.app["busy"] = True
    try:
        await ws.prepare(request)
    except BaseException:
        request.app["busy"] = False
        raise
    engine = request.app["engine"]
    room = Room(engine, ws.send_json)
    audio = bytearray()
    recording = False
    transcription = None

    async def recognize(pcm, epoch):
        try:
            await ws.send_json({"type": "status", "status": "transcribing"})
            text = await engine.transcribe_async(pcm, room.language)
            if room.epoch != epoch or ws.closed:
                return
            if text:
                await room.moderate(text)
            else:
                await ws.send_json({"type": "notice", "message": "No clear speech detected. Try again or type your prompt."})
                await ws.send_json({"type": "status", "status": "paused"})
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if not ws.closed and room.epoch == epoch:
                room.active = False
                await ws.send_json({"type": "error", "message": "Transcription failed: " + str(error)})
                await ws.send_json({"type": "status", "status": "paused"})

    try:
        await ws.send_json({"type": "ready", "epoch": room.epoch})
        async for message in ws:
            try:
                if message.type == WSMsgType.BINARY:
                    if not recording:
                        continue
                    if len(message.data) % 4 or len(audio) + len(message.data) > MAX_AUDIO:
                        recording = False
                        audio.clear()
                        raise ValueError("Microphone input must be float32 PCM and under 21 seconds.")
                    audio.extend(message.data)
                elif message.type == WSMsgType.TEXT:
                    data = json.loads(message.data)
                    if not isinstance(data, dict):
                        raise ValueError("Expected a JSON object.")
                    kind = data.get("type")
                    if kind in ("start", "pause", "resume", "moderator", "interrupt"):
                        if transcription and not transcription.done():
                            transcription.cancel()
                        if kind != "interrupt":
                            recording = False
                            audio.clear()
                    if kind == "start":
                        await room.start(data)
                    elif kind == "pause":
                        await room.pause()
                    elif kind == "resume":
                        await room.resume()
                    elif kind == "moderator":
                        await room.moderate(data.get("text"))
                    elif kind == "interrupt":
                        if not room.topic:
                            raise ValueError("Start the room before using your microphone.")
                        await room.interrupt()
                        audio.clear()
                        recording = True
                    elif kind == "speech_end":
                        if recording:
                            recording = False
                            if len(audio) >= 16000 * 4 * 0.2:
                                transcription = asyncio.create_task(recognize(bytes(audio), room.epoch))
                            else:
                                await ws.send_json({"type": "status", "status": "paused"})
                            audio.clear()
                    elif kind == "played":
                        room.acknowledge(data.get("epoch"), data.get("turn"))
                    else:
                        raise ValueError("Unsupported room message.")
                elif message.type == WSMsgType.ERROR:
                    break
            except (ValueError, TypeError) as error:
                await ws.send_json({"type": "error", "message": str(error)})
    finally:
        room.active = False
        if transcription:
            transcription.cancel()
            try:
                await transcription
            except asyncio.CancelledError:
                pass
        if room.task:
            room.task.cancel()
            try:
                await room.task
            except asyncio.CancelledError:
                pass
        request.app["busy"] = False
    return ws


async def health(request):
    if not allowed_request(request):
        raise web.HTTPForbidden()
    if not request.app["local_mode"]:
        return web.json_response({"ready": True, "local": False, "access_verified": request.app["engine"].access_verified, "model": "Sarvam 105B Conversations", "speech": "Saaras v3 + Bulbul v3"})
    try:
        async with request.app["engine"].http.get(LLM_URL + "/health", timeout=ClientTimeout(total=3)) as response:
            available = response.status == 200
    except Exception:
        available = False
    return web.json_response({"ready": available, "model": "Qwen3 0.6B", "speech": "Piper + Whisper tiny", "local": True})


async def static(request):
    if not allowed_request(request):
        raise web.HTTPForbidden()
    name = request.match_info.get("name", "index.html")
    if name not in ("index.html", "style.css", "app.js", "audio.js", "mic-worklet.js", "voice-arena-mark.png", "listening-ear.png"):
        raise web.HTTPNotFound()
    return web.FileResponse(ROOT / "web" / name, headers={"Cache-Control": "no-store"})


async def lifecycle(app):
    if app["local_mode"]:
        from local_engine import Engine
        engine = Engine()
        print("Loading optional local models...", flush=True)
        await engine.cpu(engine.load)
    else:
        engine = SarvamEngine(app["api_key"])
        print("Cloud voice mode: no local AI models loaded. API access remains unverified until your first turn.", flush=True)
    app["engine"] = engine
    engine.http = ClientSession(timeout=ClientTimeout(total=120))
    try:
        yield
    finally:
        await engine.http.close()
        if hasattr(engine, "pool"):
            engine.pool.shutdown(wait=False, cancel_futures=True)


def load_local_env(path=ROOT / ".env"):
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        name, separator, value = line.partition("=")
        name = name.strip()
        if separator and name in ("SARVAM_API_KEY", "VOICE_ARENA_FREE_CREDITS_CONFIRMED"):
            if not os.environ.get(name):
                os.environ[name] = value.strip().strip("\"\'")


def main():
    load_local_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", action="store_true", help="Optional CPU-heavy local inference")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    key = ""
    if not args.local:
        key = os.environ.get("SARVAM_API_KEY") or getpass.getpass("Sarvam API key (hidden, not saved): ").strip()
        if os.environ.get("VOICE_ARENA_FREE_CREDITS_CONFIRMED") != "1":
            confirmed = input("Verify you have remaining free Sarvam credits and will not use paid credits. Type FREE to continue: ").strip()
            if confirmed != "FREE":
                raise SystemExit("Cloud startup cancelled. No API requests made.")
            os.environ["VOICE_ARENA_FREE_CREDITS_CONFIRMED"] = "1"
    app = web.Application()
    app["local_mode"] = args.local
    app["api_key"] = key
    app["busy"] = False
    app.cleanup_ctx.append(lifecycle)
    app.router.add_get("/", static)
    app.router.add_get("/health", health)
    app.router.add_get("/ws", websocket)
    app.router.add_get("/{name}", static)
    web.run_app(app, host="127.0.0.1", port=args.port, print=lambda line: print(line, flush=True))


if __name__ == "__main__":
    main()
