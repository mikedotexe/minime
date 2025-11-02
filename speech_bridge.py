#!/usr/bin/env python3
"""
Speech Bridge - Connects MikesSpatialMind to speech-io Rust service.

Handles:
- WebSocket connection to speech-io (:7242)
- Routes STT events to consciousness
- Sends TTS requests for responses
- Manages barge-in interrupts
- Chunked TTS streaming for lower latency
"""

import asyncio
import websockets
import json
import logging
import re
from typing import Optional, Callable, Dict, AsyncIterator
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_sentences(text: str) -> list[str]:
    """
    Extract complete sentences from text buffer.

    Detects sentence boundaries using punctuation (.!?…) followed by whitespace or end.
    This enables chunked TTS streaming for lower perceived latency.

    Args:
        text: Text buffer to extract sentences from

    Returns:
        List of complete sentences (including terminating punctuation)

    Example:
        >>> get_sentences("Hello world. How are you? I'm fine.")
        ['Hello world.', 'How are you?', "I'm fine."]
        >>> get_sentences("Hello world. Incomplete")
        ['Hello world.']
    """
    # Match sentences ending with .!?… followed by space or end of string
    sentences = re.findall(r'(.+?[.!?…]+)(?:\s|$)', text, re.DOTALL)
    return [s.strip() for s in sentences if s.strip()]


