"""Runtime execution-policy helpers for workflow previews and runs."""

from typing import Any, Literal

ExecutionPolicy = Literal["safe", "fast"]
PreviewBasis = Literal["safe_sandbox", "fast_static"]


def normalize_execution_policy(value: Any) -> ExecutionPolicy:
    if isinstance(value, str) and value.strip().lower() == "fast":
        return "fast"
    return "safe"


def execution_policy_from_deps(deps: Any) -> ExecutionPolicy:
    return normalize_execution_policy(getattr(deps, "execution_policy", None))


def preview_basis_for_policy(policy: ExecutionPolicy) -> PreviewBasis:
    return "fast_static" if policy == "fast" else "safe_sandbox"


def preview_requires_sandbox(policy: ExecutionPolicy) -> bool:
    return policy == "safe"
