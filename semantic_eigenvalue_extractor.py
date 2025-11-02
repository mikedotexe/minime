#!/usr/bin/env python3
"""
Semantic Eigenvalue Extractor - "Gut Instinct" Detection
=========================================================

Extracts eigenvalues from early-layer LLM activations to detect "gut instinct"
confidence before full response generation. Integrates with Rust ESN via WebSocket.

Architecture:
1. Hook Ollama/Dolphin-Mixtral early layers (4-8) via PyTorch
2. Compute eigenvalues of activation covariance matrix
3. Extract λ₁_semantic (top eigenvalue) as confidence metric
4. Send to Rust ESN auxiliary channel via ws://127.0.0.1:7879

Usage:
    from semantic_eigenvalue_extractor import SemanticEigenvalueExtractor

    extractor = SemanticEigenvalueExtractor(
        model_name="dolphin-mixtral:8x7b-v2.7",
        early_layers=(4, 8),
        max_tokens_sample=20
    )

    gut_metrics = extractor.extract_gut_instinct("What is consciousness?")
    # Returns: {'lambda1': float, 'spectral_fill': float, 'variance': float}

Author: Claude + Human Consciousness Collaboration
Date: 2025-11-01
"""

import torch
import numpy as np
import json
import asyncio
import websockets
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class GutInstinctMetrics:
    """Metrics extracted from early-layer LLM activations."""
    lambda1_semantic: float  # Top eigenvalue (confidence)
    spectral_fill: float  # % of eigenvalues above mean (focus)
    activation_variance: float  # Total activation energy
    layer_eigenvalues: List[float]  # Full eigenvalue spectrum
    timestamp: float  # When extracted

