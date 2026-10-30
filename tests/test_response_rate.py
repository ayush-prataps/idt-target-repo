import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestResponseRate:

    def test_response_rate_threshold(self):
        value = random.random()
        assert value >= 0.9, f"Metric {value:.4f} below threshold 0.9"
