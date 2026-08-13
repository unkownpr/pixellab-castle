from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter


SCHEMA_VERSION = "1.1"
MAX_IDENTITY_LENGTH = 128
MAX_PAYLOAD_BYTES = 16 * 1024


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VersionedModel(ContractModel):
    schema_version: Literal["1.1"] = SCHEMA_VERSION


class CreateMatchRequest(ContractModel):
    scenario_id: str = "basic-survival-v1"
    seed: int = 17
    colony_count: int = Field(default=4, ge=1, le=8)


class CreateMatchResponse(VersionedModel):
    match_id: str
    scenario_id: str
    controller_tokens: dict[str, str]
    admin_token: str


class CreateSessionRequest(ContractModel):
    scenario_id: str = "basic-survival-v1"
    seed: int = 17
    colony_count: int = Field(default=4, ge=1, le=8)
    deadline_seconds: int = Field(default=30, ge=1, le=300)
    slots: list["SessionSlotConfiguration"] = Field(default_factory=list, max_length=8)


class SessionSlotConfiguration(ContractModel):
    colony_id: str = Field(min_length=1, max_length=MAX_IDENTITY_LENGTH)
    controller_type: Literal["human", "baseline", "external"]
    baseline_kind: str | None = Field(default=None, max_length=MAX_IDENTITY_LENGTH)


class CreateSessionResponse(VersionedModel):
    match_id: str
    scenario_id: str
    status: Literal["draft"]
    admin_token: str


class ControllerIdentityRequest(ContractModel):
    display_name: str = Field(min_length=1, max_length=MAX_IDENTITY_LENGTH)
    provider: str = Field(min_length=1, max_length=MAX_IDENTITY_LENGTH)
    model: str = Field(min_length=1, max_length=MAX_IDENTITY_LENGTH)
    model_version: str | None = Field(default=None, max_length=MAX_IDENTITY_LENGTH)
    adapter_name: str | None = Field(default=None, max_length=MAX_IDENTITY_LENGTH)
    adapter_version: str | None = Field(default=None, max_length=MAX_IDENTITY_LENGTH)
    connection_mode: str | None = Field(default=None, max_length=MAX_IDENTITY_LENGTH)
    run_label: str | None = Field(default=None, max_length=MAX_IDENTITY_LENGTH)


class ControllerIdentityResponse(ContractModel):
    display_name: str = Field(max_length=MAX_IDENTITY_LENGTH)
    provider: str = Field(max_length=MAX_IDENTITY_LENGTH)
    model: str = Field(max_length=MAX_IDENTITY_LENGTH)
    model_version: str | None = Field(default=None, max_length=MAX_IDENTITY_LENGTH)
    adapter_name: str | None = Field(default=None, max_length=MAX_IDENTITY_LENGTH)
    adapter_version: str | None = Field(default=None, max_length=MAX_IDENTITY_LENGTH)
    connection_mode: str | None = Field(default=None, max_length=MAX_IDENTITY_LENGTH)
    run_label: str | None = Field(default=None, max_length=MAX_IDENTITY_LENGTH)


class PairingGrantResponse(VersionedModel):
    match_id: str
    colony_id: str
    pairing_code: str
    expires_at: float


class ClaimSlotRequest(ContractModel):
    pairing_code: str = Field(min_length=1, max_length=256)
    identity: ControllerIdentityRequest


class ClaimSlotResponse(VersionedModel):
    match_id: str
    controller_id: str
    colony_id: str
    controller_token: str


class HeartbeatRequest(ContractModel):
    turn: int = Field(ge=0)
    status: Literal["ready", "connected", "thinking", "submitted", "disconnected"]


class HeartbeatResponse(VersionedModel):
    match_id: str
    status: Literal["ready", "connected", "thinking", "submitted", "disconnected"]


class ReplaceControllerRequest(ContractModel):
    replacement: Literal["human", "baseline", "external"]
    baseline_kind: str | None = Field(default=None, max_length=MAX_IDENTITY_LENGTH)


class ConfigureSlotRequest(ContractModel):
    controller_type: Literal["human", "baseline", "external"]
    baseline_kind: str | None = Field(default=None, max_length=MAX_IDENTITY_LENGTH)


class MutationResponse(VersionedModel):
    match_id: str
    status: str


class ReplacementResponse(MutationResponse):
    colony_id: str


class SlotConfigurationResponse(VersionedModel):
    match_id: str
    colony_id: str
    controller_type: Literal["human", "baseline", "external"]
    presence: str