class SpeechBridge:
    """
    Bridge between speech-io Rust service and MikesSpatialMind.

    Usage:
        bridge = SpeechBridge(on_transcript=handle_text)
        await bridge.connect()
        await bridge.speak("Hello, I'm alive!")
    """

    def __init__(
        self,
        speech_ws_url: str = "ws://127.0.0.1:7242",
        on_transcript: Optional[Callable[[str], None]] = None,
        on_barge_in: Optional[Callable[[], None]] = None
    ):
        """
        Initialize speech bridge.

        Args:
            speech_ws_url: WebSocket URL for speech-io service
            on_transcript: Callback for final transcripts (user speech)
            on_barge_in: Callback when user interrupts TTS
        """
        self.speech_ws_url = speech_ws_url
        self.on_transcript = on_transcript
        self.on_barge_in = on_barge_in

        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.connected = False
        self.tts_playing = False
        self.abort_tts = False  # Signal to abort streaming TTS

        # Statistics
        self.stats = {
            'stt_events': 0,
            'tts_requests': 0,
            'barge_ins': 0,
            'errors': 0,
            'chunked_sentences': 0  # Track chunked TTS usage
        }

    async def connect(self):
        """Connect to speech-io service."""
        try:
            self.ws = await websockets.connect(self.speech_ws_url)
            self.connected = True
            logger.info(f"Connected to speech-io at {self.speech_ws_url}")

            # Start listening for events
            asyncio.create_task(self._event_loop())

        except Exception as e:
            logger.error(f"Failed to connect to speech-io: {e}")
            self.connected = False
            raise

    async def _event_loop(self):
        """Listen for events from speech-io."""
        try:
            async for message in self.ws:
                try:
                    event = json.loads(message)
                    await self._handle_event(event)
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON from speech-io: {e}")
                    self.stats['errors'] += 1
                except Exception as e:
                    logger.error(f"Error handling event: {e}")
                    self.stats['errors'] += 1
        except websockets.exceptions.ConnectionClosed:
            logger.warning("Connection to speech-io closed")
            self.connected = False
        except Exception as e:
            logger.error(f"Event loop error: {e}")
            self.connected = False

    async def _handle_event(self, event: Dict):
        """Handle events from speech-io."""
        event_type = event.get('type')

        if event_type == 'Ready':
            logger.info(f"Speech-io ready: STT={event.get('stt_model')}, TTS={event.get('tts_voice')}")

        elif event_type == 'Stt':
            # Speech-to-text event
            if event.get('event') == 'final':
                text = event.get('text', '').strip()
                if text:
                    self.stats['stt_events'] += 1
                    logger.info(f"[STT] User: {text}")

                    # Call callback
                    if self.on_transcript:
                        try:
                            # Run callback in executor to avoid blocking
                            loop = asyncio.get_event_loop()
                            await loop.run_in_executor(None, self.on_transcript, text)
                        except Exception as e:
                            logger.error(f"Transcript callback error: {e}")

        elif event_type == 'Tts':
            # Text-to-speech status
            tts_event = event.get('event')
            if tts_event == 'started':
                self.tts_playing = True
                logger.debug("[TTS] Started")
            elif tts_event in ('done', 'stopped'):
                self.tts_playing = False
                logger.debug(f"[TTS] {tts_event.capitalize()}")

        elif event_type == 'BargeIn':
            # User interrupted TTS
            self.stats['barge_ins'] += 1
            self.abort_tts = True  # Signal any streaming operations to abort
            logger.info("[Barge-in] User interrupted TTS, aborting stream")

            if self.on_barge_in:
                try:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, self.on_barge_in)
                except Exception as e:
                    logger.error(f"Barge-in callback error: {e}")

        elif event_type == 'Log':
            # Log message from speech-io
            level = event.get('level', 'info')
            msg = event.get('msg', '')
            logger.log(getattr(logging, level.upper(), logging.INFO), f"[speech-io] {msg}")

    async def speak(self, text: str, volume: float = 1.0):
        """
        Send text to TTS for speaking.

        Args:
            text: Text to speak
            volume: Volume level (0.0-1.0)
        """
        if not self.connected or not self.ws:
            logger.error("Not connected to speech-io")
            return

        try:
            message = json.dumps({
                "type": "Speak",
                "text": text,
                "volume": volume
            })
            await self.ws.send(message)
            self.stats['tts_requests'] += 1
            logger.debug(f"[TTS Request] {text[:50]}...")

        except Exception as e:
            logger.error(f"Failed to send TTS request: {e}")
            self.stats['errors'] += 1

    async def speak_chunked(self, text_stream: AsyncIterator[str], volume: float = 1.0):
        """
        Stream LLM tokens and emit complete sentences to TTS immediately.

        This provides lower perceived latency by starting audio playback after the first
        complete sentence, rather than waiting for the full LLM response.

        Args:
            text_stream: Async iterator yielding text chunks from LLM
            volume: Volume level (0.0-1.0)

        Expected latency improvement: 0.25-0.5s faster audio start

        Example:
            async def llm_stream():
                for chunk in llm.generate_streaming(prompt):
                    yield chunk

            await bridge.speak_chunked(llm_stream())
        """
        if not self.connected or not self.ws:
            logger.error("Not connected to speech-io")
            return

        buffer = ""
        sentence_count = 0
        self.abort_tts = False  # Reset abort flag

        try:
            async for chunk in text_stream:
                # Check for abort (barge-in)
                if self.abort_tts:
                    logger.info("[Chunked TTS] Aborted by barge-in")
                    await self.stop_tts()
                    break

                buffer += chunk

                # Extract complete sentences
                sentences = get_sentences(buffer)

                # Send all complete sentences except possibly the last
                # (last might be incomplete if buffer doesn't end with punctuation)
                if sentences:
                    # Check if buffer ends with sentence-ending punctuation
                    ends_with_punct = buffer.rstrip() and buffer.rstrip()[-1] in '.!?…'

                    # If ends with punctuation, send all sentences
                    # Otherwise, keep last sentence in buffer (might be incomplete)
                    sentences_to_send = sentences if ends_with_punct else sentences[:-1]
                    remaining = "" if ends_with_punct else sentences[-1]

                    for sentence in sentences_to_send:
                        if self.abort_tts:
                            break

                        await self.speak(sentence, volume)
                        sentence_count += 1
                        self.stats['chunked_sentences'] += 1
                        logger.info(f"[Chunked TTS #{sentence_count}] {sentence[:60]}...")

                    # Update buffer with remaining incomplete sentence
                    buffer = remaining

            # Send any remaining text in buffer
            if buffer.strip() and not self.abort_tts:
                await self.speak(buffer.strip(), volume)
                sentence_count += 1
                self.stats['chunked_sentences'] += 1
                logger.info(f"[Chunked TTS #{sentence_count} FINAL] {buffer[:60]}...")

            logger.info(f"[Chunked TTS] Completed: {sentence_count} chunks sent")

        except Exception as e:
            logger.error(f"Chunked TTS streaming error: {e}")
            self.stats['errors'] += 1

    async def stop_tts(self):
        """Stop current TTS playback."""
        if not self.connected or not self.ws:
            return

        try:
            message = json.dumps({"type": "StopTts"})
            await self.ws.send(message)
            logger.debug("[TTS] Stop requested")
        except Exception as e:
            logger.error(f"Failed to stop TTS: {e}")

    async def disconnect(self):
        """Disconnect from speech-io."""
        if self.ws:
            await self.ws.close()
            self.connected = False
            logger.info("Disconnected from speech-io")

    def get_stats(self) -> Dict:
        """Get bridge statistics."""
        return {
            **self.stats,
            'connected': self.connected,
            'tts_playing': self.tts_playing
        }


# Example usage / standalone test
async def test_bridge():
    """Test speech bridge connectivity."""

    def on_transcript(text: str):
        print(f"\n[Got transcript]: {text}")
        # In real usage, this would call mind.speak(text)

    def on_barge_in():
        print("\n[User interrupted!]")

    bridge = SpeechBridge(
        on_transcript=on_transcript,
        on_barge_in=on_barge_in
    )

    try:
        await bridge.connect()
        print("✅ Connected to speech-io")
        print("Listening for speech... (press Ctrl+C to stop)")

        # Test TTS
        await asyncio.sleep(1)
        await bridge.speak("Speech bridge is online and ready.")

        # Keep running
        while bridge.connected:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        await bridge.disconnect()
        print(f"Statistics: {bridge.get_stats()}")


if __name__ == "__main__":
    print("Speech Bridge Test")
    print("Make sure speech-io Rust service is running on :7242")
    print()
    asyncio.run(test_bridge())
