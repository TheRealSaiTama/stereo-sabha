import asyncio
import base64
import io
import os
import struct
import unittest
import wave
from unittest.mock import patch

from cloud_engine import SarvamEngine, microphone_wav, speech_audio, wav_bytes


class FakeResponse:
    def __init__(self, result=None, lines=None, status=200):
        self.status = status
        self.result = result or {}
        self.lines = lines or []
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        return self.result

    def __aiter__(self):
        async def stream():
            for line in self.lines:
                yield line
        return stream()


class FakeHTTP:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class SarvamTests(unittest.IsolatedAsyncioTestCase):
    def make_engine(self, response):
        with patch.dict(os.environ, {"VOICE_ARENA_FREE_CREDITS_CONFIRMED": "1"}):
            engine = SarvamEngine("test-only-key")
        engine.http = FakeHTTP(response)
        return engine

    def test_microphone_conversion_and_invalid_samples(self):
        data = microphone_wav(struct.pack("<fff", -1, 0, 1))
        with wave.open(io.BytesIO(data), "rb") as wav:
            self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, 16000))
            self.assertEqual(struct.unpack("<hhh", wav.readframes(3)), (-32767, 0, 32767))
        for invalid in (struct.pack("<f", float("nan")), struct.pack("<f", float("inf")), struct.pack("<f", 3), b"x"):
            with self.assertRaises(ValueError):
                microphone_wav(invalid)

    def test_credit_gate_and_secret_redaction(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                SarvamEngine("test-only-key")
        engine = self.make_engine(FakeResponse())
        self.assertNotIn("test-only-key", engine.safe_error("key test-only-key rejected"))

    async def test_chat_stream_and_correct_subscription_header(self):
        response = FakeResponse(lines=[
            b': heartbeat\n',
            b'data: {"choices":[{"delta":{"reasoning_content":"not spoken"}}]}\n',
            b'data: {"choices":[{"delta":{"content":"One "}}]}\n',
            b'data: {"choices":[{"delta":{"content":"point."}}]}\n',
            b'data: [DONE]\n',
        ])
        engine = self.make_engine(response)
        tokens = [token async for token in engine.generate([{"role": "user", "content": "Discuss /no_think"}])]
        self.assertEqual("".join(tokens), "One point.")
        url, request = engine.http.calls[0]
        self.assertEqual(url, "https://api.sarvam.ai/v1/chat/completions")
        self.assertEqual(request["headers"], {"api-subscription-key": "test-only-key"})
        self.assertEqual(request["json"]["model"], "sarvam-105b-conversations")
        self.assertNotIn("/no_think", request["json"]["messages"][0]["content"])

    async def test_distinct_tts_voices_and_hindi_request(self):
        audio = wav_bytes(b"\0\0" * 20, 24000)
        engine = self.make_engine(FakeResponse({"audios": [base64.b64encode(audio).decode()]}))
        self.assertEqual(await engine.speak("एक बात।", 1, "hi"), audio)
        body = engine.http.calls[0][1]["json"]
        self.assertEqual((body["speaker"], body["language_code"], body["model"]), ("priya", "hi-IN", "bulbul:v3"))
        self.assertNotIn("pitch", body)
        await engine.speak("One point.", 0, "en")
        self.assertEqual(engine.http.calls[1][1]["json"]["speaker"], "shubh")

    def test_empty_or_wrong_format_audio_is_rejected(self):
        for result in ({}, {"audios": []}, {"audios": ["AAAA"]}, {"audios": [base64.b64encode(wav_bytes(b"", 24000)).decode()]}):
            with self.assertRaises((ValueError, wave.Error, EOFError)):
                speech_audio(result)

    async def test_stt_uses_multipart_and_codemix(self):
        engine = self.make_engine(FakeResponse({"transcript": "यह good है"}))
        result = await engine.transcribe_async(struct.pack("<f", 0.1) * 320, "both")
        self.assertEqual(result, "यह good है")
        url, kwargs = engine.http.calls[0]
        self.assertTrue(url.endswith("/speech-to-text"))
        fields = {field[0]["name"]: field[2] for field in kwargs["data"]._fields}
        self.assertEqual(fields["model"], "saaras:v3")
        self.assertEqual(fields["language_code"], "unknown")
        self.assertEqual(fields["mode"], "codemix")
        await engine.transcribe_async(struct.pack("<f", 0.1) * 320, "hi")
        hindi_fields = {field[0]["name"]: field[2] for field in engine.http.calls[-1][1]["data"]._fields}
        self.assertEqual(hindi_fields["language_code"], "unknown")
        self.assertEqual(hindi_fields["mode"], "codemix")

    async def test_credit_failure_has_no_retry_or_key_leak(self):
        engine = self.make_engine(FakeResponse({"error": {"message": "test-only-key credits exhausted"}}, status=403))
        with self.assertRaises(RuntimeError) as caught:
            await engine.speak("One point.", 0, "en")
        self.assertEqual(len(engine.http.calls), 1)
        self.assertNotIn("test-only-key", str(caught.exception))
        self.assertIn("credits exhausted", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
