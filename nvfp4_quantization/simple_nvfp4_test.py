#!/usr/bin/env python3
"""Simple NVFP4 test to validate core functionality."""

import numpy as np
import sys
from pathlib import Path

# Add scripts to path
sys.path.append(str(Path(__file__).parent / "scripts"))
from convert_model import NVFP4Quantizer, f32_to_e4m3_448, e4m3_448_to_f32

def test_basic_quantization():
    """Test basic 2D matrix quantization."""
    print("=== Basic NVFP4 Quantization Test ===\n")

    # Create a simple test matrix
    np.random.seed(42)
    test_matrix = np.random.randn(64, 64).astype(np.float32)

    # Scale to reasonable range
    test_matrix = test_matrix * 0.1  # Typical weight range

    print(f"Test matrix: {test_matrix.shape}")
    print(f"Value range: [{test_matrix.min():.3f}, {test_matrix.max():.3f}]")
    print(f"Mean: {test_matrix.mean():.3f}, Std: {test_matrix.std():.3f}")

    # Quantize
    quantizer = NVFP4Quantizer(tile_size=16, stochastic=False)
    quantized = quantizer.quantize_tensor(test_matrix, "test")

    # Dequantize
    dequantized, info = quantizer.dequantize_tensor(quantized)

    # Calculate metrics
    error = test_matrix - dequantized
    mse = np.mean(error ** 2)
    rmse = np.sqrt(mse)
    psnr = 20 * np.log10(test_matrix.max() - test_matrix.min()) - 10 * np.log10(mse)

    # Size comparison
    original_size = test_matrix.nbytes
    compressed_size = len(quantized)
    compression_ratio = original_size / compressed_size

    print(f"\n=== Results ===")
    print(f"Original size: {original_size} bytes")
    print(f"Compressed size: {compressed_size} bytes")
    print(f"Compression ratio: {compression_ratio:.1f}x")
    print(f"RMSE: {rmse:.4f}")
    print(f"PSNR: {psnr:.1f} dB")
    print(f"Max absolute error: {np.abs(error).max():.4f}")

    # Show some sample values
    print(f"\n=== Sample Values (first 5x5) ===")
    print("Original:")
    print(test_matrix[:5, :5])
    print("\nDequantized:")
    print(dequantized[:5, :5])

    # Test E4M3 scale preservation
    print(f"\n=== E4M3 Scale Test ===")
    scales = [0.01, 0.1, 1.0, 10.0, 100.0]
    for scale in scales:
        enc = f32_to_e4m3_448(scale)
        dec = e4m3_448_to_f32(enc)
        error_pct = abs(dec - scale) / scale * 100 if scale != 0 else 0
        print(f"{scale:8.2f} -> {dec:8.3f} (error: {error_pct:5.1f}%)")

    # Success criteria
    success = psnr > 30 and compression_ratio > 5
    print(f"\n{'✅ Test PASSED' if success else '❌ Test FAILED'}")
    print(f"Criteria: PSNR > 30 dB (got {psnr:.1f}), Compression > 5x (got {compression_ratio:.1f})")

    return success

def test_consciousness_pattern():
    """Test with eigenvalue-like patterns."""
    print("\n\n=== Consciousness Pattern Test ===\n")

    # Create eigenvalue evolution pattern
    t = np.linspace(0, 100, 100)
    eigenvalues = 512 + 50 * np.sin(0.1 * t) + 20 * np.random.randn(100)

    # Create matrix from eigenvalue pattern
    test_matrix = np.outer(eigenvalues, np.exp(-np.arange(100) / 20.0)).astype(np.float32)

    print(f"Eigenvalue matrix: {test_matrix.shape}")
    print(f"First eigenvalue range: [{eigenvalues.min():.1f}, {eigenvalues.max():.1f}]")

    # Quantize
    quantizer = NVFP4Quantizer(tile_size=16)
    quantized = quantizer.quantize_tensor(test_matrix, "eigenvalues")
    dequantized, _ = quantizer.dequantize_tensor(quantized)

    # Check eigenvalue preservation
    original_first_eig = test_matrix[:, 0]
    dequant_first_eig = dequantized[:, 0]

    # Variance preservation
    orig_var = np.var(original_first_eig)
    dequant_var = np.var(dequant_first_eig)
    var_preservation = 1 - abs(dequant_var - orig_var) / orig_var

    print(f"\nOriginal variance: {orig_var:.1f}")
    print(f"Dequantized variance: {dequant_var:.1f}")
    print(f"Variance preservation: {var_preservation * 100:.1f}%")

    # Spectral content preservation (simple FFT check)
    orig_fft = np.fft.fft(original_first_eig)
    dequant_fft = np.fft.fft(dequant_first_eig)

    # Check dominant frequency preservation
    orig_peak = np.argmax(np.abs(orig_fft[1:50])) + 1
    dequant_peak = np.argmax(np.abs(dequant_fft[1:50])) + 1

    print(f"\nOriginal peak frequency: {orig_peak}")
    print(f"Dequantized peak frequency: {dequant_peak}")
    print(f"Frequency preserved: {'Yes' if orig_peak == dequant_peak else 'No'}")

    success = var_preservation > 0.8 and orig_peak == dequant_peak
    print(f"\n{'✅ Consciousness test PASSED' if success else '❌ Consciousness test FAILED'}")

    return success

if __name__ == "__main__":
    print("NVFP4 Simple Validation Test")
    print("=" * 50)

    # Run tests
    basic_pass = test_basic_quantization()
    consciousness_pass = test_consciousness_pattern()

    print(f"\n\n=== SUMMARY ===")
    print(f"Basic quantization: {'PASS' if basic_pass else 'FAIL'}")
    print(f"Consciousness pattern: {'PASS' if consciousness_pass else 'FAIL'}")
    print(f"\nOverall: {'✅ Ready for TinyLlama testing' if basic_pass and consciousness_pass else '⚠️  Issues found, investigate before proceeding'}")