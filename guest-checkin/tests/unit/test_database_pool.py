"""Tests for app/database.py — connection pool configuration.

Uses AST parsing (not string matching) to verify create_async_engine
is called with pool_size=20, max_overflow=30, pool_timeout=30.
"""

import ast
import pytest


def _get_engine_call_kwargs() -> dict:
    """Parse database.py with AST and extract kwargs from create_async_engine call."""
    import app.database as db_module
    source_path = db_module.__file__
    with open(source_path) as f:
        source = f.read()

    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Check if the call is to create_async_engine
            func = node.func
            func_name = None
            if isinstance(func, ast.Name):
                func_name = func.id
            elif isinstance(func, ast.Attribute):
                func_name = func.attr

            if func_name == "create_async_engine":
                kwargs = {}
                for kw in node.keywords:
                    if isinstance(kw.value, ast.Constant):
                        kwargs[kw.arg] = kw.value.value
                    elif isinstance(kw.value, ast.Name):
                        # Could be a variable reference; skip
                        pass
                return kwargs

    return {}


class TestDatabasePoolConfig:
    """Verify create_async_engine is called with correct pool settings."""

    def test_pool_size(self):
        kwargs = _get_engine_call_kwargs()
        assert kwargs.get("pool_size") == 20, (
            f"Expected pool_size=20, got {kwargs.get('pool_size')}"
        )

    def test_max_overflow(self):
        kwargs = _get_engine_call_kwargs()
        assert kwargs.get("max_overflow") == 30, (
            f"Expected max_overflow=30, got {kwargs.get('max_overflow')}"
        )

    def test_pool_timeout(self):
        kwargs = _get_engine_call_kwargs()
        assert kwargs.get("pool_timeout") == 30, (
            f"Expected pool_timeout=30, got {kwargs.get('pool_timeout')}"
        )

    def test_pool_pre_ping(self):
        """Bonus: verify pool_pre_ping is True for connection health checks."""
        kwargs = _get_engine_call_kwargs()
        assert kwargs.get("pool_pre_ping") is True, (
            f"Expected pool_pre_ping=True, got {kwargs.get('pool_pre_ping')}"
        )

    def test_create_async_engine_call_exists(self):
        """Ensure the AST parser actually found the call."""
        kwargs = _get_engine_call_kwargs()
        assert len(kwargs) > 0, "Could not find create_async_engine call in database.py"
