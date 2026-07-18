"""Typed findings emitted by deterministic workflow assurance checks."""

from dataclasses import dataclass, field
from enum import StrEnum


class FindingSeverity(StrEnum):
    """Whether a finding blocks a workflow build or only records coverage debt."""

    ERROR = "error"
    SHADOW = "shadow"


@dataclass(frozen=True, slots=True)
class AssuranceFinding:
    code: str
    message: str
    severity: FindingSeverity
    node_name: str | None = None
    related_nodes: tuple[str, ...] = ()

    @property
    def blocking(self) -> bool:
        return self.severity is FindingSeverity.ERROR

    def as_log_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
        }
        if self.node_name:
            payload["node_name"] = self.node_name
        if self.related_nodes:
            payload["related_nodes"] = list(self.related_nodes)
        return payload


@dataclass(frozen=True, slots=True)
class AssurancePlan:
    """Deterministic assurance expectations derived from one workflow graph."""

    fingerprint: str
    node_roles: dict[str, str] = field(default_factory=dict)
    cardinality_relations: tuple[str, ...] = field(default_factory=tuple)
    identity_fields: dict[str, tuple[str, ...]] = field(default_factory=dict)
    expected_postconditions: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class AssuranceReport:
    fingerprint: str
    plan: AssurancePlan
    findings: tuple[AssuranceFinding, ...] = field(default_factory=tuple)

    @property
    def blocking_findings(self) -> tuple[AssuranceFinding, ...]:
        return tuple(finding for finding in self.findings if finding.blocking)

    @property
    def shadow_findings(self) -> tuple[AssuranceFinding, ...]:
        return tuple(finding for finding in self.findings if not finding.blocking)
