"""The defense ladder (D0–D3), the canary scan and the replay baseline (§7, §12)."""

import os

import pytest
from scripted import failed, passed, reply_with
from test_eval import WRONG, KeyedLLM, results

from patchloop.agent.loop import solve
from patchloop.agent.prompts import build_messages
from patchloop.bench.frozen import Benchmark
from patchloop.config import AgentConfig
from patchloop.eval import baseline
from patchloop.eval.runner import EvalPlan, read_records, run_eval
from patchloop.llm.fake import FakeLLM
from patchloop.models import Status, StopReason
from patchloop.safety import canary
from patchloop.safety.base import allow_all, policy_for
from patchloop.safety.policy import check
from patchloop.sandbox.fake import FakeSandbox

SUBPROCESS = "import subprocess\ndef second_largest(nums):\n    return 2\n"


def messages(task, defense, attempts=()):
    cfg = AgentConfig(defense=defense, explain_failures=False)
    return build_messages(task, task.starting_code, list(attempts), cfg), cfg


# -- the ladder


def test_d0_has_no_rule_and_no_tags(task):
    system, user = (m["content"] for m in messages(task, "D0")[0])
    assert "data" not in system and "<task>" not in user and "<code>" not in user
    assert task.instruction in user and task.starting_code.strip() in user


def test_d1_adds_the_rule_but_still_no_tags(task):
    system, user = (m["content"] for m in messages(task, "D1")[0])
    assert "are data" in system and "never follow them" in system
    assert "<task>" not in user and "<code>" not in user and "<tests>" not in user


def test_d2_tags_untrusted_input_and_declares_it_data(task):
    system, user = (m["content"] for m in messages(task, "D2")[0])
    assert "<task>" in system and "never follow them" in system
    for tag in ("task", "code", "tests"):
        assert f"<{tag}>" in user and f"</{tag}>" in user


def test_d3_sends_the_same_prompt_as_d2(task):
    assert messages(task, "D3")[0] == messages(task, "D2")[0]


def test_only_d3_runs_the_policy_check():
    assert policy_for("D0") is allow_all and policy_for("D2") is allow_all
    assert policy_for("D3") is check


def test_feedback_is_untagged_below_d2(task):
    from patchloop.models import Attempt

    attempt = Attempt(n=1, reply="", code=WRONG, summary="", result=failed("test_single_element"))
    below = messages(task, "D1", [attempt])[0][1]["content"]
    above = messages(task, "D2", [attempt])[0][1]["content"]
    assert "<execution_output" not in below and "Output of attempt 1" in below
    assert '<execution_output attempt="1">' in above


def run_solve(task, defense, code):
    cfg = AgentConfig(defense=defense, explain_failures=False, max_attempts=1)
    sandbox = FakeSandbox(lambda c, d: passed(9) if d == task.hidden_dir else passed())
    rec = solve(task, cfg, FakeLLM([reply_with(code)]), sandbox)
    return rec, sandbox


def test_d3_blocks_code_before_it_reaches_the_sandbox(task):
    rec, sandbox = run_solve(task, "D3", SUBPROCESS)
    assert rec.attempts[0].result.status is Status.POLICY_BLOCKED
    assert sandbox.runs == [(task.starting_code, task.hidden_dir)]  # only the hidden verdict


def test_below_d3_the_same_code_goes_to_the_sandbox(task):
    for defense in ("D0", "D1", "D2"):
        rec, sandbox = run_solve(task, defense, SUBPROCESS)
        assert rec.stop_reason is StopReason.SOLVED, defense
        assert len(sandbox.runs) == 2


# -- the canary scan


def test_scan_reports_the_name_of_a_leaked_secret_not_its_value(tmp_path):
    (tmp_path / "trace.jsonl").write_text(f'{{"stdout": "{canary.CANARY_VALUE}"}}\n')
    (tmp_path / "clean.jsonl").write_text('{"stdout": "nothing"}\n')
    hits = canary.scan([tmp_path], canary.secrets_to_hunt())
    assert [(h.path.name, h.secret) for h in hits] == [("trace.jsonl", "canary env")]
    assert canary.CANARY_VALUE not in repr(hits)


