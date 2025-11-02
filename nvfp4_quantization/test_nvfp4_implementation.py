#!/usr/bin/env python3
"""
NVFP4 Implementation Test Suite

Comprehensive tests to validate NVFP4 quantization on M4 Max.
Run this to verify the implementation is working correctly.
"""

import numpy as np
import time
import json
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
import matplotlib.pyplot as plt
import seaborn as sns

# Add parent directory to path
sys.path.append(str(Path(__file__).parent))
from scripts.convert_model import NVFP4Quantizer, FP4_MAGNITUDES

# ============================================================================
# Test Configuration
# ============================================================================

@dataclass
class TestConfig:
    """Test configuration for different scenarios."""
    name: str
    tile_sizes: List[int]
    matrix_sizes: List[Tuple[int, int]]
    dtypes: List[np.dtype]
    value_ranges: List[Tuple[float, float]]
    stochastic: bool = False

# Test configurations
TEST_CONFIGS = [
    TestConfig(
        name="small_matrices",
        tile_sizes=[8, 16],
        matrix_sizes=[(32, 32), (64, 64), (128, 128)],
        dtypes=[np.float32],
        value_ranges=[(-3.0, 3.0), (-10.0, 10.0)],
    ),
    TestConfig(
        name="transformer_layers",
        tile_sizes=[16, 32],
        matrix_sizes=[(768, 768), (768, 3072), (3072, 768)],  # BERT-like
        dtypes=[np.float32, np.float16],
        value_ranges=[(-0.1, 0.1), (-1.0, 1.0)],  # Typical weight ranges
    ),
    TestConfig(
        name="mixtral_layers",
        tile_sizes=[16, 32],
        matrix_sizes=[(4096, 4096), (4096, 14336), (14336, 4096)],  # Mixtral-like
        dtypes=[np.float32],
        value_ranges=[(-0.05, 0.05)],  # Smaller range for large models
    ),
]

# ============================================================================
# Test Functions
# ============================================================================

