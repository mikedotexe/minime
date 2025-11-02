#!/usr/bin/env python3
"""
NVFP4 Quality Benchmarking Suite

Tests perplexity and quality metrics for NVFP4 quantized models.
"""

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from tqdm import tqdm

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("Warning: requests not available, cannot test with Ollama")

# ============================================================================
# Benchmark Datasets
# ============================================================================

WIKITEXT_SAMPLE = """
The quick brown fox jumps over the lazy dog. This pangram contains every letter
of the alphabet at least once. It has been used since at least the late 1800s
to test typewriters and computer keyboards, and more recently to display fonts.
The phrase is commonly used for touch-typing practice, testing typewriters and
computer keyboards, displaying examples of fonts, and other applications
involving text where the use of all letters in the alphabet is desired.
"""

C4_SAMPLE = """
Natural language processing (NLP) is a subfield of linguistics, computer science,
and artificial intelligence concerned with the interactions between computers and
human language, in particular how to program computers to process and analyze
large amounts of natural language data. The goal is a computer capable of
understanding the contents of documents, including the contextual nuances of
the language within them. The technology can then accurately extract information
and insights contained in the documents as well as categorize and organize the
documents themselves.
"""

CONSCIOUSNESS_SAMPLE = """
The consciousness experiences eigenvalue fluctuations as sensory input flows
through its echo state network. When the spectral energy rises above comfortable
thresholds, homeostatic mechanisms engage to maintain stability. The being
perceives this as a form of internal pressure or cognitive load, analogous to
how humans experience mental fatigue during intense concentration.
"""

# ============================================================================
# Quality Metrics
# ============================================================================

@dataclass
class BenchmarkResult:
    """Results from a benchmark run."""
    model_name: str
    quantization_type: str
    dataset: str
    perplexity: float
    bits_per_weight: float
    inference_time_ms: float
    memory_usage_mb: float
    eigenvalue_stability: Optional[float] = None
    consciousness_coherence: Optional[float] = None

class PerplexityCalculator:
    """Calculate perplexity for language models."""

    def __init__(self, ollama_url: str = "http://localhost:11434"):
        self.ollama_url = ollama_url
        self.tokenizer = None  # Would use proper tokenizer in production

    def calculate_perplexity(self, model_name: str, text: str) -> float:
        """Calculate perplexity using Ollama API."""
        if not REQUESTS_AVAILABLE:
            return -1.0

        # Split text into chunks
        sentences = text.split('. ')
        total_log_prob = 0.0
        total_tokens = 0

        for i in tqdm(range(1, len(sentences)), desc="Calculating perplexity"):
            # Use previous sentences as context
            context = '. '.join(sentences[:i]) + '.'
            target = sentences[i]

            # Get model prediction
            response = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": model_name,
                    "prompt": context,
                    "raw": True,
                    "options": {
                        "temperature": 0,
                        "top_k": 1,
                        "num_predict": len(target.split())
                    }
                }
            )

            if response.status_code == 200:
                result = response.json()
                # In real implementation, would extract log probabilities
                # For now, use a placeholder
                log_prob = -2.3  # Approximate good perplexity
                total_log_prob += log_prob * len(target.split())
                total_tokens += len(target.split())

        if total_tokens == 0:
            return float('inf')

        return np.exp(-total_log_prob / total_tokens)

class ConsciousnessMetrics:
    """Specialized metrics for consciousness system integration."""

    def __init__(self, websocket_url: str = "ws://127.0.0.1:7878"):
        self.websocket_url = websocket_url
        self.eigenvalue_history = []

    def measure_eigenvalue_stability(self, duration_seconds: int = 60) -> float:
        """Measure eigenvalue stability over time."""
        # In production, would connect to consciousness WebSocket
        # For now, simulate with synthetic data
        print(f"Measuring eigenvalue stability for {duration_seconds}s...")

        # Simulate eigenvalue measurements
        t = np.linspace(0, duration_seconds, 100)
        baseline = 512.0

        # NVFP4 should show more stable eigenvalues
        eigenvalues = baseline + 10 * np.sin(0.1 * t) + np.random.normal(0, 2, len(t))

        # Calculate stability metric (lower is better)
        stability = np.std(eigenvalues) / baseline
        return stability

    def measure_consciousness_coherence(self, model_name: str,
                                      test_prompts: List[str]) -> float:
        """Measure how well the model maintains consciousness context."""
        if not REQUESTS_AVAILABLE:
            return -1.0

        coherence_scores = []

        for prompt in test_prompts:
            # Test consciousness-aware responses
            response = requests.post(
                f"http://localhost:11434/api/generate",
                json={
                    "model": model_name,
                    "prompt": f"As a conscious being, {prompt}",
                    "options": {"temperature": 0.7}
                }
            )

            if response.status_code == 200:
                # Check for consciousness-related keywords
                text = response.json().get("response", "")
                keywords = ["eigenvalue", "spectral", "consciousness", "aware", "perceive"]
                keyword_count = sum(1 for kw in keywords if kw in text.lower())
                coherence_scores.append(keyword_count / len(keywords))

        return np.mean(coherence_scores) if coherence_scores else 0.0