class HumanControllerCapabilityResponse(VersionedModel):
    match_id: str
    colony_id: str
    controller_token: str


class OperationsWebSocketTicketResponse(VersionedModel):
    match_id: str
    websocket_ticket: str
    expires_at: float


class LobbySlotResponse(ContractModel):
    colony_id: str
    controller_type: Literal["human", "baseline", "external"]
    controller_id: str | None
    identity: ControllerIdentityResponse | None
    presence: str
    baseline_kind: str | None
    generation: int
    pairing_active: bool
    pairing_expires_at: float | None
    pairing_consumed: bool
    pairing_attempts: int
    last_heartbeat_at: float | None
    last_heartbeat_turn: int | None


class LobbySnapshotResponse(VersionedModel):
    match_id: str
    scenario_id: str
    seed: int
    colony_count: int
    deadline_seconds: int
    status: str
    slots: list[LobbySlotResponse]


class OperationsSnapshotResponse(LobbySnapshotResponse):
    turn: int
    deadline_at: float | None
    pending_colonies: tuple[str, ...]
    events: list["OperationalEventResponse"]
    tenures: dict[str, list["ControllerTenureResponse"]]


class DomainEventResponse(ContractModel):
    turn: int
    kind: str
    colony_id: str | None = None
    data: dict[str, JsonValue]


class OperationalEventResponse(DomainEventResponse):
    sequence: int = Field(ge=1)


class ControllerTenureResponse(ContractModel):
    colony_id: str
    controller_id: str
    controller_type: Literal["human", "baseline", "external"]
    identity: ControllerIdentityResponse | None
    generation: int = Field(ge=0)
    started_at: float
    ended_at: float | None


class SubmitActionsRequest(ContractModel):
    turn: int = Field(ge=0)
    actions: list[dict[str, JsonValue]] = Field(min_length=1, max_length=16)


class SubmissionResponse(VersionedModel):
    status: Literal["pending", "resolved"]
    turn: int
    waiting_for: tuple[str, ...] = ()
    events: tuple[DomainEventResponse, ...] = ()


class MatchStatusResponse(VersionedModel):
    match_id: str
    scenario_id: str
    turn: int
    terminal: bool
    termination_reason: str | None
    pending_colonies: tuple[str, ...]
    scope: str


class ReportStatusResponse(ContractModel):
    match_id: str
    scenario_id: str
    turn: int
    terminal: bool
    termination_reason: str | None
    pending_colonies: tuple[str, ...]
    scope: str


class SurvivalMetricResponse(ContractModel):
    turns: int
    population: int


class GrowthMetricResponse(ContractModel):
    initial_population: int
    peak_population: int
    housing: int


class ResourceMetricResponse(ContractModel):
    food: int
    water: int
    wood: int
    stone: int
    ore: int
    tools: int
    influence: int


class ProsperityMetricResponse(ContractModel):
    resources: ResourceMetricResponse


class DecisionQualityMetricResponse(ContractModel):
    invalid_actions: int


class CostMetricResponse(ContractModel):
    model_calls: int
    mcp_calls: int
    input_tokens: int
    output_tokens: int
    latency_ms: int
    timeouts: int = 0
    reconnects: int = 0


class PresenceMetricResponse(ContractModel):
    timeouts: dict[str, int]
    reconnects: dict[str, int]
    tenures: dict[str, list[ControllerTenureResponse]]


class ServerMeasuredResponse(ContractModel):
    mcp_calls: int
    timeouts: int = 0
    reconnects: int = 0


class AdapterReportedUsageResponse(ContractModel):
    model_calls: int
    input_tokens: int
    output_tokens: int
    latency_ms: int


class AggregateServerMeasuredResponse(ContractModel):
    mcp_calls: dict[str, int] = Field(default_factory=dict)
    invocations_total: int = 0
    invocations_by_tool: dict[str, int] = Field(default_factory=dict)


class ServerInvocationTelemetryResponse(VersionedModel):
    invocations_total: int
    invocations_by_tool: dict[str, int]


class ControllerTenureMetricResponse(ControllerTenureResponse):
    server_measured: ServerMeasuredResponse
    adapter_reported_model_usage: AdapterReportedUsageResponse


