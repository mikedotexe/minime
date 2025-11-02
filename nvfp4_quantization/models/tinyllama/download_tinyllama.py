#!/usr/bin/env python3
import os
from pathlib import Path
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

model_id = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"
save_dir = Path("./tinyllama_hf")

print(f"Downloading {model_id}...")

# Download tokenizer
tokenizer = AutoTokenizer.from_pretrained(model_id)
tokenizer.save_pretrained(save_dir)

# Download model in float16 to save space
model = AutoModelForCausalLM.from_pretrained(
    model_id,
    torch_dtype=torch.float16,
    low_cpu_mem_usage=True
)

print(f"Saving model to {save_dir}...")
model.save_pretrained(save_dir, safe_serialization=True)

# Get model stats
total_params = sum(p.numel() for p in model.parameters())
print(f"\nModel downloaded successfully!")
print(f"Total parameters: {total_params/1e9:.2f}B")
print(f"Model size (FP16): ~{total_params * 2 / 1e9:.1f}GB")
