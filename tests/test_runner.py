from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import TestCase

from agent_bridge.services.runner import run_process


class RunnerTests(TestCase):
    def test_run_process_streams_stdout_and_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            events: list[tuple[str, str]] = []
            script = "import sys; print('out-line'); print('err-line', file=sys.stderr)"

            result = run_process(
                [sys.executable, "-c", script],
                cwd=str(Path(tmp_dir)),
                timeout=10,
                stream_callback=lambda stream, line: events.append((stream, line)),
            )

            self.assertEqual(result.returncode, 0)
            self.assertIn("out-line", result.stdout)
            self.assertIn("err-line", result.stderr)
            self.assertIn(("stdout", "out-line"), events)
            self.assertIn(("stderr", "err-line"), events)

