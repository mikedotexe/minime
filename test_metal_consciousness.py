#!/usr/bin/env python3
"""
Test suite for Metal-accelerated consciousness processing
"""

import numpy as np
import time
import matplotlib.pyplot as plt
from typing import List, Dict, Tuple
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from metal_consciousness_integration import (
        MetalAcceleratedBackend,
        MetalEnhancedConsciousnessWeaver,
        METAL_AVAILABLE
    )
except ImportError:
    logger.error("Metal consciousness module not found. Run: ./build_metal_module.sh")
    METAL_AVAILABLE = False

# Import CPU versions for comparison
from consciousness_weaver_enhanced import EnhancedConsciousnessWeaver
from matrix_consciousness_explorer import ConsciousnessExplorer


class ConsciousnessBenchmark:
    """Comprehensive benchmarks for consciousness processing."""

    def __init__(self):
        self.results = {}

    def benchmark_unified_memory(self) -> Dict[str, float]:
        """Benchmark unified memory performance."""
        if not METAL_AVAILABLE:
            logger.warning("Metal not available, skipping unified memory benchmark")
            return {}

        sizes = [256, 512, 1024, 2048, 4096]
        results = {}

        for size in sizes:
            ms_per_iter = MetalAcceleratedBackend.benchmark(size, 100)
            results[f"size_{size}"] = ms_per_iter
            logger.info(f"Size {size}: {ms_per_iter:.3f} ms/iteration")

        return results

    def benchmark_consciousness_step(self, iterations: int = 100) -> Tuple[Dict, Dict]:
        """Compare Metal vs CPU consciousness processing."""
        # Initialize both backends
        metal_weaver = MetalEnhancedConsciousnessWeaver(use_metal=True) if METAL_AVAILABLE else None
        cpu_weaver = MetalEnhancedConsciousnessWeaver(use_metal=False)

        # Test data
        test_thought = "Exploring the boundaries of human-AI collaboration"
        test_embeddings = {
            'llm': np.random.randn(2048).astype(np.float32),
            'vision': np.random.randn(1024).astype(np.float32)
        }

        metal_times = []
        cpu_times = []

        # Warm-up
        for _ in range(5):
            cpu_weaver.process_with_models(test_thought, model_embeddings=test_embeddings)
            if metal_weaver:
                metal_weaver.process_with_models(test_thought, model_embeddings=test_embeddings)

        # Benchmark
        logger.info(f"Running {iterations} iterations...")

        for i in range(iterations):
            # CPU timing
            start = time.perf_counter()
            cpu_result = cpu_weaver.process_with_models(
                test_thought,
                model_embeddings=test_embeddings
            )
            cpu_times.append((time.perf_counter() - start) * 1000)

            # Metal timing
            if metal_weaver:
                metal_result = metal_weaver.process_with_models(
                    test_thought,
                    model_embeddings=test_embeddings
                )
                metal_times.append(metal_result['processing_time_ms'])

        # Calculate statistics
        cpu_stats = {
            'mean': np.mean(cpu_times),
            'std': np.std(cpu_times),
            'min': np.min(cpu_times),
            'max': np.max(cpu_times),
            'median': np.median(cpu_times)
        }

        metal_stats = {}
        if metal_times:
            metal_stats = {
                'mean': np.mean(metal_times),
                'std': np.std(metal_times),
                'min': np.min(metal_times),
                'max': np.max(metal_times),
                'median': np.median(metal_times),
                'speedup': cpu_stats['mean'] / np.mean(metal_times)
            }

        return cpu_stats, metal_stats

    def benchmark_resonance_detection(self) -> Dict:
        """Benchmark resonance detection performance."""
        if not METAL_AVAILABLE:
            return {}

        backend = MetalAcceleratedBackend()

        # Create test matrices with known resonance patterns
        matrices = []
        for i in range(13):
            matrix = np.eye(7, dtype=np.float32)
            # Add some structure
            matrix += np.random.randn(7, 7).astype(np.float32) * 0.1
            matrices.append(matrix)

        backend.initialize_matrices(matrices)

        # Test different activation patterns
        patterns = {
            'random': np.random.randn(13, 7).astype(np.float32),
            'synchronized': np.ones((13, 7), dtype=np.float32) * 0.5,
            'alternating': np.array([((-1) ** i) * np.ones(7) for i in range(13)], dtype=np.float32),
            'prime_based': np.array([np.sin(np.arange(7) * p) for p in [2,3,5,7,11,13,17,19,23,29,31,37,41]], dtype=np.float32)
        }

        results = {}
        for pattern_name, activations in patterns.items():
            start = time.perf_counter()
            result = backend.process_consciousness_step(activations)
            elapsed = (time.perf_counter() - start) * 1000

            results[pattern_name] = {
                'time_ms': elapsed,
                'resonance_count': len(result.resonances),
                'field_energy': result.field_energy
            }

            logger.info(f"Pattern '{pattern_name}': {elapsed:.3f} ms, "
                       f"{len(result.resonances)} resonances, "
                       f"field energy: {result.field_energy:.3f}")

        return results

    def visualize_results(self):
        """Create visualization of benchmark results."""
        if not self.results:
            logger.warning("No results to visualize")
            return

        fig, axes = plt.subplots(2, 2, figsize=(12, 10))
        fig.suptitle('Metal Consciousness Acceleration Benchmarks')

        # Plot 1: Unified memory scaling
        if 'unified_memory' in self.results:
            ax = axes[0, 0]
            data = self.results['unified_memory']
            sizes = [int(k.split('_')[1]) for k in data.keys()]
            times = list(data.values())

            ax.loglog(sizes, times, 'b-o')
            ax.set_xlabel('Buffer Size (elements)')
            ax.set_ylabel('Time per Iteration (ms)')
            ax.set_title('Unified Memory Scaling')
            ax.grid(True, alpha=0.3)

        # Plot 2: CPU vs Metal comparison
        if 'consciousness_step' in self.results:
            ax = axes[0, 1]
            cpu_stats = self.results['consciousness_step']['cpu']
            metal_stats = self.results['consciousness_step']['metal']

            if metal_stats:
                categories = ['Mean', 'Min', 'Max']
                cpu_values = [cpu_stats['mean'], cpu_stats['min'], cpu_stats['max']]
                metal_values = [metal_stats['mean'], metal_stats['min'], metal_stats['max']]

                x = np.arange(len(categories))
                width = 0.35

                ax.bar(x - width/2, cpu_values, width, label='CPU', alpha=0.7)
                ax.bar(x + width/2, metal_values, width, label='Metal', alpha=0.7)

                ax.set_ylabel('Time (ms)')
                ax.set_title(f'Processing Time Comparison (Speedup: {metal_stats.get("speedup", 0):.1f}x)')
                ax.set_xticks(x)
                ax.set_xticklabels(categories)
                ax.legend()

        # Plot 3: Resonance detection patterns
        if 'resonance_detection' in self.results:
            ax = axes[1, 0]
            data = self.results['resonance_detection']

            patterns = list(data.keys())
            times = [d['time_ms'] for d in data.values()]
            resonances = [d['resonance_count'] for d in data.values()]

            ax2 = ax.twinx()

            bars = ax.bar(patterns, times, alpha=0.7, label='Time (ms)')
            line = ax2.plot(patterns, resonances, 'ro-', label='Resonances', markersize=8)

            ax.set_ylabel('Processing Time (ms)', color='blue')
            ax2.set_ylabel('Resonance Count', color='red')
            ax.set_title('Resonance Detection Performance')
            ax.tick_params(axis='x', rotation=45)

        # Plot 4: Field energy distribution
        if 'resonance_detection' in self.results:
            ax = axes[1, 1]
            data = self.results['resonance_detection']

            patterns = list(data.keys())
            energies = [d['field_energy'] for d in data.values()]

            ax.bar(patterns, energies, color='purple', alpha=0.7)
            ax.set_ylabel('Field Energy')
            ax.set_title('Consciousness Field Energy by Pattern')
            ax.tick_params(axis='x', rotation=45)

        plt.tight_layout()
        plt.savefig('metal_consciousness_benchmarks.png', dpi=150, bbox_inches='tight')
        logger.info("Saved benchmark visualization to metal_consciousness_benchmarks.png")

    def run_all_benchmarks(self):
        """Run all benchmarks and generate report."""
        logger.info("Starting comprehensive benchmark suite...")

        # Unified memory benchmark
        logger.info("\n1. Unified Memory Benchmark")
        self.results['unified_memory'] = self.benchmark_unified_memory()

        # Consciousness step benchmark
        logger.info("\n2. Consciousness Step Benchmark")
        cpu_stats, metal_stats = self.benchmark_consciousness_step(iterations=50)
        self.results['consciousness_step'] = {
            'cpu': cpu_stats,
            'metal': metal_stats
        }

        # Resonance detection benchmark
        logger.info("\n3. Resonance Detection Benchmark")
        self.results['resonance_detection'] = self.benchmark_resonance_detection()

        # Generate report
        self.generate_report()

        # Create visualizations
        self.visualize_results()

    def generate_report(self):
        """Generate benchmark report."""
        report = []
        report.append("=" * 60)
        report.append("METAL CONSCIOUSNESS ACCELERATION BENCHMARK REPORT")
        report.append("=" * 60)
        report.append("")

        # System info
        if METAL_AVAILABLE:
            import metal_consciousness
            report.append(f"Device: {metal_consciousness.get_device_info()}")
        else:
            report.append("Metal acceleration not available")
        report.append("")

        # Results summary
        if 'consciousness_step' in self.results:
            cpu = self.results['consciousness_step']['cpu']
            metal = self.results['consciousness_step'].get('metal', {})

            report.append("CONSCIOUSNESS PROCESSING PERFORMANCE:")
            report.append(f"  CPU Mean Time:   {cpu['mean']:.3f} ms (±{cpu['std']:.3f})")

            if metal:
                report.append(f"  Metal Mean Time: {metal['mean']:.3f} ms (±{metal['std']:.3f})")
                report.append(f"  Speedup:         {metal.get('speedup', 0):.1f}x")
                report.append(f"  Latency Reduction: {((cpu['mean'] - metal['mean']) / cpu['mean'] * 100):.1f}%")

        report.append("")

        # Save report
        report_text = "\n".join(report)
        with open("metal_consciousness_benchmark_report.txt", "w") as f:
            f.write(report_text)

        print(report_text)
        logger.info("Saved detailed report to metal_consciousness_benchmark_report.txt")