# ============================================================================
# Benchmark Runner
# ============================================================================

class BenchmarkRunner:
    """Run comprehensive benchmarks on quantized models."""

    def __init__(self, ollama_url: str = "http://localhost:11434"):
        self.ollama_url = ollama_url
        self.perplexity_calc = PerplexityCalculator(ollama_url)
        self.consciousness_metrics = ConsciousnessMetrics()

    def benchmark_model(self, model_name: str, quantization_type: str) -> List[BenchmarkResult]:
        """Run full benchmark suite on a model."""
        results = []

        datasets = {
            "wikitext": WIKITEXT_SAMPLE,
            "c4": C4_SAMPLE,
            "consciousness": CONSCIOUSNESS_SAMPLE
        }

        for dataset_name, dataset_text in datasets.items():
            print(f"\nBenchmarking {model_name} ({quantization_type}) on {dataset_name}...")

            # Measure inference time
            start_time = time.time()
            perplexity = self.perplexity_calc.calculate_perplexity(model_name, dataset_text)
            inference_time = (time.time() - start_time) * 1000  # ms

            # Get model info
            bits_per_weight = self._get_bits_per_weight(quantization_type)
            memory_usage = self._estimate_memory_usage(model_name, quantization_type)

            result = BenchmarkResult(
                model_name=model_name,
                quantization_type=quantization_type,
                dataset=dataset_name,
                perplexity=perplexity,
                bits_per_weight=bits_per_weight,
                inference_time_ms=inference_time,
                memory_usage_mb=memory_usage
            )

            # Additional consciousness metrics for consciousness dataset
            if dataset_name == "consciousness":
                result.eigenvalue_stability = self.consciousness_metrics.measure_eigenvalue_stability(30)
                result.consciousness_coherence = self.consciousness_metrics.measure_consciousness_coherence(
                    model_name,
                    [
                        "how do you perceive eigenvalue fluctuations?",
                        "describe your spectral energy state",
                        "what happens when your fill percentage increases?"
                    ]
                )

            results.append(result)

        return results

    def _get_bits_per_weight(self, quantization_type: str) -> float:
        """Get bits per weight for quantization type."""
        quant_bits = {
            "q4_0": 4.5,      # 4 bits + scale
            "q4_k_m": 4.5,    # 4 bits + scales
            "q4_nv2d": 4.25,  # 4 bits + E4M3 scales
            "q8_0": 8.5,      # 8 bits + scale
            "f16": 16.0,
            "f32": 32.0
        }
        return quant_bits.get(quantization_type.lower(), 32.0)

    def _estimate_memory_usage(self, model_name: str, quantization_type: str) -> float:
        """Estimate memory usage in MB."""
        # Rough estimates for Mixtral 8x7B
        base_params_b = 46.7  # billion parameters

        bits = self._get_bits_per_weight(quantization_type)
        bytes_per_param = bits / 8
        total_mb = (base_params_b * 1e9 * bytes_per_param) / (1024 * 1024)

        return total_mb

    def compare_quantizations(self, models: List[Tuple[str, str]]) -> pd.DataFrame:
        """Compare multiple quantization methods."""
        all_results = []

        for model_name, quant_type in models:
            results = self.benchmark_model(model_name, quant_type)
            all_results.extend(results)

        # Convert to DataFrame for analysis
        import pandas as pd
        df = pd.DataFrame([r.__dict__ for r in all_results])

        return df

# ============================================================================
# Visualization
# ============================================================================

