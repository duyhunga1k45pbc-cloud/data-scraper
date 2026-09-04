from __future__ import annotations

from types import SimpleNamespace

from src.storage.repositories import lock_product_identities_for_transition


class _FakeSession:
    def __init__(self, dialect_name: str) -> None:
        self._bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect_name))
        self.calls: list[int] = []

    def get_bind(self):
        return self._bind

    def execute(self, statement, params):
        self.calls.append(int(params["lock_id"]))


def _product(source: str, *, record_id: str | None = None, url: str | None = None):
    return SimpleNamespace(
        source=source,
        source_record_id=record_id,
        canonical_product_url=url,
    )


def test_m7_identity_locks_are_deduplicated_and_acquired_in_stable_order() -> None:
    session = _FakeSession("postgresql")
    products = (
        _product("source-b", record_id="2"),
        _product("source-a", record_id="1"),
        _product("source-b", record_id="2"),
    )

    lock_product_identities_for_transition(session, products)

    assert len(session.calls) == 2
    assert session.calls == sorted(session.calls)


def test_m7_identity_locking_is_noop_outside_postgresql() -> None:
    session = _FakeSession("sqlite")

    lock_product_identities_for_transition(
        session,
        (_product("source-a", record_id="1"),),
    )

    assert session.calls == []
