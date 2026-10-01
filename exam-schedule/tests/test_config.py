"""Tests for configuration loading, defaults and validation."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sdu_exam_watch import config as cfg  # noqa: E402


class RenderAndLoadTests(unittest.TestCase):
    def test_rendered_template_loads(self) -> None:
        text = cfg.render_default_config("topic-abc123")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(text, encoding="utf-8")
            loaded = cfg.load_config(path)
        self.assertEqual(loaded.notify.ntfy_topic, "topic-abc123")
        self.assertTrue(loaded.notify.attach_files)
        self.assertEqual(len(loaded.targets), 1)
        target = loaded.targets[0]
        self.assertEqual(target.programmes, (cfg.MSC_SOFTWARE_ENGINEERING,))
        self.assertTrue(target.summary)
        # state_file is resolved relative to the config file.
        self.assertEqual(loaded.settings.state_file, (Path(tmp) / "state.json").resolve())

    def test_commented_options_are_not_values(self) -> None:
        text = cfg.render_default_config("t", include_targets=False)
        self.assertIn("# webhook_url", text)
        self.assertIn("# macos_notification", text)


def _write(tmp: str, body: str) -> Path:
    path = Path(tmp) / "config.toml"
    path.write_text(body, encoding="utf-8")
    return path


MINIMAL = """
[notify]
ntfy_topic = "t"
[[target]]
name = "x"
url = "https://example.org/page"
"""


class ValidationTests(unittest.TestCase):
    def test_missing_file(self) -> None:
        with self.assertRaises(cfg.ConfigError):
            cfg.load_config(Path("/nonexistent/config.toml"))

    def test_no_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, '[notify]\nntfy_topic = "t"\n')
            with self.assertRaises(cfg.ConfigError):
                cfg.load_config(path)

    def test_no_channel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(
                tmp,
                '[[target]]\nname = "x"\nurl = "https://example.org"\n',
            )
            with self.assertRaises(cfg.ConfigError):
                cfg.load_config(path)

    def test_bad_priority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, MINIMAL.replace('"t"', '"t"\npriority = "urgent"'))
            with self.assertRaises(cfg.ConfigError):
                cfg.load_config(path)

    def test_bad_number_has_clear_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(tmp, "[settings]\ntimeout_seconds = \"soon\"\n" + MINIMAL)
            with self.assertRaises(cfg.ConfigError) as ctx:
                cfg.load_config(path)
            self.assertIn("timeout_seconds", str(ctx.exception))

    def test_accepts_programs_spelling_and_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(
                tmp,
                MINIMAL
                + 'programmes = ["A"]\n'
                + 'link_pattern = "\\\\.pdf$"\n',
            )
            loaded = cfg.load_config(path)
        self.assertEqual(loaded.targets[0].programmes, ("A",))
        self.assertEqual(loaded.targets[0].link_pattern, r"\.pdf$")

    def test_attach_files_defaults_true_and_can_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(cfg.load_config(_write(tmp, MINIMAL)).notify.attach_files)
        with tempfile.TemporaryDirectory() as tmp:
            disabled = MINIMAL.replace(
                'ntfy_topic = "t"', 'ntfy_topic = "t"\nattach_files = false'
            )
            self.assertFalse(
                cfg.load_config(_write(tmp, disabled)).notify.attach_files
            )


if __name__ == "__main__":
    unittest.main()
