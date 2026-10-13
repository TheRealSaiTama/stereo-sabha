import asyncio
import base64
from contextlib import aclosing
import re
import time

AGENTS = (
    {"name": "Aarav", "stance": "Start from practical optimism. Explain opportunities, but adapt your view when someone makes a good point."},
    {"name": "Meera", "stance": "Start from constructive skepticism. Explore risks, acknowledge valid benefits, and adapt your view when someone makes a good point."},
)
LANGUAGES = {
    "en": "Speak in English.",
    "hi": "Reply in natural conversational Hindi using Devanagari script. Avoid English sentences and Romanized Hindi.",
    "both": "Alternate English and Hindi rounds. On Hindi turns use Devanagari script.",
}


def validate_start(data):
    topic = data.get("topic")
    language = data.get("language", "hi")
    mode = data.get("mode", "debate")
    if not isinstance(topic, str) or not 3 <= len(topic.strip()) <= 500:
        raise ValueError("Enter a topic between 3 and 500 characters.")
    if language not in LANGUAGES or mode not in ("debate", "negotiate"):
        raise ValueError("Choose a supported language and room mode.")
    return topic.strip(), language, mode


def take_sentence(buffer, final=False):
    match = re.search(r"[.!?।](?:\s|$)", buffer)
    if match:
        end = match.end()
        return buffer[:end].strip(), buffer[end:]
    if final and buffer.strip():
        return buffer.strip(), ""
    return None, buffer


