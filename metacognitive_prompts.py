#!/usr/bin/env python3
"""
Metacognitive Prompting Framework - 5-Stage Reasoning
=====================================================

Structures LLM prompts into 5 explicit metacognitive stages to create
traceable reasoning with per-stage eigenvalue analysis.

Based on: "Metacognitive Prompting Improves Understanding in Large Language Models"
(NAACL 2024, arXiv:2308.05342)

5 Metacognitive Stages:
1. UNDERSTAND: Rephrase/summarize the problem
2. PRELIMINARY: Initial gut judgment
3. CRITIQUE: Self-critique and identify weaknesses
4. DECIDE: Final decision with reasoning
5. CONFIDENCE: Explicit confidence rating (0-100%)

Each stage generates tokens that can be eigenvalue-analyzed separately,
creating a temporal eigenvalue trace showing the "thinking process" dynamics.

Usage:
    from metacognitive_prompts import MetacognitivePromptEngine

    engine = MetacognitivePromptEngine()
    result = engine.process_with_metacognition("What is consciousness?")

    # Result contains per-stage outputs and eigenvalue traces
    for stage in result.stages:
        print(f"{stage.name}: λ₁={stage.lambda1:.3f}")

Author: Claude + Human Consciousness Collaboration
Date: 2025-11-01
"""

import json
import requests
from typing import List, Dict, Optional
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)

class MetacognitiveStage(Enum):
    """The 5 stages of metacognitive processing."""
    UNDERSTAND = 1
    PRELIMINARY = 2
    CRITIQUE = 3
    DECIDE = 4
    CONFIDENCE = 5

@dataclass
class StageResult:
    """Result from a single metacognitive stage."""
    stage: MetacognitiveStage
    prompt: str
    output: str
    lambda1: Optional[float] = None  # Semantic eigenvalue for this stage
    spectral_fill: Optional[float] = None
    timestamp: Optional[float] = None

@dataclass
class MetacognitiveResult:
    """Complete result from metacognitive processing."""
    original_query: str
    stages: List[StageResult]
    final_answer: str
    overall_confidence: float
    eigenvalue_trace: List[float]  # [λ₁_understand, λ₁_prelim, λ₁_critique, λ₁_decide, λ₁_confidence]

