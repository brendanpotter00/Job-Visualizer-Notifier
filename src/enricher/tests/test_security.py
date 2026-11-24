import time

from job_enricher import security as sec


def test_sign_verify_roundtrip():
    secret, wid, ts = "s3cr3t", "wh_1", str(int(time.time()))
    body = b'{"jobs":[]}'
    header = sec.sign(secret, wid, ts, body)
    assert header.startswith("v1,")
    assert sec.verify(secret, wid, ts, header, body)


def test_reject_tampered_body():
    secret, wid, ts = "s", "id", str(int(time.time()))
    header = sec.sign(secret, wid, ts, b"a")
    assert not sec.verify(secret, wid, ts, header, b"b")


def test_reject_stale():
    secret, wid = "s", "id"
    old = str(int(time.time()) - 10_000)
    header = sec.sign(secret, wid, old, b"x")
    assert not sec.verify(secret, wid, old, header, b"x")


def test_freshness_ms_timestamps():
    now = time.time()
    assert sec.is_fresh(str(int(now * 1000)), now=now)
    assert not sec.is_fresh(str(int((now - 10_000) * 1000)), now=now)
