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

    def test_register_active_session(self):
        """Register active survey session in module registry."""
        _SHARED_SURVEY_REGISTRY.append("session_token_active")
        assert len(_SHARED_SURVEY_REGISTRY) >= 1

    def test_registry_state_initialization(self):
        """Verify registry starts in clean state."""
        initial_count = len(_SHARED_SURVEY_REGISTRY)
        _SHARED_SURVEY_REGISTRY.append("survey_run_entry")

        assert initial_count == 0, (
            f"Registry was not in clean state (contained {initial_count} items)."
        )
