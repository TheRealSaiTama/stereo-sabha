import asyncio
import base64
import io
import json
import math
import os
import struct
import wave

API_URL = "https://api.sarvam.ai"
CHAT_MODEL = "sarvam-105b-conversations"
STT_MODEL = "saaras:v3"
TTS_MODEL = "bulbul:v3"
VOICES = ("shubh", "priya")


def wav_bytes(pcm, rate):
    if len(pcm) % 2:
        raise ValueError("Audio must be 16-bit PCM.")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return output.getvalue()


def microphone_wav(samples):
    if len(samples) % 4:
        raise ValueError("Microphone input must be float32 PCM.")
    pcm = bytearray()
    for (value,) in struct.iter_unpack("<f", samples):
        if not math.isfinite(value) or abs(value) > 1.01:
            raise ValueError("Invalid microphone samples.")
        pcm.extend(struct.pack("<h", round(max(-1, min(1, value)) * 32767)))
    return wav_bytes(pcm, 16000)


def speech_audio(result):
    audios = result.get("audios", [])
    if len(audios) != 1 or not isinstance(audios[0], str):
        raise ValueError("Sarvam returned an unexpected audio response.")
    audio = base64.b64decode(audios[0], validate=True)
    with wave.open(io.BytesIO(audio), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != 24000 or wav.getnframes() == 0:
            raise ValueError("Sarvam returned unexpected WAV format or empty speech.")
    return audio


class SarvamEngine:
    def __init__(self, key):
        if not key:
            raise ValueError("A Sarvam API key is required for cloud mode.")
        if os.environ.get("VOICE_ARENA_FREE_CREDITS_CONFIRMED") != "1":
            raise ValueError("Confirm remaining free Sarvam credits before making API calls.")
        self.key = key
        self.http = None
        self.access_verified = False

    @property
    def headers(self):
        return {"api-subscription-key": self.key}

    def safe_error(self, error):
        return str(error).replace(self.key, "[redacted]")[:300]

    async def check_response(self, response, operation):
        if response.status == 200:
            self.access_verified = True
            return
        detail = ""
        try:
            result = await response.json()
            error = result.get("error", result)
            detail = error.get("message", "") if isinstance(error, dict) else str(error)
        except Exception:
            pass
        raise RuntimeError(
            operation + " returned HTTP " + str(response.status) + ". "
            + self.safe_error(detail) + " Room paused; check free credits, key access, and rate limits."
        )

    async def generate(self, messages):
        payload = {
            "model": CHAT_MODEL, "messages": [
                {"role": item["role"], "content": item["content"].replace(" /no_think", "")}
                for item in messages
            ],
            "stream": True, "temperature": 0.6, "max_tokens": 250, "reasoning_effort": None,
        }
        try:
            async with self.http.post(API_URL + "/v1/chat/completions", headers=self.headers, json=payload) as response:
                await self.check_response(response, "Sarvam chat")
                async for line in response.content:
                    if not line.startswith(b"data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw:
                        continue
                    if raw == b"[DONE]":
                        return
                    event = json.loads(raw)
                    if "error" in event:
                        raise RuntimeError(self.safe_error(event["error"]))
                    choices = event.get("choices", [])
                    if choices:
                        text = choices[0].get("delta", {}).get("content")
                        if text:
                            yield text
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise RuntimeError("Sarvam chat failed: " + self.safe_error(error)) from None

    async def speak(self, text, agent, language):
        if not 1 <= len(text) <= 2500 or agent not in (0, 1) or language not in ("en", "hi"):
            raise ValueError("Invalid speech text, agent, or language.")
        payload = {
            "text": text, "language_code": "hi-IN" if language == "hi" else "en-IN",
            "model": TTS_MODEL, "speaker": VOICES[agent], "pace": 1.0,
            "speech_sample_rate": 24000, "output_audio_codec": "wav",
        }
        try:
            async with self.http.post(API_URL + "/text-to-speech", headers=self.headers, json=payload) as response:
                await self.check_response(response, "Sarvam TTS")
                return speech_audio(await response.json())
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise RuntimeError("Sarvam speech failed: " + self.safe_error(error)) from None

    async def transcribe_async(self, pcm, language):
        from aiohttp import FormData
        form = FormData()
        form.add_field("file", microphone_wav(pcm), filename="moderator.wav", content_type="audio/wav")
        form.add_field("model", STT_MODEL)
        form.add_field("language_code", "unknown")
        form.add_field("mode", "codemix")
        try:
            async with self.http.post(API_URL + "/speech-to-text", headers=self.headers, data=form) as response:
                await self.check_response(response, "Sarvam STT")
                result = await response.json()
                transcript = result.get("transcript")
                if not isinstance(transcript, str):
                    raise ValueError("Sarvam returned no valid transcript.")
                return transcript.strip()[:1000]
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise RuntimeError("Sarvam transcription failed: " + self.safe_error(error)) from None
