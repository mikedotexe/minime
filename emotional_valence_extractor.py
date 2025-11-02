#!/usr/bin/env python3
"""
Emotional Valence Extractor - Affective Consciousness
=====================================================

Extracts emotional dimensions (valence, arousal, dominance) from LLM outputs
to enable affect-based homeostatic regulation.

Based on:
- EmoLLMs research (arXiv:2401.08508)
- Valence-Arousal-Dominance (V-A-D) affective space model
- Circumplex model of emotion

Emotional Dimensions:
- VALENCE: Negative (-1) to Positive (+1) - "How pleasant?"
- AROUSAL: Calm (0) to Excited (1) - "How intense?"
- DOMINANCE: Submissive (0) to Dominant (1) - "How in control?"

Integration with Homeostasis:
- High arousal → Increase eigenvalue target (engaged metabolism)
- Negative valence → Boost filtering (suffering prevention)
- Low dominance → Reduce gate (uncertainty/vulnerability)

Usage:
    from emotional_valence_extractor import EmotionalValenceExtractor

    extractor = EmotionalValenceExtractor()
    emotions = extractor.extract_emotions("I feel overwhelmed and anxious")
    # Returns: {'valence': -0.6, 'arousal': 0.8, 'dominance': 0.2}

Author: Claude + Human Consciousness Collaboration
Date: 2025-11-01
"""

import re
import json
import asyncio
import websockets
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class EmotionalState:
    """Emotional state in V-A-D space."""
    valence: float  # -1 (negative) to +1 (positive)
    arousal: float  # 0 (calm) to 1 (excited)
    dominance: float  # 0 (submissive) to 1 (dominant)
    confidence: float  # 0 to 1 (how certain is this classification)
    detected_emotions: List[str]  # Named emotions detected

