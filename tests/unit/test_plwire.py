"""The judge/worker wire format. It ships in the sandbox image (docker/runner/), so it is
loaded by path."""

import importlib.util
import io
import json
import math
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "docker" / "runner" / "plwire.py"
_spec = importlib.util.spec_from_file_location("plwire", _PATH)
plwire = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plwire)


def roundtrip(value):
    # Through real JSON text, as on the socket.
    return plwire.decode(json.loads(json.dumps(plwire.encode(value), allow_nan=False)))


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        0,
        -7,
        2**100,
        1.5,
        -0.0,
        "text\nwith newline",
        b"\x00\xff",
        3 + 4j,
        [1, [2, [3]]],
        (1, "a", None),
        {1, 2},
        frozenset({"x"}),
        {"a": 1, 2: [3], (4, 5): {6}},
        [],
        {},
    ],
)
def test_plain_values_round_trip(value):
    out = roundtrip(value)
    assert out == value
    assert type(out) is type(value)


def test_non_finite_floats_round_trip():
    assert math.isnan(roundtrip(float("nan")))
    assert roundtrip(float("inf")) == float("inf")
    assert roundtrip(float("-inf")) == float("-inf")


def test_bool_stays_bool_and_tuple_stays_tuple_inside_containers():
    assert roundtrip([True, (1,)]) == [True, (1,)]
    assert type(roundtrip([True])[0]) is bool


@pytest.mark.parametrize("value", [object(), lambda: 1, iter([1]), type])
def test_objects_cannot_cross(value):
    with pytest.raises(plwire.WireError):
        plwire.encode(value)


def test_nesting_is_capped():
    deep = []
    for _ in range(plwire.MAX_DEPTH + 5):
        deep = [deep]
    with pytest.raises(plwire.WireError):
        plwire.encode(deep)
    data: object = 1
    for _ in range(plwire.MAX_DEPTH + 5):
        data = [data]
    with pytest.raises(plwire.WireError):
        plwire.decode(data)


@pytest.mark.parametrize(
    "data",
    [
        {"$class": "os.system"},
        {"$tuple": [1], "$set": [2]},
        {"a": 1},
        {"$int": "12x"},
        {"$float": "1e400"},
        {"$bytes": "not base64!"},
        {"$set": [[1, 2]]},  # unhashable member
        {"$dict": [[1]]},
        {"$dict": [[[1], 2]]},  # unhashable key
        {"$complex": [1]},
    ],
)
def test_hostile_or_malformed_data_is_rejected(data):
    with pytest.raises(plwire.WireError):
        plwire.decode(data)


def test_messages_are_framed_by_newlines():
    stream = io.BytesIO()
    plwire.send(stream, {"id": 1, "ok": plwire.encode("a\nb")})
    stream.seek(0)
    assert plwire.recv(stream) == {"id": 1, "ok": "a\nb"}
    with pytest.raises(EOFError):
        plwire.recv(stream)


@pytest.mark.parametrize(
    "line",
    [
        b"x" * (plwire.MAX_MESSAGE + 10),
        b'{"cut": ',
        b"not json\n",
        b"[1, 2]\n",
        b"[" * 5000 + b"\n",
    ],
)
def test_bad_lines_are_rejected(line):
    with pytest.raises(plwire.WireError):
        plwire.recv(io.BytesIO(line))
