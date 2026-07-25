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
