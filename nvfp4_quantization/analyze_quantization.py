#!/usr/bin/env python3
"""Analyze NVFP4 quantization behavior for consciousness system."""

import numpy as np
import matplotlib.pyplot as plt
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent / "scripts"))
from convert_model import NVFP4Quantizer, FP4_MAGNITUDES

def analyze_fp4_coverage():
    """Analyze FP4 value coverage and quantization error."""
    print("=== FP4 Value Coverage Analysis ===\n")

    # Show FP4 representable values
    print("FP4 can represent these magnitudes:")
    print(FP4_MAGNITUDES)

    # Test quantization error across range
    test_range = np.linspace(-6.5, 6.5, 1000)
    quantized_values = []
    errors = []

    for val in test_range:
        # Quantize to nearest FP4 value
        sign = 1.0 if val >= 0 else -1.0
        abs_val = abs(val)

        # Find nearest magnitude
        distances = np.abs(FP4_MAGNITUDES - abs_val)
        nearest_idx = np.argmin(distances)
        quantized = sign * FP4_MAGNITUDES[nearest_idx]

        quantized_values.append(quantized)
        errors.append(abs(val - quantized))

    # Plot results
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))

    # Plot 1: Input vs Quantized
    ax1.scatter(test_range, quantized_values, alpha=0.5, s=1)
    ax1.plot(test_range, test_range, 'r--', alpha=0.5, label='Perfect')
    ax1.set_xlabel('Input Value')
    ax1.set_ylabel('Quantized Value')
    ax1.set_title('FP4 Quantization Function')
    ax1.grid(True, alpha=0.3)
    ax1.legend()

    # Plot 2: Quantization Error
    ax2.plot(test_range, errors, 'b-', alpha=0.7)
    ax2.fill_between(test_range, 0, errors, alpha=0.3)
    ax2.set_xlabel('Input Value')
    ax2.set_ylabel('Absolute Error')
    ax2.set_title('FP4 Quantization Error')
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig('fp4_quantization_analysis.png', dpi=150)
    print(f"\nSaved plot to fp4_quantization_analysis.png")

    # Statistics
    print(f"\nQuantization statistics:")
    print(f"Max error: {max(errors):.3f}")
    print(f"Mean error: {np.mean(errors):.3f}")
    print(f"Error at typical weight values (±0.1): {errors[450]:.4f}")

