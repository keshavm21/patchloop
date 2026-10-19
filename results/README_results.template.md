## Results

Test splits, repair rate = share of tasks whose **hidden** tests pass, with 95% bootstrap intervals over tasks ([full report](results/REPORT.md)).

| Benchmark (model) | Tasks × repeats | Single shot | Repair loop (3 attempts, test feedback) | Difference, points |
|---|---|---|---|---|
| MutBench, bugs new to the model (`$mb_model`) | $mb_full_n | $mb_single_shot | $mb_full | **$mb_single_shot_vs_full** |
| MutBench (`$qwen_model`) | $qwen_full_n | $qwen_single_shot | $qwen_full | **$qwen_single_shot_vs_full** |
| HumanEvalFix, public and likely memorised (`$hef_model`) | $hef_full_n | $hef_single_shot | $hef_full | $hef_single_shot_vs_full |

- **Where the model can't recall the answer.** MutBench: $mb_single_shot_vs_full_verdict for the main model, $qwen_single_shot_vs_full_verdict for the second. HumanEvalFix: the model already solves $hef_single_shot_rate% in one shot ($hef_single_shot_vs_full_verdict).
- **How the loop gains.** Of the main model's $mb_gained extra MutBench solves, $mb_gained_feedback were wrong answers fixed after seeing a failing test. Of the second model's $qwen_gained, $qwen_gained_format were malformed replies that a second attempt recovered.
- **Why the rest fail.** In $ea_total hand-labelled failures: wrong diagnosis ($ea_wrong_diagnosis), partial fixes ($ea_partial_fix), benchmark noise where the reference contradicts its own spec ($ea_benchmark_noise), and over-defensive validation ($ea_over_defensive_validation). There was no case of hard-coding the visible tests.
