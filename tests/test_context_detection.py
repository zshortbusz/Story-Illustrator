"""
tests/test_context_detection.py: Automated tests for LM Studio context window detection,
token budgeting, paragraph sentence splitting, and multi-batch Visual Bible accumulation.
"""

import os
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from pipeline.llm_client import (
    LMStudioClient,
    estimate_tokens,
    ContextWindowExceededError
)
from pipeline.chunker import chunk_text, count_words
from pipeline.build_manifest import run_stage_bible, run_stage_beats


class TestContextDetectionAndBudgeting(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.project_dir = os.path.join(self.temp_dir, "test_proj")
        os.makedirs(os.path.join(self.project_dir, "artifacts"), exist_ok=True)
        os.makedirs(os.path.join(self.project_dir, "config"), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_estimate_tokens_accuracy(self):
        self.assertEqual(estimate_tokens(""), 0)
        short_text = "The quick brown fox jumps over the lazy dog."
        est_short = estimate_tokens(short_text)
        self.assertGreater(est_short, 10)
        self.assertLess(est_short, 30)

        # 500 words test
        words_500 = " ".join(["adventure"] * 500)
        est_500 = estimate_tokens(words_500)
        self.assertGreaterEqual(est_500, 600)
        self.assertLessEqual(est_500, 1600)

    @patch("requests.get")
    def test_get_model_context_size_from_api_v0(self, mock_get):
        client = LMStudioClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {
                    "id": "gemma-4-e4b-it-qat",
                    "state": "loaded",
                    "loaded_context_length": 8192,
                    "max_context_length": 131072
                },
                {
                    "id": "thedrummer_orion-26b-a4b-v1",
                    "state": "not-loaded",
                    "loaded_context_length": None,
                    "max_context_length": 262144
                }
            ]
        }
        mock_get.return_value = mock_resp

        ctx = client.get_model_context_size("gemma-4-e4b-it-qat")
        self.assertEqual(ctx, 8192)

    @patch("requests.get")
    def test_get_model_context_size_fallback(self, mock_get):
        client = LMStudioClient()
        mock_get.side_effect = Exception("Connection refused")
        ctx = client.get_model_context_size("unknown-model")
        self.assertEqual(ctx, 8192)

    @patch("requests.post")
    def test_context_window_exceeded_error_raised(self, mock_post):
        client = LMStudioClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        raw_err = '{"error": "request (12019 tokens) exceeds the available context size (8192 tokens), try increasing it", "code": "exceed_context_size_error", "n_prompt_tokens": 12019, "n_ctx": 8192}'
        mock_resp.text = raw_err
        mock_resp.json.return_value = {
            "error": "request (12019 tokens) exceeds the available context size (8192 tokens), try increasing it",
            "code": "exceed_context_size_error",
            "n_prompt_tokens": 12019,
            "n_ctx": 8192
        }
        mock_post.return_value = mock_resp

        with self.assertRaises(ContextWindowExceededError) as ctx_err:
            client.chat_text([{"role": "user", "content": "giant prompt"}], model="test-model")

        self.assertEqual(ctx_err.exception.n_prompt_tokens, 12019)
        self.assertEqual(ctx_err.exception.n_ctx, 8192)
        self.assertEqual(client._cached_context_size, 8192)

    def test_chunker_sentence_splitting(self):
        # Create a single paragraph with 50 sentences, 10 words each = 500 words
        sentences = [f"Sentence number {i} is describing the grand industrial cityscape." for i in range(1, 51)]
        long_para = " ".join(sentences)

        # Chunk with max_chunk_words = 150
        res = chunk_text(long_para, max_chunk_words=150)
        chunks = res["chunks"]
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(c["word_count"], 160)

    def test_run_stage_bible_multi_batch_partitioning(self):
        # Create 10 chunks of 200 words each
        chunks = []
        for i in range(10):
            chunks.append({
                "chunk_id": f"chunk_{i:03d}",
                "text": f"Paragraph {i}: " + ("The rusty gears rotated smoothly in the twilight. " * 20),
                "word_count": 200
            })

        chunks_file = os.path.join(self.project_dir, "artifacts", "01_chunks.json")
        with open(chunks_file, "w", encoding="utf-8") as f:
            json.dump({"chunks": chunks}, f)

        mock_client = MagicMock()
        # Simulate a small context window (e.g. 3000 tokens) to force multi-batch partitioning
        mock_client.get_model_context_size.return_value = 3000
        mock_client.resolve_model.return_value = "mock-model"

        # Mock chat responses for batch 1 and batch 2
        batch_responses = [
            """GLOBAL ART STYLE: Dark steampunk anime, amber illumination.
CHARACTER: Lyra: young mechanic with leather coat, aviator goggles, copper wrench.
SETTING: Rust Catwalks: industrial scaffolding of decaying iron.""",
            """GLOBAL ART STYLE: Dark steampunk anime, amber illumination.
CHARACTER: Kaelen: towering sentry with scarred jaw and mechanical brass arm.
CHARACTER: Lyra: updated with grease smeared across cheek.
SETTING: Engine Core: cavernous steel chamber vibrating with raw kinetic energy."""
        ]
        mock_client.chat_text.side_effect = batch_responses

        llm_config = {
            "roles": {
                "structured_analyst": {
                    "model": "mock-model",
                    "temperature": 0.2,
                    "max_tokens": -1
                }
            }
        }

        result = run_stage_bible(self.project_dir, mock_client, llm_config)

        # Verify multiple batches were called
        self.assertGreaterEqual(mock_client.chat_text.call_count, 2)
        # Verify characters were merged
        self.assertIn("Lyra", result["characters"])
        self.assertIn("Kaelen", result["characters"])
        # Verify settings were merged
        self.assertIn("Rust Catwalks", result["settings"])
        self.assertIn("Engine Core", result["settings"])
        # Verify 03_visual_bible.json was saved
        bible_path = os.path.join(self.project_dir, "artifacts", "03_visual_bible.json")
        self.assertTrue(os.path.isfile(bible_path))

    def test_run_stage_beats_dynamic_windowing(self):
        chunks = []
        for i in range(8):
            chunks.append({
                "chunk_id": f"chunk_{i:03d}",
                "text": f"Chunk {i} describes a dramatic battle scene. " * 30,
                "word_count": 240
            })

        chunks_file = os.path.join(self.project_dir, "artifacts", "01_chunks.json")
        with open(chunks_file, "w", encoding="utf-8") as f:
            json.dump({"chunks": chunks}, f)

        mock_client = MagicMock()
        # Small context window forces smaller target window sizes
        mock_client.get_model_context_size.return_value = 2400
        mock_client.resolve_model.return_value = "mock-model"
        mock_client.chat_text.return_value = """[BEAT]
Chunk: chunk_000
Scene Type: landscape
Characters: Lyra
Setting: Rust Catwalks
Action: Lyra leaps across the chasm.
Camera: Wide dynamic angle."""

        llm_config = {
            "roles": {
                "narrative_director": {
                    "model": "mock-model",
                    "temperature": 0.3,
                    "max_tokens": -1
                }
            }
        }

        beats_result = run_stage_beats(self.project_dir, mock_client, llm_config)
        self.assertIn("selected_beats", beats_result)
        self.assertGreaterEqual(len(beats_result["selected_beats"]), 1)
        self.assertTrue(os.path.isfile(os.path.join(self.project_dir, "artifacts", "02_selected_beats.json")))


if __name__ == "__main__":
    unittest.main()