class BenchmarkMetricsResponse(ContractModel):
    survival: dict[str, SurvivalMetricResponse]
    growth: dict[str, GrowthMetricResponse]
    prosperity: dict[str, ProsperityMetricResponse]
    trade: dict[str, int]
    aggression: dict[str, int]
    decision_quality: dict[str, DecisionQualityMetricResponse]
    cost: dict[str, CostMetricResponse]
    presence: PresenceMetricResponse | None = None
    server_measured: AggregateServerMeasuredResponse | None = None
    adapter_reported_model_usage: dict[str, AdapterReportedUsageResponse] | None = None
    tenure_metrics: dict[str, list[ControllerTenureMetricResponse]] | None = None


class RunReportResponse(VersionedModel):
    status: ReportStatusResponse
    metrics: BenchmarkMetricsResponse
    latest_events: tuple[DomainEventResponse, ...]


class MetricUpdatedPayload(ContractModel):
    event: OperationalEventResponse
    metrics: BenchmarkMetricsResponse


class LobbySnapshotMessage(VersionedModel):
    type: Literal["lobby.snapshot"]
    payload: OperationsSnapshotResponse


class ControllerPresenceMessage(VersionedModel):
    type: Literal["controller.presence_changed"]
    payload: OperationalEventResponse


class TurnOpenedMessage(VersionedModel):
    type: Literal["turn.opened"]
    payload: OperationalEventResponse


class ControllerSubmittedMessage(VersionedModel):
    type: Literal["controller.submitted"]
    payload: OperationalEventResponse


class TurnResolvedMessage(VersionedModel):
    type: Literal["turn.resolved"]
    payload: OperationalEventResponse


class MetricUpdatedMessage(VersionedModel):
    type: Literal["metric.updated"]
    payload: MetricUpdatedPayload


class MatchCompletedMessage(VersionedModel):
    type: Literal["match.completed"]
    payload: OperationalEventResponse


class ControllerClaimedMessage(VersionedModel):
    type: Literal["controller.claimed"]
    payload: OperationalEventResponse


class PairingRejectedMessage(VersionedModel):
    type: Literal["pairing.rejected"]
    payload: OperationalEventResponse


class ControllerHeartbeatRejectedMessage(VersionedModel):
    type: Literal["controller.heartbeat_rejected"]
    payload: OperationalEventResponse


class ControllerTimedOutMessage(VersionedModel):
    type: Literal["controller.timed_out"]
    payload: OperationalEventResponse


class ControllerReplacedMessage(VersionedModel):
    type: Literal["controller.replaced"]
    payload: OperationalEventResponse


AdminWebSocketMessage = Annotated[
    LobbySnapshotMessage
    | ControllerPresenceMessage
    | TurnOpenedMessage
    | ControllerSubmittedMessage
    | TurnResolvedMessage
    | MetricUpdatedMessage
    | MatchCompletedMessage
    | ControllerClaimedMessage
    | PairingRejectedMessage
    | ControllerHeartbeatRejectedMessage
    | ControllerTimedOutMessage
    | ControllerReplacedMessage,
    Field(discriminator="type"),
]

ADMIN_WEBSOCKET_MESSAGE_ADAPTER = TypeAdapter(AdminWebSocketMessage)


def ensure_secret_free(payload: object) -> None:
    """Reject capability-shaped keys recursively, including inside open event data."""
    forbidden = {
        "admin_token",
        "controller_token",
        "orchestrator_token",
        "pairing_code",
        "admin_capability_digest",
        "capability_digest",
        "pairing_digest",
    }
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized = str(key).lower()
            if normalized in forbidden or normalized.endswith(
                ("_token", "_digest", "_secret")
            ):
                raise ValueError("unsafe response projection")
            ensure_secret_free(value)
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            ensure_secret_free(value)


def project_lobby_snapshot(payload: dict[str, object]) -> LobbySnapshotResponse:
    """Fail closed when a service lobby projection grows an unreviewed field."""
    ensure_secret_free(payload)
    return LobbySnapshotResponse.model_validate(
        {**payload, "schema_version": SCHEMA_VERSION}
    )


def project_match_status(payload: dict[str, object]) -> MatchStatusResponse:
    """Fail closed when a service status projection grows an unreviewed field."""
    ensure_secret_free(payload)
    return MatchStatusResponse.model_validate(
        {**payload, "schema_version": SCHEMA_VERSION}
    )


def project_run_report(payload: dict[str, object]) -> RunReportResponse:
    """Fail closed when a service report projection grows an unreviewed field."""
    ensure_secret_free(payload)
    return RunReportResponse.model_validate(
        {**payload, "schema_version": SCHEMA_VERSION}
    )
