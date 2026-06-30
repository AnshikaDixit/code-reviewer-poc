import asyncio
import os
from typing import NamedTuple
from services.review_service import analyze_pull_request

class ReviewTask(NamedTuple):
    priority: int  # Number of changed files (lower number = higher priority)
    repo_name: str
    pr_number: int
    commit_sha: str

# Global priority queue
review_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()

async def worker(worker_id: int):
    print(f"[Worker {worker_id}] Started.")
    while True:
        try:
            task: ReviewTask = await review_queue.get()
            print(f"[Worker {worker_id}] Picked up PR #{task.pr_number} from {task.repo_name} (Priority: {task.priority})")
            
            try:
                await analyze_pull_request(task.repo_name, task.pr_number, task.commit_sha)
            except Exception as e:
                print(f"[Worker {worker_id}] Error processing PR #{task.pr_number}: {e}")
            finally:
                review_queue.task_done()
                
        except asyncio.CancelledError:
            print(f"[Worker {worker_id}] Shutting down.")
            break
        except Exception as e:
            print(f"[Worker {worker_id}] Unexpected error in worker loop: {e}")
            await asyncio.sleep(1)

async def start_workers(concurrency: int = 2) -> list[asyncio.Task]:
    workers = []
    for i in range(concurrency):
        task = asyncio.create_task(worker(i + 1))
        workers.append(task)
    return workers
