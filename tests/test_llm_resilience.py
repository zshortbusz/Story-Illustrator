"""
tests/test_llm_resilience.py: Resilience tests for LMStudioClient / OpenAI-compatible
LLM interactions under network failures, null content payloads, and reasoning-only responses.
"""

import unittest
from unittest.mock import patch, MagicMock
import requests

from pipeline.llm_client import LMStudioClient


class TestLLMClientResilience(unittest.TestCase):
    def setUp(self):
        self.client = LMStudioClient(
            api_base="http://localhost:1234/v1",
            api_key=None,
            timeout=5
        )

    @patch("requests.post")
    def test_chat_json_null_content(self, mock_post):
        """Verifies chat_json does not crash on AttributeError when content is None."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # Return content: None as commonly seen with certain stop reasons
        mock_resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": None
                    }
                }
            ]
        }
        mock_post.return_value = mock_resp

        messages = [{"role": "user", "content": "Test prompt"}]
        try:
            res = self.client.chat_json(messages, model="test-model", retries=1)
            self.assertIsInstance(res, dict)
        except AttributeError as ae:
            self.fail(f"BUG REPRODUCED: chat_json crashed with AttributeError on null content: {ae}")
        except RuntimeError:
            pass  # Clean RuntimeError is acceptable if no JSON found

    @patch("requests.post")
    def test_chat_json_empty_choices(self, mock_post):
        """Verifies chat_json safely handles empty choices array without IndexError."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"choices": []}
        mock_post.return_value = mock_resp

        messages = [{"role": "user", "content": "Test prompt"}]
        try:
            self.client.chat_json(messages, model="test-model", retries=1)
            self.fail("Expected RuntimeError on empty choices, but call succeeded")
        except IndexError as ie:
            self.fail(f"BUG REPRODUCED: chat_json crashed with IndexError on empty choices: {ie}")
        except RuntimeError:
            pass  # Expected clean RuntimeError

    @patch("requests.post")
    def test_chat_json_reasoning_content_fallback(self, mock_post):
        """Verifies chat_json falls back to reasoning_content if content is null/empty."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "reasoning_content": "```json\n{\"status\": \"ok\", \"extracted\": true}\n```"
                    }
                }
            ]
        }
        mock_post.return_value = mock_resp

        messages = [{"role": "user", "content": "Test prompt"}]
        try:
            res = self.client.chat_json(messages, model="test-model", retries=1)
            self.assertEqual(res.get("status"), "ok")
            self.assertTrue(res.get("extracted"))
        except AttributeError as ae:
            self.fail(f"BUG REPRODUCED: chat_json crashed with AttributeError on null content before checking reasoning: {ae}")

    @patch("requests.post")
    def test_chat_text_network_timeout_retries(self, mock_post):
        """Verifies chat_text retries on Timeout and raises clean RuntimeError after retries exhausted."""
        mock_post.side_effect = requests.exceptions.Timeout("Connection timed out")
        messages = [{"role": "user", "content": "Hello"}]

        with patch("time.sleep", return_value=None):
            with self.assertRaises(RuntimeError) as ctx:
                self.client.chat_text(messages, model="test-model", retries=2)
            self.assertIn("Failed to communicate with LLM provider", str(ctx.exception))
            self.assertEqual(mock_post.call_count, 2)

    @patch("requests.post")
    def test_chat_text_connection_error_retries(self, mock_post):
        """Verifies chat_text retries on ConnectionError and raises clean RuntimeError."""
        mock_post.side_effect = requests.exceptions.ConnectionError("Failed to connect to LM Studio")
        messages = [{"role": "user", "content": "Hello"}]

        with patch("time.sleep", return_value=None):
            with self.assertRaises(RuntimeError) as ctx:
                self.client.chat_text(messages, model="test-model", retries=2)
    @patch("requests.post")
    def test_chat_text_token_exhaustion_during_thinking(self, mock_post):
        """Verifies chat_text raises an informative error if the model ran out of tokens during thinking."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": "* Thinking about Nancy Drew and the blue roadster..."
                    },
                    "finish_reason": "length"
                }
            ]
        }
        mock_post.return_value = mock_resp

        messages = [{"role": "user", "content": "Create prompt"}]
        with self.assertRaises(RuntimeError) as ctx:
            self.client.chat_text(messages, model="test-model", retries=1)
        self.assertIn("token budget exhausted", str(ctx.exception).lower())
        self.assertIn("thinking phase", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
