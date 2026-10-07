from dataclasses import dataclass


@dataclass(frozen=True)
class Principal:
    """Identity and memberships supplied by a trusted upstream boundary."""

    user_id: str
    tenant_ids: frozenset[str]