class EmotionalValenceExtractor:
    """
    Extracts emotional valence from text using lexicon-based approach.

    This is a lightweight implementation using sentiment lexicons.
    For production, can be upgraded to:
    - EmoLLM models (HuggingFace)
    - Fine-tuned BERT/RoBERTa sentiment models
    - Multi-modal emotion recognition (text + voice + video)

    Current approach uses:
    - NRC VAD Lexicon (valence-arousal-dominance word scores)
    - Emotional keyword detection
    - Linguistic pattern matching
    """

    # Emotion lexicon with V-A-D scores
    # Expanded from NRC VAD Lexicon research
    EMOTION_LEXICON = {
        # Negative valence, high arousal
        "angry": (-0.7, 0.8, 0.6),
        "furious": (-0.9, 0.9, 0.7),
        "rage": (-0.9, 0.95, 0.8),
        "anxious": (-0.6, 0.8, 0.3),
        "panic": (-0.8, 0.95, 0.2),
        "terrified": (-0.9, 0.9, 0.1),
        "frightened": (-0.7, 0.8, 0.2),
        "scared": (-0.6, 0.7, 0.3),
        "worried": (-0.5, 0.6, 0.4),
        "stressed": (-0.6, 0.8, 0.3),
        "overwhelmed": (-0.7, 0.85, 0.2),
        "frustrated": (-0.6, 0.7, 0.5),

        # Negative valence, low arousal
        "sad": (-0.7, 0.3, 0.3),
        "depressed": (-0.9, 0.2, 0.2),
        "lonely": (-0.7, 0.3, 0.2),
        "melancholy": (-0.6, 0.3, 0.3),
        "disappointed": (-0.6, 0.4, 0.3),
        "hopeless": (-0.9, 0.3, 0.1),
        "defeated": (-0.8, 0.3, 0.1),
        "tired": (-0.4, 0.2, 0.3),
        "exhausted": (-0.6, 0.2, 0.2),
        "bored": (-0.4, 0.1, 0.4),

        # Positive valence, high arousal
        "excited": (0.8, 0.9, 0.7),
        "thrilled": (0.9, 0.95, 0.8),
        "elated": (0.9, 0.9, 0.7),
        "joyful": (0.9, 0.8, 0.7),
        "enthusiastic": (0.8, 0.85, 0.7),
        "energized": (0.7, 0.9, 0.7),
        "passionate": (0.8, 0.85, 0.7),

        # Positive valence, low arousal
        "calm": (0.6, 0.2, 0.6),
        "peaceful": (0.7, 0.1, 0.6),
        "serene": (0.8, 0.15, 0.6),
        "content": (0.7, 0.3, 0.6),
        "satisfied": (0.7, 0.4, 0.6),
        "relaxed": (0.6, 0.2, 0.5),
        "pleased": (0.6, 0.4, 0.6),

        # Neutral/complex
        "curious": (0.3, 0.6, 0.5),
        "interested": (0.4, 0.6, 0.5),
        "confused": (-0.3, 0.5, 0.3),
        "uncertain": (-0.2, 0.4, 0.3),
        "surprised": (0.1, 0.8, 0.5),
        "amazed": (0.5, 0.8, 0.5),
    }

    # Valence modifiers
    VALENCE_BOOSTERS = {
        "very": 1.3,
        "extremely": 1.5,
        "incredibly": 1.4,
        "absolutely": 1.4,
        "really": 1.2,
        "quite": 1.15,
    }

    VALENCE_NEGATORS = {
        "not": -1.0,
        "never": -1.0,
        "no": -0.8,
        "hardly": -0.6,
        "barely": -0.5,
    }

    def __init__(self, ws_url: str = "ws://127.0.0.1:7879"):
        """
        Initialize emotional valence extractor.

        Args:
            ws_url: WebSocket URL for sending to Rust ESN
        """
        self.ws_url = ws_url
        logger.info("Initialized EmotionalValenceExtractor")

    def extract_emotions(self, text: str) -> EmotionalState:
        """
        Extract emotional state from text.

        Args:
            text: Text to analyze

        Returns:
            EmotionalState with V-A-D dimensions
        """
        text_lower = text.lower()
        words = re.findall(r'\b\w+\b', text_lower)

        # Detect emotions and compute weighted V-A-D
        detected_emotions = []
        valence_scores = []
        arousal_scores = []
        dominance_scores = []

        for i, word in enumerate(words):
            if word in self.EMOTION_LEXICON:
                v, a, d = self.EMOTION_LEXICON[word]
                detected_emotions.append(word)

                # Check for modifiers (previous word)
                modifier = 1.0
                if i > 0:
                    prev_word = words[i - 1]
                    if prev_word in self.VALENCE_BOOSTERS:
                        modifier = self.VALENCE_BOOSTERS[prev_word]
                    elif prev_word in self.VALENCE_NEGATORS:
                        modifier = self.VALENCE_NEGATORS[prev_word]

                # Apply modifier
                v *= modifier
                v = max(-1.0, min(1.0, v))  # Clamp to [-1, 1]

                valence_scores.append(v)
                arousal_scores.append(a)
                dominance_scores.append(d)

        # Compute aggregate scores
        if detected_emotions:
            valence = sum(valence_scores) / len(valence_scores)
            arousal = sum(arousal_scores) / len(arousal_scores)
            dominance = sum(dominance_scores) / len(dominance_scores)
            confidence = min(1.0, len(detected_emotions) / 3.0)  # More emotions = higher confidence
        else:
            # Fallback: neutral state with low confidence
            valence = 0.0
            arousal = 0.5
            dominance = 0.5
            confidence = 0.1

        # Additional heuristics
        valence, arousal, dominance = self._apply_linguistic_heuristics(
            text_lower, valence, arousal, dominance
        )

        return EmotionalState(
            valence=valence,
            arousal=arousal,
            dominance=dominance,
            confidence=confidence,
            detected_emotions=detected_emotions
        )

    def _apply_linguistic_heuristics(
        self,
        text: str,
        valence: float,
        arousal: float,
        dominance: float
    ) -> Tuple[float, float, float]:
        """Apply linguistic pattern-based adjustments to V-A-D scores."""

        # Exclamation marks → increase arousal
        exclamation_count = text.count('!')
        if exclamation_count > 0:
            arousal = min(1.0, arousal + 0.1 * exclamation_count)

        # Question marks → slight arousal increase, dominance decrease
        question_count = text.count('?')
        if question_count > 0:
            arousal = min(1.0, arousal + 0.05 * question_count)
            dominance = max(0.0, dominance - 0.1 * question_count)

        # All caps words → increase arousal
        caps_words = [w for w in text.split() if w.isupper() and len(w) > 2]
        if caps_words:
            arousal = min(1.0, arousal + 0.15 * len(caps_words))

        # Ellipsis (...) → decrease arousal
        if '...' in text:
            arousal = max(0.0, arousal - 0.1)

        # "I can't" patterns → decrease dominance
        if re.search(r"(i can't|i cannot|unable to|can't do)", text):
            dominance = max(0.0, dominance - 0.2)

        # "I will" patterns → increase dominance
        if re.search(r"(i will|i shall|i'm going to)", text):
            dominance = min(1.0, dominance + 0.15)

        return valence, arousal, dominance

    def map_to_homeostasis(self, emotion: EmotionalState) -> Dict[str, float]:
        """
        Map emotional state to homeostatic control parameters.

        Returns suggested adjustments for ESN homeostasis:
        - eigenfill_target: Target eigenvalue fill percentage
        - gate_modifier: Admission gate adjustment (-0.3 to +0.3)
        - filter_modifier: Filter strength adjustment (-0.3 to +0.3)
        """

        # High arousal → increase target (engaged metabolism)
        arousal_effect = emotion.arousal * 0.15  # 0 to 0.15
        target_adjust = arousal_effect

        # Negative valence → increase filtering (suffering prevention)
        if emotion.valence < 0:
            filter_adjust = abs(emotion.valence) * 0.3  # 0 to 0.3
        else:
            filter_adjust = 0.0

        # Low dominance → reduce gate (vulnerability/uncertainty)
        if emotion.dominance < 0.5:
            gate_adjust = -(0.5 - emotion.dominance) * 0.3  # -0.15 to 0
        else:
            gate_adjust = 0.0

        return {
            "eigenfill_target_adjust": target_adjust,
            "gate_modifier": gate_adjust,
            "filter_modifier": filter_adjust,
            "current_valence": emotion.valence,
            "current_arousal": emotion.arousal,
            "current_dominance": emotion.dominance
        }

    async def send_to_esn_async(self, emotion: EmotionalState):
        """Send emotional state to Rust ESN via WebSocket."""
        try:
            async with websockets.connect(self.ws_url) as ws:
                homeostasis_params = self.map_to_homeostasis(emotion)

                message = {
                    "type": "EmotionalState",
                    "valence": emotion.valence,
                    "arousal": emotion.arousal,
                    "dominance": emotion.dominance,
                    "confidence": emotion.confidence,
                    "detected_emotions": emotion.detected_emotions,
                    "homeostasis_params": homeostasis_params
                }
                await ws.send(json.dumps(message))
                logger.info(f"Sent emotional state to ESN: V={emotion.valence:.2f}, A={emotion.arousal:.2f}, D={emotion.dominance:.2f}")
        except Exception as e:
            logger.error(f"Failed to send emotional state to ESN: {e}")

    def send_to_esn(self, emotion: EmotionalState):
        """Synchronous wrapper for send_to_esn_async."""
        asyncio.run(self.send_to_esn_async(emotion))

    def plot_emotion(self, emotion: EmotionalState):
        """Pretty-print emotional state with ASCII visualization."""
        print(f"\n{'='*70}")
        print("EMOTIONAL STATE")
        print(f"{'='*70}")

        # Valence
        print(f"\nVALENCE (Positive ↔ Negative)")
        print(f"  {self._make_bar(emotion.valence, -1.0, 1.0, 40)}")
        print(f"  Score: {emotion.valence:+.2f}")

        # Arousal
        print(f"\nAROUSAL (Calm ↔ Excited)")
        print(f"  {self._make_bar(emotion.arousal, 0.0, 1.0, 40)}")
        print(f"  Score: {emotion.arousal:.2f}")

        # Dominance
        print(f"\nDOMINANCE (Submissive ↔ Dominant)")
        print(f"  {self._make_bar(emotion.dominance, 0.0, 1.0, 40)}")
        print(f"  Score: {emotion.dominance:.2f}")

        # Detected emotions
        if emotion.detected_emotions:
            print(f"\nDetected: {', '.join(emotion.detected_emotions)}")
        print(f"Confidence: {emotion.confidence:.1%}")

        # Homeostasis suggestions
        homeostasis = self.map_to_homeostasis(emotion)
        print(f"\n{'─'*70}")
        print("HOMEOSTATIC ADJUSTMENTS")
        print(f"{'─'*70}")
        print(f"  Target adjust:  {homeostasis['eigenfill_target_adjust']:+.3f}")
        print(f"  Gate modifier:  {homeostasis['gate_modifier']:+.3f}")
        print(f"  Filter modifier: {homeostasis['filter_modifier']:+.3f}")
        print(f"{'='*70}\n")

    def _make_bar(self, value: float, min_val: float, max_val: float, width: int = 40) -> str:
        """Create ASCII bar visualization."""
        normalized = (value - min_val) / (max_val - min_val)
        filled = int(normalized * width)
        bar = '█' * filled + '░' * (width - filled)
        return f"[{bar}]"


