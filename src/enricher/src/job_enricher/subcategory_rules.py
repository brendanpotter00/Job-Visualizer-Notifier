"""Deterministic title+tag subcategory labelling — no model call, no network.

⚠ THIS IS A PRODUCTION MODULE, deliberately NOT `eval/weak_subcategory.py`. It
has two callers that must never diverge:

  1. the eval's WEAK BASELINE — the number a v7 model has to beat before it has
     earned the right to ship (a model that cannot out-label a regex on the
     titles the regex can type has no business shipping); and
  2. the BACKFILL's free layers — the rows labelled at zero model cost before
     anything reaches an engine.

Two implementations would drift until "the baseline the model must beat" stopped
describing what actually ran, which is a comparison that quietly means nothing.

HARD RULES, enforced by tests, not just by this docstring:

* ⚠ IT NEVER READS DESCRIPTIONS. Title and tags only. The backfill lane's
  injection boundary is structural (`build_subcategory_prompt` cannot render a
  description); this module is on the same side of it.

* ⚠ IT NEVER ROUTES ON AN AI/ML-FAMILY TAG. Measured on the corpus: 2,462 SWE
  rows — 22% — carry an ai/ml-family tag while being ordinary backend or
  full-stack work, and 11.5% of plain SWE descriptions mention LLMs. A bare `ai`
  tag is a company's marketing vocabulary, not a role signal. `ai_engineering`
  and `ml_engineering` therefore have NO tag coverage at all; they are reachable
  only from an explicit title phrase.

* ⚠ "VALIDATION" IN A HARDWARE POSTING IS SILICON BRING-UP, NOT QA.
  `Silicon Validation Software Engineer` is `embedded_systems`. `qa_testing`
  deliberately carries no bare `validation` pattern.

* `full_stack` is EXCLUSIVE — the suppression and the 2-slug cap are applied by
  `taxonomy.validate_subcategories`, the same code the write path uses, so there
  is exactly one implementation of the contract.

* ⚠ THE 17 SLUGS ARE NEVER RE-ENUMERATED AS AN INDEPENDENT LIST.
  `_TITLE_PATTERNS` and `_PRIORITY` are checked against `taxonomy.SUBCATEGORIES`
  at import time, so the canonical frozenset stays the single arbiter and a slug
  added there fails loudly here instead of silently going unlabelled.
"""

from __future__ import annotations

import re
from typing import Iterable

from job_enricher.taxonomy import SUBCATEGORIES, SUBCATEGORY_PARENT, validate_subcategories

