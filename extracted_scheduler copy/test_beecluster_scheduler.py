"""Regression checks for the BeeCluster scheduler extraction.

Run from the repository root:

    python -m unittest extracted_scheduler.test_beecluster_scheduler
"""

from __future__ import annotations

import unittest

from .beecluster import prediction_partitioning, schedule
from .models import Drone, PredictedTask, Task


class BeeClusterSchedulerTests(unittest.TestCase):
    def test_assigns_real_tasks_before_speculation(self) -> None:
        """Real requests should be returned as assignments, predictions as speculation."""

        tasks = [Task(id=10, loc=(10.0, 0.0, 0.0))]
        drones = [
            Drone(id=0, loc=(0.0, 0.0, 0.0)),
            Drone(id=1, loc=(100.0, 0.0, 0.0)),
        ]
        predictions = [
            PredictedTask(loc=(90.0, 0.0, 0.0), probability=1.0, depth=0),
            PredictedTask(loc=(95.0, 0.0, 0.0), probability=1.0, depth=1),
        ]

        result = schedule(
            tasks,
            {
                "drones": drones,
                "global_prediction": predictions,
                "seed": 1,
            },
        )

        self.assertIn(10, result.assignments.values())
        self.assertTrue(result.speculation_targets)
        self.assertNotEqual(
            set(result.assignments),
            set(result.speculation_targets),
            "one drone should do real work while another speculates",
        )

    def test_phase_two_task_is_not_open(self) -> None:
        """BeeCluster does not schedule tasks whose phase is already acquired."""

        tasks = [Task(id=10, loc=(10.0, 0.0, 0.0), phase=2)]
        drones = [Drone(id=0, loc=(0.0, 0.0, 0.0))]

        result = schedule(tasks, {"drones": drones})

        self.assertEqual(result.assignments, {})
        self.assertEqual(result.speculation_targets, {})

    def test_prediction_partitioning_creates_one_cluster_per_drone(self) -> None:
        """PredictionPartitioning is the bridge from DAG forecasts to scheduling."""

        predictions = [
            PredictedTask(loc=(0.0, 0.0, 0.0), probability=1.0, depth=0),
            PredictedTask(loc=(100.0, 0.0, 0.0), probability=1.0, depth=0),
        ]

        assignment, clusters = prediction_partitioning(predictions, 2)

        self.assertEqual(len(assignment), 2)
        self.assertEqual(len(clusters), 2)


if __name__ == "__main__":
    unittest.main()