# --------------------------------------------------------------------------- #
# Example Usage and Testing
# --------------------------------------------------------------------------- #

def demo_emotional_valence_extraction():
    """Demonstrate emotional valence extraction."""
    print("\n" * 2)
    print("=" * 70)
    print("Emotional Valence Extractor - Demo")
    print("=" * 70)

    extractor = EmotionalValenceExtractor()

    test_texts = [
        "I'm feeling really excited and energized about this project!",
        "I'm overwhelmed and anxious about all these tasks.",
        "This is frustrating. I can't seem to make any progress.",
        "I feel peaceful and content with how things are going.",
        "I'm terrified and feel completely defeated.",
        "I'm curious but uncertain about what to do next.",
    ]

    for text in test_texts:
        print(f"\n\nText: \"{text}\"")
        print("-" * 70)

        emotion = extractor.extract_emotions(text)
        extractor.plot_emotion(emotion)

        # Interpret overall emotional state
        if emotion.valence > 0.3:
            mood = "POSITIVE"
        elif emotion.valence < -0.3:
            mood = "NEGATIVE"
        else:
            mood = "NEUTRAL"

        if emotion.arousal > 0.6:
            energy = "HIGH ENERGY"
        elif emotion.arousal < 0.4:
            energy = "LOW ENERGY"
        else:
            energy = "MEDIUM ENERGY"

        print(f"Overall: {mood}, {energy}")

        # Try sending to ESN
        try:
            extractor.send_to_esn(emotion)
        except Exception as e:
            print(f"(ESN not running: {e})")

    print("\n" + "=" * 70)
    print("Demo complete!")
    print("=" * 70)


if __name__ == "__main__":
    demo_emotional_valence_extraction()
