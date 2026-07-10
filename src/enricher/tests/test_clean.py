from job_enricher.clean import (
    clean_description, has_residual_html, truncate_for_agent,
)


def test_strips_html_and_scripts():
    html = "<div><script>evil()</script><p>Build <b>backend</b> systems.</p></div>"
    out = clean_description(html)
    assert "evil" not in out
    assert "backend" in out
    assert not has_residual_html(out)


def test_cuts_trailing_boilerplate():
    body = "We are hiring an engineer. " * 40
    html = f"<p>{body}</p><h2>Equal Opportunity</h2><p>We are an equal opportunity employer.</p>"
    out = clean_description(html)
    assert "equal opportunity" not in out.lower()
    assert "engineer" in out.lower()


def test_truncate_budget():
    text = "sentence. " * 2000
    out = truncate_for_agent(text, char_budget=100)
    assert len(out) < len(text)
    assert "truncated" in out


def test_empty():
    assert clean_description(None) == ""
    assert clean_description("") == ""
