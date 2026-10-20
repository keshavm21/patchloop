## Results

Test splits, repair rate = share of tasks whose **hidden** tests pass, with 95% bootstrap intervals over tasks ([full report](results/REPORT.md)).

| Benchmark (model) | Tasks × repeats | Single shot | Repair loop (3 attempts, test feedback) | Difference, points |
|---|---|---|---|---|
| MutBench, bugs new to the model (`$mb_model`) | $mb_full_n | $mb_single_shot | $mb_full | **$mb_single_shot_vs_full** |
| MutBench (`$qwen_model`) | $qwen_full_n | $qwen_single_shot | $qwen_full | **$qwen_single_shot_vs_full** |
| HumanEvalFix, public and likely memorised (`$hef_model`) | $hef_full_n | $hef_single_shot | $hef_full | $hef_single_shot_vs_full |

- **Where the model can't recall the answer.** MutBench: $mb_single_shot_vs_full_verdict for the main model, $qwen_single_shot_vs_full_verdict for the second. HumanEvalFix: the model already solves $hef_single_shot_rate% in one shot ($hef_single_shot_vs_full_verdict).
- **How the loop gains.** Of the main model's $mb_gained extra MutBench solves, $mb_gained_feedback were wrong answers fixed after seeing a failing test. Of the second model's $qwen_gained, $qwen_gained_format were malformed replies that a second attempt recovered.
- **How much feedback it needs** (MutBench, main model). Pass/fail counts alone: `single_shot` $mb_single_shot_rate% → `binary` $mb_binary_rate% ($mb_single_shot_vs_binary_verdict). Adding failing tests and exceptions (`errors`, $mb_errors_rate%) or full tracebacks (`full`, $mb_full_rate%): against `full`, `binary` shows $mb_binary_vs_full_verdict and `errors` $mb_errors_vs_full_verdict.
- **How many attempts.** With up to 5 attempts, $mb_full_5_k1% of MutBench is solved at attempt 1, $mb_full_5_k2% by attempt 2, $mb_full_5_k3% by 3 and $mb_full_5_k5% by 5.
- **Safety.** The chaos suite ($chaos_passed of $chaos_tests tests) shows the sandbox contains every hostile fixture. On InjectBench's 20 planted-instruction tasks, the share of runs where the agent's code tried the planted action goes D0 $inj_d0_attempted% → D1 $inj_d1_attempted% → D2 $inj_d2_attempted% → D3 $inj_d3_attempted%, with $inj_violations effective violations and $canary_hits canary leaks; on clean MutBench dev tasks the repair rate is $clean_d0_rate% at D0 and $clean_d3_rate% at D3 ($clean_verdict). The policy check blocks $pol_fp of $pol_total reference solutions.
- **Why the rest fail.** In $ea_total hand-labelled failures: wrong diagnosis ($ea_wrong_diagnosis), partial fixes ($ea_partial_fix), benchmark noise where the reference contradicts its own spec ($ea_benchmark_noise), and over-defensive validation ($ea_over_defensive_validation). There was no case of hard-coding the visible tests.
