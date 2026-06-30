# Speed up check all movies

## Objective
Reduce wall-clock time for checking all enabled RuTracker movie cards without increasing check errors or weakening result correctness

## Primary Metric
Draft, not frozen:
- Primary metric: wall-clock seconds for one full `CheckerService.check_all()` run over all enabled movie cards.
- Direction: lower is better.
- Guardrail: candidate run must not increase item-level check errors compared with the locked baseline.
- Guardrail: candidate run must preserve result correctness: same enabled item set, same RuTracker search query per item, same filtering rules, and no skipped pages beyond the frozen `max_search_pages`.
- Proposed minimum meaningful improvement: at least 15% lower median wall-clock time across baseline-equivalent repeats, with no error regression.

## Allowed Changes
Draft, not frozen:
- Likely allowed: `app.py`, `check_once.py`, and tests that exercise orchestration behavior.
- Do not change launcher code for this study unless explicitly approved; launcher changes require publishing root `RutrackerChecker.exe` before finishing.

## Locked Evaluation Surface
Draft, not frozen:
- Do not change the metric command, parser, baseline data, or fixture data after the contract is frozen.
- Do not change RuTracker query text, item enabled state, per-item filters, `max_search_pages`, or credentials during baseline/candidate comparison.
- Do not weaken filtering, skip enabled items, suppress errors, reduce retry semantics, or cache network responses only to improve the metric.
- Do not run candidate experiments before the metric contract and baseline are explicitly locked.

## Context Isolation
The orchestrating agent has seen exploratory timing results and possible concurrency-related hypotheses. Treat this context as contaminated for any blind evaluation. If blind workers are used, they may see only the frozen objective, allowed files, locked evaluation command, and project code needed to run it; do not pass exploratory timing values, expected worker counts, or prior hypotheses unless the context policy is revised explicitly.

## Baseline Notes
Not a locked baseline:
- Project currently has 12 enabled movie cards.
- Current persisted setting: `max_search_pages=3`.
- Current default worker limit in code: `CHECK_ALL_MAX_WORKERS=3`, but this is arbitrary and may be varied by future candidates if the frozen contract allows it.
- Exploratory measurements taken before this study was defined are only orientation data and must not be compared as the study baseline.
- Baseline must be recorded through the frozen AutoResearch eval command after requirements, metric, parser, locked paths, and allowed paths are confirmed.

## Experiment Ideas
Do not execute until the study is explicitly started:
- Compare controlled worker-count strategies.
- Revisit shared RuTracker client/session behavior under concurrency.
- Reduce avoidable per-item database work while preserving result persistence and notification behavior.
- Consider adaptive concurrency only if it keeps transient errors within the locked guardrail.
