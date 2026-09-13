"""Run this file to see the first extracted scheduler in action.

From the repo root:

    python -m extracted_scheduler.demo
"""

from __future__ import annotations

from .baseline import schedule
from .models import Drone, Task


def main() -> None:
    drones = [
        Drone(id=0, loc=(0.0, 0.0, 0.0)),
        Drone(id=1, loc=(100.0, 0.0, 0.0)),
    ]

    tasks = [
        Task(id=10, loc=(10.0, 0.0, 0.0)),
        Task(id=11, loc=(90.0, 0.0, 0.0)),
        Task(id=12, loc=(50.0, 20.0, 0.0)),
    ]

    result = schedule(tasks, drones)

    print("assignments:", result.assignments)
    print()
    print("debug:")
    for line in result.debug:
        print(" ", line)


if __name__ == "__main__":
    main()
