import asyncio
import io
import json
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web


ROOT = Path(__file__).resolve().parent
MODELS = ROOT / "models"
VOICES = {
    (0, "en"): "en_US-lessac-medium",
    (1, "en"): "en_US-amy-medium",
    (0, "hi"): "hi_IN-pratham-medium",
    (1, "hi"): "hi_IN-priyamvada-medium",
}
MAX_AUDIO = 16000 * 4 * 21
LLM_URL = "http://127.0.0.1:8081"


class Engine:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.voices = {}
        self.whisper = None
        self.http = None

    async def cpu(self, function, *args):
        return await asyncio.get_running_loop().run_in_executor(self.pool, function, *args)

    def load(self):
        import onnxruntime as ort
        from faster_whisper import WhisperModel
        from piper import PiperVoice
        from piper.config import PiperConfig

        for key, name in VOICES.items():
            path = MODELS / "voices" / (name + ".onnx")
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            options.add_session_config_entry("session.intra_op.allow_spinning", "0")
            with open(str(path) + ".json", encoding="utf-8") as config:
                voice_config = PiperConfig.from_dict(json.load(config))
            self.voices[key] = PiperVoice(
                session=ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"]),
                config=voice_config,
            )
        self.whisper = WhisperModel(
            str(MODELS / "whisper-tiny"), device="cpu", compute_type="int8",
            cpu_threads=2, num_workers=1, local_files_only=True,
        )

    async def generate(self, messages):
        payload = {
            "messages": messages, "stream": True, "max_tokens": 180,
            "temperature": 0.7, "repeat_penalty": 1.15,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        async with self.http.post(LLM_URL + "/v1/chat/completions", json=payload) as response:
            if response.status != 200:
                raise RuntimeError("Local model failed: " + (await response.text())[:300])
            async for line in response.content:
                if not line.startswith(b"data: "):
                    continue
                raw = line[6:].strip()
                if raw == b"[DONE]":
                    return
                event = json.loads(raw)
                if "error" in event:
                    raise RuntimeError(str(event["error"]))
                choices = event.get("choices", [])
                if choices:
                    text = choices[0].get("delta", {}).get("content")
                    if text:
                        yield text

    def synthesize(self, text, agent, language):
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            self.voices[(agent, language)].synthesize_wav(text, wav)
        return output.getvalue()

    async def speak(self, text, agent, language):
        return await self.cpu(self.synthesize, text, agent, language)

    async def transcribe_async(self, pcm, language):
        return await self.cpu(self.transcribe, pcm, language)

    def transcribe(self, pcm, language):
        import numpy as np
        audio = np.frombuffer(pcm, dtype="<f4").copy()
        if not np.isfinite(audio).all() or np.max(np.abs(audio), initial=0) > 1.01:
            raise ValueError("Invalid microphone samples.")
        segments, _ = self.whisper.transcribe(
            audio, language=None if language == "both" else language,
            beam_size=1, condition_on_previous_text=False,
            vad_filter=True, vad_parameters={"min_silence_duration_ms": 400},
        )
        return " ".join(s.text.strip() for s in segments if s.no_speech_prob < 0.8).strip()
