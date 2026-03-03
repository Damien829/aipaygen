import pytest
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from eas_reputation import init_eas_db, create_reputation_attestation, get_reputation_attestations, get_reputation_summary, get_pending_attestations, mark_submitted
import eas_reputation


def setup_module():
    eas_reputation._DB_PATH = "/tmp/test_eas_rep.db"
    try:
        os.unlink("/tmp/test_eas_rep.db")
    except FileNotFoundError:
        pass
    init_eas_db()


def test_create_attestation():
    result = create_reputation_attestation("0xABC123", "task_completed", 4, "did good work")
    assert result is not None
    assert result["status"] == "queued"
    assert result["score"] == 4


def test_invalid_type():
    result = create_reputation_attestation("0xABC123", "invalid_type", 3)
    assert result is None


def test_get_attestations():
    create_reputation_attestation("0xDEF456", "upvote", 5)
    create_reputation_attestation("0xDEF456", "service_rating", 3)
    atts = get_reputation_attestations("0xDEF456")
    assert len(atts) >= 2


def test_reputation_summary():
    summary = get_reputation_summary("0xDEF456")
    assert summary["total_attestations"] >= 2
    assert summary["average_score"] > 0


def test_pending_and_submit():
    pending = get_pending_attestations()
    assert len(pending) > 0
    ids = [p["id"] for p in pending[:2]]
    mark_submitted(ids, "0xfaketxhash123")
    # Re-check pending should have fewer
    new_pending = get_pending_attestations()
    submitted_ids = {p["id"] for p in new_pending}
    for aid in ids:
        assert aid not in submitted_ids
