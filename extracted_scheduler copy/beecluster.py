"""Faithful Python extraction of BeeCluster's predictive scheduler.

This module is a direct, research-oriented port of the scheduling path in:

  * os/framework.go:1192       Framework.Schedule
  * os/scheduler.go:1270       Framework.ScheduleBeeCluster
  * os/scheduler.go:63         ScheduleProblem
  * os/scheduler.go:161        ScheduleProblem.Solve
  * os/scheduler.go:280        ScheduleProblem.ComputeCost

Important boundary:
BeeCluster's Go runtime obtains predictions from dag.go. The intern guide asks
for a standalone function, so this Python version accepts those predictions as
inputs. That preserves the actual scheduling optimizer while avoiding a hard
dependency on the full Go Framework/DAG server.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import permutations
import math
import random
from typing import Iterable

from .baseline import is_open_task
from .models import (
    Assignment,
    Drone,
    Location,
    PredictedTask,
    ScheduleResult,
    Task,
    beecluster_flight_time,
    distance,
)


REAL_TASK_REWARD = 1000.0
PREDICTED_TASK_REWARD = 1000.0


DEFAULT_WEIGHTS: dict[str, float] = {
    "WorkloadImbalanceCost": 1.0,
    "MutualUtilityCost": 1.0,
    "EfficientRouteCost(a)": 4.0,
    "EfficientRouteCost(b)": 20.0,
    "Time2Cost": 1.0,
}


@dataclass
class Prediction:
    """Container matching BeeCluster's Go Prediction struct.

    In Go, a Prediction contains []*VirtualNode plus a timestamp. The timestamp
    matters to dag.go's refresh logic, but not to ScheduleProblem itself.
    """

    nodes: list[PredictedTask] = field(default_factory=list)
    timestamp: int = 0


@dataclass
class FleetState:
    """Optional richer input object for schedule().

    The intern guide's shape is schedule(tasks, fleet_state). To keep that API
    while still reproducing BeeCluster, fleet_state can carry:

    * drones: current drone states
    * global_prediction: predicted future tasks used for speculation/clustering
    * per_task_prediction: task_id -> predictions, mostly for cancellation logic
    * weights: BeeCluster scheduler weights from framework_config_beecluster.json
    """

    drones: list[Drone]
    global_prediction: Prediction | list[PredictedTask] | None = None
    per_task_prediction: dict[int, Prediction | list[PredictedTask]] = field(
        default_factory=dict
    )
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))


@dataclass
class TaskInfo:
    """Scheduler-private metadata attached to each real/shadow task."""

    cluster_id: int = -1
    utility: float = 0.0


@dataclass
class DroneInfo:
    """Scheduler-private metadata attached to each drone."""

    cluster_id: int = -1


@dataclass
class ScheduleProblem:
    """Python version of BeeCluster's Go ScheduleProblem struct.

    Assignment encoding exactly follows the Go comments:
      -1 means the drone receives no target.
      0..len(tasks)-1 refer to real/shadow tasks.
      len(tasks)..len(tasks)+len(predicted_tasks)-1 refer to predictions.
    """

    tasks: list[Task]
    drones: list[Drone]
    predicted_tasks: list[PredictedTask] = field(default_factory=list)
    per_task_prediction: list[Prediction | None] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    rng: random.Random = field(default_factory=random.Random)
    preserve_go_return_bug: bool = True
    preserve_go_furthest_bug: bool = True

    task_info: list[TaskInfo] = field(default_factory=list)
    drone_info: list[DroneInfo] = field(default_factory=list)
    predicted_task_cluster_assignment: list[int] = field(default_factory=list)
    predicted_task_cluster: list[Location] = field(default_factory=list)
    task_per_cluster: list[list[int]] = field(default_factory=list)
    predicted_task_per_cluster: list[list[int]] = field(default_factory=list)
    drone_closest_prediction: list[int] = field(default_factory=list)
    drone2task_affinity: list[list[int]] = field(default_factory=list)
    unassigned_task: list[int] = field(default_factory=list)
    unassigned_drone: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.task_info:
            self.task_info = [TaskInfo() for _ in self.tasks]
        if not self.per_task_prediction:
            self.per_task_prediction = [None for _ in self.tasks]

    @property
    def assignment_size(self) -> int:
        """BeeCluster assigns at most one next target to each drone."""

        return len(self.drones)

    def setup(self) -> None:
        """Prepare cluster lookup tables and drone-task affinity.

        This ports ScheduleProblem.setup from os/scheduler.go:101. Most of the
        scheduler repeatedly asks questions like "which tasks are in this
        cluster?" and "may this drone handle this task?", so setup precomputes
        those lists once before simulated annealing starts.
        """

        self.drone_closest_prediction = [-1 for _ in self.drones]

        if len(self.predicted_task_cluster) > 1:
            self.task_per_cluster = [[] for _ in self.predicted_task_cluster]
            self.predicted_task_per_cluster = [[] for _ in self.predicted_task_cluster]

            for task_id, info in enumerate(self.task_info):
                if 0 <= info.cluster_id < len(self.task_per_cluster):
                    self.task_per_cluster[info.cluster_id].append(task_id)

            for prediction_id, cluster_id in enumerate(
                self.predicted_task_cluster_assignment
            ):
                if 0 <= cluster_id < len(self.predicted_task_per_cluster):
                    self.predicted_task_per_cluster[cluster_id].append(prediction_id)

            for drone_id, drone in enumerate(self.drones):
                cluster_id = self.drone_info[drone_id].cluster_id
                candidate_ids = self.predicted_task_per_cluster[cluster_id]
                locs = {tid: self.predicted_tasks[tid].loc for tid in candidate_ids}
                self.drone_closest_prediction[drone_id] = find_closest_key(
                    drone.loc, locs
                )

        self.drone2task_affinity = []
        for drone_id in range(len(self.drones)):
            task_ids: list[int] = []
            for task_id in range(len(self.tasks) + len(self.predicted_tasks)):
                if self.drone_task_affinity(drone_id, task_id):
                    task_ids.append(task_id)
            self.drone2task_affinity.append(task_ids)

    def solve(self) -> list[int]:
        """Find the next target for each drone.

        This ports ScheduleProblem.Solve from os/scheduler.go:161. BeeCluster
        starts with a greedy assignment, then perturbs it with simulated
        annealing, then does a local greedy improvement pass.

        The original Go code computes best_assignment, but returns assignment at
        the end. That looks like a bug, but this port preserves it by default
        because the current goal is to reproduce BeeCluster's actual repo code.
        Set preserve_go_return_bug=False to return the improved local-search
        result that the Go comments appear to intend.
        """

        self.setup()
        assignment = self.find_first_assignment()

        if len(self.tasks) + len(self.predicted_tasks) < len(self.drones):
            return assignment

        best_assignment = list(assignment)
        current_assignment = list(assignment)
        self.before_random_assignment(current_assignment)
        best_cost = self.compute_cost(current_assignment)

        # Simulated annealing: same loop counts and temperature schedule as Go.
        k_max = 100.0
        for k in range(500):
            temperature = k_max / float(k + 1)
            self.before_random_assignment(current_assignment)

            for _ in range(10):
                candidate = self.random_assignment_basic(current_assignment)
                candidate = self.filter_assignment(candidate)
                if candidate == current_assignment:
                    continue

                candidate_cost = self.compute_cost(candidate)
                accept_probability = 1.0
                if candidate_cost > best_cost:
                    accept_probability = math.exp(
                        -((candidate_cost - best_cost) / temperature)
                    )

                if accept_probability > self.rng.random():
                    best_cost = candidate_cost
                    current_assignment = list(candidate)
                break

        best_assignment = list(current_assignment)

        # Local greedy improvement: try random neighbors and keep improvements.
        for _ in range(10):
            self.before_random_assignment(current_assignment)
            for _ in range(100):
                candidate = self.random_assignment_basic(current_assignment)
                candidate = self.filter_assignment(candidate)
                candidate_cost = self.compute_cost(candidate)
                if candidate_cost < best_cost:
                    best_cost = candidate_cost
                    best_assignment = list(candidate)
            current_assignment = list(best_assignment)

        if self.preserve_go_return_bug:
            return assignment
        return best_assignment

    def compute_cost(self, assignment: list[int]) -> float:
        """Combine BeeCluster's scheduler cost terms.

        This ports ComputeCost from os/scheduler.go:280. Lower is better.
        Negative terms are rewards. The default weights come from
        os/configs/framework/framework_config_beecluster.json.
        """

        task_reward = self.task_reward(assignment)

        # The Go code computes workload imbalance, but multiplies it by 0.0.
        # We preserve that behavior so the port does not invent extra influence.
        workload_weight = self.weights.get("WorkloadImbalanceCost", 1.0)
        workload_imbalance = self.workload_imbalance_cost(assignment)
        workload_imbalance *= workload_weight * 0.0

        mutual_weight = self.weights.get("MutualUtilityCost", 1.0)
        mutual_task = self.mutual_task_cost(assignment) * mutual_weight

        route_a_weight = self.weights.get("EfficientRouteCost(a)", 4.0)
        route_cost = self.efficient_route_cost(assignment) * route_a_weight

        route_b_weight = self.weights.get("EfficientRouteCost(b)", 20.0)
        route_cost += (
            self.efficient_route_furthest_task_heuristic(assignment)
            * route_b_weight
        )

        time_weight = self.weights.get("Time2Cost", 1.0)
        time2 = self.time2_cost(assignment) * time_weight

        return task_reward + workload_imbalance + mutual_task + route_cost + time2

    def task_reward(self, assignment: list[int]) -> float:
        """Reward assigning drones to useful real or predicted work.

        This is the main reason BeeCluster uses spare drones for speculation:
        a predicted task receives a negative cost reward, discounted by depth,
        so nearer-future predictions are preferred.
        """

        reward = 0.0
        task2drone: dict[int, int] = {}

        for drone_id, task_id in enumerate(assignment):
            if 0 <= task_id < len(self.tasks):
                if not self.tasks[task_id].is_shadow_request:
                    reward -= REAL_TASK_REWARD
                    task2drone[task_id] = drone_id
            elif task_id >= len(self.tasks):
                prediction = self.predicted_tasks[task_id - len(self.tasks)]
                reward -= PREDICTED_TASK_REWARD / float(prediction.depth + 1)

        # Shadow requests preserve BeeCluster's non-interruptible handoff logic.
        # They are uncommon for the test apps, but keeping them matters for a
        # faithful scheduler port.
        for drone_id, task_id in enumerate(assignment):
            if not (0 <= task_id < len(self.tasks)):
                continue
            task = self.tasks[task_id]
            if not task.is_shadow_request:
                continue

            if task.local_shadow_request_parent >= 0:
                parent_drone = task2drone.get(task.local_shadow_request_parent)
                if parent_drone is None:
                    reward += 100.0
                    continue
                time_to_fly = self.drones[parent_drone].remaining_flight_time
            else:
                time_to_fly = max(0.0, task.duration)

            time_to_target = beecluster_flight_time(self.drones[drone_id], task.loc)
            if time_to_fly - 5.0 <= time_to_target:
                reward -= REAL_TASK_REWARD - (time_to_target - (time_to_fly - 5.0))

        return reward

    def workload_imbalance_cost(self, assignment: list[int]) -> float:
        """Port the workload-balancing estimate, even though Go disables it.

        BeeCluster estimates how long each drone's cluster will take to finish
        if it greedily handles remaining same-cluster tasks and then moves toward
        prediction work. ComputeCost multiplies this by zero in the official
        code, so the method is present for completeness and future experiments.
        """

        if len(self.predicted_task_cluster) <= 1:
            return 0.0

        assigned = set(assignment)
        if -1 in assigned:
            return 0.0

        max_cost = 0.0
        min_cost = float("inf")

        for drone_id, drone in enumerate(self.drones):
            cluster_id = self.drone_info[drone_id].cluster_id
            next_task = assignment[drone_id]
            if next_task < 0:
                continue

            cost = 0.0
            if next_task < len(self.tasks):
                cost += beecluster_flight_time(drone, self.tasks[next_task].loc)
                cost += self.tasks[next_task].duration
                current_loc = self.tasks[next_task].loc

                remaining = {
                    task_id: task.loc
                    for task_id, task in enumerate(self.tasks)
                    if self.task_info[task_id].cluster_id == cluster_id
                    and task_id not in assigned
                }
                while remaining:
                    task_id = find_closest_key(current_loc, remaining)
                    cost += distance(current_loc, self.tasks[task_id].loc) / max(
                        drone.flying_speed, 1e-9
                    )
                    cost += self.tasks[task_id].duration
                    current_loc = self.tasks[task_id].loc
                    del remaining[task_id]
            else:
                pred_id = next_task - len(self.tasks)
                current_loc = self.predicted_tasks[pred_id].loc
                cost += beecluster_flight_time(drone, current_loc)

            predicted = {
                pred_id: pred.loc
                for pred_id, pred in enumerate(self.predicted_tasks)
                if pred_id < len(self.predicted_task_cluster_assignment)
                and self.predicted_task_cluster_assignment[pred_id] == cluster_id
            }
            if predicted:
                pred_id = find_closest_key(current_loc, predicted)
                cost += distance(current_loc, self.predicted_tasks[pred_id].loc) / max(
                    drone.flying_speed, 1e-9
                )

            max_cost = max(max_cost, cost)
            min_cost = min(min_cost, cost)

        return max_cost if min_cost < float("inf") else 0.0

    def mutual_task_cost(self, assignment: list[int]) -> float:
        """Reward useful coverage while accounting for predicted cancellations.

        This ports MutualTaskCost from os/scheduler.go:606. If doing one task
        is predicted to cancel nearby tasks, BeeCluster reduces the value of
        separately covering those nearby tasks.
        """

        covered_task: dict[int, float] = {}
        for info in self.task_info:
            info.utility = 0.0

        for task_id in assignment:
            if 0 <= task_id < len(self.tasks):
                self.task_info[task_id].utility = 1.0
                covered_task[task_id] = 1.0

        for task_id in assignment:
            if not (0 <= task_id < len(self.tasks)):
                continue
            prediction = self.per_task_prediction[task_id]
            if prediction is None or not prediction.nodes:
                continue

            first_prediction = prediction.nodes[0]
            if not first_prediction.cancel_other_task:
                continue

            radius = first_prediction.cancel_other_task_radius
            if radius <= 0:
                continue

            for other_task_id in range(len(self.task_info)):
                if other_task_id == task_id:
                    continue
                d = distance(self.tasks[task_id].loc, self.tasks[other_task_id].loc)
                if d < radius:
                    self.task_info[other_task_id].utility += (
                        (1.0 - d / radius) * first_prediction.probability
                    )
                    if self.task_info[other_task_id].utility != 0.0:
                        covered_task[other_task_id] = (
                            1.0 / self.task_info[other_task_id].utility
                        )

        return -sum(covered_task.values())

    def time2_cost(self, assignment: list[int]) -> float:
        """Penalize long flights to real tasks using squared travel time."""

        cost = 0.0
        for drone_id, task_id in enumerate(assignment):
            if 0 <= task_id < len(self.tasks):
                flight_time = beecluster_flight_time(
                    self.drones[drone_id], self.tasks[task_id].loc
                )
                cost += flight_time * flight_time
        return cost

    def efficient_route_cost(self, assignment: list[int]) -> float:
        """Reward assignments that move real-task drones away from task center.

        This ports EfficientRouteCost from os/scheduler.go:706. It is a
        heuristic to avoid zig-zag routes by preferring drones whose next real
        task continues outward from the current task/prediction center.
        """

        center = weighted_center(
            [task.loc for task in self.tasks],
            [(pred.loc, pred.probability) for pred in self.predicted_tasks],
        )
        if center is None:
            return 0.0

        cost = 0.0
        for drone_id, task_id in enumerate(assignment):
            if 0 <= task_id < len(self.tasks):
                t1 = beecluster_flight_time(self.drones[drone_id], center)
                pseudo_drone = replace_drone_loc(
                    self.drones[drone_id], self.tasks[task_id].loc
                )
                t2 = beecluster_flight_time(pseudo_drone, center)
                route_reward = max(0.0, t2 - t1)
                cost -= route_reward
        return cost

    def efficient_route_furthest_task_heuristic(self, assignment: list[int]) -> float:
        """Extra reward for sending a drone to the furthest real task.

        This ports EfficientRouteFurthestTaskHeuristic from os/scheduler.go:753.
        Note: the Go code appears to forget updating d_max in its loop. This
        method preserves that typo by default for repo compatibility. Set
        preserve_go_furthest_bug=False to use the intended furthest-task logic.
        """

        if not self.tasks:
            return 0.0

        center = average([task.loc for task in self.tasks])
        furthest_task_id = 0
        max_distance = 0.0
        for task_id, task in enumerate(self.tasks):
            d = distance(task.loc, center)
            if d > max_distance:
                furthest_task_id = task_id
                if not self.preserve_go_furthest_bug:
                    max_distance = d

        cost = 0.0
        for drone_id, task_id in enumerate(assignment):
            if task_id == furthest_task_id:
                vec1 = loc_subtract(center, self.drones[drone_id].loc)
                vec2 = loc_subtract(self.tasks[task_id].loc, self.drones[drone_id].loc)
                if loc_dot(vec1, vec2) < 0.0:
                    cost -= 1.0
        return cost

    def before_random_assignment(self, assignment: list[int]) -> None:
        """Refresh lists of tasks and drones currently left unassigned."""

        assigned_tasks = {task_id for task_id in assignment if task_id >= 0}
        self.unassigned_task = [
            task_id
            for task_id in range(len(self.tasks) + len(self.predicted_tasks))
            if task_id not in assigned_tasks
        ]
        self.unassigned_drone = [
            drone_id for drone_id, task_id in enumerate(assignment) if task_id < 0
        ]

    def drone_task_affinity(self, drone_id: int, task_id: int) -> bool:
        """Return whether a drone is allowed to handle a task.

        BeeCluster prevents a task acquired by one drone from being assigned to
        a different drone. Predictions are always considered compatible.
        """

        if task_id < len(self.tasks):
            task = self.tasks[task_id]
            if task.acquired_drone_id == -1:
                return True
            return task.acquired_drone_id == self.drones[drone_id].id
        return True

    def random_assignment_basic(self, assignment: list[int]) -> list[int]:
        """Random neighbor generator used by simulated annealing.

        This ports RandomAssignmentBasic from os/scheduler.go:861. It mutates a
        copy through one of four moves: relocate, swap, activate, deactivate.
        """

        out = list(assignment)
        total_targets = len(self.tasks) + len(self.predicted_tasks)
        if not self.drones:
            return out

        if total_targets > len(self.drones):
            random_type = self.rng.choice(["relocate", "swap", "active"])
        else:
            random_type = self.rng.choice(["swap", "deactive", "active"])

        if random_type == "relocate" and self.unassigned_task:
            drone_id = self.rng.randrange(len(self.drones))
            task_id = self.rng.choice(self.unassigned_task)
            out[drone_id] = task_id
        elif random_type == "swap":
            drone1 = self.rng.randrange(len(self.drones))
            drone2 = self.rng.randrange(len(self.drones))
            out[drone1], out[drone2] = out[drone2], out[drone1]
        elif random_type == "active":
            if self.unassigned_drone and self.unassigned_task:
                drone_id = self.rng.choice(self.unassigned_drone)
                task_id = self.rng.choice(self.unassigned_task)
                out[drone_id] = task_id
        elif random_type == "deactive":
            drone_id = self.rng.randrange(len(self.drones))
            out[drone_id] = -1

        return out

    def filter_assignment(self, assignment: list[int]) -> list[int]:
        """Remove assignments that BeeCluster considers impossible."""

        out = list(assignment)
        for drone_id, task_id in enumerate(out):
            if task_id == -1:
                continue
            if not self.drone_task_affinity(drone_id, task_id):
                out[drone_id] = -1
            if self.drones[drone_id].returning_home:
                out[drone_id] = -1
        return out

    def find_first_assignment(self) -> list[int]:
        """Greedy initial assignment before simulated annealing.

        This ports FindFirstAssignment from os/scheduler.go:1113. Real tasks
        are preferred over predictions by adding max real-task distance to every
        prediction candidate.
        """

        pairs: list[Assignment] = []
        max_distance = 0.0
        center = average([task.loc for task in self.tasks]) if self.tasks else (0, 0, 0)

        for drone_id, drone in enumerate(self.drones):
            for task_id, task in enumerate(self.tasks):
                if not self.drone_task_affinity(drone_id, task_id):
                    continue
                if drone.returning_home:
                    continue

                cost = beecluster_flight_time(drone, task.loc)
                t1 = beecluster_flight_time(drone, center)
                pseudo_drone = replace_drone_loc(drone, task.loc)
                t2 = beecluster_flight_time(pseudo_drone, center)
                route_reward = max(0.0, t2 - t1)
                cost -= route_reward * 4.0
                max_distance = max(max_distance, cost)
                pairs.append(Assignment(drone_id, task_id, cost))

        for drone_id, drone in enumerate(self.drones):
            for prediction_id, prediction in enumerate(self.predicted_tasks):
                cost = beecluster_flight_time(drone, prediction.loc)
                cost += max_distance
                pairs.append(
                    Assignment(drone_id, prediction_id + len(self.tasks), cost)
                )

        pairs.sort(key=lambda item: item.cost)

        used_tasks: set[int] = set()
        used_drones: set[int] = set()
        assignment = [-1 for _ in range(self.assignment_size)]

        for pair in pairs:
            task_id = pair.task_id
            drone_id = pair.drone_id
            if task_id in used_tasks or drone_id in used_drones:
                continue

            # If prediction clustering exists, BeeCluster requires task and
            # drone to be in the same predicted cluster at initialization.
            if len(self.predicted_task_cluster) > 1:
                if task_id < len(self.tasks):
                    if self.task_info[task_id].cluster_id != self.drone_info[
                        drone_id
                    ].cluster_id:
                        continue
                else:
                    prediction_id = task_id - len(self.tasks)
                    if self.predicted_task_cluster_assignment[
                        prediction_id
                    ] != self.drone_info[drone_id].cluster_id:
                        continue

            used_tasks.add(task_id)
            used_drones.add(drone_id)
            assignment[drone_id] = task_id

        return assignment


def schedule(tasks: list[Task], fleet_state: FleetState | dict) -> ScheduleResult:
    """BeeCluster-style scheduling function requested by the intern guide.

    Args:
        tasks: Located real tasks that currently exist.
        fleet_state: Either a FleetState object or a dict with at least
            {"drones": [...]}. Optional keys:
            - "global_prediction" or "predictions"
            - "per_task_prediction"
            - "weights"
            - "seed"
            - "preserve_go_return_bug"
            - "preserve_go_furthest_bug"

    Returns:
        ScheduleResult:
            assignments maps drone_id -> real task_id.
            speculation_targets maps drone_id -> predicted location.
            raw_assignment exposes BeeCluster's internal assignment encoding.
    """

    state = coerce_fleet_state(fleet_state)
    seed = fleet_state.get("seed") if isinstance(fleet_state, dict) else None
    preserve_bug = (
        bool(fleet_state.get("preserve_go_return_bug", True))
        if isinstance(fleet_state, dict)
        else True
    )
    preserve_furthest_bug = (
        bool(fleet_state.get("preserve_go_furthest_bug", True))
        if isinstance(fleet_state, dict)
        else True
    )

    drones = [drone for drone in state.drones if drone.online]
    open_tasks = [task for task in tasks if is_open_task(task)]
    predictions = normalize_prediction(state.global_prediction).nodes
    per_task_prediction = build_per_task_prediction(open_tasks, state.per_task_prediction)

    problem = make_schedule_problem(
        open_tasks,
        drones,
        predictions,
        per_task_prediction,
        state.weights,
        seed=seed,
        preserve_go_return_bug=preserve_bug,
        preserve_go_furthest_bug=preserve_furthest_bug,
    )

    result = ScheduleResult()
    if not problem.tasks or not problem.drones:
        result.debug.append("no schedulable BeeCluster problem")
        return result

    assignment = problem.solve()
    result.cost = problem.compute_cost(assignment)

    for local_drone_id, encoded_task_id in enumerate(assignment):
        drone = problem.drones[local_drone_id]
        result.raw_assignment[drone.id] = encoded_task_id

        if encoded_task_id < 0:
            continue
        if encoded_task_id < len(problem.tasks):
            task = problem.tasks[encoded_task_id]
            if task.is_shadow_request:
                if drone.phase == 0:
                    result.speculation_targets[drone.id] = task.loc
                continue
            result.assignments[drone.id] = task.id
        else:
            if drone.phase == 0:
                prediction = problem.predicted_tasks[encoded_task_id - len(problem.tasks)]
                result.speculation_targets[drone.id] = prediction.loc

    result.debug.extend(
        [
            f"nTask={len(problem.tasks)} nDrone={len(problem.drones)} "
            f"nPred={len(problem.predicted_tasks)}",
            f"clusters={problem.predicted_task_cluster}",
            f"raw_assignment={assignment}",
            f"cost={result.cost:.4f}",
        ]
    )
    return result


def make_schedule_problem(
    tasks: list[Task],
    drones: list[Drone],
    predictions: list[PredictedTask],
    per_task_prediction: list[Prediction | None],
    weights: dict[str, float],
    *,
    seed: int | None = None,
    preserve_go_return_bug: bool = True,
    preserve_go_furthest_bug: bool = True,
) -> ScheduleProblem:
    """Build the Python equivalent of ScheduleBeeCluster's ScheduleProblem."""

    cluster_assignment, clusters = prediction_partitioning(predictions, len(drones))
    drone_locs = [drone.loc for drone in drones]
    drone_to_cluster = find_best_match(drone_locs, clusters)

    drone_info = [
        DroneInfo(cluster_id=drone_to_cluster.get(drone_id, -1))
        for drone_id in range(len(drones))
    ]
    task_info = [
        TaskInfo(cluster_id=find_closest_index(task.loc, clusters))
        for task in tasks
    ]

    return ScheduleProblem(
        tasks=tasks,
        drones=drones,
        predicted_tasks=predictions,
        per_task_prediction=per_task_prediction,
        weights={**DEFAULT_WEIGHTS, **weights},
        rng=random.Random(seed),
        preserve_go_return_bug=preserve_go_return_bug,
        preserve_go_furthest_bug=preserve_go_furthest_bug,
        task_info=task_info,
        drone_info=drone_info,
        predicted_task_cluster_assignment=cluster_assignment,
        predicted_task_cluster=clusters,
    )


