"""Run the BeeCluster-style scheduler extraction.

Use from the repository root:

    python -m extracted_scheduler.demo_beecluster
"""

from __future__ import annotations

from .beecluster import schedule
from .models import Drone, PredictedTask, Task


tasks = [
    Task(id=10, loc=(30.0, 0.0, 0.0)),
    Task(id=11, loc=(60.0, 0.0, 0.0)),
]

drones = [
    Drone(id=0, loc=(0.0, 0.0, 0.0)),
    Drone(id=1, loc=(20.0, 20.0, 0.0)),
    Drone(id=2, loc=(70.0, 5.0, 0.0)),
]

predictions = [
    PredictedTask(loc=(90.0, 0.0, 0.0), probability=1.0, depth=0),
    PredictedTask(loc=(95.0, 20.0, 0.0), probability=0.8, depth=1),
    PredictedTask(loc=(10.0, 45.0, 0.0), probability=0.6, depth=1),
]

result = schedule(
    tasks,
    {
        "drones": drones,
        "global_prediction": predictions,
        "seed": 7,
    },
)

print("assignments:", result.assignments)
print("speculation targets:", result.speculation_targets)
print("raw BeeCluster assignment:", result.raw_assignment)
print("cost:", result.cost)
for line in result.debug:
    print("debug:", line)
