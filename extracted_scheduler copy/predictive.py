"""First predictive scheduler step inspired by BeeCluster.

This is intentionally smaller than the full Go implementation in os/scheduler.go.
It adds BeeCluster's central idea to the baseline scheduler:

1. Assign drones to real, currently visible tasks.
2. If any drones are still idle, pre-position them near predicted future tasks.

BeeCluster calls this second behavior "speculative execution".
"""

from __future__ import annotations

from .baseline import is_open_task, is_schedulable_drone
from .models import (
    Assignment,
    Drone,
    PredictedTask,
    ScheduleResult,
    Task,
    estimate_flight_time,
)


def schedule(
    tasks: list[Task],
    drones: list[Drone],
    predictions: list[PredictedTask] | None = None,
    *,
    speed: float = 10.0,
    action_overhead: float = 1.0,
) -> ScheduleResult:
    """Assign real tasks, then give unused drones speculative targets.

    Returns:
      assignments: drone_id -> real task_id
      speculation_targets: drone_id -> predicted future location
    """

    predictions = predictions or []
    result = ScheduleResult()

    real_candidates: list[Assignment] = []

    for drone in drones:
        if not is_schedulable_drone(drone):
            result.debug.append(f"skip drone {drone.id}: not schedulable")
            continue

        for task in tasks:
            if not is_open_task(task):
                continue

            cost = estimate_flight_time(drone.loc, task.loc, speed) + action_overhead
            real_candidates.append(Assignment(drone.id, task.id, cost))

    real_candidates.sort(key=lambda item: item.cost)

    used_drones: set[int] = set()
    used_tasks: set[int] = set()

    for candidate in real_candidates:
        if candidate.drone_id in used_drones:
            continue
        if candidate.task_id in used_tasks:
            continue

        result.assignments[candidate.drone_id] = candidate.task_id
        used_drones.add(candidate.drone_id)
        used_tasks.add(candidate.task_id)
        result.debug.append(
            f"assign drone {candidate.drone_id} to real task "
            f"{candidate.task_id}, cost {candidate.cost:.2f}"
        )

    prediction_candidates: list[tuple[float, int, int]] = []

    for drone in drones:
        if not is_schedulable_drone(drone):
            continue
        if drone.id in used_drones:
            continue

        for prediction_index, prediction in enumerate(predictions):
            cost = estimate_flight_time(drone.loc, prediction.loc, speed)
            if prediction.probability > 0:
                cost = cost / prediction.probability
            prediction_candidates.append((cost, drone.id, prediction_index))

    prediction_candidates.sort(key=lambda item: item[0])

    used_predictions: set[int] = set()

    for cost, drone_id, prediction_index in prediction_candidates:
        if drone_id in used_drones:
            continue
        if prediction_index in used_predictions:
            continue

        prediction = predictions[prediction_index]
        result.speculation_targets[drone_id] = prediction.loc
        used_drones.add(drone_id)
        used_predictions.add(prediction_index)
        result.debug.append(
            f"speculate drone {drone_id} toward predicted task "
            f"{prediction_index}, cost {cost:.2f}"
        )

    return result
