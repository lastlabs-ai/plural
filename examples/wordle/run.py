"""Run the same public Job used by job.yaml."""

from agent import agent
from benchmark import benchmark

from plural import Client, Job

if __name__ == "__main__":
    job = Job(benchmark, agents=[agent], client=Client())
    result = job.run()
    print(f"{result.job_id}: {result.status}")
