"""Real DuckDB execution of the portable managed-warehouse acceptance model."""
import hashlib

import pytest

from signals.integration_warehouse import LocalWarehouse, WarehouseContractError, digest


def ref(value):
    return hashlib.sha256(value.encode()).hexdigest()


def account(**updates):
    return {"source_ref": ref("account"), "source_modified_at": "2026-10-01T00:00:00Z",
            "brand": "cedar", "account_key": "account-0012", "owner_key": "cedar-east",
            "owner_ref": ref("owner"), "active": True, "synthetic": True, **updates}


def review(**updates):
    return {"source_ref": ref("review"), "source_modified_at": "2026-10-01T01:00:00Z",
            "account_source_ref": ref("account"), "action_key": ref("action"),
            "review_status": "Reviewed", "proposed_action": "schedule_discovery", **updates}


def test_governed_decision_and_durable_exact_replay(tmp_path):
    path = tmp_path / "warehouse.duckdb"
    with LocalWarehouse(path) as warehouse:
        first = warehouse.load([account()], [review()], run_id="batch-1")
        assert first["inserted"] == {"accounts": 1, "reviews": 1}
        expected = warehouse.decisions()
        row = expected[0]
        assert row["decision_action"] == "clarify_need"
        assert row["reviewed_count"] == 1
        assert row["pending_count"] == 0
        payload = dict(row)
        assert payload.pop("decision_hash") == digest(payload)
        replay = warehouse.load([account(), account()], [review(), review()], run_id="batch-1")
        assert replay["inserted"] == {"accounts": 0, "reviews": 0}
        assert warehouse.decisions() == expected
    with LocalWarehouse(path) as reopened:
        assert reopened.decisions() == expected
        assert len(reopened.source_rows()["reviews"]) == 1


@pytest.mark.parametrize("active,synthetic,status,expected", [
    (True, True, "Reviewed", "clarify_need"), (False, True, "Reviewed", "hold"),
    (True, False, "Reviewed", "hold"), (True, True, "Pending", "hold"),
    (True, True, "Rejected", "hold"),
])
def test_readiness_contract(active, synthetic, status, expected):
    with LocalWarehouse() as warehouse:
        warehouse.load([account(active=active, synthetic=synthetic)], [review(review_status=status)])
        assert warehouse.decisions()[0]["decision_action"] == expected


def test_pending_review_blocks_other_reviewed_record():
    with LocalWarehouse() as warehouse:
        warehouse.load([account()], [review(), review(source_ref=ref("second"), action_key=ref("second-action"),
                                                       review_status="Pending")])
        row = warehouse.decisions()[0]
        assert (row["review_count"], row["reviewed_count"], row["pending_count"]) == (2, 1, 1)
        assert row["decision_action"] == "hold"


def test_empty_review_account_is_held():
    with LocalWarehouse() as warehouse:
        warehouse.load([account()], [])
        assert warehouse.decisions()[0]["review_count"] == 0
        assert warehouse.decisions()[0]["decision_action"] == "hold"


def test_late_versions_do_not_regress_and_full_build_matches(tmp_path):
    old = review(review_status="Pending")
    corrected = review(source_modified_at="2026-10-02T00:00:00Z")
    inactive = account(source_modified_at="2026-10-03T00:00:00Z", active=False)
    with LocalWarehouse(tmp_path / "incremental.duckdb") as incremental, LocalWarehouse() as full:
        incremental.load([account()], [old])
        incremental.load([], [corrected])
        assert incremental.decisions()[0]["decision_action"] == "clarify_need"
        incremental.load([inactive], [])
        expected = incremental.decisions()
        incremental.load([account()], [old])
        assert incremental.decisions() == expected
        full.load([inactive, account()], [corrected, old])
        assert incremental.decisions() == full.decisions()
        assert expected[0]["decision_action"] == "hold"


