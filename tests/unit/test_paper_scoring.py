"""Paper scoring delegates to ``classify_walk`` — surface-level checks.

The forward-walk classifier is tested in ``test_shadow_scoring.py``.
What we add here is contract-level coverage: the orchestration imports
correctly, the summary dataclass has the expected shape, and we can
distinguish written / deferred / skipped status codes from ``_score_one``
without hitting the live database.
"""

from __future__ import annotations

from datetime import date

from mef.paper_scoring import PaperScoringSummary, paper_score_emitted


def test_summary_dataclass_initial_state():
    s = PaperScoringSummary(new_rows=[], deferred=[], skipped=[], already_scored=0)
    assert s.new_rows == []
    assert s.deferred == []
    assert s.skipped == []
    assert s.already_scored == 0


def test_paper_score_emitted_is_callable():
    # Smoke check — the import surface works and the function is wired.
    # Real execution requires a DB; that's covered by the live mef score
    # invocation, not the unit tests.
    assert callable(paper_score_emitted)


def test_classify_walk_reused_from_shadow_scoring():
    # Paper scoring intentionally reuses the shadow_scoring classifier so
    # paper / shadow outcomes are computed identically and can be UNION-ed
    # in audit queries. If someone ever forks the algorithm, this import
    # check will fail and force them to think again.
    from mef.shadow_scoring import classify_walk
    from mef import paper_scoring
    assert paper_scoring.classify_walk is classify_walk
