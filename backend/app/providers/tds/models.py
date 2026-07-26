from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class TDSProfileEndpoint(BaseModel):
    method: Literal["GET"]
    path: str
    fields: str
    data_field: str
    username_field: str
    balance_field: str
    secondary_balance_field: str
    facebook_id_field: str


class TDSJobResponseMapping(BaseModel):
    jobs_field: str
    cache_field: str
    external_id_field: str
    code_field: str
    action_field: str


class TDSJobProfile(BaseModel):
    key: str
    display_name: str
    provider: Literal["tds"]
    platform: Literal["facebook"]
    job_method: Literal["GET"]
    job_path: str
    job_field: str
    claim_method: Literal["GET"]
    claim_path: str
    claim_type: str
    id_format: Literal["job.code"]
    settlement_type: str
    settlement_id: str
    settlement_threshold: int = Field(gt=0)
    url_template: str
    response_mapping: TDSJobResponseMapping
    minimum_claim_wait_seconds: int = Field(ge=0)
    enabled: bool
    verification_status: Literal["GO", "PILOT"] = "GO"
    verified_at: str
    fixture_version: str

    @field_validator("url_template")
    @classmethod
    def validate_url_template(cls, value: str) -> str:
        if not value.startswith("https://www.facebook.com/") or "{external_id}" not in value:
            raise ValueError("url_template must be an HTTPS Facebook URL with {external_id}")
        return value


class TDSProviderConfig(BaseModel):
    version: int = Field(gt=0)
    profile: TDSProfileEndpoint
    profiles: list[TDSJobProfile]

    @model_validator(mode="after")
    def unique_profile_keys(self) -> TDSProviderConfig:
        keys = [profile.key for profile in self.profiles]
        if len(keys) != len(set(keys)):
            raise ValueError("TDS profile keys must be unique")
        return self

    def get_enabled_profile(self, key: str) -> TDSJobProfile:
        for profile in self.profiles:
            if profile.key == key and profile.enabled:
                return profile
        raise ValueError(f"Unknown or disabled TDS profile: {key}")


class TDSProfileResult(BaseModel):
    username: str
    balance: int = Field(ge=0)
    secondary_balance: int = Field(ge=0)
    facebook_id: str
    raw: dict[str, Any]


class TDSJob(BaseModel):
    external_id: str
    code: str
    action: str
    url: str
    raw: dict[str, Any]


class TDSJobsResult(BaseModel):
    jobs: list[TDSJob]
    cache_count: int = Field(ge=0)

    @property
    def no_jobs(self) -> bool:
        return not self.jobs


class TDSClaimStatus(StrEnum):
    CACHE_ACCEPTED = "CACHE_ACCEPTED"
    SETTLED = "SETTLED"


class TDSClaimResult(BaseModel):
    status: TDSClaimStatus
    cache_count: int | None = Field(default=None, ge=0)
    balance: int | None = Field(default=None, ge=0)
    jobs_success: int | None = Field(default=None, ge=0)
    points_earned: int | None = Field(default=None, ge=0)
    message: str | None = None
    raw: dict[str, Any]


class TDSRequestContext(BaseModel):
    account_id: UUID
    session_id: UUID | None = None
    job_id: UUID | None = None


def load_provider_config(path: Path | None = None) -> TDSProviderConfig:
    config_path = path or Path(__file__).parents[3] / "config" / "job_profiles.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    return TDSProviderConfig.model_validate(payload)
