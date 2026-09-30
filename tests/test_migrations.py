"""Tests for Alembic migrations and revision integrity."""

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_migration_chain_integrity():
    """Verify that Alembic migrations form a single unbroken chain to head."""
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)

    # Verify head is unique (no divergent branches)
    heads = script.get_heads()
    assert len(heads) == 1, f"Expected exactly 1 migration head, found {heads}"
    head_rev = heads[0]
    assert head_rev == "0006_phase10_dashboard_analytics"

    # Walk backwards from head to root
    rev = script.get_revision(head_rev)
    chain = []
    while rev is not None:
        chain.append(rev.revision)
        if rev.down_revision:
            rev = script.get_revision(rev.down_revision)
        else:
            rev = None

    expected_chain = [
        "0006_phase10_dashboard_analytics",
        "0005_phase8_semantic_cache",
        "0004_add_user_id_to_api_keys",
        "0003_phase6_usage_pipeline",
        "0002_phase5_budgets",
        "0001_phase1_identity",
    ]
    assert chain == expected_chain, f"Migration chain mismatch: {chain} != {expected_chain}"


def test_alembic_revision_descriptions():
    """Verify all revisions contain valid metadata and docstrings."""
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)

    for rev in script.walk_revisions():
        assert (
            rev.doc is not None and len(rev.doc) > 0
        ), f"Revision {rev.revision} is missing a docstring."
        assert rev.revision is not None
