# Experiments

Use one folder per session/run. Each folder should contain the same basic artifacts so results are easy to compare later.

## Folder Format

```text
experiments/
└── 001_short_session_or_run_name/
    ├── notes.md
    ├── session_export.json
    ├── result_export.json
    └── screenshots/
```

## File Roles

- `notes.md`: human-readable lab notes, decisions, commands, blockers, and observations.
- `session_export.json`: the session/world/task snapshot used as input for the run.
- `result_export.json`: the output/results from a task run or AI Agent Auto-Check export.
- `screenshots/`: UI screenshots, maps, task windows, or result screenshots.

## Notes Template

```markdown
# Experiment: Title

## Goal

What task or behavior am I trying to reproduce?

## Setup

- Date:
- MultiUAV-Plat commit/version:
- Server mode:
- Controller/UI used:
- Agent used:
- Session export:

## Procedure

1. 
2. 
3. 

## Results

- Passed tasks:
- Failed tasks:
- Notable observations:

## Artifacts

- Session export: `session_export.json`
- Result export: `result_export.json`
- Screenshots: `screenshots/`

## Questions / Next Steps

- 
```

## Naming

Use a short numbered folder name for real experiments:

```text
001_example_session_manual_smoke_test
002_target_assignment_agent4drone
003_area_search_manual_replay
```

The `sample-sessions/` folder uses the same structure, but those folders are starter examples rather than completed experiment runs.
