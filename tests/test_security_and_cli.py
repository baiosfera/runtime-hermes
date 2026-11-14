"""Security and interactive REPL tests for Hermes-Agent (BAI-470)."""
import pathlib
import sys
import unittest

HERMES_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(HERMES_ROOT) not in sys.path:
    sys.path.insert(0, str(HERMES_ROOT))


class TestHermesSecurityAndCli(unittest.TestCase):
    def test_telegram_gateway_is_fail_closed(self):
        text = (HERMES_ROOT / "telegram_gateway.py").read_text(encoding="utf-8")
        self.assertNotIn("Open mode if no whitelist specified yet", text)
        self.assertIn("Telegram fail-closed", text)
        self.assertIn("Cerrada (sin usuarios autorizados)", text)

    def test_main_uses_tmux_and_hermes_cli_instead_of_bash(self):
        text = (HERMES_ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("hermes_cli.py", text)
        self.assertIn('"new-session", "-A", "-s", "hermes"', text)
        self.assertNotIn('"bash", "-l"', text)

    def test_hermes_cli_compiles_and_no_hardcodes_in_tools(self):
        cli_text = (HERMES_ROOT / "hermes_cli.py").read_text(encoding="utf-8")
        compile(cli_text, str(HERMES_ROOT / "hermes_cli.py"), "exec")
        tools_text = (HERMES_ROOT / "tools.py").read_text(encoding="utf-8")
        self.assertNotIn("paperclip-2b6-3100.ny1.zerops.app", tools_text)
        self.assertNotIn("http://astrobranding:3000", tools_text)
        self.assertNotIn("MentorIA/dev", tools_text)


if __name__ == "__main__":
    unittest.main()
