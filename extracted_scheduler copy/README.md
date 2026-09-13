# Extracted Scheduler

This folder is a Python workspace for extracting BeeCluster's scheduling logic.

The main research-facing function now follows the intern guide shape:

```python
schedule(tasks, fleet_state)
```

It returns:

```python
ScheduleResult(
    assignments={drone_id: task_id},
    speculation_targets={drone_id: predicted_location},
)
```

## BeeCluster-style scheduler

The closest port lives in `beecluster.py`:

```python
from extracted_scheduler import Drone, PredictedTask, Task, schedule

tasks = [Task(id=1, loc=(30.0, 0.0, 0.0))]
drones = [Drone(id=0, loc=(0.0, 0.0, 0.0))]
predictions = [PredictedTask(loc=(60.0, 0.0, 0.0), probability=1.0)]

result = schedule(tasks, {
    "drones": drones,
    "global_prediction": predictions,
})
```

Run the BeeCluster-style demo from the repo root:

```bash
python -m extracted_scheduler.demo_beecluster
```

This version ports BeeCluster's `ScheduleProblem`, greedy initialization,
simulated annealing/local search, prediction clustering, and cost terms from
`os/scheduler.go`. It accepts prediction inputs directly instead of running
BeeCluster's full `dag.go` application-forecasting runtime.

## Learning references

`baseline.py` ports the simple baseline scheduler from:

```text
os/framework.go:790
```

The idea is:

1. Keep only drones that are online, not returning home, and not already at a
   task.
2. Keep only tasks whose phase is less than 2.
3. Compute every possible drone-task travel cost.
4. Sort by cheapest cost.
5. Pick pairs without reusing the same drone or the same task.

`predictive.py` adds the first BeeCluster idea: speculative execution.
It assigns real tasks first. Then, if any drones are still idle, it sends them
toward predicted future tasks.

Run the demo from the repo root:

```bash
python -m extracted_scheduler.demo
```

Run the predictive demo:

```bash
python -m extracted_scheduler.demo_predictive
```