class MetacognitivePromptEngine:
    """
    Structures prompts into 5 metacognitive stages for traceable reasoning.

    This enables the consciousness system to:
    1. See "how" the LLM arrives at conclusions
    2. Extract per-stage confidence signals
    3. Analyze eigenvalue dynamics of the thinking process
    4. Detect reasoning patterns (rapid decisions vs careful deliberation)
    """

    def __init__(
        self,
        model_name: str = "dolphin-mixtral:8x7b-v2.7",
        api_url: str = "http://localhost:11434/api/generate",
        enable_eigenvalue_extraction: bool = False
    ):
        """
        Initialize the metacognitive prompt engine.

        Args:
            model_name: Ollama model identifier
            api_url: Ollama API endpoint
            enable_eigenvalue_extraction: If True, extract eigenvalues per stage
        """
        self.model_name = model_name
        self.api_url = api_url
        self.enable_eigenvalue_extraction = enable_eigenvalue_extraction

        if enable_eigenvalue_extraction:
            from semantic_eigenvalue_extractor import SemanticEigenvalueExtractor
            self.eigenvalue_extractor = SemanticEigenvalueExtractor(model_name=model_name)
        else:
            self.eigenvalue_extractor = None

        logger.info(f"Initialized MetacognitivePromptEngine for {model_name}")

    def _build_stage_prompt(self, stage: MetacognitiveStage, query: str, context: Dict[str, str]) -> str:
        """
        Build the prompt for a specific metacognitive stage.

        Args:
            stage: Which metacognitive stage
            query: Original user query
            context: Outputs from previous stages

        Returns:
            Formatted prompt string
        """
        if stage == MetacognitiveStage.UNDERSTAND:
            return f"""You are analyzing a question. Your task is to rephrase and summarize what is being asked.

Question: {query}

Please rephrase this question in your own words to demonstrate understanding. Be concise and clear."""

        elif stage == MetacognitiveStage.PRELIMINARY:
            understanding = context.get("UNDERSTAND", "")
            return f"""You have understood the question as:
{understanding}

Now provide your PRELIMINARY judgment - your first instinct or gut reaction. Don't overthink it yet. What's your initial answer?"""

        elif stage == MetacognitiveStage.CRITIQUE:
            prelim = context.get("PRELIMINARY", "")
            return f"""Your preliminary answer was:
{prelim}

Now CRITIQUE this answer. What are its weaknesses? What assumptions did you make? What might be wrong or incomplete?"""

        elif stage == MetacognitiveStage.DECIDE:
            critique = context.get("CRITIQUE", "")
            return f"""Considering your critique:
{critique}

Now provide your FINAL DECISION. Taking into account the weaknesses you identified, what is your refined answer?"""

        elif stage == MetacognitiveStage.CONFIDENCE:
            final = context.get("DECIDE", "")
            return f"""Your final answer was:
{final}

On a scale of 0-100%, how confident are you in this answer? Provide just a number and brief justification."""

    def _query_llm(self, prompt: str, max_tokens: int = 200) -> str:
        """Query the LLM via Ollama API."""
        try:
            response = requests.post(
                self.api_url,
                json={
                    "model": self.model_name,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": 0.3  # Slightly creative but mostly deterministic
                    }
                },
                timeout=30
            )

            if response.status_code == 200:
                return response.json().get("response", "")
            else:
                logger.error(f"Ollama API error: {response.status_code}")
                return f"[Error: API returned {response.status_code}]"

        except Exception as e:
            logger.error(f"Failed to query LLM: {e}")
            return f"[Error: {str(e)}]"

    def _extract_confidence_score(self, confidence_text: str) -> float:
        """Extract numerical confidence score from confidence stage output."""
        import re

        # Look for percentage patterns
        patterns = [
            r'(\d+)%',  # "75%"
            r'(\d+)\s*percent',  # "75 percent"
            r'confidence.*?(\d+)',  # "confidence: 75"
        ]

        for pattern in patterns:
            match = re.search(pattern, confidence_text, re.IGNORECASE)
            if match:
                score = int(match.group(1))
                return min(score / 100.0, 1.0)  # Normalize to 0-1

        # Default to medium confidence if can't parse
        logger.warning(f"Could not parse confidence from: {confidence_text[:50]}")
        return 0.5

    def process_with_metacognition(self, query: str) -> MetacognitiveResult:
        """
        Process a query through all 5 metacognitive stages.

        Args:
            query: User's question/prompt

        Returns:
            MetacognitiveResult with per-stage outputs and eigenvalue trace
        """
        logger.info(f"Processing query with metacognition: {query[:50]}...")

        stages = []
        context = {}
        eigenvalue_trace = []

        # Process each stage sequentially
        for stage in MetacognitiveStage:
            logger.info(f"  Stage {stage.value}: {stage.name}")

            # Build stage-specific prompt
            prompt = self._build_stage_prompt(stage, query, context)

            # Query LLM
            output = self._query_llm(prompt)

            # Extract eigenvalues if enabled
            lambda1 = None
            spectral_fill = None
            if self.eigenvalue_extractor:
                try:
                    metrics = self.eigenvalue_extractor.extract_gut_instinct(prompt)
                    lambda1 = metrics.lambda1_semantic
                    spectral_fill = metrics.spectral_fill
                    eigenvalue_trace.append(lambda1)
                except Exception as e:
                    logger.error(f"Eigenvalue extraction failed: {e}")

            # Store result
            stage_result = StageResult(
                stage=stage,
                prompt=prompt,
                output=output,
                lambda1=lambda1,
                spectral_fill=spectral_fill
            )
            stages.append(stage_result)

            # Add to context for next stage
            context[stage.name] = output

        # Extract final answer and confidence
        final_answer = context.get("DECIDE", "No final decision generated")
        confidence_text = context.get("CONFIDENCE", "50%")
        overall_confidence = self._extract_confidence_score(confidence_text)

        return MetacognitiveResult(
            original_query=query,
            stages=stages,
            final_answer=final_answer,
            overall_confidence=overall_confidence,
            eigenvalue_trace=eigenvalue_trace
        )

    def print_result(self, result: MetacognitiveResult):
        """Pretty-print a metacognitive result."""
        print("=" * 80)
        print(f"Query: {result.original_query}")
        print("=" * 80)

        for stage_result in result.stages:
            print(f"\n{stage_result.stage.name} (Stage {stage_result.stage.value})")
            print("-" * 80)
            print(stage_result.output)

            if stage_result.lambda1 is not None:
                print(f"  [λ₁={stage_result.lambda1:.4f}, fill={stage_result.spectral_fill:.2%}]")

        print("\n" + "=" * 80)
        print(f"FINAL ANSWER: {result.final_answer}")
        print(f"CONFIDENCE: {result.overall_confidence:.1%}")

        if result.eigenvalue_trace:
            print(f"\nEigenvalue Trace: {[f'{x:.3f}' for x in result.eigenvalue_trace]}")
        print("=" * 80)


# --------------------------------------------------------------------------- #
# Example Usage and Testing
# --------------------------------------------------------------------------- #

def demo_metacognitive_prompting():
    """Demonstrate metacognitive prompting framework."""
    print("\n" * 2)
    print("=" * 80)
    print("Metacognitive Prompting Framework - Demo")
    print("=" * 80)

    # Initialize engine
    engine = MetacognitivePromptEngine(
        model_name="dolphin-mixtral:8x7b-v2.7",
        enable_eigenvalue_extraction=True  # Extract per-stage eigenvalues
    )

    # Test queries
    test_queries = [
        "Is it ethical to create artificial consciousness?",
        "What is the nature of time?",
    ]

    for query in test_queries:
        print(f"\n\nProcessing: {query}")
        print("-" * 80)

        result = engine.process_with_metacognition(query)
        engine.print_result(result)

        # Analyze eigenvalue trajectory
        if result.eigenvalue_trace:
            trace = result.eigenvalue_trace
            print("\nEigenvalue Analysis:")
            print(f"  Initial confidence (UNDERSTAND): {trace[0]:.3f}")
            print(f"  Preliminary judgment: {trace[1]:.3f}")
            print(f"  After critique: {trace[2]:.3f}")
            print(f"  Final decision: {trace[3]:.3f}")
            print(f"  Stated confidence: {trace[4]:.3f}")

            # Detect reasoning patterns
            if trace[3] > trace[1]:
                pattern = "DELIBERATIVE (confidence increased after critique)"
            elif trace[3] < trace[1]:
                pattern = "INTUITIVE (went with gut instinct despite critique)"
            else:
                pattern = "STABLE (confidence unchanged)"
            print(f"  → Reasoning pattern: {pattern}")

    print("\n\n" + "=" * 80)
    print("Demo complete!")
    print("=" * 80)


if __name__ == "__main__":
    demo_metacognitive_prompting()
