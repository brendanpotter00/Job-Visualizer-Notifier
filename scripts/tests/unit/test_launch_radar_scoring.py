"""Deterministic scoring (CONTRACT §6.6): VC tiers, exit-only founder signal, null talent,
and the 50/50 Talent blend (leaders' half + the team tally's half)."""

import re
from fractions import Fraction

import pytest
from launch_radar.card import build_funding, build_payload
from launch_radar.scoring import (
    LEADERS_MAX,
    TEAM_EMPLOYER_POINTS,
    TEAM_SCHOOL_POINTS,
    blend_talent,
    half_up,
    leaders_part,
    rescored_scores,
    score_talent,
    score_team,
    score_vc,
    talent_scores,
)


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


# ---- the 50/50 blend: leaders' half -------------------------------------------------------
def test_leaders_max_is_the_sum_of_the_rubric_caps():
    assert LEADERS_MAX == 24 + 30 + 30 + 10 == 94


@pytest.mark.parametrize("raw,part", [(94, 50), (70, 37), (47, 25), (48, 26), (4, 2), (1, 1), (0, 0), (None, None)])
def test_leaders_part_rescales_the_94_point_score_to_50(raw, part):
    assert leaders_part(raw) == part


def test_half_up_never_rounds_half_to_even():
    assert [half_up(x) for x in (12.5, 13.5, 0.5, 0.49, Fraction(5, 2), Fraction(7, 3))] == [13, 14, 1, 0, 3, 2]


# ---- the team's half -----------------------------------------------------------------------
def _team(n=33, schools=(), employers=(), **legacy):
    return {"profiles_found": n, "team_size_estimate": "50-100", "schools": [{"name": a, "count": c} for a, c in schools],
            "prior_employers": [{"name": a, "count": c} for a, c in employers], "sample_names": [], **legacy}


LIGHTFIELD = _team(33, schools=[("Stanford University", 10), ("MIT", 5), ("State University", 4)],
                   employers=[("Google", 6), ("Stripe", 3), ("Acme Corp", 10)])


def test_team_part_is_schools_and_employers_only():
    # Prior exits are a leaders' signal: the team's half is 25 for schools + 25 for employers.
    assert TEAM_SCHOOL_POINTS + TEAM_EMPLOYER_POINTS == 50
    assert TEAM_SCHOOL_POINTS == TEAM_EMPLOYER_POINTS == 25


def test_team_part_is_shares_of_the_profiles_found():
    # 19 schools and 19 employers listed for 33 profiles: the share is over the 33 profiles.
    # schools 25 * (15/33) / (1/2) = 22.7 -> 23; employers 25 * (9/33) / (1/2) = 13.6 -> 14.
    assert score_team(LIGHTFIELD) == (37, ["15 of the 19 schools listed across 33 profiles are top schools (+23)",
                                           "9 of the 19 employers listed across 33 profiles are top employers (+14)"])


def test_shares_beat_headcount():
    small_strong = _team(33, schools=[("Stanford", 15)])
    big_weak = _team(140, schools=[("Stanford", 21)])
    assert score_team(small_strong)[0] > score_team(big_weak)[0]


def test_full_points_at_half_the_profiles_and_shares_capped_at_one():
    assert score_team(_team(20, schools=[("Stanford", 10)], employers=[("OpenAI", 10)]))[0] == 25 + 25
    over = _team(10, schools=[("Stanford", 10), ("MIT", 10), ("Harvard", 10)], employers=[("Google", 25)])
    assert score_team(over) == (50, ["30 of the 30 schools listed across 10 profiles are top schools (+25)",
                                     "25 of the 25 employers listed across 10 profiles are top employers (+25)"])


def test_entries_listed_bound_double_counting():
    # The tally lists schools, not people: 9 school entries and 16 employer entries for 5 profiles.
    # The share is over the entries listed, not the 5 profiles (Bluecore: 1 Columbia, Google + SpaceX).
    bluecore = _team(5, schools=[("Columbia University", 1)] + [(f"School {i}", 1) for i in range(8)],
                     employers=[("Google", 1), ("SpaceX", 1)] + [(f"Firm {i}", 1) for i in range(14)])
    # schools 25 * (1/9) / (1/2) = 5.6 -> 6; employers 25 * (2/16) / (1/2) = 6.25 -> 6.
    assert score_team(bluecore) == (12, ["1 of the 9 schools listed across 5 profiles is a top school (+6)",
                                         "2 of the 16 employers listed across 5 profiles are top employers (+6)"])
    # Two top schools for one person can no longer max the share on their own.
    # 25 * (2/7) / (1/2) = 14.3 -> 14 (it was 2 of 5 profiles, 20, when the share was over the profiles).
    assert score_team(_team(5, schools=[("Imperial College", 1), ("Oxford", 1)] + [("Local U", 1)] * 5,
                            employers=[("Acme", 5)]))[0] == 14


