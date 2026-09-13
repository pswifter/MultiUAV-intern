"""Run a tiny predictive scheduling example.

From the repo root:

    python -m extracted_scheduler.demo_predictive
"""

from __future__ import annotations

from .models import Drone, PredictedTask, Task
from .predictive import schedule


def main() -> None:
    drones = [
        Drone(id=0, loc=(0.0, 0.0, 0.0)),
        Drone(id=1, loc=(100.0, 0.0, 0.0)),
        Drone(id=2, loc=(50.0, 50.0, 0.0)),
    ]

    tasks = [
        Task(id=10, loc=(10.0, 0.0, 0.0)),
        Task(id=11, loc=(90.0, 0.0, 0.0)),
    ]

    predictions = [
        PredictedTask(loc=(45.0, 45.0, 0.0), probability=0.9),
        PredictedTask(loc=(200.0, 200.0, 0.0), probability=0.3),
    ]

    result = schedule(tasks, drones, predictions)

    print("real assignments:", result.assignments)
    print("speculation targets:", result.speculation_targets)
    print()
    print("debug:")
    for line in result.debug:
        print(" ", line)


if __name__ == "__main__":
    main()
