# MultiUAV-Plat Intern Work

This folder is a lightweight working record for learning, reproducing tasks, and tracking experiment results with MultiUAV-Plat.

## Purpose

- Record setup steps and environment details.
- Track daily progress, blockers, and questions.
- Store copied sample sessions used for learning.
- Store experiment notes, exported sessions, and result files.
- Keep any helper scripts separate from the upstream project code.

## Suggested Workflow

1. Start the server and controller.
2. Import or create a session.
3. Run one task or experiment.
4. Export the session/results when useful.
5. Write a short daily log entry.

## Folder Layout

```text
intern-work/
├── README.md
├── setup/
│   ├── environment.md
│   └── install_notes.md
├── experiments/
│   └── README.md
└── daily-logs/
    └── XXXX-XX-XX.md
```

## Daily Log Format

Use one Markdown file per day, named `YYYY-MM-DD.md`.

This is easier to review in GitHub because each day has a focused diff. If a day becomes long, split the details into an experiment folder and link to it from the daily log.

## What To Commit

- Markdown notes
- Environment/setup notes.
- Session exports used for experiments.
- Result exports from the agent checker.
- Small helper scripts you write.

## What Not To Commit

- API keys or tokens
- `agent4drone/llm_settings.json`
- Large raw logs
- Temporary build/cache files