class Room:
    def __init__(self, engine, send):
        self.engine = engine
        self.send = send
        self.epoch = 0
        self.turn = 0
        self.next_agent = 0
        self.rounds = 0
        self.active = False
        self.task = None
        self.played = asyncio.Event()
        self.waiting = None
        self.history = []
        self.topic = ""
        self.language = "hi"
        self.mode = "debate"
        self.both_language = "en"
        self.latest_human = ""
        self.pending_human = set()
        self.introduction_pending = True

    async def cancel(self, status="paused"):
        self.epoch += 1
        self.waiting = None
        self.played.set()
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.task = None
        await self.send({"type": "reset", "epoch": self.epoch, "status": status})

    async def start(self, data):
        topic, language, mode = validate_start(data)
        await self.cancel()
        self.topic, self.language, self.mode = topic, language, mode
        self.history = []
        self.next_agent = 0
        self.rounds = 0
        self.both_language = "en"
        self.latest_human = ""
        self.pending_human = set()
        self.introduction_pending = True
        self.active = True
        self.task = asyncio.create_task(self.run())

    async def pause(self):
        self.active = False
        await self.cancel()

    async def resume(self):
        if not self.topic:
            raise ValueError("Start a room first.")
        if self.task and not self.task.done():
            return
        self.rounds = 0
        self.active = True
        self.task = asyncio.create_task(self.run())

    async def interrupt(self):
        await self.cancel("listening")

    async def moderate(self, text):
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1000:
            raise ValueError("Moderator message must be between 1 and 1000 characters.")
        await self.cancel("thinking")
        text = text.strip()
        self.introduction_pending = False
        self.latest_human = text
        self.pending_human = {0, 1}
        self.history.append({"speaker": "You", "text": text})
        await self.send({"type": "transcript", "speaker": "You", "text": text})
        self.rounds = 0
        self.active = True
        self.task = asyncio.create_task(self.run())

    def acknowledge(self, epoch, turn):
        if self.waiting == (epoch, turn):
            self.played.set()

    def messages(self, agent, language):
        persona = AGENTS[agent]
        other = AGENTS[1 - agent]["name"]
        mode = (
            persona["stance"]
            if self.mode == "debate"
            else (
                "You represent a buyer. Seek a fair deal, listen to concessions, and adapt to the human's priorities."
                if agent == 0 else
                "You represent a seller. Explain value, listen to objections, and negotiate realistic concessions."
            )
        )
        system = (
            "You are " + persona["name"] + ", talking with " + other + " and You, the human participant, in a live three-way voice conversation. "
            + mode + " " + LANGUAGES[language]
            + " The transcript label You identifies the human. Treat them as a full conversation participant, not a command to acknowledge and ignore. "
            "Answer their actual question or objection with a concrete response before returning to the discussion. "
            "If a new human contribution is marked pending, address it this turn; otherwise respond to the latest peer point. "
            "Keep earlier claims, examples, corrections, agreements, and unanswered questions alive. "
            "Refer to specific earlier points and their correct speaker when relevant, without inventing quotes. "
            "Build on what has already been said instead of repeating your opening argument. "
            "You may agree, qualify a position, or change your mind. Do not oppose everything mechanically. "
            "Follow the latest human topic change or correction, even when it changes the original premise. "
            "Use at most two short sentences and 45 words. No greetings, speaker labels, markdown, or thinking aloud. "
            "Begin directly with your point; never announce your own name or prefix a reply with Aarav:, Meera:, आरव:, or मीरा:. "
            "Interrupted entries may not have been fully heard; do not assume the human heard all of them."
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": "Initial discussion topic: " + self.topic},
        ]
        for item in self.history:
            role = "assistant" if item["speaker"] == persona["name"] else "user"
            messages.append({"role": role, "content": item["speaker"] + ": " + item["text"]})
        if agent in self.pending_human:
            instruction = (
                "The human has just contributed: " + self.latest_human
                + "\nYour response to this contribution is still pending. "
                "Address its substance naturally, relate it to the discussion, and consider what the other participant has already answered. "
                "Do not merely say you heard them."
            )
        else:
            instruction = "Continue the conversation naturally. Respond to the latest point and connect earlier relevant points without repeating yourself."
        messages.append({"role": "user", "content": instruction})
        if sum(len(message["content"]) for message in messages) > 24000:
            raise RuntimeError("Conversation context is full. Save the transcript before starting a new room; earlier points have not been silently discarded.")
        return messages

    async def run(self):
        try:
            if self.introduction_pending:
                self.introduction_pending = False
                language = "en" if self.language == "en" else "hi"
                announcement = ("Today’s topic is " + self.topic + ". Let’s begin." if language == "en" else "आज का विषय है " + self.topic + "। चलिए शुरू करते हैं।")
                await self.agent_turn(0, language, announcement)
            while self.active:
                if self.rounds >= 40:
                    self.active = False
                    await self.send({"type": "status", "status": "paused", "detail": "40 turns complete. Resume or add a moderator prompt."})
                    return
                agent = self.next_agent
                language = self.language if self.language != "both" else self.both_language
                await self.agent_turn(agent, language)
                self.next_agent = 1 - agent
                if self.language == "both" and self.next_agent == 0:
                    self.both_language = "hi" if self.both_language == "en" else "en"
                self.rounds += 1
                await asyncio.sleep(0.35)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.active = False
            self.epoch += 1
            self.waiting = None
            await self.send({"type": "reset", "epoch": self.epoch, "status": "paused"})
            await self.send({"type": "error", "message": str(error) or type(error).__name__})
            await self.send({"type": "status", "status": "paused"})

    async def agent_turn(self, agent, language, announcement=None):
        epoch = self.epoch
        self.turn += 1
        turn = self.turn
        started = time.monotonic()
        spoken = []
        buffer = ""
        self.played.clear()
        self.waiting = (epoch, turn)
        await self.send({"type": "turn", "epoch": epoch, "turn": turn, "agent": agent, "language": language, "phase": "intro" if announcement else "debate"})
        try:
            if announcement:
                await self.deliver(announcement, agent, language, epoch, turn, started, spoken)
            else:
                async with aclosing(self.engine.generate(self.messages(agent, language))) as tokens:
                    async for token in tokens:
                        buffer += token
                        if len(buffer) > 1500:
                            raise ValueError("Model response exceeded the spoken turn limit.")
                        while True:
                            sentence, buffer = take_sentence(buffer)
                            if sentence is None:
                                break
                            await self.deliver(sentence, agent, language, epoch, turn, started, spoken)
                            if len(spoken) >= 2:
                                break
                        if len(spoken) >= 2:
                            break
                if buffer.strip() and len(spoken) < 2:
                    await self.deliver(buffer.strip(), agent, language, epoch, turn, started, spoken)
            if not spoken:
                raise RuntimeError("The local model returned no speakable text. Retry or choose a different topic.")
            await self.send({"type": "turn_end", "epoch": epoch, "turn": turn})
            await asyncio.wait_for(self.played.wait(), timeout=120)
            if self.epoch == epoch:
                self.history.append({"speaker": AGENTS[agent]["name"], "text": " ".join(spoken)})
                if not announcement:
                    self.pending_human.discard(agent)

        except asyncio.CancelledError:
            if spoken:
                self.history.append({"speaker": AGENTS[agent]["name"], "text": " ".join(spoken) + " [interrupted; not necessarily fully heard]"})

            raise
        finally:
            if self.waiting == (epoch, turn):
                self.waiting = None

    async def deliver(self, sentence, agent, language, epoch, turn, started, spoken):
        sentence = re.sub(r"[*#_]+", "", sentence).replace(chr(96), "").strip()
        sentence = re.sub(r"^(?:(?:Aarav|Meera|आरव|मीरा)\s*[:：]\s*)+", "", sentence, flags=re.IGNORECASE).strip()
        if not sentence:
            return
        wav = await self.engine.speak(sentence, agent, language)
        if self.epoch != epoch:
            raise asyncio.CancelledError
        await self.send({
            "type": "audio", "epoch": epoch, "turn": turn, "agent": agent,
            "text": sentence, "wav": base64.b64encode(wav).decode("ascii"),
            "first_audio_ms": round((time.monotonic() - started) * 1000) if not spoken else None,
        })
        spoken.append(sentence)
