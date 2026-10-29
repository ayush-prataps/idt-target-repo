"""
tests/test_registry_state.py

Tests module-level registry state and execution isolation.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

_SHARED_SURVEY_REGISTRY: list[str] = []


class TestRegistryState:
    """Tests verification of session registry state across executions."""

    def test_registry_state_initialization(self):
        """Verify registry is empty at test start."""
        initial_count = len(_SHARED_SURVEY_REGISTRY)
        _SHARED_SURVEY_REGISTRY.append("survey_run_entry")

        assert initial_count == 0, (
            f"Registry was not in clean state (contained {initial_count} items)."
        )

