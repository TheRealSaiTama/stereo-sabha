import asyncio
import os

from aiohttp import ClientSession, ClientTimeout

from cloud_engine import SarvamEngine
from server import load_local_env


async def main():
    load_local_env()
    engine = SarvamEngine(os.environ.get("SARVAM_API_KEY", ""))
    async with ClientSession(timeout=ClientTimeout(total=30)) as session:
        engine.http = session
        try:
            text = "".join([part async for part in engine.generate([
                {"role": "system", "content": "Reply in one short English sentence of at most 12 words."},
                {"role": "user", "content": "State one benefit of launching a startup product early."},
            ])])
            if not text:
                raise RuntimeError("Empty chat response")
            print("PASS: Sarvam streamed chat", flush=True)
            english = await engine.speak("Welcome to Stereo Sabha.", 0, "en")
            print("PASS: Aarav English WAV (" + str(len(english)) + " bytes)", flush=True)
            hindi = await engine.speak("नमस्ते, अपनी बात कहिए।", 1, "hi")
            print("PASS: Meera Hindi WAV (" + str(len(hindi)) + " bytes)", flush=True)
            import io
            import struct
            import wave
            with wave.open(io.BytesIO(english), "rb") as wav:
                samples = struct.unpack("<" + "h" * wav.getnframes(), wav.readframes(wav.getnframes()))
            selected = (samples[int(index * 1.5)] for index in range(int(len(samples) * 2 / 3)))
            pcm = b"".join(struct.pack("<f", value / 32768) for value in selected)
            transcript = await engine.transcribe_async(pcm, "en")
            if not transcript:
                raise RuntimeError("Empty STT response")
            print("PASS: moderator transcription (" + str(len(transcript)) + " characters)", flush=True)
        except Exception as error:
            print("FAIL: " + engine.safe_error(error), flush=True)
            raise SystemExit(1) from None


if __name__ == "__main__":
    asyncio.run(main())
