"""
Yandex Maps business parser.

Public API:
    run()      — CLI entry point (reads config from state module)
    run_web()  — Web entry point called by app.py
"""
from .runner import run, run_web

__all__ = ["run", "run_web"]