@pytest.mark.parametrize("n,schools,employers", [
    (25, [("Stanford", 4), ("MIT", 3), ("State U", 2)], [("Google", 4)] + [("Firm", 1)] * 19),  # Composio-like
    (25, [("Stanford", 7), ("Local", 18)], [("Meta", 4), ("Acme", 21)]),
    (18, [("Tsinghua", 5), ("Local", 11)], [("Microsoft", 2), ("Acme", 9)]),  # StepFun-like
    (23, [("Stanford", 5), ("Local", 22)], [("Apple", 1), ("Acme", 20)]),  # Poseidon-like
    (33, [("Stanford", 15), ("Local", 33)], [("Google", 9), ("Acme", 12)]),
    (27, [("Stanford", 4), ("Local", 23)], [("Meta", 5), ("Acme", 22)]),
    (9, [], [("Google", 2), ("Acme", 4)]),
    (3, [("MIT", 1)], [("Apple", 1), ("Acme", 2)]),
])
def test_reason_points_add_up_to_the_team_part(n, schools, employers):
    score, reasons = score_team(_team(n, schools=schools, employers=employers))
    shown = [int(m) for r in reasons for m in re.findall(r"\(\+(\d+)\)$", r)]
    if n >= 5:
        assert sum(shown) == score
    else:  # a small sample scales the summed points; the line says by how much
        assert score == half_up(Fraction(n, 5) * sum(shown))


def test_each_side_is_rounded_once_and_the_part_is_their_sum():
    # 25 * (4/27) * 2 = 7.4 -> 7; 25 * (5/27) * 2 = 9.3 -> 9: the part is 16, not half_up(16.7) = 17.
    score, reasons = score_team(_team(27, schools=[("Stanford", 4), ("Local", 23)],
                                      employers=[("Meta", 5), ("Acme", 22)]))
    assert score == 16 and [re.findall(r"\(\+\d+\)$", r)[0] for r in reasons] == ["(+7)", "(+9)"]


@pytest.mark.parametrize("exits", [0, 1, 2, 6, None])
def test_a_stored_ex_founder_count_is_ignored(exits):
    # Cards tallied before 2026-10-07 carry ex_founders_with_exit. The team is not checked for
    # prior exits (the leaders are), so the count never scores and no reason line mentions it.
    plain = _team(10, schools=[("Stanford", 2), ("State U", 3)], employers=[("Acme", 3)])
    old = _team(10, schools=[("Stanford", 2), ("State U", 3)], employers=[("Acme", 3)], ex_founders_with_exit=exits)
    assert score_team(old) == score_team(plain) == (10, ["2 of the 5 schools listed across 10 profiles are top schools (+10)",
                                                         "none of the 3 employers listed across 10 profiles is a top employer"])
    assert not any("exit" in r or "founder" in r for r in score_team(old)[1])
    assert talent_scores([], old) == talent_scores([], plain)


def test_small_samples_count_proportionally_and_the_rest_follows_the_leaders():
    # 1 of 3 at a top school: 25 * (1/3) / (1/2) = 16.7 -> 17; the same for employers; 34 x 0.6 = 20.4 -> 20.
    assert score_team(_team(3, schools=[("Stanford", 1)], employers=[("Google", 1)])) == (
        20, ["the 1 school listed across 3 profiles is a top school (+17)",
             "the 1 employer listed across 3 profiles is a top employer (+17)",
             "only 3 profiles found: counts at 60%"])
    # With a leaders' part the other 40% follows it: 0.6 * 34 + 0.4 * 12 = 25.2 -> 25.
    score, reasons = score_team(_team(3, schools=[("Stanford", 1)], employers=[("Google", 1)]), leaders=12)
    assert score == 25
    assert reasons[-1] == "only 3 profiles found: counts at 60%, the other 40% follows the leaders' part (12)"
    score, reasons = score_team(_team(1, schools=[("MIT", 1)], employers=[("Apple", 1)]))
    assert score == half_up((25 + 25) * Fraction(1, 5)) == 10
    assert reasons[-1] == "only 1 profile found: counts at 20%"
    assert "the 1 school listed across 1 profile is a top school (+25)" in reasons
    assert not any("counts at" in r for r in score_team(_team(5, schools=[("MIT", 1)]))[1])


