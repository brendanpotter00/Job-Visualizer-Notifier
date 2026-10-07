"""Deterministic scoring (CONTRACT §6.6): VC tiers, exit-only founder signal, null talent."""

from launch_radar.scoring import score_talent, score_vc


def _brief(leads=(), others=(), amount=None, prior=()):
    return {
        "latest_round": {"stage": "Series A", "amount_usd": amount, "announced_at": "2026-09-17",
                         "lead_investors": list(leads), "other_investors": list(others)},
        "prior_rounds": [{"stage": "Seed", "amount_usd": None, "announced_at": None, "investors": p} for p in prior],
    }


def _leader(name="Ada Lovelace", *, schools=(), prior=(), founded=(), years=None, conf=None):
    return {"name": name, "schools": list(schools), "prior_companies": list(prior), "founded_raw": list(founded),
            "years": years, "confidence": conf or {}}


# ---- VC ---------------------------------------------------------------------------------
def test_vc_raindrop_example_matches_poc_points():
    # CRV led (tier 2 lead = 35), Lightspeed joined (tier 1 participant = 45), $35M -> +10.
    score, reasons = score_vc(_brief(leads=["CRV"], others=["Lightspeed Venture Partners"], amount="$35M"))
    assert score == 55
    assert reasons == ["Lightspeed joined (tier 1)", "CRV led (tier 2)", "round over $20M"]


def test_vc_tier1_lead_plus_extra_tier1_investors():
    score, reasons = score_vc(_brief(leads=["Sequoia Capital"], others=["Accel", "Benchmark"]))
    assert score == 60 + 20
    assert "Sequoia led (tier 1)" in reasons
    assert "+2 more tier-1 investors" in reasons


def test_vc_yc_participant_and_prior_round_investors_count():
    score, reasons = score_vc(_brief(prior=["Y Combinator, SV Angel"]))
    # SV Angel is tier 2 participant (25); YC participant 15 -> best 25.
    assert score == 25
    assert "Y Combinator joined" in reasons
    assert "SV Angel joined (tier 2)" in reasons


def test_vc_untiered_named_investors():
    score, reasons = score_vc(_brief(leads=["Some Family Office"]))
    assert score == 10
    assert reasons == ["named investors, none tiered"]


def test_vc_amount_only():
    score, reasons = score_vc(_brief(amount="$60 million"))
    assert score == 15
    assert reasons == ["round over $50M"]


def test_vc_none_without_brief_or_data():
    assert score_vc(None) == (None, [])
    assert score_vc({}) == (None, [])
    assert score_vc(_brief(amount="undisclosed")) == (None, [])


def test_vc_capped_at_100():
    leads = ["Sequoia", "a16z", "Benchmark", "Accel", "Founders Fund"]
    score, _ = score_vc(_brief(leads=leads, others=["Felicis", "CRV", "Neo", "8VC"], amount="$100M"))
    assert score == 100


# ---- talent -------------------------------------------------------------------------------
def test_talent_null_when_no_people_data():
    assert score_talent([]) == (None, [])
    assert score_talent([_leader(), _leader("Grace Hopper")]) == (None, [])


def test_talent_zero_when_data_but_no_signal():
    score, reasons = score_talent([_leader(schools=["State College BS"], years=3)])
    assert score == 0
    assert reasons == []


def test_founding_without_exit_scores_nothing():
    founded = [{"company": "Foo", "outcome": "operating", "acquirer": None, "exit_year": None},
               {"company": "Bar", "outcome": "shut_down", "acquirer": None, "exit_year": None}]
    score, reasons = score_talent([_leader(founded=founded, conf={"founded_before": "high"})])
    assert score == 0
    assert not any("exit" in r for r in reasons)


def test_prior_exit_counts_with_acquirer():
    founded = [{"company": "Ledgerline", "outcome": "acquired", "acquirer": "Northwind", "exit_year": "2025"}]
    score, reasons = score_talent([_leader("Taylor Brooks", founded=founded, conf={"founded_before": "high"})])
    assert score == 15
    assert reasons == ["Taylor Brooks: prior exit (Ledgerline, acquired by Northwind)"]


def test_medium_confidence_weighs_80_percent():
    score, reasons = score_talent([_leader("Priya Raman", schools=["UC Berkeley BS CS"],
                                           conf={"education": "medium"})])
    assert score == round(8 * 0.8)
    assert "Priya Raman: top school (Berkeley)" in reasons
    assert reasons[-1] == "medium-confidence facts count at 80%"


def test_missing_confidence_is_treated_as_medium():
    score, _ = score_talent([_leader(prior=["Google (Engineer)"])])
    assert score == 8  # 10 * 0.8


def test_ten_plus_years_and_caps():
    leaders = [_leader(f"Person {i}", schools=["Stanford"], prior=["Stripe"], years=12,
                       conf={"education": "high", "prior_roles": "high", "years_experience": "high"})
               for i in range(5)]
    score, reasons = score_talent(leaders)
    # schools 5*8=40 -> cap 24; employers 5*10=50 -> cap 30; years 5*5=25 -> cap 10.
    assert score == 24 + 30 + 10
    assert "Person 0: 10+ years" in reasons
    assert "top schools capped at 24" in reasons
    assert "top employers capped at 30" in reasons


def test_case_sensitive_acronyms_do_not_false_match():
    # "mit" inside a word or lowercase must not count as MIT.
    score, _ = score_talent([_leader(schools=["Smith College"], conf={"education": "high"})])
    assert score == 0