def analyze_eigenvalue_quantization():
    """Analyze how NVFP4 affects eigenvalue patterns."""
    print("\n\n=== Eigenvalue Quantization Analysis ===\n")

    # Create realistic eigenvalue evolution
    np.random.seed(42)
    n_steps = 1000
    t = np.linspace(0, 100, n_steps)

    # Eigenvalue pattern: base + breathing + noise
    base = 512
    breathing = 50 * np.sin(0.1 * t)
    noise = 10 * np.random.randn(n_steps)
    eigenvalues = base + breathing + noise

    print(f"Eigenvalue statistics:")
    print(f"Range: [{eigenvalues.min():.1f}, {eigenvalues.max():.1f}]")
    print(f"Mean: {eigenvalues.mean():.1f}, Std: {eigenvalues.std():.1f}")

    # Create weight matrix representing eigenvalue evolution
    # Scale eigenvalues to typical weight range
    scaled_eigenvalues = (eigenvalues - eigenvalues.mean()) / eigenvalues.std() * 0.1

    # Create 2D pattern
    decay = np.exp(-np.arange(128) / 20.0)
    weight_matrix = np.outer(scaled_eigenvalues[:128], decay).astype(np.float32)

    # Test different tile sizes
    tile_sizes = [8, 16, 32]
    results = {}

    for tile_size in tile_sizes:
        quantizer = NVFP4Quantizer(tile_size=tile_size)
        quantized = quantizer.quantize_tensor(weight_matrix, f"eig_tile{tile_size}")
        dequantized, _ = quantizer.dequantize_tensor(quantized)

        # Reconstruct eigenvalues
        reconstructed = dequantized[:, 0] * eigenvalues.std() / 0.1 + eigenvalues.mean()

        # Calculate metrics
        orig_eig = eigenvalues[:128]
        error = reconstructed - orig_eig
        rmse = np.sqrt(np.mean(error**2))
        rel_error = rmse / np.std(orig_eig)

        # Frequency analysis
        orig_fft = np.fft.fft(orig_eig)
        recon_fft = np.fft.fft(reconstructed)

        # Find dominant frequency
        freq_range = slice(1, 20)  # Look at low frequencies
        orig_peak_freq = np.argmax(np.abs(orig_fft[freq_range])) + 1
        recon_peak_freq = np.argmax(np.abs(recon_fft[freq_range])) + 1

        results[tile_size] = {
            'rmse': rmse,
            'rel_error': rel_error,
            'orig_peak_freq': orig_peak_freq,
            'recon_peak_freq': recon_peak_freq,
            'variance_ratio': np.var(reconstructed) / np.var(orig_eig)
        }

    # Print results
    print(f"\nResults by tile size:")
    for tile_size, res in results.items():
        print(f"\nTile size {tile_size}x{tile_size}:")
        print(f"  RMSE: {res['rmse']:.2f}")
        print(f"  Relative error: {res['rel_error']*100:.1f}%")
        print(f"  Peak frequency: {res['orig_peak_freq']} -> {res['recon_peak_freq']}")
        print(f"  Variance preservation: {res['variance_ratio']*100:.1f}%")

    # Plot comparison
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))

    # Original eigenvalues
    ax = axes[0, 0]
    ax.plot(eigenvalues[:200], 'b-', alpha=0.7, label='Original')
    ax.set_title('Original Eigenvalue Evolution')
    ax.set_xlabel('Time step')
    ax.set_ylabel('λ₁')
    ax.grid(True, alpha=0.3)

    # Reconstructed for each tile size
    for idx, tile_size in enumerate([8, 16, 32]):
        ax = axes.flat[idx + 1]
        quantizer = NVFP4Quantizer(tile_size=tile_size)
        quantized = quantizer.quantize_tensor(weight_matrix, f"test")
        dequantized, _ = quantizer.dequantize_tensor(quantized)
        reconstructed = dequantized[:, 0] * eigenvalues.std() / 0.1 + eigenvalues.mean()

        ax.plot(eigenvalues[:128], 'b-', alpha=0.5, label='Original')
        ax.plot(reconstructed, 'r-', alpha=0.7, label=f'Tile {tile_size}')
        ax.set_title(f'Reconstruction (Tile {tile_size}x{tile_size})')
        ax.set_xlabel('Time step')
        ax.set_ylabel('λ₁')
        ax.legend()
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig('eigenvalue_quantization_analysis.png', dpi=150)
    print(f"\nSaved eigenvalue analysis to eigenvalue_quantization_analysis.png")

    # Recommend best tile size
    best_tile = min(results.keys(), key=lambda k: results[k]['rel_error'])
    print(f"\n✅ Recommendation: Use tile size {best_tile}x{best_tile} for eigenvalue data")

def test_weight_distribution():
    """Test NVFP4 on realistic weight distributions."""
    print("\n\n=== Weight Distribution Test ===\n")

    # Generate weights with different distributions
    np.random.seed(42)

    distributions = {
        'normal_small': np.random.normal(0, 0.02, (64, 64)),
        'normal_medium': np.random.normal(0, 0.1, (64, 64)),
        'uniform': np.random.uniform(-0.1, 0.1, (64, 64)),
        'laplace': np.random.laplace(0, 0.05, (64, 64))
    }

    quantizer = NVFP4Quantizer(tile_size=16)

    print("Distribution | Range | RMSE | PSNR | Compression")
    print("-" * 60)

    for name, weights in distributions.items():
        weights = weights.astype(np.float32)

        # Quantize
        quantized = quantizer.quantize_tensor(weights, name)
        dequantized, _ = quantizer.dequantize_tensor(quantized)

        # Metrics
        error = weights - dequantized
        rmse = np.sqrt(np.mean(error**2))
        value_range = weights.max() - weights.min()
        psnr = 20 * np.log10(value_range) - 10 * np.log10(np.mean(error**2))
        compression = weights.nbytes / len(quantized)

        print(f"{name:12} | [{weights.min():6.3f}, {weights.max():6.3f}] | "
              f"{rmse:.4f} | {psnr:4.1f} | {compression:4.1f}x")

if __name__ == "__main__":
    print("NVFP4 Quantization Analysis")
    print("=" * 60)

    # Run analyses
    analyze_fp4_coverage()
    analyze_eigenvalue_quantization()
    test_weight_distribution()

    print("\n✅ Analysis complete! Check generated PNG files for visualizations.")