@pytest.mark.parametrize("leaders,team_part", [(2, 2), (14, 11), (30, 24)])
def test_one_profile_with_no_hit_is_not_full_negative_evidence(leaders, team_part):
    # Cleavr: 1 profile, nothing on the lists. 0.2 * 0 + 0.8 * L: the card scores about the
    # leaders-only 2L (Cleavr 2 + 2 = 4, its leaders-only score), not L + 0.
    team = _team(1, schools=[("Local U", 1)], employers=[("Acme", 6)])
    score, reasons = score_team(team, leaders=leaders)
    assert score == team_part == half_up(Fraction(4, 5) * leaders)
    assert talent_scores([], team)["talent"] == 0  # no leaders' part to follow: the rest is 0, as stated
    assert reasons[-1] == f"only 1 profile found: counts at 20%, the other 80% follows the leaders' part ({leaders})"


@pytest.mark.parametrize("team,reason", [
    (None, "no team tally on this card"),
    (_team(0, schools=[("Stanford", 1)]), "no public profiles found for the rest of the team"),
    (_team(None, schools=[("Stanford", 1)]), "no public profiles found for the rest of the team"),
    # An old tally's exit count does not make a background: still no schools or employers.
    (_team(12, ex_founders_with_exit=2), "the team tally lists no schools or employers"),
    (_team(12, schools=[("Stanford", 0)], employers=[("Acme", 0)]), "the team tally lists no schools or employers"),
])
def test_team_part_is_null_not_zero_without_data(team, reason):
    assert score_team(team) == (None, [reason])


def test_an_empty_side_is_missing_and_the_other_is_scaled_to_fifty():
    # No schools listed: employers (25) are scaled to 50.
    assert score_team(_team(9, employers=[("Acme", 4)])) == (
        0, ["none of the 4 employers listed across 9 profiles is a top employer",
            "no school data listed: employers are scaled to 50"])
    # 50 * min(1, (5/10) / (1/2)) = 50; 50 * (2/10) / (1/2) = 20.
    assert score_team(_team(10, employers=[("Google", 5), ("Acme", 5)]))[0] == 50
    assert score_team(_team(10, employers=[("Google", 2), ("Acme", 8)]))[0] == 20
    # No employers listed: schools by 50/25. Harvard 2 of 4 -> 50; 4 profiles at 80% -> 40.
    assert score_team(_team(4, schools=[("Harvard Business School Online", 2)])) == (
        40, ["2 of the 2 schools listed across 4 profiles are top schools (+50)",
             "no employer data listed: schools are scaled to 50", "only 4 profiles found: counts at 80%"])
    # 50 * (3/10) / (1/2) = 30.
    assert score_team(_team(10, schools=[("MIT", 3), ("Local U", 7)]))[0] == 30


def test_a_sparse_list_says_what_it_counted():
    # One school listed for 8 profiles: the line names what was listed, not "no top schools on 8 profiles".
    _, reasons = score_team(_team(8, schools=[("Local U", 1)], employers=[("Acme", 11)]))
    assert reasons == ["the 1 school listed across 8 profiles is not a top school",
                       "none of the 11 employers listed across 8 profiles is a top employer"]


def test_malformed_tally_entries_are_ignored():
    team = _team(10, schools=[("Stanford", 5)], employers=[("Acme", 5)])
    team["schools"] += [{"name": "MIT", "count": True}, {"name": "MIT", "count": -3}, "MIT", {"count": 4}]
    assert score_team(team)[0] == 25


# ---- the blend ------------------------------------------------------------------------------
def test_blend_sums_both_doubles_a_lone_part_and_is_null_without_either():
    assert blend_talent(37, 35) == (72, "both")
    assert blend_talent(19, None) == (38, "leaders")
    assert blend_talent(None, 12) == (24, "team")
    assert blend_talent(0, 0) == (0, "both")
    assert blend_talent(None, None) == (None, None)


STANFORD_LEADER = _leader("Ada", schools=["Stanford BS"], prior=["Stripe (Eng)"], years=12,
                          conf={"education": "high", "prior_roles": "high", "years_experience": "high"})