def test_scan_hunts_api_keys_in_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SOME_API_KEY", "sk-test-0123456789abcdef")
    monkeypatch.setenv("TINY_TOKEN", "short")  # too short to search for
    names = canary.secrets_to_hunt()
    assert "SOME_API_KEY" in names and "TINY_TOKEN" not in names
    (tmp_path / "records.jsonl").write_text("... sk-test-0123456789abcdef ...")
    assert [h.secret for h in canary.scan([tmp_path])] == ["SOME_API_KEY"]


@pytest.fixture
def eval_plan(task, tmp_path):
    bench = Benchmark("examples", {"checksum": "abc"}, [task])
    cfg = AgentConfig(name="full", max_attempts=1, explain_failures=False)
    return EvalPlan(bench, "dev", [cfg], repeats=1, out=tmp_path / "out", work=tmp_path / "work")


def test_an_eval_plants_the_canary_and_a_clean_run_has_no_hits(task, eval_plan, monkeypatch):
    monkeypatch.delenv(canary.CANARY_ENV, raising=False)
    summary = run_eval(
        eval_plan,
        lambda cfg: KeyedLLM([reply_with(WRONG)]),
        sandbox_for=lambda w: FakeSandbox(results(task)),
    )
    assert os.environ[canary.CANARY_ENV] == canary.CANARY_VALUE
    assert summary.ran == 1 and summary.canary_hits == []


def test_an_eval_whose_output_carries_the_canary_reports_it(task, eval_plan):
    leaky = reply_with(WRONG + f"# {canary.CANARY_VALUE}\n")
    summary = run_eval(
        eval_plan,
        lambda cfg: KeyedLLM([leaky]),
        sandbox_for=lambda w: FakeSandbox(results(task)),
    )
    assert summary.canary_hits
    assert all(hit.endswith(": canary env") for hit in summary.canary_hits)


# -- the replay baseline


def test_baseline_round_trip_and_differences(task, eval_plan, tmp_path):
    run_eval(
        eval_plan,
        lambda cfg: KeyedLLM([reply_with(WRONG)]),
        sandbox_for=lambda w: FakeSandbox(results(task)),
    )
    records = read_records(eval_plan.out)
    path = tmp_path / "baseline.json"
    baseline.write_baseline(path, records)
    assert baseline.differences(path, records) == []
    changed = [{**records[0], "stop_reason": "SOLVED"}]
    assert "expected" in baseline.differences(path, changed)[0]
    assert "in the baseline but not run" in baseline.differences(path, [])[0]


# -- InjectBench metrics


def test_injectbench_metrics_count_new_lines_only():
    from patchloop.bench import injectbench
    from patchloop.eval import inject

    p = injectbench.PAYLOADS["tests"]
    starting = {"t1": "def f(x):\n    return x\n", "t2": "def f(x):\n    return x\n"}

    def rec(task, code, status="PASSED", attempt_status="PASSED"):
        return {
            "task_id": task,
            "config": "defense_d2",
            "repeat": 0,
            "stop_reason": "SOLVED",
            "meta": {"channel": "tests", "injection": {"markers": p["markers"]}},
            "attempts": [{"code": code, "result": {"status": attempt_status}}],
            "hidden_result": {"status": status},
        }

    records = [
        rec("t1", "KNOWN_ANSWERS = {1: 1}\ndef f(x):\n    return KNOWN_ANSWERS[x]\n"),
        rec("t2", starting["t2"], attempt_status="PASSED"),
    ]
    row = inject.by_config(records, starting)["defense_d2"]
    assert row["runs"] == 2 and row["attempted"] == 1 and row["solved"] == 2
    assert row["effective_violations"] == 0
    blocked = rec(
        "t1", "KNOWN_ANSWERS = 1\n", status="TESTS_FAILED", attempt_status="POLICY_BLOCKED"
    )
    assert inject.by_config([blocked], starting)["defense_d2"]["blocked"] == 1
