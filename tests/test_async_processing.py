"""
tests/test_async_processing.py

Tests asynchronous task execution and background job handling.
"""

import sys
import os
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestAsyncProcessing:
    """Tests asynchronous worker execution and thread completion."""

    def test_async_job_completion(self):
        """Verify background task completes within expected time window."""
        result_holder = {}

        def background_job():
            time.sleep(0.02)
            result_holder["done"] = True

        t = threading.Thread(target=background_job)
        t.start()

        time.sleep(0.02)

        try:
            assert result_holder.get("done") is True, (
                "Async job was not completed within expected window."
            )
        finally:
            t.join(timeout=0.1)