def test_talent_scores_leaders_only_team_only_both_and_neither():
    both = talent_scores([STANFORD_LEADER], LIGHTFIELD)  # leaders 23 of 94 -> 12
    assert both == {"talent": 49, "talent_leaders": 12, "talent_team": 37, "talent_basis": "both",
                    "talent_reasons": ["Ada: top school (Stanford)", "Ada: top employer (Stripe)", "Ada: 10+ years"],
                    "talent_team_reasons": score_team(LIGHTFIELD)[1]}
    leaders_only = talent_scores([STANFORD_LEADER], _team(0))
    assert (leaders_only["talent"], leaders_only["talent_basis"], leaders_only["talent_team"]) == (24, "leaders", None)
    assert leaders_only["talent_team_reasons"] == ["no public profiles found for the rest of the team"]
    team_only = talent_scores([_leader("Nobody")], LIGHTFIELD)
    assert (team_only["talent"], team_only["talent_basis"], team_only["talent_leaders"]) == (74, "team", None)
    assert team_only["talent_reasons"] == []
    neither = talent_scores([], None)
    assert (neither["talent"], neither["talent_basis"], neither["talent_leaders"], neither["talent_team"]) == (
        None, None, None, None)


# ---- rescoring a stored card -----------------------------------------------------------------
BRIEF = {"latest_round": {"stage": "Series A", "amount_usd": "$35M", "announced_at": "2026-09-17",
                          "lead_investors": ["CRV"], "other_investors": ["Lightspeed Venture Partners"]},
         "prior_rounds": [{"stage": "Seed", "amount_usd": "$5M", "announced_at": None,
                           "investors": "Y Combinator, SV Angel"}]}


def _legacy_scores(leaders, brief):
    """The scores block the loop stored before the blend: the raw 0-94 talent, no breakdown."""
    talent, talent_reasons = score_talent(leaders)
    vc, vc_reasons = score_vc(brief)
    return {"talent": talent, "vc": vc, "talent_reasons": talent_reasons, "vc_reasons": vc_reasons}


def test_rescore_of_a_legacy_card_carries_the_exact_leader_points():
    payload = {"scores": _legacy_scores([STANFORD_LEADER], BRIEF), "team_stats": LIGHTFIELD,
               "funding": build_funding(BRIEF)}
    assert payload["scores"]["talent"] == 23
    new = rescored_scores(payload)
    # VC recomputed from the stored funding block reproduces the brief's score and reasons.
    assert (new["vc"], new["vc_reasons"]) == score_vc(BRIEF) == (payload["scores"]["vc"], payload["scores"]["vc_reasons"])
    assert new == {**talent_scores([STANFORD_LEADER], LIGHTFIELD), "vc": new["vc"], "vc_reasons": new["vc_reasons"]}
    assert new["talent_leaders"] == leaders_part(23) == 12


@pytest.mark.parametrize("raw", list(range(0, LEADERS_MAX + 1)))
def test_rescore_reproduces_todays_leader_points_for_every_legacy_value(raw):
    payload = {"scores": {"talent": raw, "vc": None, "talent_reasons": ["r"], "vc_reasons": []},
               "team_stats": None, "funding": build_funding(None)}
    new = rescored_scores(payload)
    assert new["talent_leaders"] == half_up(raw * 50 / 94) and new["talent_reasons"] == ["r"]
    assert (new["talent"], new["talent_basis"]) == (2 * new["talent_leaders"], "leaders")


def test_rescore_of_a_blended_card_is_a_fixed_point_and_reproduces_vc():
    from tests.unit.launch_radar_fakes import candidate

    ped = {"content": {"education": [{"school": "Stanford"}], "prior_roles": [{"company": "Stripe"}],
                       "founded_before": [], "years_experience": 12},
           "confidence": {"education": "medium", "prior_roles": "low"}}
    for brief, team, leaders in ((BRIEF, LIGHTFIELD, [(candidate("Ada", "https://x.com/a"), ped)]),
                                 (None, None, []), (BRIEF, _team(3, schools=[("MIT", 2)]), []),
                                 # A small tally follows the leaders' part: the carried part reproduces it.
                                 (BRIEF, _team(2, schools=[("MIT", 1)], employers=[("Acme", 3)]),
                                  [(candidate("Ada", "https://x.com/a"), ped)])):
        p = build_payload(company="X", domain="x.ai", monitor_event=None, brief=brief, brief_basis=[], leaders=leaders,
                          leaders_dropped=0, team=team,
                          ats={"provider": None, "board_token": None, "verified": False, "job_count": None,
                               "board_url": None, "checked_url": None},
                          run_ids={}, cost_usd=0, timings={}, issues=[], generated_at="2026-10-07T00:00:00Z")
        assert rescored_scores(p) == p["scores"]


def test_rescore_with_no_scores_block_scores_from_scratch():
    new = rescored_scores({"team_stats": LIGHTFIELD, "funding": build_funding(None)})
    assert (new["talent"], new["talent_basis"], new["vc"], new["talent_reasons"]) == (74, "team", None, [])
