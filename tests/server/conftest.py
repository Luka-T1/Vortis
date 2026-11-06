"""Shared fixtures for server route tests.

Server tests build apps via ``create_app``, which (with traces enabled by
default) wires a ``TraceStore`` at the real ``~/.vortis/traces.db``. Now
that the chat endpoints actually *write* traces, an unguarded run would
pollute the developer's real trace DB and make tests non-hermetic. This
autouse fixture redirects the traces DB to a per-test temp path.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _isolate_traces_db(tmp_path, monkeypatch):
    """Point ``config.traces.db_path`` at a temp file for every server test.

    ``load_config`` returns a fresh ``JarvisConfig`` per call (no caching), so
    wrapping it to rewrite ``traces.db_path`` only affects calls made during
    the test — there is no global leak.
    """
    from vortis.core import config as _config

    real_load_config = _config.load_config
    db_path = str(tmp_path / "traces.db")

    def _patched_load_config(*args, **kwargs):
        cfg = real_load_config(*args, **kwargs)
        cfg.traces.db_path = db_path
        return cfg

    monkeypatch.setattr(_config, "load_config", _patched_load_config)
    return db_path


@pytest.fixture(scope="module", autouse=True)
def _isolate_connector_dbs(tmp_path_factory):
    """Point the knowledge store and sync-state DBs at a per-module temp dir.

    ``connectors_router`` opens ``KnowledgeStore()`` and ``SyncEngine`` with no
    path, so they default to the real ``~/.vortis``. Without this, a sync
    test ingests its fixture note there and a disconnect test purges the
    developer's real indexed vault. Module scope, not function scope:
    ``POST /sync`` starts a background thread that can outlive the test, and a
    function-scoped patch would be undone while it is still writing.
    """
    home = tmp_path_factory.mktemp("vortis-home")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("vortis.core.config.DEFAULT_CONFIG_DIR", home)
        mp.setattr("vortis.connectors.sync_engine.DEFAULT_CONFIG_DIR", home)
        yield


@pytest.fixture(autouse=True)
def _finish_connector_syncs(monkeypatch):
    """Drain each test's sync workers before its mocks and DB isolation expire."""
    from vortis.server import connectors_router

    workers: list[threading.Thread] = []

    def tracked_thread(*args, **kwargs):
        worker = threading.Thread(*args, **kwargs)
        workers.append(worker)
        return worker

    router_threading = SimpleNamespace(**vars(threading))
    router_threading.Thread = tracked_thread
    monkeypatch.setattr(connectors_router, "threading", router_threading)
    try:
        yield
    finally:
        for worker in workers:
            if worker.ident is not None:
                worker.join()
