"""The replay smoke eval's baseline: a snapshot of every run's outcome that a replay of the
recorded replies must reproduce exactly (§12). With the model replaced by recorded replies, any
difference is a change in the agent, the sandbox or the prompts, never in the model."""

import json
from pathlib import Path


def outcome(record: dict) -> dict:
    hidden = (record.get("hidden_result") or {}).get("status")
    return {
        "stop_reason": record["stop_reason"],
        "hidden": hidden,
        "attempts": len(record["attempts"]),
        "final_attempt": record.get("final_attempt"),
        "statuses": [a["result"]["status"] for a in record["attempts"]],
    }


def snapshot(records: list[dict]) -> dict:
    latest = {}
    for r in records:
        if r["stop_reason"] != "INFRA_ERROR":
            latest[f"{r['task_id']}|{r['config']}|r{r['repeat']}"] = outcome(r)
    return {"runs": dict(sorted(latest.items()))}


def write_baseline(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot(records), indent=2) + "\n")


def differences(path: Path, records: list[dict]) -> list[str]:
    """What differs between the baseline file and this run, one line each; empty if equal."""
    expected = json.loads(path.read_text())["runs"]
    actual = snapshot(records)["runs"]
    lines = []
    for key in sorted(set(expected) | set(actual)):
        if key not in actual:
            lines.append(f"{key}: in the baseline but not run")
        elif key not in expected:
            lines.append(f"{key}: run but not in the baseline")
        elif expected[key] != actual[key]:
            lines.append(f"{key}: expected {expected[key]}, got {actual[key]}")
    return lines
