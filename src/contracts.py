from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ModelId = Literal["MDL_CREDIT_V1", "MDL_CREDIT_V2", "MDL_CREDIT_TREE"]
MigrationModelId = Literal["MDL_CREDIT_V1"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class InventorySource(StrictModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    excerpt: str = Field(min_length=1)

    def validate_range(self) -> None:
        if self.line_end < self.line_start:
            raise ValueError("line_end must be >= line_start")


class ModelInventory(StrictModel):
    schema_version: Literal["1"]
    run_id: str
    model_id: ModelId
    model_type: str
    owner: str
    training_date: str
    feature_order: list[str]
    code_threshold: float
    documented_threshold: float
    unknowns: list[str]
    conflicts: list[dict[str, object]]
    sources: list[InventorySource]
    review_status: Literal["PENDING", "APPROVED", "REJECTED"]


class InventoryFinding(StrictModel):
    field: str


class InventoryPayload(StrictModel):
    model_id: ModelId
    model_type: str
    owner: str
    training_date: str
    feature_order: list[str]
    code_threshold: float
    documented_threshold: float
    unknowns: list[str]
    conflicts: list[InventoryFinding]
    sources: list[InventorySource]


class ReviewEntry(StrictModel):
    schema_version: Literal["1"] = "1"
    run_id: str
    gate: Literal["Gate_A", "Gate_B", "Gate_C"]
    decision: Literal["APPROVED", "REJECTED"]
    reviewer: str = Field(min_length=1)
    timestamp: str
    comment: str
    reviewed_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class CandidatePayload(StrictModel):
    model_id: MigrationModelId
    code: str = Field(min_length=1)

    @field_validator("code")
    @classmethod
    def reject_nul(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("Candidate code contains NUL")
        return value


class MigrationResult(StrictModel):
    schema_version: Literal["1"] = "1"
    run_id: str
    model_id: MigrationModelId
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    attempt: int = Field(ge=0, le=2)
    dev_status: Literal["NOT_RUN", "PASS", "FAIL", "BLOCKED"]
    fixture_status: Literal["NOT_RUN", "PASS", "FAIL", "BLOCKED"] = "NOT_RUN"
    final_status: Literal["NOT_RUN", "PASS", "FAIL", "BLOCKED"]
    diagnostics_ref: str | None
    context_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class AcceptanceRecord(StrictModel):
    acceptance_id: str
    version: Literal["v1", "v2"] = "v1"
    expected: str
    actual: str
    status: Literal["PASS", "FAIL", "NOT_RUN", "BLOCKED"]
    evidence_path: str
    reviewer: str
    timestamp: str
    commit_sha: str
