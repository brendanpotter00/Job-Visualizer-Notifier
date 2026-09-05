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


def test_double_escaped_html_is_stripped():
    """Greenhouse serves some bodies (e.g. Vercel's) DOUBLE-escaped: the tags
    arrive as "&lt;li&gt;" text. One pass only unescapes them into literal tags,
    so the classifier saw raw markup as prose — the second pass removes them."""
    html = (
        "<div>&lt;h2&gt;About You&lt;/h2&gt; "
        "&lt;li data-stringify-indent=&quot;0&quot;&gt;7+ years of TypeScript.&lt;/li&gt;</div>"
    )
    out = clean_description(html)
    assert not has_residual_html(out)
    assert "data-stringify-indent" not in out
    assert "7+ years of TypeScript." in out


def test_residual_strip_is_bounded_and_idempotent():
    """The re-run happens at most once and clean stays idempotent."""
    html = "<p>Compare a &lt;b&gt;bold&lt;/b&gt; claim.</p>"
    once = clean_description(html)
    assert not has_residual_html(once)
    assert clean_description(once) == once


def test_escaped_code_samples_are_not_eaten():
    """The double-escape re-run must key on escaped real TAGS in the input, not on
    "the output still has angle brackets" — postings carry generics and JSX, and
    an output-keyed check silently DELETED them."""
    assert "Promise<T>" in clean_description(
        "<p>Use <code>Promise&lt;T&gt;</code> daily.</p>"
    )
    assert "Map<String, Integer>" in clean_description(
        "<p>Refactor <code>Map&lt;String, Integer&gt;</code> lookups.</p>"
    )
    assert "<Button />" in clean_description("<p>Build the &lt;Button /&gt; one.</p>")


def test_boilerplate_cut_survives_an_escaped_fragment():
    """Regression: re-running the markdown pass on an already-markdown document
    collapses every newline, which disables the line-based boilerplate cut and
    leaks the EEO/benefits block into the classifier."""
    body = "<p>" + ("We are hiring an engineer to build services. " * 12) + "</p>"
    html = (
        f"<div>{body}<ul><li>Write <code>Promise&lt;T&gt;</code> code</li>"
        "<li>Own services</li></ul>"
        "<h2>Benefits</h2><p>Great perks.</p>"
        "<h2>Equal Opportunity</h2><p>We are an equal opportunity employer.</p></div>"
    )
    out = clean_description(html)
    assert "\n" in out, "document structure collapsed to a single line"
    assert "benefits" not in out.lower()
    assert "equal opportunity" not in out.lower()
    assert "Promise<T>" in out


def test_empty():
    assert clean_description(None) == ""
    assert clean_description("") == ""