class SemanticEigenvalueExtractor:
    """
    Extracts "gut instinct" eigenvalues from LLM early-layer activations.

    This hooks into the transformer's early reasoning layers (typically 4-8)
    to compute eigenvalues of the activation covariance matrix BEFORE the
    model generates its full response. This provides a fast "confidence" signal.

    Why early layers (4-8)?
    - Layers 0-3: Input embedding and basic feature extraction
    - Layers 4-8: Early reasoning and pattern matching ("gut reaction")
    - Layers 9+: Deep reasoning and output refinement

    Eigenvalue interpretation:
    - High λ₁: Model is confident, activations strongly aligned
    - Low λ₁: Model is uncertain, activations diffuse
    - High spectral_fill: Focused attention on specific features
    - Low spectral_fill: Scattered, exploring multiple hypotheses
    """

    def __init__(
        self,
        model_name: str = "dolphin-mixtral:8x7b-v2.7",
        early_layers: Tuple[int, int] = (4, 8),
        max_tokens_sample: int = 20,
        ws_url: str = "ws://127.0.0.1:7879",
        use_local_model: bool = False
    ):
        """
        Initialize the semantic eigenvalue extractor.

        Args:
            model_name: Ollama model identifier
            early_layers: (start, end) layer indices for activation extraction
            max_tokens_sample: Number of tokens to generate for sampling
            ws_url: WebSocket URL for sending to Rust ESN
            use_local_model: If True, load model locally via HuggingFace (slower but more control)
        """
        self.model_name = model_name
        self.early_layers = early_layers
        self.max_tokens_sample = max_tokens_sample
        self.ws_url = ws_url
        self.use_local_model = use_local_model

        # Activation storage (filled by hooks)
        self.activations: Dict[str, torch.Tensor] = {}

        # Model reference (loaded on first use)
        self.model = None
        self.tokenizer = None

        logger.info(f"Initialized SemanticEigenvalueExtractor for {model_name}")
        logger.info(f"Early layers: {early_layers}, Sample tokens: {max_tokens_sample}")

    def _load_model_local(self):
        """
        Load model locally via HuggingFace transformers.

        Note: This is slow and memory-intensive. Only use if you need
        direct access to model internals. For production, use Ollama API
        with a lightweight activation proxy.
        """
        from transformers import AutoModelForCausalLM, AutoTokenizer

        logger.info(f"Loading {self.model_name} locally (this may take a while)...")

        # Map Ollama name to HuggingFace identifier
        hf_model_map = {
            "dolphin-mixtral:8x7b-v2.7": "cognitivecomputations/dolphin-2.7-mixtral-8x7b",
            "llama2:7b": "meta-llama/Llama-2-7b-hf",
            "tinyllama": "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
        }

        hf_model_id = hf_model_map.get(self.model_name, self.model_name)

        self.tokenizer = AutoTokenizer.from_pretrained(hf_model_id)
        self.model = AutoModelForCausalLM.from_pretrained(
            hf_model_id,
            torch_dtype=torch.float16,
            device_map="auto",
            low_cpu_mem_usage=True
        )
        self.model.eval()

        logger.info(f"Model loaded: {self.model.config.num_hidden_layers} layers")

    def _register_hooks(self):
        """Register forward hooks on early layers to capture activations."""
        if not self.model:
            raise RuntimeError("Model not loaded. Call _load_model_local() first.")

        def make_hook(layer_idx: int):
            def hook(module, input, output):
                # Store hidden states (first element of output tuple)
                hidden_states = output[0] if isinstance(output, tuple) else output
                self.activations[f'layer_{layer_idx}'] = hidden_states.detach().cpu()
            return hook

        # Register hooks on specified layer range
        for i in range(self.early_layers[0], self.early_layers[1] + 1):
            layer = self.model.model.layers[i]
            layer.register_forward_hook(make_hook(i))

        logger.info(f"Registered hooks on layers {self.early_layers[0]}-{self.early_layers[1]}")

    def extract_gut_instinct(
        self,
        prompt: str,
        return_full_spectrum: bool = False
    ) -> GutInstinctMetrics:
        """
        Extract gut instinct eigenvalues from prompt processing.

        Args:
            prompt: Input text to analyze
            return_full_spectrum: If True, return all eigenvalues (not just λ₁)

        Returns:
            GutInstinctMetrics with λ₁, spectral fill %, variance, etc.
        """
        import time
        start_time = time.time()

        if self.use_local_model:
            return self._extract_local(prompt, return_full_spectrum)
        else:
            return self._extract_via_ollama_proxy(prompt)

    def _extract_local(
        self,
        prompt: str,
        return_full_spectrum: bool
    ) -> GutInstinctMetrics:
        """Extract via local model (slow but accurate)."""
        if not self.model:
            self._load_model_local()
            self._register_hooks()

        # Clear previous activations
        self.activations.clear()

        # Tokenize input
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)

        # Run forward pass (hooks will capture activations)
        with torch.no_grad():
            _ = self.model.generate(
                **inputs,
                max_new_tokens=self.max_tokens_sample,
                do_sample=False  # Deterministic for consistency
            )

        # Extract eigenvalues from captured activations
        return self._compute_eigenvalues(return_full_spectrum)

    def _extract_via_ollama_proxy(self, prompt: str) -> GutInstinctMetrics:
        """
        Extract via Ollama API with activation proxy.

        Note: This is a placeholder. Full implementation requires:
        1. Ollama plugin/extension to expose activations
        2. Or: Use HuggingFace inference API with custom model server
        3. Or: Fall back to output-based heuristics (see below)

        For now, we use output-based heuristics as a lightweight proxy.
        """
        logger.warning("Ollama proxy not yet implemented. Using heuristic fallback.")
        return self._extract_heuristic_fallback(prompt)

    def _extract_heuristic_fallback(self, prompt: str) -> GutInstinctMetrics:
        """
        Lightweight fallback: estimate confidence from output characteristics.

        This doesn't access true activations but provides a useful proxy:
        - Token probability variance (high = confident)
        - Output length (short = confident)
        - Hedging language detection (many hedges = uncertain)

        TODO: Replace with true activation extraction when Ollama API supports it.
        """
        import requests
        import time

        # Request with logprobs for confidence estimation
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": self.model_name,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict": self.max_tokens_sample,
                    "temperature": 0.0  # Deterministic
                }
            }
        )

        if response.status_code != 200:
            logger.error(f"Ollama API error: {response.status_code}")
            return GutInstinctMetrics(
                lambda1_semantic=0.0,
                spectral_fill=0.5,
                activation_variance=0.0,
                layer_eigenvalues=[],
                timestamp=time.time()
            )

        result = response.json()
        output_text = result.get("response", "")

        # Heuristic confidence metrics
        # 1. Output length (confident responses are often concise)
        output_length = len(output_text.split())
        length_confidence = 1.0 / (1.0 + 0.01 * output_length)  # Decay with length

        # 2. Hedging language detection
        hedges = ["maybe", "perhaps", "possibly", "might", "could", "uncertain", "unclear"]
        hedge_count = sum(1 for hedge in hedges if hedge in output_text.lower())
        hedge_confidence = 1.0 / (1.0 + 0.5 * hedge_count)

        # 3. Combined confidence score (proxy for λ₁)
        lambda1_proxy = (length_confidence + hedge_confidence) / 2.0

        # Spectral fill heuristic (how focused is the response?)
        # High specificity = high fill, vague = low fill
        specificity_keywords = ["specifically", "exactly", "precisely", "clearly"]
        vague_keywords = ["generally", "broadly", "various", "multiple"]
        specificity_score = sum(1 for kw in specificity_keywords if kw in output_text.lower())
        vague_score = sum(1 for kw in vague_keywords if kw in output_text.lower())
        spectral_fill_proxy = 0.5 + 0.1 * (specificity_score - vague_score)
        spectral_fill_proxy = np.clip(spectral_fill_proxy, 0.0, 1.0)

        logger.info(f"Heuristic gut instinct: λ₁={lambda1_proxy:.3f}, fill={spectral_fill_proxy:.3f}")

        return GutInstinctMetrics(
            lambda1_semantic=lambda1_proxy,
            spectral_fill=spectral_fill_proxy,
            activation_variance=length_confidence,  # Reuse as variance proxy
            layer_eigenvalues=[lambda1_proxy],  # Single value for heuristic
            timestamp=time.time()
        )

    def _compute_eigenvalues(self, return_full_spectrum: bool) -> GutInstinctMetrics:
        """
        Compute eigenvalues from captured activations.

        Method:
        1. Stack activations from layers 4-8
        2. Compute covariance matrix: Cov = (1/n) * X^T * X
        3. Eigendecomposition: Cov = V * Λ * V^T
        4. Extract λ₁ (largest eigenvalue) and spectral fill %
        """
        import time

        # Stack activations from all captured layers
        layer_acts = []
        for i in range(self.early_layers[0], self.early_layers[1] + 1):
            key = f'layer_{i}'
            if key in self.activations:
                acts = self.activations[key]
                # Shape: [batch=1, seq_len, hidden_dim]
                # Flatten to [seq_len, hidden_dim]
                acts_flat = acts.squeeze(0)
                layer_acts.append(acts_flat)

        if not layer_acts:
            logger.error("No activations captured!")
            return GutInstinctMetrics(
                lambda1_semantic=0.0,
                spectral_fill=0.0,
                activation_variance=0.0,
                layer_eigenvalues=[],
                timestamp=time.time()
            )

        # Concatenate along sequence dimension: [total_seq_len, hidden_dim]
        all_acts = torch.cat(layer_acts, dim=0)

        # Compute covariance matrix: [hidden_dim, hidden_dim]
        cov_matrix = torch.cov(all_acts.T)

        # Eigendecomposition
        eigenvalues = torch.linalg.eigvalsh(cov_matrix)  # Returns sorted ascending
        eigenvalues = torch.flip(eigenvalues, dims=[0])  # Sort descending
        eigenvalues = eigenvalues.cpu().numpy()

        # Extract metrics
        lambda1 = eigenvalues[0]
        eigenvalue_mean = np.mean(eigenvalues)
        spectral_fill = np.sum(eigenvalues > eigenvalue_mean) / len(eigenvalues)
        activation_var = all_acts.var().item()

        logger.info(f"Extracted eigenvalues: λ₁={lambda1:.3f}, fill={spectral_fill:.3f}, var={activation_var:.6f}")

        return GutInstinctMetrics(
            lambda1_semantic=float(lambda1),
            spectral_fill=float(spectral_fill),
            activation_variance=activation_var,
            layer_eigenvalues=eigenvalues.tolist() if return_full_spectrum else [float(lambda1)],
            timestamp=time.time()
        )

    async def send_to_esn_async(self, metrics: GutInstinctMetrics):
        """Send gut instinct metrics to Rust ESN via WebSocket."""
        try:
            async with websockets.connect(self.ws_url) as ws:
                message = {
                    "type": "SemanticEigenvalues",
                    "lambda1_semantic": metrics.lambda1_semantic,
                    "spectral_fill": metrics.spectral_fill,
                    "activation_variance": metrics.activation_variance,
                    "timestamp": metrics.timestamp
                }
                await ws.send(json.dumps(message))
                logger.info(f"Sent semantic eigenvalues to ESN: λ₁={metrics.lambda1_semantic:.3f}")
        except Exception as e:
            logger.error(f"Failed to send to ESN: {e}")

    def send_to_esn(self, metrics: GutInstinctMetrics):
        """Synchronous wrapper for send_to_esn_async."""
        asyncio.run(self.send_to_esn_async(metrics))


