"""Stands in for the candidate's solution.py inside the judge container, which never holds the
candidate's code. Importing it waits for the candidate's worker to connect, then defines one
stub per public name; calling a stub sends the arguments to the worker and returns its answer.

Everything the worker sends is untrusted: it decodes only to plain data, and its exceptions
are rebuilt as builtin exception types. The tests, pytest and the JUnit report all stay in this
process, out of the candidate's reach.
"""

import builtins as _builtins
import importlib as _importlib
import os as _os
import socket as _socket
import sys as _sys

import plwire as _plwire

_ACCEPT_TIMEOUT_S = 20.0
_STUB = object()  # marks an export that becomes a call stub
# Modules a candidate's exports may name (as `import math` does); the judge imports them itself.
_IMPORTABLE = (set(_sys.stdlib_module_names) | {"numpy"}) - {
    "antigravity",
    "this",
    "idlelib",
    "tkinter",
    "turtle",
    "turtledemo",
}


class CandidateError(RuntimeError):
    """The candidate's process failed in a way no builtin exception describes."""


def _accept():
    server = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    server.bind(_plwire.SOCKET)
    server.listen(1)
    server.settimeout(_ACCEPT_TIMEOUT_S)
    try:
        conn, _ = server.accept()
    except TimeoutError:
        # A harness problem, not the candidate's: exit 4 makes the run a SANDBOX_ERROR.
        print("the candidate's worker never connected", file=_sys.__stderr__, flush=True)
        _os._exit(4)
    server.close()
    conn.settimeout(None)
    return conn.makefile("rwb")


_wire = _accept()
_next_id = 0
_unanswered: set[int] = set()  # calls interrupted (by a timeout) before their reply arrived


def _call(name, args, kwargs):
    __tracebackhide__ = True
    global _next_id
    _next_id += 1
    call_id = _next_id
    request = {"id": call_id, "name": name, "args": _plwire.encode(list(args))}
    request["kwargs"] = _plwire.encode(dict(kwargs))
    try:
        _plwire.send(_wire, request)
        while True:
            reply = _receive()
            late = reply.get("id")
            if isinstance(late, int) and late in _unanswered:  # reply to an interrupted call
                _unanswered.discard(late)
                continue
            break
    except BaseException:
        _unanswered.add(call_id)
        raise
    if reply.get("id") != call_id:
        raise CandidateError("the candidate's worker answered out of turn")
    _echo(reply)
    if "raise" in reply:
        raise _rebuild(reply["raise"]) from None
    if "ok" not in reply:
        raise CandidateError("malformed reply from the candidate's worker")
    return _plwire.decode(reply["ok"])


def _receive() -> dict:
    __tracebackhide__ = True
    try:
        return _plwire.recv(_wire)
    except EOFError:
        raise CandidateError("the candidate's process exited") from None


def _echo(reply: dict) -> None:
    """Print what the candidate printed, so pytest captures it with the test."""
    text = reply.get("stdout")
    if isinstance(text, str) and text:
        _sys.stdout.write(text)


def _rebuild(info) -> Exception:
    """The candidate's exception as the nearest builtin type, with its traceback as a note."""
    if not isinstance(info, dict):
        return CandidateError("malformed exception from the candidate's worker")
    name, message = str(info.get("type", "Exception")), str(info.get("message", ""))
    bases = info.get("bases") if isinstance(info.get("bases"), list) else []
    cls = CandidateError
    for base in [name, *bases]:
        found = getattr(_builtins, str(base), None)
        if isinstance(found, type) and issubclass(found, Exception):
            cls = found
            break
    text = message if cls.__name__ == name else f"{name}: {message}"
    try:
        exc = cls(text)
    except TypeError:  # builtin types whose constructors need more arguments
        exc = CandidateError(f"{name}: {message}")
    trace = info.get("traceback")
    if isinstance(trace, str) and trace:
        exc.add_note("Traceback from the candidate's code:\n" + trace.rstrip())
    return exc


def _stub(name):
    def call(*args, **kwargs):
        __tracebackhide__ = True
        return _call(name, args, kwargs)

    call.__name__ = call.__qualname__ = name
    call.__test__ = False  # `from solution import *` must not make pytest collect test_* names
    return call


def _rebuild_export(spec):
    if not isinstance(spec, dict):
        raise _plwire.WireError("malformed export")
    if spec.get("callable") is True:
        return _STUB
    if "value" in spec:
        return _plwire.decode(spec["value"])
    target = spec.get("module") or (spec.get("ref") or [None])[0]
    if not isinstance(target, str) or target.split(".")[0] not in _IMPORTABLE:
        raise _plwire.WireError("not importable in the judge")
    module = _importlib.import_module(target)
    if "module" in spec:
        return module
    return getattr(module, str(spec["ref"][1]))


def _load() -> list[str]:
    hello = _receive()
    _echo(hello)
    if "import_error" in hello:
        error = hello["import_error"] if isinstance(hello["import_error"], dict) else {}
        raise ImportError(
            "importing the candidate's solution.py failed:\n" + str(error.get("traceback", ""))
        )
    exports = hello.get("exports")
    if not isinstance(exports, dict):
        raise CandidateError("malformed hello from the candidate's worker")
    names = []
    for name, spec in exports.items():
        # Never let a candidate's name replace this module's own machinery.
        if not isinstance(name, str) or not name.isidentifier() or name in globals():
            continue
        try:
            value = _rebuild_export(spec)
        except (ImportError, AttributeError, IndexError, TypeError, _plwire.WireError):
            continue
        globals()[name] = _stub(name) if value is _STUB else value
        names.append(name)
    return names


try:
    __all__ = _load()
except (CandidateError, _plwire.WireError) as e:
    raise ImportError(f"importing the candidate's solution.py failed: {e}") from None