def prediction_partitioning(
    predictions: list[PredictedTask], k: int
) -> tuple[list[int], list[Location]]:
    """Port Framework.PredictionPartitioning from os/scheduler.go:1594.

    BeeCluster partitions predicted future tasks into k clusters, then assigns
    each drone to a cluster. The implementation uses a custom initialization
    followed by 30 k-means-style updates weighted by prediction probability.
    """

    if k <= 0 or len(predictions) < k:
        return [], []

    depth_counter: dict[int, int] = {}
    min_depth = min(pred.depth for pred in predictions)
    for pred in predictions:
        depth_counter[pred.depth] = depth_counter.get(pred.depth, 0) + 1

    cancel_at_min_depth = sum(
        1
        for pred in predictions
        if pred.cancel_other_task and pred.depth == min_depth
    )
    if len(predictions) - cancel_at_min_depth < k:
        return [], []

    base_depth = 0
    count = 0
    while True:
        count += depth_counter.get(base_depth, 0)
        if count >= k:
            break
        base_depth += 1

    clusters: list[Location] = [(0.0, 0.0, 0.0) for _ in range(k)]
    assignments = [0 for _ in predictions]

    candidate: dict[int, Location] = {}
    min_distance: dict[int, float] = {}
    first = True
    for pred_id, pred in enumerate(predictions):
        if pred.depth <= base_depth:
            if first:
                clusters[0] = pred.loc
                first = False
            else:
                candidate[pred_id] = pred.loc
                min_distance[pred_id] = distance(pred.loc, clusters[0])

    for cluster_id in range(1, k):
        if not candidate:
            break

        max_coverage = -1
        max_coverage_id = next(iter(candidate))
        for candidate_id, loc1 in candidate.items():
            coverage = 0
            for other_id, loc2 in candidate.items():
                if distance(loc1, loc2) < min_distance[other_id]:
                    coverage += 1
            if coverage > max_coverage:
                max_coverage = coverage
                max_coverage_id = candidate_id

        clusters[cluster_id] = candidate[max_coverage_id]
        for other_id, loc2 in candidate.items():
            d = distance(clusters[cluster_id], loc2)
            if d < min_distance[other_id]:
                min_distance[other_id] = d
        del candidate[max_coverage_id]

    for _ in range(30):
        cluster_acc = [(0.0, 0.0, 0.0) for _ in range(k)]
        cluster_weight = [0.0 for _ in range(k)]

        for pred_id, pred in enumerate(predictions):
            best_cluster = find_closest_index(pred.loc, clusters)
            if best_cluster < 0:
                best_cluster = 0
            assignments[pred_id] = best_cluster
            cluster_acc[best_cluster] = loc_add(
                cluster_acc[best_cluster], loc_mul(pred.loc, pred.probability)
            )
            cluster_weight[best_cluster] += pred.probability

        for cluster_id in range(k):
            if cluster_weight[cluster_id] != 0.0:
                clusters[cluster_id] = loc_divide(
                    cluster_acc[cluster_id], cluster_weight[cluster_id]
                )

    return assignments, clusters


