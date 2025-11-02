#!/usr/bin/env python3
import time
import json
import psutil
import platform

def test_inference(model_path, prompt="Hello! How are you?", max_tokens=50):
    """Test inference performance."""
    print(f"\nTesting {model_path}")
    print(f"Prompt: {prompt}")

    # Simulate inference (would use actual Ollama API)
    start_time = time.time()

    # Mock response
    response = "I'm doing great! I'm TinyLlama, a small but capable AI assistant."

    inference_time = time.time() - start_time

    # Calculate metrics
    tokens_per_second = max_tokens / inference_time if inference_time > 0 else 0

    return {
        "model": model_path,
        "inference_time": inference_time,
        "tokens_per_second": tokens_per_second,
        "response": response
    }

def get_system_info():
    """Get system information."""
    info = {
        "platform": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": psutil.cpu_count(),
        "memory_gb": psutil.virtual_memory().total / (1024**3),
        "python_version": platform.python_version()
    }

    # Detect if running on Raspberry Pi
    try:
        with open('/proc/cpuinfo', 'r') as f:
            cpuinfo = f.read()
            if 'Raspberry Pi' in cpuinfo:
                info["device"] = "Raspberry Pi"
                # Extract model
                import re
                model_match = re.search(r'Raspberry Pi (\d+)', cpuinfo)
                if model_match:
                    info["rpi_model"] = model_match.group(1)
    except:
        pass

    # Detect Apple Silicon
    if platform.machine() == 'arm64' and platform.system() == 'Darwin':
        info["device"] = "Apple Silicon"
        # Could use system_profiler to get exact chip

    return info

def benchmark_models():
    """Benchmark all available models."""
    print("=== TinyLlama NVFP4 Benchmark ===")

    # Get system info
    sys_info = get_system_info()
    print(f"\nSystem: {sys_info.get('device', sys_info['platform'])}")
    print(f"CPU: {sys_info['processor']}")
    print(f"Cores: {sys_info['cpu_count']}")
    print(f"Memory: {sys_info['memory_gb']:.1f} GB")

    # Test prompts
    test_prompts = [
        "Hello! How are you?",
        "What is the capital of France?",
        "Explain quantum computing in simple terms.",
        "Write a haiku about artificial intelligence."
    ]

    # Models to test
    models = []
    if sys_info.get('device') == 'Apple Silicon':
        models.append("tinyllama-nvfp4-m4max.gguf")
    elif sys_info.get('device') == 'Raspberry Pi':
        models.append("tinyllama-nvfp4-rpi.gguf")
    else:
        models.extend(["tinyllama-nvfp4-m4max.gguf", "tinyllama-nvfp4-rpi.gguf"])

    results = []

    for model in models:
        print(f"\n--- Testing {model} ---")
        model_results = []

        for prompt in test_prompts:
            result = test_inference(model, prompt)
            model_results.append(result)
            print(f"  {prompt[:30]}... : {result['tokens_per_second']:.1f} tokens/s")

        avg_tps = sum(r['tokens_per_second'] for r in model_results) / len(model_results)
        print(f"  Average: {avg_tps:.1f} tokens/s")

        results.append({
            "model": model,
            "avg_tokens_per_second": avg_tps,
            "results": model_results
        })

    # Save results
    with open("benchmark_results.json", "w") as f:
        json.dump({
            "system": sys_info,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "results": results
        }, f, indent=2)

    print(f"\nResults saved to benchmark_results.json")

if __name__ == "__main__":
    benchmark_models()
