import asyncio
import unittest

from room import Room, take_sentence, validate_start


class FakeEngine:
    def __init__(self):
        self.requests = []
        self.speech = []
        self.block = None
        self.entered = asyncio.Event()

    async def generate(self, messages):
        self.requests.append(messages)
        if self.block:
            self.entered.set()
            await self.block.wait()
        for token in ("A concrete ", "benefit. ", "A second point. ", "Never speak a third point."):
            yield token

    async def speak(self, sentence, agent, language):
        if not sentence.startswith(("आज का विषय है", "Today’s topic is")):
            self.speech.append((sentence, agent, language))
        return b"RIFF-test-audio"


class RoomTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.events = []
        self.intro_turns = set()
        self.engine = FakeEngine()

        async def send(event):
            if event.get("phase") == "intro":
                self.intro_turns.add(event["turn"])
            if event.get("turn") in self.intro_turns:
                if event["type"] == "turn_end":
                    self.room.acknowledge(event["epoch"], event["turn"])
                return
            self.events.append(event)

        self.room = Room(self.engine, send)

    async def asyncTearDown(self):
        await self.room.pause()

    async def until(self, condition):
        for _ in range(200):
            if condition():
                return
            await asyncio.sleep(0.005)
        self.fail("Timed out waiting for room event")

    async def test_playback_acknowledgement_controls_turns(self):
        await self.room.start({"topic": "Launch early?", "language": "en"})
        await self.until(lambda: any(e["type"] == "turn_end" for e in self.events))
        self.assertEqual(len(self.engine.speech), 2)
        self.assertEqual(self.engine.speech[0][1], 0)
        self.assertEqual(len(self.engine.requests), 1)
        self.room.acknowledge(self.room.epoch - 1, self.room.turn)
        await asyncio.sleep(0.03)
        self.assertEqual(len(self.engine.requests), 1)
        self.room.acknowledge(self.room.epoch, self.room.turn)
        await self.until(lambda: len(self.engine.requests) == 2)
        self.assertIn("Aarav: A concrete benefit.", "\n".join(message["content"] for message in self.engine.requests[1]))
        self.assertIn("constructive skepticism", self.engine.requests[1][0]["content"])

    async def test_interrupt_cancels_pending_generation_and_stale_ack(self):
        self.engine.block = asyncio.Event()
        await self.room.start({"topic": "Launch early?"})
        await self.engine.entered.wait()
        old_epoch, old_turn = self.room.epoch, self.room.turn
        await self.room.interrupt()
        self.engine.block.set()
        self.room.acknowledge(old_epoch, old_turn)
        await asyncio.sleep(0.02)
        self.assertFalse(any(e["type"] == "audio" for e in self.events))
        self.assertEqual(self.events[-1]["status"], "listening")
        self.assertGreater(self.room.epoch, old_epoch)

    async def test_moderator_prompt_reaches_both_agents(self):
        await self.room.start({"topic": "Launch early?", "language": "hi", "mode": "negotiate"})
        await self.until(lambda: any(e["type"] == "turn_end" for e in self.events))
        await self.room.moderate("Change the topic to open source business models.")
        await self.until(lambda: len(self.engine.requests) == 2)
        content = self.engine.requests[-1]
        self.assertIn("open source business models", "\n".join(message["content"] for message in content))
        self.assertIn("Devanagari", content[0]["content"])
        self.assertIn("buyer", content[0]["content"])
        await self.until(lambda: any(e["type"] == "turn_end" and e["epoch"] == self.room.epoch for e in self.events))
        self.room.acknowledge(self.room.epoch, self.room.turn)
        await self.until(lambda: len(self.engine.requests) == 3)
        self.assertIn("open source business models", "\n".join(message["content"] for message in self.engine.requests[-1]))
        self.assertIn("seller", self.engine.requests[-1][0]["content"])

    async def test_bilingual_rounds_give_both_agents_both_languages(self):
        await self.room.start({"topic": "Launch early?", "language": "both"})
        seen = []
        for _ in range(4):
            await self.until(lambda: any(e["type"] == "turn_end" and e["turn"] == self.room.turn for e in self.events))
            turn = next(e for e in reversed(self.events) if e["type"] == "turn")
            seen.append((turn["agent"], turn["language"]))
            self.room.acknowledge(turn["epoch"], turn["turn"])
            if len(seen) < 4:
                await self.until(lambda: self.room.turn > turn["turn"])
        self.assertEqual(seen, [(0, "en"), (1, "en"), (0, "hi"), (1, "hi")])

    async def test_pause_and_restart_reset_context(self):
        await self.room.start({"topic": "Launch early?"})
        await self.until(lambda: any(e["type"] == "audio" for e in self.events))
        await self.room.pause()
        count = len(self.engine.requests)
        await asyncio.sleep(0.02)
        self.assertEqual(len(self.engine.requests), count)
        await self.room.start({"topic": "Public transport"})
        self.assertEqual(self.room.history, [])
        self.assertEqual(self.room.next_agent, 0)
        await self.until(lambda: len(self.engine.requests) > count)
        self.assertNotIn("Launch early", self.engine.requests[-1][1]["content"])

    async def test_failed_synthesis_pauses_without_advancing(self):
        async def fail(*args):
            raise RuntimeError("Voice unavailable")

        self.engine.speak = fail
        await self.room.start({"topic": "Launch early?"})
        await self.until(lambda: any(e["type"] == "error" for e in self.events))
        self.assertFalse(self.room.active)
        self.assertEqual(self.room.next_agent, 0)
        self.assertFalse(any(e["type"] == "turn_end" for e in self.events))


    async def test_moderator_context_survives_history_window_and_resets_on_restart(self):
        await self.room.start({"topic": "Launch early?"})
        await self.room.moderate("Change the topic to public transport.")
        await self.room.pause()
        self.room.history = [{"speaker": "Aarav", "text": "Later point"} for _ in range(20)]
        self.assertIn("public transport", "\n".join(message["content"] for message in self.room.messages(1, "en")))
        await self.room.start({"topic": "Remote work"})
        self.assertEqual(self.room.latest_human, "")
        self.assertNotIn("public transport", "\n".join(message["content"] for message in self.room.messages(0, "en")))

    async def test_interruption_during_synthesis_drops_pending_audio(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def slow_speech(*args):
            entered.set()
            await release.wait()
            return b"stale-audio"

        self.engine.speak = slow_speech
        await self.room.start({"topic": "Launch early?"})
        await entered.wait()
        await self.room.interrupt()
        release.set()
        await asyncio.sleep(0.02)
        self.assertFalse(any(e["type"] == "audio" for e in self.events))

    async def test_generation_stream_is_closed_after_two_sentences(self):
        closed = asyncio.Event()

        async def stream(messages):
            try:
                yield "First point. Second point. Third point."
            finally:
                closed.set()

        self.engine.generate = stream
        await self.room.start({"topic": "Launch early?"})
        await self.until(lambda: any(e["type"] == "turn_end" for e in self.events))
        self.assertTrue(closed.is_set())
        self.assertEqual(len(self.engine.speech), 2)

    async def test_opening_announces_topic_and_waits_before_first_debate(self):
        events = []

        async def send(event):
            events.append(event)

        self.room = Room(self.engine, send)
        await self.room.start({"topic": "खुला स्रोत", "language": "hi"})
        await self.until(lambda: any(event["type"] == "turn_end" for event in events))
        opening = next(event for event in events if event["type"] == "audio")
        self.assertEqual(opening["text"], "आज का विषय है खुला स्रोत। चलिए शुरू करते हैं।")
        self.assertEqual(opening["agent"], 0)
        self.assertEqual(self.engine.requests, [])
        self.room.acknowledge(opening["epoch"], opening["turn"])
        await self.until(lambda: len(self.engine.requests) == 1)
        self.assertEqual(self.room.next_agent, 0)

    def test_full_history_preserves_early_points_and_long_human_input(self):
        early = "पहले यह कहा था कि ग्राहक की जरूरत समझना जरूरी है। " * 8
        human = "मेरा सवाल है कि सुरक्षा और लागत का संतुलन कैसे बनेगा? " * 8
        self.room.topic = "उत्पाद"
        self.room.history = [
            {"speaker": "Aarav", "text": early},
            {"speaker": "You", "text": human},
        ] + [{"speaker": "Meera", "text": "Later point " + str(index)} for index in range(12)]
        messages = self.room.messages(0, "hi")
        full = "\n".join(message["content"] for message in messages)
        self.assertIn(early, full)
        self.assertIn(human, full)
        self.assertEqual(messages[2]["role"], "assistant")
        self.assertEqual(messages[3]["role"], "user")

    async def test_human_input_is_pending_for_both_until_each_reply_finishes(self):
        await self.room.start({"topic": "उत्पाद"})
        await self.until(lambda: any(event["type"] == "turn_end" for event in self.events))
        await self.room.moderate("मेरे पास केवल दो लोग हैं, इस सीमा को ध्यान में रखो।")
        await self.until(lambda: len(self.engine.requests) == 2)
        self.assertEqual(self.room.pending_human, {0, 1})
        self.assertIn("response to this contribution is still pending", self.engine.requests[-1][-1]["content"])
        await self.until(lambda: any(event["type"] == "turn_end" and event["epoch"] == self.room.epoch for event in self.events))
        self.room.acknowledge(self.room.epoch, self.room.turn)
        await self.until(lambda: len(self.engine.requests) == 3)
        self.assertEqual(self.room.pending_human, {1})
        self.assertIn("केवल दो लोग", self.engine.requests[-1][-1]["content"])
        self.assertIn("Aarav: A concrete benefit.", "\n".join(message["content"] for message in self.engine.requests[-1]))

    async def test_more_than_three_human_points_remain_in_context(self):
        await self.room.start({"topic": "उत्पाद"})
        for index in range(5):
            await self.room.moderate("Human point " + str(index))
        await self.room.pause()
        full = "\n".join(message["content"] for message in self.room.messages(1, "hi"))
        for index in range(5):
            self.assertIn("Human point " + str(index), full)

    def test_context_limit_is_explicit_and_does_not_delete_history(self):
        self.room.history = [{"speaker": "You", "text": "x" * 1000} for _ in range(30)]
        with self.assertRaisesRegex(RuntimeError, "not been silently discarded"):
            self.room.messages(0, "hi")
        self.assertEqual(len(self.room.history), 30)

    async def test_speaker_prefixes_are_removed_before_synthesis(self):
        cases = (
            ("**Aarav:** A concrete point.", "A concrete point."),
            ("meera: आरव: सही बात है।", "सही बात है।"),
            ("मीरा： यह जरूरी है।", "यह जरूरी है।"),
            ("Meera, your earlier point matters.", "Meera, your earlier point matters."),
            ("You said Aarav: earlier.", "You said Aarav: earlier."),
        )
        for original, expected in cases:
            spoken = []
            await self.room.deliver(original, 0, "hi", self.room.epoch, 1, 0, spoken)
            self.assertEqual(self.engine.speech[-1][0], expected)
            self.assertEqual(self.events[-1]["text"], expected)
            self.assertEqual(spoken, [expected])
        count = len(self.engine.speech)
        await self.room.deliver("Aarav:", 0, "hi", self.room.epoch, 1, 0, [])
        self.assertEqual(len(self.engine.speech), count)

    def test_sentence_boundaries_and_input_validation(self):
        self.assertEqual(take_sentence("One point. Another"), ("One point.", "Another"))
        self.assertEqual(take_sentence("एक बात। दूसरी"), ("एक बात।", "दूसरी"))
        self.assertEqual(take_sentence("unfinished"), (None, "unfinished"))
        for bad in ({}, {"topic": "x"}, {"topic": "valid", "language": "fr"}, {"topic": "valid", "mode": "other"}):
            with self.assertRaises(ValueError):
                validate_start(bad)


if __name__ == "__main__":
    unittest.main()