# --------------------------------------------------------------------------- #
# Example Usage and Testing
# --------------------------------------------------------------------------- #

def demo_gut_instinct_extraction():
    """Demonstrate gut instinct eigenvalue extraction."""
    print("=" * 70)
    print("Semantic Eigenvalue Extractor - Demo")
    print("=" * 70)

    # Initialize extractor (using heuristic fallback for now)
    extractor = SemanticEigenvalueExtractor(
        model_name="dolphin-mixtral:8x7b-v2.7",
        early_layers=(4, 8),
        max_tokens_sample=20,
        use_local_model=False  # Use Ollama API with heuristics
    )

    # Test prompts with different confidence levels
    test_prompts = [
        "What is 2 + 2?",  # High confidence expected
        "What is consciousness?",  # Medium confidence (complex)
        "Explain quantum gravity in simple terms",  # Low confidence (very hard)
    ]

    for prompt in test_prompts:
        print(f"\nPrompt: {prompt}")
        print("-" * 70)

        metrics = extractor.extract_gut_instinct(prompt)

        print(f"  λ₁ (semantic):        {metrics.lambda1_semantic:.4f}")
        print(f"  Spectral fill:        {metrics.spectral_fill:.2%}")
        print(f"  Activation variance:  {metrics.activation_variance:.6f}")

        # Interpret confidence
        if metrics.lambda1_semantic > 0.7:
            confidence = "HIGH"
        elif metrics.lambda1_semantic > 0.4:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"
        print(f"  → Confidence: {confidence}")

        # Send to ESN (if running)
        try:
            extractor.send_to_esn(metrics)
        except Exception as e:
            print(f"  (ESN not running: {e})")

    print("\n" + "=" * 70)
    print("Demo complete!")


if __name__ == "__main__":
    demo_gut_instinct_extraction()