def coerce_fleet_state(fleet_state: FleetState | dict) -> FleetState:
    """Allow schedule() to accept either a dataclass or a plain dict."""

    if isinstance(fleet_state, FleetState):
        return fleet_state
    if not isinstance(fleet_state, dict):
        raise TypeError("fleet_state must be FleetState or dict")
    if "drones" not in fleet_state:
        raise ValueError("fleet_state must contain a 'drones' entry")

    global_prediction = fleet_state.get(
        "global_prediction", fleet_state.get("predictions")
    )
    return FleetState(
        drones=list(fleet_state["drones"]),
        global_prediction=global_prediction,
        per_task_prediction=dict(fleet_state.get("per_task_prediction", {})),
        weights=dict(fleet_state.get("weights", DEFAULT_WEIGHTS)),
    )


def normalize_prediction(value: Prediction | list[PredictedTask] | None) -> Prediction:
    """Convert user-friendly prediction input into a Prediction object."""

    if value is None:
        return Prediction()
    if isinstance(value, Prediction):
        return value
    return Prediction(nodes=list(value))


def build_per_task_prediction(
    tasks: list[Task],
    predictions_by_task_id: dict[int, Prediction | list[PredictedTask]],
) -> list[Prediction | None]:
    """Align task-id keyed predictions with ScheduleProblem's task list order."""

    aligned: list[Prediction | None] = []
    for task in tasks:
        prediction = predictions_by_task_id.get(task.id)
        aligned.append(normalize_prediction(prediction) if prediction is not None else None)
    return aligned


