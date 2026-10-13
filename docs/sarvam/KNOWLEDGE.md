# Sarvam knowledge for Voice Arena

Captured 2026-10-14 from official Sarvam documentation.
Scope: the API Reference section linked from the supplied introduction.
Coverage: 140 URLs indexed and attempted, 123 retrieved, 17 unavailable after retry. See [coverage ledger](api-reference-index.json).
This is a source-linked contract digest. Nested schemas hidden by the documentation UI may be missing from automated extraction; empty field lists do not prove fields are optional.

## Authentication and account operation

Send the subscription credential in api-subscription-key. Keep it on the Python server, supplied by hidden startup input or SARVAM_API_KEY. Do not place it in browser code, transcripts, source, or documentation. Some beta APIs require account access beyond possession of a key.
Sources: [authentication](https://docs.sarvam.ai/api-reference/authentication), [beta access](https://docs.sarvam.ai/api-reference/beta-apis).

Requests consume account credits. The published signup allocation is ₹100, shared across products; exhausted credits cause requests to fail. Account limits also apply independently to API families. Do not automatically purchase credits or retry failures indefinitely.
Sources: [credits](https://docs.sarvam.ai/api/getting-started/ratelimits), [pricing](https://docs.sarvam.ai/api/getting-started/pricing).

## Chat

Voice Arena uses POST https://api.sarvam.ai/v1/chat/completions with sarvam-105b-conversations. Supply system/user messages; request SSE streaming and consume choices[].delta.content. Ignore reasoning-only deltas. End at [DONE], close the response on cancellation, and keep spoken turns short.
The V1 route serves Sarvam 105B variants. V2 adds a broader model interface and model discovery; access may differ. Responses is a separate API.
Source: [chat V1](https://docs.sarvam.ai/api-reference/chat/chat-completions-v1), [V2](https://docs.sarvam.ai/api-reference/chat/chat-completions-v2).

## Speech recognition

The implemented endpoint is POST /speech-to-text, multipart file upload, with saaras:v3. Input is mono 16 kHz WAV; REST serves short clips, while batch handles longer recordings. language_code uses en-IN, hi-IN, or unknown. mode=codemix preserves mixed scripts; transcribe preserves the source language.
Saaras v4 is now documented, including keyterm biasing. Its mode wording differs across documentation, so this implementation explicitly retains the documented v3 contract.
Source: [REST STT](https://docs.sarvam.ai/api-reference/speech-to-text/transcribe), [streaming STT](https://docs.sarvam.ai/api-reference/speech-to-text/transcribe/realtime/ws).

## Speech synthesis

POST /text-to-speech accepts text, language_code, model, speaker, pace, sample rate and codec. Voice Arena chooses bulbul:v3, shubh for Atlas and priya for Nova, 24 kHz WAV. Decode audios[0] from base64 and validate it before playback. V3 supports up to 2500 characters per request and does not accept pitch/loudness/preprocessing controls used by older models.
Bulbul v4-flash is documented as newer, with persona identifiers rather than v3 short speaker names. Switching models must also update the speaker configuration.
Source: [REST TTS](https://docs.sarvam.ai/api-reference/text-to-speech/convert).

TTS also has REST streaming and a WebSocket endpoint. The socket uses initial configuration, text messages, flush signals, audio messages, and completion notifications. REST sentence audio is the current implementation; the browser room itself remains WebSocket-based.
Sources: [streaming REST](https://docs.sarvam.ai/api-reference/text-to-speech/convert-stream), [TTS socket](https://docs.sarvam.ai/api-reference/text-to-speech/stream).

## Other API families

The complete ledger includes voice cloning and voice management, pronunciation dictionaries, translation/transliteration/language detection, dubbing jobs, document translation, document digitization/extraction, and legacy routes.
Managed Voice Agents adds deployments, cohorts, campaigns, outbound calls, analytics, boards/tabs/widgets/filters/notifications, test suites/cases/runs, variable mappings, BYOK and webhook delivery operations.
These contracts are indexed for future lookup; they are not invoked by Voice Arena. Overview links:
[API introduction](https://docs.sarvam.ai/api-reference/introduction),
[managed conversations](https://docs.sarvam.ai/api-reference/conversations),
[boards](https://docs.sarvam.ai/api-reference/boards/overview),
[tests](https://docs.sarvam.ai/api-reference/tests/overview),
[BYOK](https://docs.sarvam.ai/api-reference/byok/overview).

## Voice Arena application rules

Keep mic capture active during playback. On interruption, stop the speaker and discard queued/stale audio. Wait for playback acknowledgement before the other agent speaks. Use separate channel buffers and distinct voices. Cancel HTTP generation/synthesis requests rather than allowing an obsolete turn to continue.
Sarvam is a modular STT → chat → TTS pipeline here; it does not reuse Gemini Live protocol messages.
For future changes, consult the exact source page and ledger status first, recheck provider contracts, and run contract tests. No successful live provider request was made in this session: outbound network access was denied.
