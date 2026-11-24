from job_enricher.cli import _merge_judge
import json


def _base():
    return {
        "job_listing_id": "1", "category": "software_engineering", "level": "senior",
        "level_includes": json.dumps(["senior"]), "tags": json.dumps(["backend"]),
        "locations": json.dumps([]),
    }


def test_pass_no_corrections_keeps_facets():
    m = _merge_judge(_base(), {"passed": True, "confidence": 0.95}, floor=0.60)
    assert m["category"] == "software_engineering"
    assert m["judge_pass"] is True
    assert m["needs_human"] is False


def test_correction_applied_and_marks_not_pass():
    m = _merge_judge(_base(), {"passed": False, "confidence": 0.9,
                               "corrections": {"category": "business_ops"}}, floor=0.60)
    assert m["category"] == "business_ops"
    assert m["judge_pass"] is False


def test_low_confidence_flags_human():
    m = _merge_judge(_base(), {"passed": True, "confidence": 0.4}, floor=0.60)
    assert m["needs_human"] is True