def find_closest_index(loc: Location, locs: list[Location]) -> int:
    """Python version of common.go findClosestIndex."""

    if not locs:
        return -1
    return min(range(len(locs)), key=lambda index: distance(loc, locs[index]))


def find_closest_key(loc: Location, locs: dict[int, Location]) -> int:
    """Python version of common.go findClosestKey."""

    if not locs:
        return -1
    return min(locs, key=lambda key: distance(loc, locs[key]))


def find_best_match(locs1: list[Location], locs2: list[Location]) -> dict[int, int]:
    """Port common.go findBestMatch.

    The Go code calls a Hungarian solver only when the two sides have equal
    length. This dependency-free port uses exhaustive assignment for the tiny
    drone counts common in BeeCluster experiments, then falls back to greedy for
    unequal lengths just like common.go does.
    """

    if not locs1 or not locs2:
        return {}
    if len(locs1) == len(locs2):
        return find_best_match_exact(locs1, locs2)

    return find_best_match_greedy(locs1, locs2)


def find_best_match_exact(
    locs1: list[Location], locs2: list[Location]
) -> dict[int, int]:
    """Small dependency-free replacement for BeeCluster's Hungarian call."""

    best_cost = float("inf")
    best_perm: tuple[int, ...] | None = None
    for perm in permutations(range(len(locs2))):
        cost = sum(distance(locs1[index], locs2[perm[index]]) for index in range(len(locs1)))
        if cost < best_cost:
            best_cost = cost
            best_perm = perm
    if best_perm is None:
        return {}
    return {index: cluster_id for index, cluster_id in enumerate(best_perm)}


