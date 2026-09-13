"""Python data model for the BeeCluster scheduler extraction.

The original BeeCluster code stores scheduler inputs inside Go structs such as
Request, Drone, Prediction, and VirtualNode. These dataclasses mirror the fields
that the scheduler actually reads, while staying small enough for another
simulator to construct them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt


Location = tuple[float, float, float]


@dataclass(frozen=True)
class Task:
    """A real, currently visible request.

    This mirrors the scheduler-relevant fields of BeeCluster's Go Request struct
    in os/framework.go. Most simple integrations only need id and loc. The
    remaining fields let us reproduce BeeCluster behaviors such as "phase 2"
    acquired tasks and non-interruptible shadow requests.
    """

    id: int
    loc: Location
    phase: int = 0
    duration: float = 0.0
    scheduled_time: float = 0.0
    non_interruptible: bool = False
    acquired_drone_id: int = -1
    is_shadow_request: bool = False
    local_shadow_request_parent: int = -1
    shadow_request_parent_drone_id: int = -1
    code_block_name: str = ""
    session_id: int = 0


@dataclass(frozen=True)
class PredictedTask:
    """A likely future request produced by BeeCluster's forecasting stage.

    BeeCluster calls these VirtualNode objects in os/dag.go. A predicted task
    does not create a real assignment yet; if a drone is mapped to one, the
    scheduler returns it as a speculation target.
    """

    loc: Location
    probability: float = 1.0
    depth: int = 0
    duration: float = 0.0
    cancel_other_task: bool = False
    cancel_other_task_radius: float = 0.0


@dataclass(frozen=True)
class Drone:
    """Current state of one drone.

    phase follows BeeCluster's simulator convention:
      0: free / idle
      1: flying toward a target
      2: acquired by an application after reaching a target
    """

    id: int
    loc: Location
    phase: int = 0
    online: bool = True
    returning_home: bool = False
    flying_speed: float = 10.0
    current_speed: float = 0.0
    acceleration: float = 1.0
    remaining_flight_time: float = 0.0


@dataclass(frozen=True)
class Assignment:
    drone_id: int
    task_id: int
    cost: float


@dataclass
class ScheduleResult:
    assignments: dict[int, int] = field(default_factory=dict)
    speculation_targets: dict[int, Location] = field(default_factory=dict)
    debug: list[str] = field(default_factory=list)
    raw_assignment: dict[int, int] = field(default_factory=dict)
    cost: float | None = None


def distance(a: Location, b: Location) -> float:
    """Match BeeCluster's rough distance function.

    The original Go code treats altitude as less important by dividing z by 3.
    """

    dx = a[0] - b[0]
    dy = a[1] - b[1]
    dz = (a[2] - b[2]) / 3.0
    return sqrt(dx * dx + dy * dy + dz * dz)


def estimate_flight_time(a: Location, b: Location, speed: float = 10.0) -> float:
    """Simple flight-time estimate for the first Python extraction.

    BeeCluster's simulator has a more detailed acceleration model. For learning
    and integration work, distance / speed is a good first approximation.
    """

    if speed <= 0:
        raise ValueError("speed must be positive")
    return distance(a, b) / speed


def beecluster_flight_time(drone: Drone, destination: Location) -> float:
    """Port BeeCluster simulator's FlyingTimeEst formula.

    Reference: os/simulator.go:960. The Go simulator accounts for acceleration
    and current speed rather than using only distance / speed. Keeping this
    formula makes the Python scheduler's cost model much closer to BeeCluster.
    """

    if drone.flying_speed <= 0:
        raise ValueError("drone.flying_speed must be positive")
    if drone.acceleration <= 0:
        raise ValueError("drone.acceleration must be positive")

    t0 = drone.current_speed / drone.acceleration
    adjusted_distance = distance(drone.loc, destination) + t0 * t0 * drone.acceleration
    accel_time_to_cruise = drone.flying_speed / drone.acceleration
    accel_distance = accel_time_to_cruise * accel_time_to_cruise * drone.acceleration

    if adjusted_distance > accel_distance:
        return (
            (adjusted_distance - accel_distance) / drone.flying_speed
            + accel_time_to_cruise * 2.0
        )
    return sqrt(adjusted_distance / drone.acceleration) * 2.0
