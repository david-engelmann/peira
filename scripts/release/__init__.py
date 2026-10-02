"""peira release tooling (proposal P-8).

Every script here is runnable directly (``python scripts/release/<name>.py``)
and every pure function is covered by ``tests/test_release.py``. No network
access in the library code; the CLIs shell out to git/pip only.
"""
