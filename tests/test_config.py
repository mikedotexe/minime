"""Smoke tests for the mikemind package -- no Ollama or Rust engine required."""

import unittest
import importlib
from pathlib import Path


class TestPackageImports(unittest.TestCase):
    """Verify that all public symbols are importable."""

    def test_import_mikemind(self):
        import mikemind
        self.assertTrue(hasattr(mikemind, "MikesSpatialMind"))
        self.assertTrue(hasattr(mikemind, "LLMEngine"))
        self.assertTrue(hasattr(mikemind, "LLaVAVisionEngine"))
        self.assertTrue(hasattr(mikemind, "ModelConfig"))
        self.assertTrue(hasattr(mikemind, "ProcessingMode"))
        self.assertTrue(hasattr(mikemind, "get_ollama_embedding"))
        self.assertTrue(hasattr(mikemind, "live_session"))

    def test_import_config(self):
        from mikemind.config import (
            BASE_DIR, MEMORY_FILE, HYPOTHESES_FILE,
            THOUGHTS_QUEUE_DIR, CORPUS_DIR, LOG_FILE,
            LLAVA_EMBEDDING_FILE, ModelConfig, ProcessingMode,
            OLLAMA_MODEL, OLLAMA_API_URL, get_ollama_embedding,
        )

    def test_import_llm_engine(self):
        from mikemind.llm_engine import LLMEngine

    def test_import_vision(self):
        from mikemind.vision import LLaVAVisionEngine

    def test_import_mind(self):
        from mikemind.mind import (
            MikesSpatialMind,
            SevenStageProcessor,
            FractalCompressionLayer,
            MultiThreadedConsciousness,
        )

    def test_import_cli(self):
        from mikemind.cli import live_session, main


class TestModelConfig(unittest.TestCase):
    """Verify model configuration is consistent."""

    def test_conversation_model(self):
        from mikemind.config import ModelConfig
        self.assertEqual(ModelConfig.CONVERSATION, "mistral-small:24b")

    def test_legacy_alias(self):
        from mikemind.config import ModelConfig
        self.assertEqual(ModelConfig.DOLPHIN_MIXTRAL, ModelConfig.CONVERSATION)

    def test_vision_model(self):
        from mikemind.config import ModelConfig
        self.assertEqual(ModelConfig.LLAVA_VISION, "llava-llama3")

    def test_api_endpoints(self):
        from mikemind.config import ModelConfig
        self.assertIn("11434", ModelConfig.OLLAMA_API)
        self.assertIn("/api/chat", ModelConfig.OLLAMA_API)
        self.assertIn("/api/generate", ModelConfig.OLLAMA_API_GENERATE)

    def test_get_active_models(self):
        from mikemind.config import ModelConfig
        models = ModelConfig.get_active_models()
        self.assertIn("conversation", models)
        self.assertIn("vision", models)
        self.assertIn("api_url", models)
        self.assertEqual(models["conversation"], "mistral-small:24b")
        self.assertEqual(models["vision"], "llava-llama3")


class TestPaths(unittest.TestCase):
    """Verify that path constants resolve to the repository root."""

    def test_base_dir_is_repo_root(self):
        from mikemind.config import BASE_DIR
        # BASE_DIR should contain minime/, mikemind/, CLAUDE.md
        self.assertTrue((BASE_DIR / "minime").is_dir(),
                        f"BASE_DIR={BASE_DIR} does not contain minime/")
        self.assertTrue((BASE_DIR / "mikemind").is_dir(),
                        f"BASE_DIR={BASE_DIR} does not contain mikemind/")
        self.assertTrue((BASE_DIR / "CLAUDE.md").is_file(),
                        f"BASE_DIR={BASE_DIR} does not contain CLAUDE.md")

    def test_corpus_dir(self):
        from mikemind.config import CORPUS_DIR
        # CORPUS_DIR should exist (it's checked at runtime)
        self.assertTrue(CORPUS_DIR.is_dir(),
                        f"CORPUS_DIR={CORPUS_DIR} does not exist")

    def test_package_files_exist(self):
        from mikemind.config import BASE_DIR
        expected = [
            "mikemind/__init__.py",
            "mikemind/config.py",
            "mikemind/llm_engine.py",
            "mikemind/vision.py",
            "mikemind/mind.py",
            "mikemind/cli.py",
        ]
        for f in expected:
            self.assertTrue((BASE_DIR / f).is_file(), f"Missing: {f}")


class TestEmbeddingHelper(unittest.TestCase):
    """Verify get_ollama_embedding fails gracefully without Ollama."""

    def test_returns_none_when_ollama_unavailable(self):
        from mikemind.config import get_ollama_embedding
        # With Ollama not running (or on a CI), this should return None, not crash
        result = get_ollama_embedding("test", base_url="http://127.0.0.1:99999")
        self.assertIsNone(result)


class TestSafetyThresholds(unittest.TestCase):
    """Verify safety threshold layering is consistent."""

    def test_python_critical_below_rust_crisis(self):
        """Python agent must act before the Rust crisis threshold."""
        from thresholds import RECESS, FOCUSED
        # Rust CRISIS_FILL_THRESHOLD is 87% (0.87 as fraction)
        RUST_CRISIS = 0.87
        self.assertLess(RECESS.critical_fill, RUST_CRISIS,
                        "RECESS critical_fill must be below Rust crisis threshold")
        self.assertLess(FOCUSED.critical_fill, RUST_CRISIS,
                        "FOCUSED critical_fill must be below Rust crisis threshold")

    def test_high_below_critical(self):
        from thresholds import RECESS, FOCUSED
        self.assertLess(RECESS.high_fill, RECESS.critical_fill)
        self.assertLess(FOCUSED.high_fill, FOCUSED.critical_fill)

    def test_focused_tighter_than_recess(self):
        """FOCUSED mode should have tighter (lower) thresholds than RECESS."""
        from thresholds import RECESS, FOCUSED
        self.assertLessEqual(FOCUSED.critical_fill, RECESS.critical_fill)
        self.assertLessEqual(FOCUSED.high_fill, RECESS.high_fill)


class TestProcessingModes(unittest.TestCase):
    """Verify ProcessingMode enum values."""

    def test_mode_values(self):
        from mikemind.config import ProcessingMode
        self.assertEqual(ProcessingMode.RESEARCH.value, "research")
        self.assertEqual(ProcessingMode.EMBEDDED.value, "embedded")
        self.assertEqual(ProcessingMode.ADAPTIVE.value, "adaptive")


if __name__ == "__main__":
    unittest.main()
