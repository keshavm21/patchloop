"""The wire between the judge and the candidate's worker: one JSON object per line over a Unix
socket, with Python values in a tagged encoding that only ever decodes to plain data
(None, bool, int, float, complex, str, bytes, list, tuple, set, frozenset, dict). Nothing
that arrives on the wire can name a class or run code, so the judge can decode what an
untrusted worker sends.
"""

import base64
import json
import math

SOCKET = "/run/pl/judge.sock"
MAX_MESSAGE = 16 << 20  # bytes per line
MAX_DEPTH = 100


class WireError(Exception):
    """A value can't cross the wire, or a message is malformed."""


def encode(value, _depth=0):
    """A JSON-ready form of `value`. Raises WireError for anything but plain data."""
    if _depth > MAX_DEPTH:
        raise WireError("value is nested too deeply")
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        if -(2**53) < value < 2**53:
            return int(value)
        try:
            return {"$int": str(value)}
        except ValueError as e:  # longer than Python's int-to-str digit limit
            raise WireError(str(e)) from None
    if isinstance(value, float):
        return float(value) if math.isfinite(value) else {"$float": repr(float(value))}
    if isinstance(value, complex):
        return {"$complex": [encode(value.real), encode(value.imag)]}
    if isinstance(value, (bytes, bytearray)):
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    if type(value).__module__ == "numpy" and hasattr(value, "tolist"):
        return encode(value.tolist(), _depth)  # numpy scalars and arrays become plain values
    if isinstance(value, list):
        return _encode_items(value, _depth)
    if isinstance(value, tuple):
        return {"$tuple": _encode_items(value, _depth)}
    if isinstance(value, frozenset):
        return {"$frozenset": _encode_items(value, _depth)}
    if isinstance(value, set):
        return {"$set": _encode_items(value, _depth)}
    if isinstance(value, dict):
        return {"$dict": [_encode_items(pair, _depth) for pair in value.items()]}
    raise WireError(f"a {type(value).__name__} can't cross the sandbox boundary")


def _encode_items(values, depth):
    return [encode(v, depth + 1) for v in values]


def decode(data, _depth=0):
    """The value `encode` produced. Raises WireError on anything else."""
    if _depth > MAX_DEPTH:
        raise WireError("value is nested too deeply")
    if data is None or isinstance(data, (bool, str, int, float)):
        return data
    if isinstance(data, list):
        return [decode(v, _depth + 1) for v in data]
    if not isinstance(data, dict) or len(data) != 1:
        raise WireError("malformed value")
    [(tag, body)] = data.items()
    try:
        if tag == "$int" and isinstance(body, str):
            return int(body)
        if tag == "$float" and body in ("nan", "inf", "-inf"):
            return float(body)
        if tag == "$complex" and isinstance(body, list) and len(body) == 2:
            real, imag = (decode(v, _depth + 1) for v in body)
            return complex(real, imag)
        if tag == "$bytes" and isinstance(body, str):
            return base64.b64decode(body, validate=True)
        if isinstance(body, list):
            values = [decode(v, _depth + 1) for v in body]
            if tag == "$tuple":
                return tuple(values)
            if tag == "$set":
                return set(values)
            if tag == "$frozenset":
                return frozenset(values)
            if tag == "$dict" and all(isinstance(p, list) and len(p) == 2 for p in values):
                return dict(values)
    except (TypeError, ValueError) as e:  # unhashable members, bad digits or base64
        raise WireError(f"malformed {tag}: {e}") from None
    raise WireError(f"malformed value tagged {tag!r}")


def send(stream, message: dict) -> None:
    line = json.dumps(message, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    if len(line) > MAX_MESSAGE:
        raise WireError("message too large")
    stream.write(line)
    stream.flush()


def recv(stream) -> dict:
    """The next message. Raises EOFError if the other side closed, WireError if malformed."""
    line = stream.readline(MAX_MESSAGE + 1)
    if not line:
        raise EOFError("the other side closed the connection")
    if not line.endswith(b"\n"):
        raise WireError("message too large or cut off")
    try:
        message = json.loads(line)
    except (ValueError, RecursionError) as e:
        raise WireError(f"malformed message: {e}") from None
    if not isinstance(message, dict):
        raise WireError("malformed message")
    return message
