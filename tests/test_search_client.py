"""Unit tests for the Client class — decode_frame + build_body only.

Retry semantics moved to test_client_rate_limiter.py after the curl_cffi
rewrite in Chunk D.
"""

import json

import pytest

from stays.search.client import (
    BatchExecuteError,
    Client,
    TransientBatchExecuteError,
)

# ------------------------------------------------------------------
# _decode_frame
# ------------------------------------------------------------------


def test_decode_frame_happy_path():
    raw = ")]}'\n" + '[["wrb.fr","RpcId","[42]",null,null,null,"1"]]'
    out = Client._decode_frame(raw, "RpcId")
    assert out == [42]


def test_decode_frame_missing_frame_raises():
    raw = ")]}'\n" + '[["wrb.fr","OtherId","[]",null,null,null,"1"]]'
    with pytest.raises(BatchExecuteError, match="No RpcId frame"):
        Client._decode_frame(raw, "RpcId")


def test_decode_frame_null_payload_raises():
    """Literal `null` frame (no quoted string) falls through to "No frame"
    because the frame regex requires a quoted capture group.
    """
    raw = ")]}'\n" + '[["wrb.fr","RpcId",null,null,null,null,"1"]]'
    with pytest.raises(BatchExecuteError, match="No RpcId frame"):
        Client._decode_frame(raw, "RpcId")


def test_decode_frame_handles_escaped_quotes():
    inner = json.dumps({"key": 'value with "quotes"'})
    escaped = inner.replace("\\", "\\\\").replace('"', '\\"')
    raw = f')]}}\'\n[["wrb.fr","RpcId","{escaped}",null,null,null,"1"]]'
    out = Client._decode_frame(raw, "RpcId")
    assert out == {"key": 'value with "quotes"'}


def test_decode_frame_preserves_utf8_non_ascii():
    """Regression: characters outside ASCII (e.g. the narrow-no-break
    space `\\u202F` that Google uses in `4:00 PM` check-in strings) must
    survive the frame decoder as single Python characters. The old
    `encode('utf-8').decode('unicode_escape')` trick mojibaked every
    non-ASCII byte into three Latin-1 chars.
    """
    # Google emits U+202F as a raw UTF-8 character in the response, not as
    # a \\u202F escape — build a response that mimics that exactly.
    inner_obj = {"time": "4:00 PM"}
    inner_json = json.dumps(inner_obj, ensure_ascii=False)
    # The frame's outer wrapper escapes backslashes + quotes, but leaves
    # the raw UTF-8 non-ASCII chars untouched (same as real responses).
    escaped = inner_json.replace("\\", "\\\\").replace('"', '\\"')
    raw = f')]}}\'\n[["wrb.fr","RpcId","{escaped}",null,null,null,"1"]]'
    out = Client._decode_frame(raw, "RpcId")
    assert out == {"time": "4:00 PM"}
    # And the character count is 7 — NOT the 9 you'd get from mojibake
    # (4, :, 0, 0, â, \\x80, ¯, P, M).
    assert len(out["time"]) == 7


def test_decode_frame_sorry_interstitial_is_transient():
    """Google's rate-limit page has no wrb.fr frame but is a retryable
    transient, not a request-shape bug."""
    raw = (
        ")]}'\n"
        "<html><body>Our systems have detected unusual traffic from your "
        "computer network. <a href='/sorry/...'>Continue</a></body></html>"
    )
    with pytest.raises(TransientBatchExecuteError, match="rate-limit"):
        Client._decode_frame(raw, "RpcId")


# ------------------------------------------------------------------
# _build_body
# ------------------------------------------------------------------


def test_build_body_shape():
    c = Client()
    body = c._build_body("RpcId", ["x", 1, True])
    assert body.startswith(b"f.req=")
    decoded = body[len(b"f.req=") :].decode()
    import urllib.parse

    outer = json.loads(urllib.parse.unquote(decoded))
    assert outer[0][0][0] == "RpcId"
    inner = json.loads(outer[0][0][1])
    assert inner == ["x", 1, True]
