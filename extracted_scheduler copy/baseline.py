"""Baseline scheduler extracted from BeeCluster's ScheduleGreedy.

The Go reference is os/framework.go:790. This version keeps only the core idea:
score every drone-task pair by travel time, sort by cost, then choose pairs
without reusing a drone or task.
"""

from __future__ import annotations

from .models import Assignment, Drone, ScheduleResult, Task, estimate_flight_time


def is_schedulable_drone(drone: Drone) -> bool:
    # BeeCluster skips offline drones and drones whose phase is 2.
    return drone.online and not drone.returning_home and drone.phase != 2


def is_open_task(task: Task) -> bool:
    # In BeeCluster, request phases below 2 are still scheduler-visible.
    return task.phase < 2


def schedule(
    tasks: list[Task],
    drones: list[Drone],
    *,
    speed: float = 10.0,
    action_overhead: float = 1.0,
) -> ScheduleResult:
    """Assign available drones to open tasks.

    Returns a mapping of drone_id -> task_id.
    """

    candidates: list[Assignment] = []
    result = ScheduleResult()

    for drone in drones:
        if not is_schedulable_drone(drone):
            result.debug.append(f"skip drone {drone.id}: not schedulable")
            continue

        for task in tasks:
            if not is_open_task(task):
                continue

            cost = estimate_flight_time(drone.loc, task.loc, speed) + action_overhead
            candidates.append(Assignment(drone.id, task.id, cost))

    candidates.sort(key=lambda item: item.cost)

    used_drones: set[int] = set()
    used_tasks: set[int] = set()

    for candidate in candidates:
        if candidate.drone_id in used_drones:
            continue
        if candidate.task_id in used_tasks:
            continue

        result.assignments[candidate.drone_id] = candidate.task_id
        used_drones.add(candidate.drone_id)
        used_tasks.add(candidate.task_id)
        result.debug.append(
            f"assign drone {candidate.drone_id} to task "
            f"{candidate.task_id}, cost {candidate.cost:.2f}"
        )

    return result
