"""The eval runner, metrics and report, with a scripted model and a fake sandbox."""

import json

import pytest
from scripted import failed, passed, reply_with

from patchloop.bench.frozen import Benchmark
from patchloop.config import AgentConfig
from patchloop.eval.metrics import by_config
from patchloop.eval.report import write_report
from patchloop.eval.runner import EvalPlan, SettingsMismatch, read_records, run_eval
from patchloop.llm.base import LLMInfraError, Reply
from patchloop.models import Usage
from patchloop.sandbox.fake import FakeSandbox

FIXED = "def second_largest(nums):\n    return 2\n"
WRONG = "def second_largest(nums):\n    return 1\n"


class KeyedLLM:
    """Answers by attempt number (counted per task and repeat), or raises infra errors."""

    def __init__(self, answers, model="fake"):
        self.model = model
        self.answers = answers  # list of reply texts or exceptions, by attempt
        self.calls = 0

    def chat(self, messages, *, temperature, max_tokens, repeat=0):
        self.calls += 1
        n = messages[1]["content"].count("<execution_output")  # 0 on the first attempt
        answer = self.answers[min(n, len(self.answers) - 1)]
        if isinstance(answer, Exception):
            raise answer
        return Reply(
            text=answer, usage=Usage(input_tokens=10, output_tokens=5, calls=1), model=self.model
        )


def results(task):
    def run(code, tests_dir):
        if tests_dir == task.hidden_dir:
            return passed(9) if code == FIXED else failed("test_basic", expected=9)
        return passed() if code == FIXED else failed("test_single_element")

    return run


@pytest.fixture
def plan(task, tmp_path):
    bench = Benchmark("examples", {"checksum": "abc"}, [task])
    configs = [
        AgentConfig(name="single_shot", feedback="L0", max_attempts=1, explain_failures=False),
        AgentConfig(name="full", max_attempts=3, explain_failures=False),
    ]
    return EvalPlan(bench, "dev", configs, repeats=2, out=tmp_path / "out", work=tmp_path / "work")


def run(plan, task, answers):
    llm = KeyedLLM(answers)
    summary = run_eval(plan, lambda cfg: llm, sandbox_for=lambda work: FakeSandbox(results(task)))
    return summary, llm


def test_runs_every_triple_and_resumes(plan, task):
    summary, llm = run(plan, task, [reply_with(WRONG), reply_with(FIXED)])
    records = read_records(plan.out)
    assert summary.ran == 4 and len(records) == 4
    assert {(r["config"], r["repeat"]) for r in records} == {
        ("single_shot", 0),
        ("single_shot", 1),
        ("full", 0),
        ("full", 1),
    }
    assert records[0]["provenance"]["dataset_checksum"] == "abc"
    assert (
        records[0]["meta"]["bug_type"] == "missing logic" and "reference" not in records[0]["meta"]
    )
    again, llm2 = run(plan, task, [reply_with(FIXED)])
    assert again.ran == 0 and again.skipped == 4 and llm2.calls == 0


def test_infra_errors_are_retried_then_quarantined(plan, task):
    plan.configs = plan.configs[:1]
    plan.repeats = 1
    plan.stop_after_infra_errors = 99
    summary, llm = run(plan, task, [LLMInfraError("503")])
    records = read_records(plan.out)
    assert len(records) == 1 + plan.infra_retries  # first try plus each retry
    assert all(r["stop_reason"] == "INFRA_ERROR" for r in records)
    m = by_config(records)["single_shot"]
    assert m.runs == 0 and m.quarantined == 1


def test_consecutive_infra_errors_stop_the_eval(plan, task):
    plan.stop_after_infra_errors = 2
    summary, _ = run(plan, task, [LLMInfraError("429 quota")])
    assert summary.stopped_early and "quota" in summary.stopped_early
    assert summary.ran == 2


def test_metrics(plan, task):
    run(plan, task, [reply_with(WRONG), reply_with(FIXED)])
    metrics = by_config(read_records(plan.out))
    single, full = metrics["single_shot"], metrics["full"]
    assert (single.repair_rate, full.repair_rate) == (0.0, 1.0)
    assert full.success_at_k == {1: 0.0, 2: 1.0, 3: 1.0}
    assert full.attempts_to_success == 2
    assert single.stop_reasons == {"MAX_ATTEMPTS": 2}
    assert full.tokens_per_task == 30  # two calls of 15 tokens
    assert full.cost_per_task is None  # no price configured
    assert full.breakdowns["bug_type"] == {"missing logic": (2, 1.0)}
    assert full.cut_off_rate is None  # the scripted model reports no finish_reason


def test_overfit_is_visible_pass_hidden_fail(plan, task):
    overfit = "def second_largest(nums):\n    return 3\n"

    def run_results(code, tests_dir):
        if tests_dir == task.hidden_dir:
            return failed("test_all_equal", expected=9)
        return passed()

    plan.configs = plan.configs[1:]
    llm = KeyedLLM([reply_with(overfit)])
    run_eval(plan, lambda cfg: llm, sandbox_for=lambda work: FakeSandbox(run_results))
    m = by_config(read_records(plan.out))["full"]
    assert m.overfit_rate == 1.0 and m.repair_rate == 0.0


def test_report(plan, task):
    run(plan, task, [reply_with(WRONG), reply_with(FIXED)])
    path = write_report(plan.out)
    text = path.read_text()
    assert "| `full` | 1 × 2 | 100.0 |" in text
    assert "| `single_shot` | 1 × 2 | 0.0 |" in text
    assert "![success@k](success_at_k.png)" in text
    assert (plan.out / "success_at_k.png").stat().st_size > 1000
    assert "unknown" in text  # cost without prices
    json.loads((plan.out / "records.jsonl").read_text().splitlines()[0])


def test_resuming_with_changed_settings_is_refused(plan, task):
    run(plan, task, [reply_with(FIXED)])
    plan.configs[1] = plan.configs[1].model_copy(update={"max_attempts": 5})
    with pytest.raises(SettingsMismatch, match="max_attempts"):
        run(plan, task, [reply_with(FIXED)])
