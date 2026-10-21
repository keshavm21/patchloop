# Results

Committed records and reports. Every number in the main README and in [REPORT.md](REPORT.md) is computed from these files by `python -m patchloop.eval.publish`; nothing is typed in by hand.

| Folder or file | What it is |
|---|---|
| `humanevalfix-test/`, `mutbench-test/` | the headline runs on the test splits (`single_shot`, `full`; MutBench also has `binary`, `errors` and `full_5`) |
| `mutbench-test-qwen/` | the same comparison with a second model (`qwen/qwen3.8-27b`) |
| `humanevalfix-dev/`, `mutbench-dev/` | exploratory dev-split runs used to fix prompts and settings before any test run |
| `humanevalfix-dev-effort-medium/` | the first dev run, at the model's default reasoning effort, kept because ten percent of its attempts spent the whole token budget thinking; it is why every config sets `reasoning_effort: low` |
| `injectbench-test/`, `mutbench-dev-defense/` | the safety runs: InjectBench at defense levels D0 to D3, and clean MutBench dev tasks at D0 and D3 |
| `policy_check.json` | the policy check's false positives on every reference solution, and which chaos fixtures it stops |
| `baseline_replay.json` | the outcome of every InjectBench run on recorded replies, which `make smoke` must reproduce exactly |
| `error_analysis.json` | 32 unsolved runs, labelled by hand against the reference solutions |
| `sandbox_overhead_arm64.json` | per-run sandbox cost on Apple Silicon |

In each folder, `records.jsonl` has one line per finished run with its provenance (model, prompt version, git SHA, sandbox image, dataset checksum, architecture); `report.md` and `success_at_k.png` are generated from it; `canary_scan.json` lists what the post-run secret scan searched for and found. `records-before-rejudge.jsonl` keeps the earlier hidden verdicts from before `patchloop rejudge` re-ran them with the benchmark's 20 s per-test timeout, and `records-unused-repeat3.jsonl` holds 21 runs of a third HumanEvalFix repeat that is not part of the reported numbers.
