"""Completeness evidence a client surfaces alongside its harvested rows (E7).

Kept deliberately dependency-free: it is imported by the ATS clients
(``greenhouse_client`` / ``workday_client`` / ``eightfold_client``) *and* by
``harvest_verification`` (the gate). If it imported either of those a cycle would
form, so it imports neither — just the stdlib ``dataclasses``.

``HarvestEvidence`` is the second half of a client's return in the custom path:
the client returns ``(rows, HarvestEvidence)`` and the gate reads the evidence to
run BUILD-PLAN §3 checks 1, 5, 6, 9, 11 (transport, cap-not-hit, page-advance,
oracle-within-tolerance, zero-proof). The six PUBLIC ATS crons never see this —
they call the unchanged ``fetch_jobs`` and discard the meta.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HarvestEvidence:
    """Completeness signals a client observed beyond the row list.

    Attributes:
        declared_total: The ATS API's own independent total, when it exposes a
            trustworthy one (Greenhouse ``meta.total``, Workday ``total``). For
            an ATS with no trustworthy total (Ashby/Lever/Gem) this is ``None``.
            Eightfold's ``count`` is recorded here as *evidence only* — the gate
            treats Eightfold as ``self_consistent`` and never trusts ``count`` as
            the oracle (it is documented to over/under-report).
        cap_hit: The pagination loop stopped on the client's safety ceiling
            (Workday 2,000 / Eightfold 1,000) rather than a natural terminus.
            Maps to check 5 → UNVERIFIED.
        terminated_cleanly: The loop ended on reached-total / short page / empty
            page — i.e. NOT a cap. The self-consistency oracle requires this.
        page_advance_ok: For a paginated fetch, every page's id-set was disjoint
            from the union of prior pages (check 6). ``None`` for a single-shot
            ATS (no pagination to check — vacuously satisfied). ``False`` on an
            offset-wrap (Intel) → UNVERIFIED.
        pages_fetched: How many pages the loop issued (1 for single-shot).
        transport_ok: The HTTP status was in the allowed set (check 1). A
            transport failure raises upstream before evidence is ever built, so
            this is ``True`` on every constructed instance; it exists so the
            zero-proof chain can assert "a live 200 declared zero".
    """

    declared_total: int | None
    cap_hit: bool
    terminated_cleanly: bool
    page_advance_ok: bool | None
    pages_fetched: int = 1
    transport_ok: bool = True

    @classmethod
    def single_shot(cls, declared_total: int | None) -> "HarvestEvidence":
        """Evidence for a one-GET ATS (Ashby/Lever/Gem, and Greenhouse).

        A single-shot fetch has no pagination, so it terminates cleanly by
        construction, never hits a cap, and ``page_advance_ok`` is ``None``
        (vacuously ok — there is no page N to compare against page N-1).
        """
        return cls(
            declared_total=declared_total,
            cap_hit=False,
            terminated_cleanly=True,
            page_advance_ok=None,
            pages_fetched=1,
        )
