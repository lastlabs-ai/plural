"""Run the same public Job used by job.yaml."""

from job import job

if __name__ == "__main__":
    result = job.run()
    print(f"{result.job_id}: {result.status}")