@pytest.mark.parametrize("change", [
    {"unexpected": "field"}, {"active": 1}, {"synthetic": "true"},
    {"source_ref": "raw-salesforce-id"}, {"owner_ref": "A" * 64},
    {"owner_key": " Cedar-East"}, {"account_key": "account-12"}, {"brand": "CEDAR"},
    {"source_modified_at": "2026-10-01T00:00:00"},
    {"source_modified_at": "2026-10-01T00:00:00-04:00"},
])
def test_rejects_invalid_account_contract_without_partial_load(change):
    with LocalWarehouse() as warehouse:
        with pytest.raises(WarehouseContractError):
            warehouse.load([account(**change)], [])
        assert warehouse.source_rows() == {"accounts": [], "reviews": []}


@pytest.mark.parametrize("change", [
    {"review_status": "Approved"}, {"proposed_action": "send_email"},
    {"account_source_ref": ref("unknown")}, {"action_key": "invalid"},
])
def test_rejects_invalid_review_contract(change):
    with LocalWarehouse() as warehouse:
        with pytest.raises(WarehouseContractError):
            warehouse.load([account()], [review(**change)])
        assert warehouse.source_rows() == {"accounts": [], "reviews": []}


def test_same_version_conflict_rejects_entire_batch():
    with LocalWarehouse() as warehouse:
        warehouse.load([account()], [review()])
        before = warehouse.source_rows()
        with pytest.raises(WarehouseContractError, match="same-version"):
            warehouse.load([account(source_ref=ref("other"), account_key="account-0013")],
                           [review(review_status="Rejected")])
        assert warehouse.source_rows() == before


def test_ambiguous_account_mapping_rejected():
    with LocalWarehouse() as warehouse:
        with pytest.raises(WarehouseContractError, match="account mapping"):
            warehouse.load([account(), account(source_ref=ref("other"))], [])


def test_shared_action_key_rejected():
    with LocalWarehouse() as warehouse:
        with pytest.raises(WarehouseContractError, match="multiple reviews"):
            warehouse.load([account()], [review(), review(source_ref=ref("other-review"))])


def test_conflicting_current_owner_mapping_rejected():
    with LocalWarehouse() as warehouse:
        with pytest.raises(WarehouseContractError, match="owner mapping"):
            warehouse.load([account(), account(source_ref=ref("other-account"), account_key="account-0013",
                                               owner_ref=ref("different-owner"))], [])


def test_review_identity_immutable_across_versions():
    with LocalWarehouse() as warehouse:
        warehouse.load([account()], [review()])
        with pytest.raises(WarehouseContractError, match="immutable"):
            warehouse.load([], [review(source_modified_at="2026-10-02T00:00:00Z", proposed_action="clarify_need")])


def test_ingestion_identity_is_separate_from_business_and_cannot_be_reused():
    with LocalWarehouse() as warehouse:
        warehouse.load([account()], [review()], run_id="one", observed_at="2026-10-04T00:00:00Z")
        before = warehouse.decisions()
        warehouse.load([account()], [review()], run_id="two", observed_at="2026-10-05T00:00:00Z")
        assert warehouse.decisions() == before
        with pytest.raises(WarehouseContractError, match="run ID reused"):
            warehouse.load([], [], run_id="one")


def test_utc_equivalent_format_collapses():
    with LocalWarehouse() as warehouse:
        warehouse.load([account(), account(source_modified_at="2026-10-01T00:00:00.000000+00:00")], [])
        assert len(warehouse.source_rows()["accounts"]) == 1


def test_corrupted_stored_same_version_is_not_silently_ranked():
    with LocalWarehouse() as warehouse:
        warehouse.load([account()], [review()])
        warehouse.connection.execute("INSERT INTO CSA_REVIEWS SELECT source_ref, source_modified_at, "
                                     "account_source_ref, action_key, 'Rejected', proposed_action FROM CSA_REVIEWS")
        with pytest.raises(WarehouseContractError, match="same-version"):
            warehouse.decisions()


def test_identical_stored_duplicate_is_not_silently_collapsed():
    with LocalWarehouse() as warehouse:
        warehouse.load([account(), account()], [review()])
        warehouse.connection.execute("INSERT INTO CSA_ACCOUNTS SELECT * FROM CSA_ACCOUNTS")
        with pytest.raises(WarehouseContractError, match="duplicate stored"):
            warehouse.decisions()
