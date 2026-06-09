# COLLAB COPY -- canonical source is /mikemind/config.py
# Model configuration, paths, and the get_ollama_embedding helper.
"""Configuration, constants, paths, and shared helpers for MikesSpatialMind."""

import logging
import os
from enum import Enum
from pathlib import Path
from typing import Optional

import numpy as np
import requests

# --------------------------------------------------------------------------- #
# Processing Modes
# --------------------------------------------------------------------------- #
class ProcessingMode(Enum):
    """Runtime processing modes for different use cases."""
    RESEARCH = "research"     # Full LLM, seven-stage processing, unlimited memory (desktop)
    EMBEDDED = "embedded"     # Fractal compression, fast, camera-ready (Pi)
    ADAPTIVE = "adaptive"     # Auto-detect based on context and resources


# --------------------------------------------------------------------------- #
# Paths -- BASE_DIR is the repository root (parent of mikemind/)
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent.parent
MEMORY_FILE = BASE_DIR / "MikesSpatialMind_memories.json"
HYPOTHESES_FILE = BASE_DIR / "spatial_hypotheses.json"
THOUGHTS_QUEUE_DIR = BASE_DIR / "thoughts_queue"
CORPUS_DIR = BASE_DIR / "corpus"
LOG_FILE = BASE_DIR / "spatial_mind.log"
LLAVA_EMBEDDING_FILE = BASE_DIR / "workspace" / "llava_embedding_latest.json"

# Global debug flag (set via --debug command line arg)
DEBUG = False


# --------------------------------------------------------------------------- #
# Model Configuration
# --------------------------------------------------------------------------- #
class ModelConfig:
    """Centralized model configuration for multi-model architecture."""

    # Primary conversation model
    CONVERSATION = "gemma4:12b"
    DOLPHIN_MIXTRAL = CONVERSATION  # Legacy compatibility alias; prefer CONVERSATION.

    # Vision understanding
    LLAVA_VISION = "llava-llama3"
    MOONDREAM_VISION = "moondream:latest"  # Lightweight alternative

    # API endpoints
    OLLAMA_API = "http://localhost:11434/api/chat"
    OLLAMA_API_GENERATE = "http://localhost:11434/api/generate"  # For vision model

    @classmethod
    def get_active_models(cls) -> dict:
        """Return dictionary of model roles and their configurations."""
        return {
            "conversation": cls.CONVERSATION,
            "vision": cls.LLAVA_VISION,
            "api_url": cls.OLLAMA_API,
        }


# Legacy compatibility aliases
OLLAMA_MODEL = ModelConfig.CONVERSATION
OLLAMA_API_URL = ModelConfig.OLLAMA_API


# --------------------------------------------------------------------------- #
# Logging setup
# --------------------------------------------------------------------------- #
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


# --------------------------------------------------------------------------- #
# Optional imports for visual processing
# --------------------------------------------------------------------------- #
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logging.warning("opencv-python not installed - visual processing disabled")


# --------------------------------------------------------------------------- #
# Ollama Embedding Helper
# --------------------------------------------------------------------------- #
def get_ollama_embedding(
    text: str,
    model: str = "nomic-embed-text",
    base_url: str = "http://localhost:11434",
) -> Optional[np.ndarray]:
    """
    Extract embeddings from an Ollama model via /api/embeddings.

    Returns an embedding vector (dimensionality depends on model) or None.
    """
    try:
        response = requests.post(
            f"{base_url}/api/embeddings",
            json={"model": model, "prompt": text},
            timeout=25.0,
        )
        if response.status_code == 200:
            data = response.json()
            embedding = np.array(data.get("embedding", []), dtype=np.float32)
            return embedding if embedding.shape[0] > 0 else None
        else:
            logging.warning(f"Ollama embedding request failed: {response.status_code}")
            return None
    except Exception as e:
        logging.error(f"Failed to get Ollama embedding: {e}")
        return None
