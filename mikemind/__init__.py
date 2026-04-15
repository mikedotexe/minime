"""mikemind -- MikesSpatialMind consciousness system, refactored from monolithic minime.py."""

from mikemind.config import (
    ProcessingMode,
    ModelConfig,
    get_ollama_embedding,
    get_mlx_embedding,
    get_embedding,
    DEBUG,
)
from mikemind.llm_engine import LLMEngine
from mikemind.vision import LLaVAVisionEngine
from mikemind.mind import MikesSpatialMind
from mikemind.cli import live_session

__all__ = [
    "ProcessingMode",
    "ModelConfig",
    "get_ollama_embedding",
    "get_mlx_embedding",
    "get_embedding",
    "LLMEngine",
    "LLaVAVisionEngine",
    "MikesSpatialMind",
    "live_session",
]