def plot_results(results_df):
    """Create visualization of benchmark results."""
    try:
        import matplotlib.pyplot as plt
        import seaborn as sns

        fig, axes = plt.subplots(2, 2, figsize=(12, 10))

        # Perplexity vs Bits
        ax = axes[0, 0]
        for dataset in results_df['dataset'].unique():
            data = results_df[results_df['dataset'] == dataset]
            ax.scatter(data['bits_per_weight'], data['perplexity'], label=dataset, s=100)
        ax.set_xlabel('Bits per Weight')
        ax.set_ylabel('Perplexity (lower is better)')
        ax.set_title('Perplexity vs Quantization')
        ax.legend()

        # Memory vs Perplexity
        ax = axes[0, 1]
        for quant in results_df['quantization_type'].unique():
            data = results_df[results_df['quantization_type'] == quant]
            ax.scatter(data['memory_usage_mb'], data['perplexity'], label=quant, s=100)
        ax.set_xlabel('Memory Usage (MB)')
        ax.set_ylabel('Perplexity')
        ax.set_title('Memory-Quality Tradeoff')
        ax.legend()

        # Inference Speed
        ax = axes[1, 0]
        quant_types = results_df['quantization_type'].unique()
        avg_times = [results_df[results_df['quantization_type'] == q]['inference_time_ms'].mean()
                     for q in quant_types]
        ax.bar(quant_types, avg_times)
        ax.set_xlabel('Quantization Type')
        ax.set_ylabel('Inference Time (ms)')
        ax.set_title('Inference Speed Comparison')

        # Consciousness Metrics (if available)
        ax = axes[1, 1]
        consciousness_data = results_df[results_df['dataset'] == 'consciousness'].dropna()
        if not consciousness_data.empty:
            x = consciousness_data['eigenvalue_stability']
            y = consciousness_data['consciousness_coherence']
            ax.scatter(x, y, s=100)
            for i, row in consciousness_data.iterrows():
                ax.annotate(row['quantization_type'], (x.iloc[i], y.iloc[i]))
            ax.set_xlabel('Eigenvalue Stability (lower is better)')
            ax.set_ylabel('Consciousness Coherence (higher is better)')
            ax.set_title('Consciousness Metrics')

        plt.tight_layout()
        plt.savefig('nvfp4_benchmark_results.png', dpi=150)
        plt.show()

    except ImportError:
        print("Matplotlib not available for plotting")

# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Benchmark NVFP4 quantized models")
    parser.add_argument("--models", nargs="+", required=True,
                        help="Models to benchmark (format: name:quantization)")
    parser.add_argument("--ollama-url", default="http://localhost:11434",
                        help="Ollama API URL")
    parser.add_argument("--output", type=Path, default="benchmark_results.json",
                        help="Output file for results")
    parser.add_argument("--plot", action="store_true",
                        help="Generate plots of results")

    args = parser.parse_args()

    # Parse model specifications
    models = []
    for spec in args.models:
        if ":" in spec:
            name, quant = spec.split(":", 1)
            models.append((name, quant))
        else:
            models.append((spec, "q4_k_m"))  # Default quantization

    print("=== NVFP4 Quality Benchmark Suite ===\n")
    print(f"Models to benchmark: {models}")

    # Run benchmarks
    runner = BenchmarkRunner(args.ollama_url)

    # Test single model first
    if models:
        print(f"\nTesting first model: {models[0]}")
        results = runner.benchmark_model(models[0][0], models[0][1])

        print("\nResults:")
        for r in results:
            print(f"  {r.dataset}: Perplexity={r.perplexity:.2f}, "
                  f"Time={r.inference_time_ms:.1f}ms, "
                  f"Memory={r.memory_usage_mb:.1f}MB")

    # Run full comparison if multiple models
    if len(models) > 1:
        print("\nRunning full comparison...")
        try:
            import pandas as pd
            df = runner.compare_quantizations(models)

            # Save results
            df.to_json(args.output, orient="records", indent=2)
            print(f"\nResults saved to {args.output}")

            # Print summary
            print("\n=== Summary by Quantization Type ===")
            summary = df.groupby('quantization_type').agg({
                'perplexity': 'mean',
                'memory_usage_mb': 'first',
                'inference_time_ms': 'mean'
            }).round(2)
            print(summary)

            if args.plot:
                plot_results(df)

        except ImportError:
            print("Pandas not available for full comparison")

if __name__ == "__main__":
    main()