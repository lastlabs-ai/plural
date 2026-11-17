"""How far a Trial's result can be trusted, from how it ran.

A tier is computed for every Trial from facts the engine observed, never from
anything the Harness reported:

- ``verified``: the App host ran as its own OS user, the network was enforced
  as requested (``no-network`` or ``allowlist``), the image is pinned, the
  provider passed the conformance suite, and the host signed its report.
- ``standard``: the App host was isolated, but something above is missing,
  such as an open network or no conformance report.
- ``unverified``: the ``local`` Runtime, or an App host that shared an OS user
  with the Agent.

Each tier below ``verified`` carries one-line reasons a person can act on.
"""

from __future__ import annotations

from typing import Literal

from plural.common import FrozenModel

TrustTier = Literal["verified", "standard", "unverified"]
ConformanceStatus = Literal["passed", "failed", "missing"]


class TrustFacts(FrozenModel):
    """What the engine observed about where and how a Trial ran.

    Attributes:
        provider: Sandbox provider name, such as ``"daytona"``.
        app_isolation: ``"os_user"`` or ``"none"``; ``None`` when the
            Environment has no Apps, so there was no App host to isolate.
        network: The network mode the sandbox was created with.
        image_identity: The image or snapshot the sandbox started from, as the
            provider reported it.
        image_pinned: Whether that identity names exactly one image, such as a
            digest or an immutable snapshot.
        snapshot: The snapshot name, when one was used.
        conformance: Whether the provider passed the conformance suite at this
            provider version: ``"passed"``, ``"failed"``, or ``"missing"``.
        conformance_failures: Check ids that failed, such as ``("NET-2",)``.
        host_report_signed: Whether the App host's report carried this
            Trial's signature; ``None`` without Apps.
    """

    provider: str
    app_isolation: Literal["os_user", "none"] | None = None
    network: str = "public"
    image_identity: str | None = None
    image_pinned: bool = False
    snapshot: str | None = None
    conformance: ConformanceStatus = "missing"
    conformance_failures: tuple[str, ...] = ()
    host_report_signed: bool | None = None


class TrustAssessment(FrozenModel):
    """A Trial's trust tier and why it is not higher.

    Attributes:
        tier: ``verified``, ``standard``, or ``unverified``.
        reasons: One line per fact that kept the tier down. Empty when
            ``verified``.
        facts: The facts the tier was computed from.
    """

    tier: TrustTier
    reasons: tuple[str, ...] = ()
    facts: TrustFacts


def trust_tier(facts: TrustFacts) -> TrustAssessment:
    """Compute the trust tier for one Trial.

    Args:
        facts: What the engine observed about the Trial's sandbox.

    Returns:
        The tier, with a reason for each fact that kept it below ``verified``.

    Examples:
        >>> facts = TrustFacts(
        ...     provider="daytona",
        ...     app_isolation="os_user",
        ...     network="allowlist",
        ...     image_identity="plural-sandbox-py312",
        ...     image_pinned=True,
        ...     conformance="passed",
        ...     host_report_signed=True,
        ... )
        >>> trust_tier(facts).tier
        'verified'
        >>> trust_tier(TrustFacts(provider="local", app_isolation="none")).tier
        'unverified'
    """
    blocking: list[str] = []
    if facts.provider == "local":
        blocking.append("local Runtime: the Agent ran as you, on this machine")
    if facts.app_isolation == "none":
        blocking.append("the App host shared an OS user with the Agent")
    elif facts.app_isolation is None:
        blocking.append("the App host never started, so its isolation was not observed")
    if blocking:
        return TrustAssessment(tier="unverified", reasons=tuple(blocking), facts=facts)

    reasons: list[str] = []
    if facts.network == "public":
        reasons.append("open internet during the episode")
    elif facts.network not in {"no-network", "allowlist"}:
        reasons.append(f"network {facts.network!r} is not enforced by the provider")
    if not facts.image_identity:
        reasons.append("the image identity was not recorded")
    elif not facts.image_pinned:
        reasons.append(f"image {facts.image_identity} is not pinned to a digest or snapshot")
    if facts.conformance == "missing":
        reasons.append(
            f"no conformance report for {facts.provider}; run plural runtime doctor --conformance"
        )
    elif facts.conformance == "failed":
        failed = ", ".join(facts.conformance_failures) or "some checks"
        reasons.append(f"{facts.provider} failed conformance: {failed}")
    if facts.host_report_signed is False:
        reasons.append("the App host's report was not signed")
    elif facts.host_report_signed is None:
        reasons.append("the App host did not finish its report")
    if reasons:
        return TrustAssessment(tier="standard", reasons=tuple(reasons), facts=facts)
    return TrustAssessment(tier="verified", facts=facts)


__all__ = ["ConformanceStatus", "TrustAssessment", "TrustFacts", "TrustTier", "trust_tier"]