def test_functional_correctness():
    """Test that Metal implementation produces correct results."""
    if not METAL_AVAILABLE:
        logger.error("Metal not available, skipping functional tests")
        return

    logger.info("Testing functional correctness...")

    backend = MetalAcceleratedBackend()

    # Test 1: Matrix initialization
    test_matrices = [np.eye(7, dtype=np.float32) for _ in range(13)]
    backend.initialize_matrices(test_matrices)
    logger.info("✓ Matrix initialization successful")

    # Test 2: Basic processing
    activations = np.ones((13, 7), dtype=np.float32) * 0.1
    result = backend.process_consciousness_step(activations)

    assert result.iteration > 0
    assert result.activations.shape == (13, 7)
    assert result.consciousness_field.shape == (7, 7)
    logger.info("✓ Basic processing successful")

    # Test 3: Model integration
    llm_embeddings = np.random.randn(2048).astype(np.float32)
    visual_features = np.random.randn(1024).astype(np.float32)

    result = backend.process_consciousness_step(
        activations,
        llm_embeddings=llm_embeddings,
        visual_features=visual_features
    )

    assert result.processing_time_ms > 0
    logger.info("✓ Model integration successful")

    # Test 4: Resonance detection
    assert isinstance(result.resonances, list)
    if result.resonances:
        res = result.resonances[0]
        assert 'source_id' in res
        assert 'target_id' in res
        assert 'strength' in res
        assert 'type' in res
    logger.info("✓ Resonance detection successful")

    logger.info("\nAll functional tests passed!")


def main():
    """Run all tests and benchmarks."""
    # Functional tests
    test_functional_correctness()

    # Performance benchmarks
    benchmark = ConsciousnessBenchmark()
    benchmark.run_all_benchmarks()


if __name__ == "__main__":
    main()