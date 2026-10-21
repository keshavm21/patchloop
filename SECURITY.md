# Security

PatchLoop runs code written by a language model, so its security model is part of what the project demonstrates. The README's [Sandbox](README.md#sandbox) and [Safety beyond the sandbox](README.md#safety-beyond-the-sandbox) sections describe the controls, and `make chaos` proves them against hostile fixtures.

## Scope

- **In scope:** a way for model-written (or other untrusted) code to escape a container, read the tests or the host's secrets, forge a passing result, or make the harness run it outside the sandbox.
- **Out of scope:** the static policy check (`safety/policy.py`) is defense in depth and is known to be bypassable, for example by building names from strings. A bypass of it alone is not a vulnerability; a bypass of the sandbox is.
- Docker shares the host kernel. Running this against code from untrusted strangers would need a stronger runtime (gVisor or Firecracker); that is a documented limitation, not a bug.

## Reporting

Please use GitHub's private vulnerability reporting (Security tab, "Report a vulnerability"), or email keshavmishra2112@gmail.com. Include the fixture or steps that reproduce it. A report that comes with a chaos-suite fixture under `tests/sandbox/cases/chaos/` is the most useful kind.

## Secrets

API keys live in `.env` (git-ignored) and are read only by the host process; they never enter a container. Every eval scans its traces and results for the planted canary secrets and for the real keys in the environment, and fails on a hit.
