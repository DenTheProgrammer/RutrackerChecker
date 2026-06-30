# AutoResearch Report: Speed up check all movies

- Study: `speed-up-check-all-movies`
- Status: `baseline_locked`
- Metric: `mean_wall_clock_seconds` (lower is better)
- Contract hash: `8ce024da65cb6f4e`
- Baseline numeric runs: 1
- Candidate runs: 3
- Decisions: keep=3, discard=0, crash=0
- Incumbent metric: 6.085898
- Incumbent commit: bbb7630
- Highlighted session: `session-20260630-061324-b2daabb2` (3 candidate runs)
- Highlighted session mode: `single`, workers: 1

![Progress](progress.svg)

## Recent Runs

| run | session | worker | metric | suggested | exit | description |
| --- | --- | --- | ---: | --- | ---: | --- |
| `20260630-061358-58d8994c` | `session-20260630-061324-b2daabb2` | `` | 9.06829 | keep | 0 | cycle 1: increase check-all worker default to 12 |
| `20260630-061533-0f2eb8b9` | `session-20260630-061324-b2daabb2` | `` | 6.35363 | keep | 0 | cycle 2: try check-all worker default 10 |
| `20260630-061802-23111926` | `session-20260630-061324-b2daabb2` | `` | 6.0859 | keep | 0 | cycle 3: try check-all worker default 8 |

## Recent Decisions

| decision | run | status | description |
| --- | --- | --- | --- |
| `decision-d3d316b9` | `20260630-061358-58d8994c` | keep | cycle 1 kept: worker default 12 improved mean_wall_clock_seconds to 9.068289 |
| `decision-a30203ab` | `20260630-061533-0f2eb8b9` | keep | cycle 2 kept: worker default 10 improved mean_wall_clock_seconds to 6.353633 |
| `decision-0a4ad445` | `20260630-061802-23111926` | keep | cycle 3 kept: worker default 8 improved mean_wall_clock_seconds to 6.085898 |
