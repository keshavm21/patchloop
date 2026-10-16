"""Runs in the candidate's container: imports the candidate's solution.py and answers the
judge's calls over the wire.

The judge trusts nothing that comes from here. The candidate shares this process, so it can
rewrite any reply; a forged reply only changes the candidate's own answers, which the judge's
tests still check.
"""

import contextlib
import importlib
import inspect
import io
import socket
import sys
import time
import traceback

import plwire

CONNECT_TIMEOUT_S = 20.0
MAX_CAPTURE = 8000  # characters of the candidate's stdout/stderr kept per call
MAX_TEXT = 4000  # per exception message


class CappedText(io.TextIOBase):
    """A text stream that keeps the first MAX_CAPTURE characters and counts the rest."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.kept = self.dropped = 0

    def writable(self) -> bool:
        return True

    def write(self, s: str) -> int:
        room = MAX_CAPTURE - self.kept
        self.parts.append(s[:room])
        self.kept += min(len(s), room)
        self.dropped += max(len(s) - room, 0)
        return len(s)

    def take(self) -> str:
        text = "".join(self.parts)
        if self.dropped:
            text += f"\n[... {self.dropped} more characters dropped]\n"
        self.parts, self.kept, self.dropped = [], 0, 0
        return text


def main() -> None:
    wire = _connect().makefile("rwb")
    out = CappedText()
    try:
        with _captured(out):
            module = importlib.import_module("solution")
    except BaseException as e:
        plwire.send(wire, {"import_error": _exception(e), "stdout": out.take()})
        return
    plwire.send(wire, {"exports": _exports(module), "stdout": out.take()})
    while True:
        try:
            request = plwire.recv(wire)
        except EOFError:
            return
        plwire.send(wire, _call(module, request, out))


def _connect() -> socket.socket:
    deadline = time.monotonic() + CONNECT_TIMEOUT_S
    while True:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(plwire.SOCKET)
            return sock
        except (FileNotFoundError, ConnectionRefusedError):
            sock.close()
            if time.monotonic() > deadline:
                sys.exit("the judge never opened its socket")
            time.sleep(0.05)


@contextlib.contextmanager
def _captured(out: CappedText):
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        yield


def _exports(module) -> dict:
    """How the judge can rebuild each public name: a call stub, a value, or a reference to a
    module (or a name inside one) that the judge imports itself."""
    names = getattr(module, "__all__", None)
    if not isinstance(names, (list, tuple)):
        names = [n for n in vars(module) if not n.startswith("_")]
    exports = {}
    for name in names:
        if not isinstance(name, str) or not hasattr(module, name):
            continue
        obj = getattr(module, name)
        if inspect.ismodule(obj):
            exports[name] = {"module": obj.__name__}
        elif (ref := _reference(obj)) is not None:
            exports[name] = {"ref": ref}
        elif callable(obj):
            exports[name] = {"callable": True}
        else:
            with contextlib.suppress(plwire.WireError):
                exports[name] = {"value": plwire.encode(obj)}
    return exports


def _reference(obj) -> list[str] | None:
    """[module, name] for something imported from another module, e.g. `from math import sqrt`."""
    owner, name = getattr(obj, "__module__", None), getattr(obj, "__name__", None)
    if not isinstance(owner, str) or not isinstance(name, str) or owner == "solution":
        return None
    if getattr(sys.modules.get(owner), name, None) is not obj:
        return None
    return [owner, name]


def _call(module, request: dict, out: CappedText) -> dict:
    call_id, name = request.get("id"), request.get("name")
    try:
        func = getattr(module, name)
        args, kwargs = plwire.decode(request["args"]), plwire.decode(request["kwargs"])
    except (AttributeError, KeyError, TypeError, plwire.WireError) as e:
        return {"id": call_id, "raise": _exception(e), "stdout": ""}
    try:
        with _captured(out):
            result = func(*args, **kwargs)
    except BaseException as e:
        return {"id": call_id, "raise": _exception(e), "stdout": out.take()}
    try:
        value = plwire.encode(result)
    except plwire.WireError as e:
        err = TypeError(f"{name}() returned a value the tests can't receive: {e}")
        return {"id": call_id, "raise": _exception(err), "stdout": out.take()}
    return {"id": call_id, "ok": value, "stdout": out.take()}


def _exception(e: BaseException) -> dict:
    """The exception's type, its builtin base classes, message, and a traceback of the
    candidate's own frames."""
    try:
        message = str(e)
        te = traceback.TracebackException.from_exception(e)
        te.stack = traceback.StackSummary.from_list(
            [f for f in te.stack if not f.filename.startswith(("/runner/", "<frozen"))]
        )
        trace = "".join(te.format())
    except Exception:  # an exception whose __str__ itself fails
        message, trace = "<unprintable exception>", ""
    return {
        "type": type(e).__name__,
        "bases": [c.__name__ for c in type(e).__mro__ if c.__module__ == "builtins"],
        "message": message[:MAX_TEXT],
        "traceback": trace[-MAX_TEXT:],
    }


if __name__ == "__main__":
    main()