def find_best_match_greedy(locs1: list[Location], locs2: list[Location]) -> dict[int, int]:
    """Port common.go findBestMatchGreedy."""

    candidates: list[tuple[float, int, int]] = []
    for ind1, loc1 in enumerate(locs1):
        for ind2, loc2 in enumerate(locs2):
            candidates.append((distance(loc1, loc2), ind1, ind2))
    candidates.sort()

    used1: set[int] = set()
    used2: set[int] = set()
    result: dict[int, int] = {}
    for _, ind1, ind2 in candidates:
        if ind1 in used1 or ind2 in used2:
            continue
        used1.add(ind1)
        used2.add(ind2)
        result[ind1] = ind2
    return result


def average(locs: Iterable[Location]) -> Location:
    """Average a collection of locations."""

    loc_list = list(locs)
    if not loc_list:
        return (0.0, 0.0, 0.0)
    total = (0.0, 0.0, 0.0)
    for loc in loc_list:
        total = loc_add(total, loc)
    return loc_divide(total, float(len(loc_list)))


def weighted_center(
    real_locs: list[Location], weighted_predictions: list[tuple[Location, float]]
) -> Location | None:
    """Center used by BeeCluster route-efficiency cost."""

    total = (0.0, 0.0, 0.0)
    weight = 0.0
    for loc in real_locs:
        total = loc_add(total, loc)
        weight += 1.0
    for loc, probability in weighted_predictions:
        total = loc_add(total, loc)
        weight += probability
    if weight <= 0.0:
        return None
    return loc_divide(total, weight)


def replace_drone_loc(drone: Drone, loc: Location) -> Drone:
    """Return a copy of drone at loc for flight-time estimates from a task."""

    return Drone(
        id=drone.id,
        loc=loc,
        phase=drone.phase,
        online=drone.online,
        returning_home=drone.returning_home,
        flying_speed=drone.flying_speed,
        current_speed=drone.current_speed,
        acceleration=drone.acceleration,
        remaining_flight_time=drone.remaining_flight_time,
    )


def loc_add(a: Location, b: Location) -> Location:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def loc_subtract(a: Location, b: Location) -> Location:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def loc_mul(a: Location, scalar: float) -> Location:
    return (a[0] * scalar, a[1] * scalar, a[2] * scalar)


def loc_divide(a: Location, scalar: float) -> Location:
    return (a[0] / scalar, a[1] / scalar, a[2] / scalar)


def loc_dot(a: Location, b: Location) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
