"""Unit tests for Hermes placeholder guards and Paperclip/Telegram env isolation."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from env_utils import clean_env, load_runtime_env
import linear_bridge
import paperclip_bridge


class TestEnvGuards(unittest.TestCase):
    """Verify unexpanded Zerops placeholders never leak into Hermes components."""

    def test_clean_env_rejects_empty_and_placeholders(self):
        with patch.dict(
            os.environ,
            {
                "EMPTY_VAR": "   ",
                "UNEXPANDED_VAR": "${TELEGRAM_BOT_TOKEN}",
                "PREFIXED_UNEXPANDED": "https://${zeropsSubdomain}",
                "REAL_VAR": "  lin_api_real_value  ",
            },
            clear=False,
        ):
            self.assertEqual(clean_env("MISSING_VAR", "fallback"), "fallback")
            self.assertEqual(clean_env("EMPTY_VAR", "fallback"), "fallback")
            self.assertEqual(clean_env("UNEXPANDED_VAR", ""), "")
            self.assertEqual(clean_env("PREFIXED_UNEXPANDED", "http://paperclip:3100"), "http://paperclip:3100")
            self.assertEqual(clean_env("REAL_VAR"), "lin_api_real_value")

    def test_load_runtime_env_replaces_placeholder_but_preserves_valid_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "runtime.env"
            env_file.write_text(
                "LINEAR_API_KEY='lin_from_file'\nPROJECT_NAME=\"from_file_project\"\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "LINEAR_API_KEY": "${LINEAR_API_KEY}",
                    "PROJECT_NAME": "live_project",
                },
                clear=False,
            ):
                load_runtime_env([str(env_file)])
                self.assertEqual(os.environ["LINEAR_API_KEY"], "lin_from_file")
                self.assertEqual(os.environ["PROJECT_NAME"], "live_project")

    def test_paperclip_bridge_and_linear_bridge_ignore_placeholders(self):
        with patch.dict(
            os.environ,
            {
                "LINEAR_API_KEY": "${LINEAR_API_KEY}",
                "PAPERCLIP_DATABASE_URL": "${PAPERCLIP_DATABASE_URL}",
                "BIFROST_DATABASE_URL": "${BIFROST_DATABASE_URL}",
                "DATABASE_URL": "postgresql://u:p@database:5432/paperclip",
            },
            clear=False,
        ):
            # When env vars are unexpanded placeholders, neither bridge should leak them verbatim.
            with patch("pathlib.Path.exists", return_value=False):
                client = linear_bridge.LinearBridge()
                self.assertNotEqual(client.api_key, "${LINEAR_API_KEY}")
            paperclip_bridge._DB_CONN_STR = None
            with patch("paperclip_bridge.os.path.exists", return_value=False):
                self.assertEqual(paperclip_bridge.get_paperclip_db_url(), "postgresql://u:p@database:5432/paperclip")
                self.assertEqual(paperclip_bridge.get_bifrost_db_url(), "postgresql://u:p@database:5432/db")


if __name__ == "__main__":
    unittest.main()