# Seniority / org furniture stripped before matching, so "Senior Backend
# Engineer II" and "Backend Engineer" type identically. Ordered longest-first so
# multi-word phrases are removed before their component words.
_SENIORITY_RE = re.compile(
    r"\b(?:"
    r"new\s*grad|entry[\s-]level|early[\s-]career|mid[\s-]level|"
    r"senior|sr\.?|staff|principal|distinguished|fellow|lead|junior|jr\.?|"
    r"intern(?:ship)?|apprentice|associate|"
    r"director|head\s+of|vp|vice\s+president|chief|manager|"
    r"i{1,3}|iv|v"
    r")\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Title layer
# ---------------------------------------------------------------------------
# ⚠ ORDER IS THE ALGORITHM. `_PRIORITY` runs most-specific to most-general, and
# matching is FIRST-MATCH-WINS per slug, so a "Senior Backend Engineer,
# Robotics" types as robotics_autonomy first and backend second — never the
# other way round. Generic slugs sit at the bottom precisely because almost
# every SWE title brushes against them.
_PRIORITY: tuple[str, ...] = (
    "forward_deployed",
    "quantitative",
    "robotics_autonomy",
    "embedded_systems",
    "security",
    "ml_engineering",
    "ai_engineering",
    "data_engineering",
    "qa_testing",
    "devops_sre",
    # A title naming a growth METRIC says more than the layer it is written in,
    # so it outranks every generic slug below — SUBCATEGORIES.md tie-breaker 12.
    # It sits above `infrastructure_platform` safely because the two patterns
    # cannot both fire on a platform title: `growth_engineering` carries no
    # `experimentation` pattern, so "Experimentation Platform Engineer" still
    # types as `infrastructure_platform` (tie-breaker 13).
    "growth_engineering",
    "infrastructure_platform",
    "mobile",
    # Above `full_stack` ON PURPOSE: "Full Stack Product Engineer" must come out
    # ["product_engineering", "full_stack"] — both are explicit, and the scope
    # claim is the narrower one. Below every technical slug above it, so
    # "Product Security Engineer" stays security-first.
    "product_engineering",
    "full_stack",
    "frontend",
    "backend",
)

_TITLE_PATTERNS: dict[str, str] = {
    "forward_deployed": r"forward[\s-]deployed|solutions?\s+engineer|"
                        r"field\s+engineer|deployment\s+engineer|"
                        r"implementation\s+engineer",
    "quantitative": r"\bquant\b|quantitative|trading\s+system|"
                    r"low[\s-]latency\s+trading|market\s+data|\bhft\b|"
                    r"electronic\s+trading|execution\s+system",
    "robotics_autonomy": r"robotic|robotics|\bautonomy\b|autonomous|"
                         r"motion\s+planning|\bslam\b|perception|\bav\b|"
                         r"self[\s-]driving|drone|\buav\b|controls?\s+engineer",
    # ⚠ `validation` lives HERE, gated on hardware context — see the docstring.
    "embedded_systems": r"embedded|firmware|\brtos\b|bare[\s-]metal|"
                        r"device\s+driver|kernel|\bbsp\b|\bfpga\b|\basic\b|\brtl\b|"
                        r"silicon|\bsoc\b|\bgpu\b|hardware\s+validation|"
                        r"silicon\s+validation|bring[\s-]up|low[\s-]level\s+system|"
                        r"\bverilog\b|\bvhdl\b|microcontroller",
    "security": r"security|appsec|infosec|\bcryptograph|penetration\s+test|"
                r"\bpentest|red\s+team|threat\s+detection|vulnerabilit|"
                r"identity\s+and\s+access|\biam\b",
    "ml_engineering": r"machine\s+learning|\bml\b|\bmlops\b|deep\s+learning|"
                      r"computer\s+vision|\bnlp\b|natural\s+language|"
                      r"recommendation|ranking|personalization|"
                      r"model\s+(?:training|serving|deployment)",
    # ⚠ Explicit AI-ENGINEERING phrases only. "AI" as an adjective on a product
    # or a company name is not a role signal — see the docstring.
    "ai_engineering": r"\bai\s+engineer|applied\s+ai|generative\s+ai|\bgenai\b|"
                      r"\bllm\b|large\s+language\s+model|prompt\s+engineer|"
                      r"\brag\b|\bagentic\b|ai\s+platform|foundation\s+model",
    "data_engineering": r"data\s+engineer|data\s+platform|data\s+pipeline|"
                        r"data\s+infrastructure|analytics\s+engineer|\betl\b|"
                        r"\belt\b|data\s+warehouse|big\s+data|\bspark\b|"
                        r"streaming\s+data|data\s+lake",
    # ⚠ NO bare `validation` pattern here. That is the silicon rule.
    "qa_testing": r"\bqa\b|quality\s+assurance|quality\s+engineer|\bsdet\b|"
                  r"test\s+engineer|test\s+automation|automation\s+engineer\b|"
                  r"software\s+(?:development\s+engineer\s+in\s+test|test)",
    "devops_sre": r"devops|\bsre\b|site\s+reliability|reliability\s+engineer|"
                  r"observability|build\s+(?:and\s+release\s+)?engineer|"
                  r"release\s+engineer|\bci/?cd\b|production\s+engineer|"
                  r"systems?\s+administrator",
    "infrastructure_platform": r"infrastructure|platform\s+engineer|"
                               r"developer\s+(?:experience|productivity|tool)|"
                               r"cloud\s+engineer|distributed\s+systems?|"
                               r"kubernetes|compute\s+platform|"
                               r"internal\s+tool|\bdevex\b|core\s+platform",
    "mobile": r"\bios\b|\bandroid\b|\bmobile\b|react[\s-]native|flutter|"
              r"\bswift\b|\bkotlin\b|\bmac\s?os\b",
    # ⚠ EXPLICIT GROWTH-ENGINEERING PHRASES ONLY, and deliberately NO
    # `experimentation` / `ab[\s-]test` pattern: an experimentation PLATFORM
    # serves other engineering teams, which is `infrastructure_platform`
    # (SUBCATEGORIES.md tie-breaker 13). A regex cannot tell the two apart from
    # the title, so it declines to try. "Growth Marketing Engineer" does not
    # match — `growth\s+engineer` requires the words adjacent — and a marketer
    # is category `growth`, which never reaches this module at all.
    "growth_engineering": r"growth\s+engineer|growth\s+software\s+engineer|"
                          r"growth\s+product\s+engineer|"
                          r"engineer\s*[,\-–—]\s*(?:[a-z]+\s+)?growth\b|"
                          r"\b(?:acquisition|activation|monetization|"
                          r"monetisation|retention)\s+engineer",
    # ⚠ The SCOPE claim, not an ownership vibe. There is no pattern here for
    # "high agency" / "wear many hats" / "0-1" / "end-to-end" — SUBCATEGORIES.md
    # tie-breaker 14 rules those out explicitly, and a regex over boilerplate
    # every startup posting carries would type half the corpus.
    "product_engineering": r"product\s+engineer|product\s+software\s+engineer|"
                           r"engineer,?\s+product\b",
    "full_stack": r"full[\s-]?stack",
    "frontend": r"front[\s-]?end|\bfrontend\b|\bui\s+engineer|"
                r"web\s+(?:developer|engineer)|\breact\b|\bux\s+engineer|"
                r"client[\s-]side",
    "backend": r"back[\s-]?end|\bbackend\b|server[\s-]side|\bapi\s+engineer|"
               r"services?\s+engineer|distributed\s+backend|"
               r"\bserver\s+engineer",
}

# ⚠ THE ARBITER CHECK. `taxonomy.SUBCATEGORIES` is the canonical list; this
# module must cover it exactly. Adding an 18th slug there fails at IMPORT here,
# which is the only way a new slug cannot quietly go unlabelled forever.
assert set(_TITLE_PATTERNS) == set(SUBCATEGORIES) == set(_PRIORITY), (
    "subcategory_rules is out of sync with taxonomy.SUBCATEGORIES: "
    f"missing={sorted(set(SUBCATEGORIES) - set(_TITLE_PATTERNS))} "
    f"extra={sorted(set(_TITLE_PATTERNS) - set(SUBCATEGORIES))}"
)

_COMPILED: dict[str, re.Pattern[str]] = {
    slug: re.compile(pat, re.IGNORECASE) for slug, pat in _TITLE_PATTERNS.items()
}

# ---------------------------------------------------------------------------
# Tag layer
# ---------------------------------------------------------------------------
# Spelling variants that mean the same thing. Collapsed BEFORE the bucket lookup
# so `c-plus-plus` and `c++` cannot land in different buckets.
_TAG_SYNONYMS: dict[str, str] = {
    "c-plus-plus": "c++",
    "cplusplus": "c++",
    "csharp": "c-sharp",
    "c#": "c-sharp",
    "cloud": "cloud",
    "cloud-computing": "cloud",
    "cloud-infrastructure": "cloud",
    "cloud-native": "cloud",
    "embedded": "embedded",
    "embedded-systems": "embedded",
}

# ⚠ SIX SLUGS HAVE NO TAG COVERAGE AT ALL, and that is deliberate:
#   forward_deployed, quantitative  — measured: ZERO tag coverage in the corpus.
#                                     The tag layer simply cannot reach them.
#   ai_engineering, ml_engineering  — the ai/ml-family tag ban (see docstring).
#   growth_engineering              — a `growth` tag is an ORG name, and it sits
#                                     on marketing-adjacent rows as often as on
#                                     engineering ones; `experimentation` /
#                                     `ab-testing` belong to platform teams just
#                                     as often (tie-breaker 13). Title only.
#   product_engineering             — there is no technology that means "owns
#                                     what ships". Any tag mapping here would be
#                                     the ownership-boilerplate trap in tag form.
# `c++` and `c-sharp` are collapsed but intentionally UNMAPPED: they appear
# across embedded, backend, quantitative and game work, so mapping them would be
# guessing dressed as a rule.
_TAG_BUCKETS: dict[str, str] = {
    # frontend
    "react": "frontend", "vue": "frontend", "angular": "frontend",
    "svelte": "frontend", "css": "frontend", "html": "frontend",
    "tailwind": "frontend", "redux": "frontend", "sass": "frontend",
    "webpack": "frontend", "nextjs": "frontend", "next-js": "frontend",
    # backend
    "django": "backend", "flask": "backend", "fastapi": "backend",
    "rails": "backend", "ruby-on-rails": "backend", "spring": "backend",
    "spring-boot": "backend", "laravel": "backend", "grpc": "backend",
    "phoenix": "backend",
    # mobile
    "ios": "mobile", "android": "mobile", "swift": "mobile",
    "kotlin": "mobile", "react-native": "mobile", "flutter": "mobile",
    "objective-c": "mobile", "swiftui": "mobile", "jetpack-compose": "mobile",
    # devops_sre
    "kubernetes": "devops_sre", "docker": "devops_sre", "terraform": "devops_sre",
    "ansible": "devops_sre", "jenkins": "devops_sre", "prometheus": "devops_sre",
    "grafana": "devops_sre", "ci-cd": "devops_sre", "helm": "devops_sre",
    # infrastructure_platform
    "cloud": "infrastructure_platform", "aws": "infrastructure_platform",
    "gcp": "infrastructure_platform", "azure": "infrastructure_platform",
    "distributed-systems": "infrastructure_platform",
    # data_engineering
    "spark": "data_engineering", "airflow": "data_engineering",
    "kafka": "data_engineering", "hadoop": "data_engineering",
    "dbt": "data_engineering", "snowflake": "data_engineering",
    "etl": "data_engineering", "databricks": "data_engineering",
    # embedded_systems
    "embedded": "embedded_systems", "firmware": "embedded_systems",
    "rtos": "embedded_systems", "verilog": "embedded_systems",
    "vhdl": "embedded_systems", "fpga": "embedded_systems",
    # security
    "security": "security", "cybersecurity": "security", "appsec": "security",
    "cryptography": "security", "penetration-testing": "security",
    # qa_testing
    "selenium": "qa_testing", "cypress": "qa_testing", "appium": "qa_testing",
    "test-automation": "qa_testing", "qa": "qa_testing",
    # robotics_autonomy
    "ros": "robotics_autonomy", "robotics": "robotics_autonomy",
    "slam": "robotics_autonomy", "lidar": "robotics_autonomy",
    "motion-planning": "robotics_autonomy",
    "autonomous-driving": "robotics_autonomy",
}

_UNCOVERED_BY_TAGS: frozenset[str] = frozenset(
    {"forward_deployed", "quantitative", "ai_engineering", "ml_engineering",
     "full_stack", "growth_engineering", "product_engineering"}
)


def _finalize(slugs: list[str]) -> list[str]:
    """Apply the CONTRACT (full_stack exclusivity + the 2-slug cap) using the
    same `taxonomy.validate_subcategories` the write path uses. Reimplementing
    the rules here is how the eval and production end up disagreeing about what
    a legal label is."""
    out, _bad, _warn = validate_subcategories(SUBCATEGORY_PARENT, slugs)
    return out or []


def strip_seniority(title: str) -> str:
    """Remove seniority/org furniture so leveling words cannot type a role."""
    return re.sub(r"\s+", " ", _SENIORITY_RE.sub(" ", title or "")).strip()


def label_from_title(title: str | None) -> list[str]:
    """0-2 slugs from the TITLE alone, in `_PRIORITY` order. Never guesses."""
    if not title:
        return []
    text = strip_seniority(title)
    if not text:
        return []
    hits = [slug for slug in _PRIORITY if _COMPILED[slug].search(text)]
    return _finalize(hits)


def normalize_tag(tag: str) -> str:
    t = (tag or "").strip().lower().replace("_", "-").replace(" ", "-")
    return _TAG_SYNONYMS.get(t, t)


def label_from_tags(tags: Iterable[str] | None) -> list[str]:
    """EXACTLY ONE slug, or `[]`.

    ⚠ ZERO buckets and TWO-OR-MORE buckets both yield `[]`. Tags are a weak,
    noisy signal — a posting tagged `react` AND `kubernetes` is telling you it
    uses both technologies, not that the role is two specialties. Picking one
    would be a guess with a rule's authority, and the whole value of this layer
    is that its output can be trusted without review."""
    if not tags:
        return []
    buckets = {
        _TAG_BUCKETS[n] for n in (normalize_tag(t) for t in tags if t)
        if n in _TAG_BUCKETS
    }
    if len(buckets) != 1:
        return []
    return _finalize(list(buckets))


def rule_label(
    title: str | None, tags: Iterable[str] | None = None
) -> tuple[list[str], str]:
    """(slugs, source) where source is 'title', 'tag' or '' — never a model call.

    TITLE FIRST: a title is what a company chose to call the role, while tags are
    a technology inventory. When the title types the row the tag layer is not
    even consulted."""
    from_title = label_from_title(title)
    if from_title:
        return from_title, "title"
    from_tags = label_from_tags(tags)
    if from_tags:
        return from_tags, "tag"
    return [], ""


# ⚠ MEASURED, not a placeholder. `PARAM_REGEX_COVERAGE` sizes tier A of the
# subcategory review pass (the rows the corroborator cannot type, which ALL go
# to a human) and therefore sizes EV-9b's review cost.
#
#   measured 2026-08-20 over the 126 gold-SWE golden titles:
#     typed 94 / 126 = 0.746   ->  tier A is 32 rows
#   RE-MEASURED over the 135 gold-SWE titles, TWO causes, neither a regex fix:
#     typed 98 / 135 = 0.726   ->  tier A is 37 rows
#       +9 rows   main's MTS eval rows (#21) joined the seed at the rebase;
#                 they are mostly untypable house titles, so coverage FELL.
#       +1 typed  the 15 -> 17 widening: `growth_engineering` /
#                 `product_engineering` type exactly one seed title between them
#                 ("Software Engineer, Product Growth" -> both).
#
# The design track's 85/126 was measured against a 7-pattern regex over 13
# slugs and does not survive the move to 15 (`ai_engineering` and `quantitative`
# were added). `quantitative` matches ZERO titles in this sample, and
# `growth_engineering` matches ONE — the eval cannot say anything about either
# slug until the seed grows.
PARAM_REGEX_COVERAGE_TYPED = 98
PARAM_REGEX_COVERAGE_TOTAL = 135


def regex_coverage(rows: Iterable[dict]) -> tuple[int, int]:
    """(typed, total) over gold-SWE rows — the reproducible form of the
    `PARAM_REGEX_COVERAGE` measurement above. TITLE LAYER ONLY, because the
    golden seed's `tags` field is a gold LABEL, not company tags."""
    swe = [r for r in rows if r.get("category") == SUBCATEGORY_PARENT]
    typed = sum(1 for r in swe if label_from_title(r.get("title")))
    return typed, len(swe)