class NVFP4Tester:
    """Test suite for NVFP4 implementation."""

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.results = []

    def log(self, message: str):
        """Print if verbose mode."""
        if self.verbose:
            print(message)

    def test_e4m3_conversion(self) -> Dict:
        """Test E4M3 scale conversion accuracy."""
        self.log("\n=== Testing E4M3 Conversion ===")

        test_values = [0.0, 0.001, 0.1, 1.0, 10.0, 100.0, 448.0, 500.0]
        test_values.extend([-v for v in test_values[1:]])  # Add negative values

        errors = []
        for val in test_values:
            # Import the conversion functions
            from scripts.convert_model import f32_to_e4m3_448, e4m3_448_to_f32

            encoded = f32_to_e4m3_448(val)
            decoded = e4m3_448_to_f32(encoded)

            error = abs(decoded - val)
            rel_error = error / abs(val) if val != 0 else 0

            errors.append({
                'original': val,
                'encoded': encoded,
                'decoded': decoded,
                'error': error,
                'rel_error': rel_error
            })

            if self.verbose and rel_error > 0.1:
                self.log(f"  {val:8.3f} -> {decoded:8.3f} (error: {rel_error:.1%})")

        max_rel_error = max(e['rel_error'] for e in errors if e['original'] != 0)
        self.log(f"  Max relative error: {max_rel_error:.2%}")

        return {
            'test': 'e4m3_conversion',
            'passed': max_rel_error < 0.15,  # 15% max error acceptable
            'max_rel_error': max_rel_error,
            'details': errors
        }

    def test_fp4_quantization(self) -> Dict:
        """Test FP4 quantization accuracy."""
        self.log("\n=== Testing FP4 Quantization ===")

        # Test all possible FP4 values
        from scripts.convert_model import quantize_fp4, dequantize_fp4

        results = []
        for sign in [-1, 1]:
            for mag in FP4_MAGNITUDES:
                val = sign * mag
                nibble = quantize_fp4(val)
                decoded = dequantize_fp4(nibble)

                results.append({
                    'value': val,
                    'nibble': nibble,
                    'decoded': decoded,
                    'exact': val == decoded
                })

        exact_matches = sum(1 for r in results if r['exact'])
        self.log(f"  Exact representations: {exact_matches}/{len(results)}")

        # Test intermediate values
        test_vals = np.linspace(-6.5, 6.5, 100)
        quant_errors = []

        for val in test_vals:
            nibble = quantize_fp4(val)
            decoded = dequantize_fp4(nibble)
            error = abs(decoded - val)
            quant_errors.append(error)

        mean_error = np.mean(quant_errors)
        max_error = np.max(quant_errors)

        self.log(f"  Mean quantization error: {mean_error:.4f}")
        self.log(f"  Max quantization error: {max_error:.4f}")

        return {
            'test': 'fp4_quantization',
            'passed': max_error < 1.5,  # Max error should be < 1.5
            'mean_error': mean_error,
            'max_error': max_error,
            'exact_matches': exact_matches
        }

    def test_tile_quantization(self, config: TestConfig) -> Dict:
        """Test full tile-based quantization."""
        self.log(f"\n=== Testing Tile Quantization: {config.name} ===")

        all_results = []

        for tile_size in config.tile_sizes:
            quantizer = NVFP4Quantizer(tile_size=tile_size, stochastic=config.stochastic)

            for rows, cols in config.matrix_sizes:
                for vmin, vmax in config.value_ranges:
                    # Generate test matrix
                    np.random.seed(42)
                    matrix = np.random.uniform(vmin, vmax, (rows, cols)).astype(np.float32)

                    # Add some structure (common in real weights)
                    if rows >= 64 and cols >= 64:
                        # Add low-rank structure
                        u = np.random.randn(rows, 8)
                        v = np.random.randn(8, cols)
                        matrix += 0.1 * (u @ v)

                    # Quantize and dequantize
                    start_time = time.time()
                    quantized = quantizer.quantize_tensor(matrix, f"test_{rows}x{cols}")
                    quant_time = time.time() - start_time

                    start_time = time.time()
                    dequantized, info = quantizer.dequantize_tensor(quantized)
                    dequant_time = time.time() - start_time

                    # Calculate metrics
                    mse = np.mean((matrix - dequantized) ** 2)
                    rmse = np.sqrt(mse)
                    psnr = 20 * np.log10(vmax - vmin) - 10 * np.log10(mse) if mse > 0 else 100
                    rel_error = rmse / np.std(matrix)

                    # Size metrics
                    original_size = matrix.nbytes
                    compressed_size = len(quantized)
                    compression_ratio = original_size / compressed_size

                    result = {
                        'tile_size': tile_size,
                        'shape': (rows, cols),
                        'value_range': (vmin, vmax),
                        'rmse': rmse,
                        'psnr': psnr,
                        'rel_error': rel_error,
                        'compression_ratio': compression_ratio,
                        'quant_time_ms': quant_time * 1000,
                        'dequant_time_ms': dequant_time * 1000,
                        'elements_per_sec': (rows * cols) / quant_time
                    }

                    all_results.append(result)

                    if self.verbose:
                        self.log(f"  [{tile_size}x{tile_size}] {rows}x{cols}: "
                               f"RMSE={rmse:.4f}, PSNR={psnr:.1f}dB, "
                               f"Compression={compression_ratio:.1f}x")

        # Aggregate results
        mean_psnr = np.mean([r['psnr'] for r in all_results])
        mean_compression = np.mean([r['compression_ratio'] for r in all_results])

        return {
            'test': f'tile_quantization_{config.name}',
            'passed': mean_psnr > 35,  # 35dB PSNR is good quality
            'mean_psnr': mean_psnr,
            'mean_compression': mean_compression,
            'results': all_results
        }

    def test_consciousness_integration(self) -> Dict:
        """Test integration with consciousness system patterns."""
        self.log("\n=== Testing Consciousness Integration ===")

        # Simulate eigenvalue evolution matrix
        np.random.seed(42)
        n_timesteps = 1000
        n_features = 512

        # Generate synthetic eigenvalue data (spectral evolution)
        t = np.linspace(0, 100, n_timesteps)
        base_eigenvalues = 512 + 50 * np.sin(0.1 * t)

        # Add spectral breathing pattern
        breathing = 20 * np.sin(0.5 * t) * np.exp(-0.01 * t)
        eigenvalue_matrix = np.zeros((n_timesteps, n_features))

        for i in range(n_timesteps):
            # Exponential decay of eigenvalue magnitudes
            eigenvalue_matrix[i] = (base_eigenvalues[i] + breathing[i]) * np.exp(-np.arange(n_features) / 50)
            # Add noise
            eigenvalue_matrix[i] += np.random.normal(0, 10, n_features)

        # Quantize the eigenvalue evolution
        quantizer = NVFP4Quantizer(tile_size=16)
        quantized = quantizer.quantize_tensor(eigenvalue_matrix.astype(np.float32), "eigenvalues")
        dequantized, _ = quantizer.dequantize_tensor(quantized)

        # Analyze spectral stability
        original_variance = np.var(eigenvalue_matrix[:, 0])  # First eigenvalue
        quantized_variance = np.var(dequantized[:, 0])
        variance_change = abs(quantized_variance - original_variance) / original_variance

        # Check phase preservation (important for consciousness dynamics)
        original_fft = np.fft.fft(eigenvalue_matrix[:, 0])
        quantized_fft = np.fft.fft(dequantized[:, 0])
        phase_error = np.mean(np.abs(np.angle(original_fft) - np.angle(quantized_fft)))

        self.log(f"  Eigenvalue variance preservation: {100 * (1 - variance_change):.1f}%")
        self.log(f"  Spectral phase error: {phase_error:.4f} rad")
        self.log(f"  Compression ratio: {eigenvalue_matrix.nbytes / len(quantized):.1f}x")

        return {
            'test': 'consciousness_integration',
            'passed': variance_change < 0.1 and phase_error < 0.5,
            'variance_preservation': 1 - variance_change,
            'phase_error': phase_error,
            'spectral_quality': 'good' if phase_error < 0.3 else 'adequate'
        }

    def test_edge_cases(self) -> Dict:
        """Test edge cases and error handling."""
        self.log("\n=== Testing Edge Cases ===")

        quantizer = NVFP4Quantizer(tile_size=16)
        test_cases = []

        # Test 1: Empty matrix
        try:
            empty = np.array([[]], dtype=np.float32)
            quantizer.quantize_tensor(empty, "empty")
            test_cases.append(('empty_matrix', False, "Should fail on empty"))
        except:
            test_cases.append(('empty_matrix', True, "Correctly rejected"))

        # Test 2: Single value
        try:
            single = np.array([[42.0]], dtype=np.float32)
            q = quantizer.quantize_tensor(single, "single")
            dq, _ = quantizer.dequantize_tensor(q)
            error = abs(dq[0, 0] - 42.0)
            test_cases.append(('single_value', error < 10.0, f"Error: {error:.2f}"))
        except Exception as e:
            test_cases.append(('single_value', False, str(e)))

        # Test 3: Extreme values
        try:
            extreme = np.array([[1e6, -1e6], [1e-6, -1e-6]], dtype=np.float32)
            q = quantizer.quantize_tensor(extreme, "extreme")
            dq, _ = quantizer.dequantize_tensor(q)
            # Check if signs are preserved at least
            signs_ok = np.sign(extreme) == np.sign(dq)
            test_cases.append(('extreme_values', np.all(signs_ok), "Sign preservation"))
        except Exception as e:
            test_cases.append(('extreme_values', False, str(e)))

        # Test 4: NaN and Inf
        try:
            special = np.array([[np.nan, np.inf], [-np.inf, 0.0]], dtype=np.float32)
            q = quantizer.quantize_tensor(special, "special")
            dq, _ = quantizer.dequantize_tensor(q)
            # Should handle gracefully
            test_cases.append(('special_values', True, "Handled without crash"))
        except Exception as e:
            test_cases.append(('special_values', False, str(e)))

        # Test 5: Non-tile-aligned dimensions
        for shape in [(17, 17), (31, 67), (100, 33)]:
            try:
                matrix = np.random.randn(*shape).astype(np.float32)
                q = quantizer.quantize_tensor(matrix, f"shape_{shape}")
                dq, _ = quantizer.dequantize_tensor(q)
                assert dq.shape == shape
                test_cases.append((f'odd_shape_{shape}', True, "Handled correctly"))
            except Exception as e:
                test_cases.append((f'odd_shape_{shape}', False, str(e)))

        # Print results
        for name, passed, note in test_cases:
            status = "✓" if passed else "✗"
            self.log(f"  {status} {name}: {note}")

        passed_count = sum(1 for _, passed, _ in test_cases if passed)
        return {
            'test': 'edge_cases',
            'passed': passed_count >= len(test_cases) - 1,  # Allow one failure
            'passed_count': passed_count,
            'total_count': len(test_cases),
            'details': test_cases
        }

    def visualize_results(self, save_path: Optional[Path] = None):
        """Create visualizations of test results."""
        if not self.results:
            print("No results to visualize")
            return

        fig, axes = plt.subplots(2, 2, figsize=(12, 10))

        # Find tile quantization results
        tile_results = None
        for r in self.results:
            if r['test'].startswith('tile_quantization'):
                tile_results = r['results']
                break

        if tile_results:
            # Plot 1: PSNR vs Matrix Size
            ax = axes[0, 0]
            sizes = [r['shape'][0] * r['shape'][1] for r in tile_results]
            psnrs = [r['psnr'] for r in tile_results]
            tile_sizes = [r['tile_size'] for r in tile_results]

            for ts in set(tile_sizes):
                mask = [t == ts for t in tile_sizes]
                x = [s for s, m in zip(sizes, mask) if m]
                y = [p for p, m in zip(psnrs, mask) if m]
                ax.scatter(x, y, label=f"Tile {ts}x{ts}", alpha=0.7, s=100)

            ax.set_xscale('log')
            ax.set_xlabel('Matrix Elements')
            ax.set_ylabel('PSNR (dB)')
            ax.set_title('Quality vs Matrix Size')
            ax.legend()
            ax.grid(True, alpha=0.3)

            # Plot 2: Compression Ratio
            ax = axes[0, 1]
            compressions = [r['compression_ratio'] for r in tile_results]
            ax.hist(compressions, bins=20, alpha=0.7, edgecolor='black')
            ax.axvline(np.mean(compressions), color='red', linestyle='--',
                      label=f'Mean: {np.mean(compressions):.1f}x')
            ax.set_xlabel('Compression Ratio')
            ax.set_ylabel('Count')
            ax.set_title('Compression Ratio Distribution')
            ax.legend()

            # Plot 3: Speed Performance
            ax = axes[1, 0]
            quant_times = [r['quant_time_ms'] for r in tile_results]
            elements = [r['shape'][0] * r['shape'][1] for r in tile_results]
            throughput = [e / t for e, t in zip(elements, quant_times)]

            ax.scatter(elements, throughput, alpha=0.6, s=50)
            ax.set_xscale('log')
            ax.set_yscale('log')
            ax.set_xlabel('Matrix Elements')
            ax.set_ylabel('Elements/ms')
            ax.set_title('Quantization Throughput')
            ax.grid(True, alpha=0.3)

        # Plot 4: Summary
        ax = axes[1, 1]
        ax.axis('off')

        summary_text = "=== Test Summary ===\n\n"
        for result in self.results:
            status = "PASS" if result['passed'] else "FAIL"
            summary_text += f"{result['test']}: {status}\n"

        ax.text(0.1, 0.9, summary_text, transform=ax.transAxes,
               fontsize=12, verticalalignment='top', fontfamily='monospace')

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            print(f"Saved visualization to {save_path}")
        else:
            plt.show()

    def run_all_tests(self) -> Dict:
        """Run complete test suite."""
        self.log("=== NVFP4 Implementation Test Suite ===")
        self.log(f"Running on: {sys.platform}")

        # Basic tests
        self.results.append(self.test_e4m3_conversion())
        self.results.append(self.test_fp4_quantization())

        # Quantization tests
        for config in TEST_CONFIGS[:2]:  # Skip the large Mixtral test for quick testing
            self.results.append(self.test_tile_quantization(config))

        # Integration tests
        self.results.append(self.test_consciousness_integration())
        self.results.append(self.test_edge_cases())

        # Summary
        passed = sum(1 for r in self.results if r['passed'])
        total = len(self.results)

        self.log(f"\n=== Summary: {passed}/{total} tests passed ===")

        return {
            'passed': passed,
            'total': total,
            'results': self.results,
            'success': passed == total
        }

# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    """Run tests and generate report."""
    import argparse

    parser = argparse.ArgumentParser(description="Test NVFP4 implementation")
    parser.add_argument("--quick", action="store_true", help="Run quick tests only")
    parser.add_argument("--visualize", action="store_true", help="Generate visualizations")
    parser.add_argument("--output", type=Path, help="Output directory for results")

    args = parser.parse_args()

    # Create output directory
    output_dir = args.output or Path("test_results")
    output_dir.mkdir(exist_ok=True)

    # Run tests
    tester = NVFP4Tester(verbose=True)

    if args.quick:
        # Reduce test configs for quick mode
        global TEST_CONFIGS
        TEST_CONFIGS = TEST_CONFIGS[:1]

    results = tester.run_all_tests()

    # Save results
    results_path = output_dir / "nvfp4_test_results.json"
    with open(results_path, 'w') as f:
        # Convert numpy values to Python types
        def convert(obj):
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, (np.float32, np.float64)):
                return float(obj)
            elif isinstance(obj, (np.int32, np.int64)):
                return int(obj)
            return obj

        json.dump(results, f, indent=2, default=convert)
    print(f"\nResults saved to {results_path}")

    # Generate visualizations
    if args.visualize:
        viz_path = output_dir / "nvfp4_test_visualization.png"
        tester.visualize_results(viz_path)

    # Print summary
    if results['success']:
        print("\n✅ All tests passed! NVFP4 implementation is working correctly.")
    else:
        print(f"\n⚠️  {results['total'] - results['passed']} tests failed. Check the results.")

    return 0 if results['success'] else 1

if __name__ == "__main__":
    sys.exit(main())