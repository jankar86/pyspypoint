import contextlib
import io
import os
from unittest import TestCase
from unittest.mock import patch

import poller


class FakeEvent:
    timeout = None

    def __init__(self):
        self.stopped = False

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True

    def wait(self, timeout):
        FakeEvent.timeout = timeout
        self.stopped = True


class TestPoller(TestCase):
    def test_runs_once_then_waits_for_interval(self):
        with patch.dict(os.environ, {"SPYPOINT_POLL_HOURS": "6"}), \
                patch.object(poller, "Event", FakeEvent), \
                patch.object(poller.signal, "signal"), \
                patch.object(poller.archive, "main", return_value=0) as run_archive, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, poller.main())
        run_archive.assert_called_once_with()
        self.assertEqual(6 * 3600, FakeEvent.timeout)
