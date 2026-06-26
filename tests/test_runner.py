from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import TestCase

from agent_bridge.services.runner import run_process, terminate_active_processes


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

    def test_terminate_active_processes_stops_running_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            result_holder = {}

            def run_long_process() -> None:
                result_holder["result"] = run_process(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    cwd=str(Path(tmp_dir)),
                    timeout=60,
                    stream_callback=lambda *_: None,
                )

            thread = threading.Thread(target=run_long_process)
            thread.start()
            time.sleep(0.2)

            stopped = terminate_active_processes()
            thread.join(timeout=5)

            self.assertGreaterEqual(stopped, 1)
            self.assertFalse(thread.is_alive())
            self.assertNotEqual(result_holder["result"].returncode, 0)
