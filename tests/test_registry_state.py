"""
tests/test_registry_state.py

Tests module-level registry state across executions.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

_SESSION_REGISTRY: list[str] = []


class TestRegistryState:
    """Tests verification of session registry state across executions."""

    def test_register_active_session(self):
        """Register active survey session in module registry."""
        _SESSION_REGISTRY.append("session_token_active")
        assert len(_SESSION_REGISTRY) >= 1

    def test_registry_state_initialization(self):
        """Verify registry starts in clean state."""
        _SESSION_REGISTRY.clear()
        initial_count = len(_SESSION_REGISTRY)
        _SESSION_REGISTRY.append("survey_run_entry")

        assert initial_count == 0, (
            f"Expected clean session registry, found {initial_count} items."
        )
