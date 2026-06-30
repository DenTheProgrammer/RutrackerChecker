# Context Policy

## Contamination Risks
Status: draft, not frozen.

The orchestrating agent has seen exploratory timing data and concurrency hypotheses before the metric contract and baseline were locked. Treat that context as contaminated for blind evaluation.

## Allowed Worker Context
- The frozen objective.
- The frozen metric contract and evaluation command.
- The project source tree and allowed change paths.
- The locked paths list and forbidden actions.

## Withheld Context
- Exploratory timing results from before baseline lock.
- Suggested worker-count values or expected optimal concurrency.
- Prior failed attempts, incumbent rationale, or conclusions from other workers.
- Any manual interpretation of why the current implementation is slow.

## Blind Agent Prompt Notes
Blind evaluation must use fresh worker context. If fresh-context subagents are not available, run only non-blind single or parallel experiments and label them accordingly.

## Parallel Worker Plan
Draft: use separate branches or worktrees per worker, each with a distinct worker id. Retest any stale candidate against the current incumbent before keep/discard.
