from app.providers.tds.error_mapping import map_provider_error
from app.providers.tds.errors import TDSClaimRejectedError


def test_inactive_tds_job_has_actionable_safe_error() -> None:
    mapped = map_provider_error(
        TDSClaimRejectedError("Không cướp job vui lòng load job")
    )

    assert mapped.code == "TDS_CLAIM_REJECTED"
    assert mapped.status_code == 422
    assert mapped.details == {"reason": "JOB_NOT_ACTIVE_IN_TDS"}
    assert "fresh batch" in mapped.message


def test_invalid_job_exposes_actionable_allowlisted_provider_reason() -> None:
    mapped = map_provider_error(
        TDSClaimRejectedError(
            "Job không hợp lệ",
            response_json={"error": "Job không hợp lệ", "cache": 0},
        )
    )

    assert mapped.code == "TDS_CLAIM_REJECTED"
    assert mapped.status_code == 422
    assert mapped.message.startswith("TDS báo job không hợp lệ")
    assert mapped.details == {
        "reason": "INVALID_JOB",
        "provider_message": "Job không hợp lệ",
        "action": "SKIP_AND_FETCH_FRESH_BATCH",
    }


def test_unknown_claim_rejection_does_not_expose_provider_payload() -> None:
    mapped = map_provider_error(
        TDSClaimRejectedError(
            "Unexpected provider text",
            response_json={"error": "Unexpected provider text"},
        )
    )

    assert mapped.message == "TDS rejected the claim"
    assert mapped.details == {"reason": "PROVIDER_REJECTED"}
