"""Run the Wordle Benchmark from Python, using the same resources as the CLI.

Equivalent to ``plural run --benchmark wordle --agent word-list``, except the Job
is not recorded under ``.plural/jobs``.
"""

from pathlib import Path

from plural import Job
from plural.project import Project, Workspace

if __name__ == "__main__":
    workspace = Workspace(Project.find(Path(__file__).parent))
    benchmark = workspace.get("benchmark", "wordle")
    agent = workspace.get("agent", "word-list")
    result = Job(benchmark, agents=[agent]).run()
    for trial in result.trials:
        print(f"{trial.receipt.task_pin.name}: score={trial.score}")
