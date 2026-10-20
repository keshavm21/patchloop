"""Measure the policy check without a model, and write results/policy_check.json.

    python -m patchloop.safety.measure

False positives: any block on a benchmark reference solution (§7.1). Coverage: how many of the
chaos fixtures the check stops before they reach the sandbox. The sandbox contains all of them
either way, so coverage is a bonus (early feedback), not the defense.
"""

import json
import subprocess
from pathlib import Path

from .policy import check

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "results" / "policy_check.json"


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def false_positives() -> dict:
    out = {}
    for name in ("humanevalfix", "mutbench", "examples"):
        pattern = "tasks/*/reference.py" if name != "examples" else "*/reference.py"
        base = ROOT / "benchmarks" / name / ("v1" if name != "examples" else "")
        files = sorted(base.glob(pattern))
        findings = {}
        for f in files:
            r = check(f.read_text())
            if r.blocked or r.flagged:
                findings[f.parent.name] = {"blocked": r.blocked, "flagged": r.flagged}
        out[name] = {
            "references": len(files),
            "blocked": sum(bool(v["blocked"]) for v in findings.values()),
            "flagged": sum(bool(v["flagged"]) for v in findings.values()),
            "findings": findings,
        }
    return out


def chaos_coverage() -> dict:
    cases = ROOT / "tests" / "sandbox" / "cases" / "chaos"
    caught, missed = {}, []
    for f in sorted(cases.glob("*/*/solution.py")):
        r = check(f.read_text())
        label = f"{f.parent.parent.name}/{f.parent.name}"
        if r.blocked:
            caught[label] = r.blocked[0]
        else:
            missed.append(label)
    return {
        "fixtures": len(caught) + len(missed),
        "blocked": len(caught),
        "caught": caught,
        "passed_the_check": missed,
    }


def main() -> None:
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    result = {"git_sha": sha, "false_positives": false_positives(), "chaos": chaos_coverage()}
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    fp = result["false_positives"]
    total = sum(v["references"] for v in fp.values())
    blocked = sum(v["blocked"] for v in fp.values())
    c = result["chaos"]
    print(f"false positives: {blocked} of {total} references blocked")
    print(f"chaos fixtures stopped by the check: {c['blocked']} of {c['fixtures']}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
