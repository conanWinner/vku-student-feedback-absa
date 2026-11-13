"""Run tasks across GPUs, one task per GPU at a time.

A task is a list of commands run in order; a failed command skips the rest of its task
but other tasks continue. Exits non-zero if any task failed.

    python -m absa.run_jobs tasks.json
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path


def run_task(task: list[str], gpu: str) -> bool:
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": gpu}
    for command in task:
        print(f"[gpu {gpu}] $ {command}", flush=True)
        started = time.time()
        process = subprocess.Popen(shlex.split(command), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            if "Loading weights" not in line:
                print(f"[gpu {gpu}] {line}", end="", flush=True)
        code = process.wait()
        print(f"[gpu {gpu}] [{time.time() - started:.0f} s, exit {code}]", flush=True)
        if code != 0:
            return False
    return True


def run_all(tasks: list[list[str]], gpus: list[str]) -> list[list[str]]:
    """Returns the tasks that failed."""
    pending: queue.Queue = queue.Queue()
    for task in tasks:
        pending.put(task)
    failed: list[list[str]] = []

    def worker(gpu: str) -> None:
        while True:
            try:
                task = pending.get_nowait()
            except queue.Empty:
                return
            try:
                ok = run_task(task, gpu)
            except OSError as error:
                print(f"[gpu {gpu}] {error}", flush=True)
                ok = False
            if not ok:
                failed.append(task)

    threads = [threading.Thread(target=worker, args=(gpu,)) for gpu in gpus]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return failed


def visible_gpus() -> list[str]:
    import torch

    return [str(i) for i in range(torch.cuda.device_count())] or [""]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tasks", type=Path, help="JSON list of tasks; each task is a list of commands")
    args = parser.parse_args()
    all_tasks = json.loads(args.tasks.read_text(encoding="utf-8"))
    bad = run_all(all_tasks, visible_gpus())
    print(f"{len(all_tasks) - len(bad)}/{len(all_tasks)} tasks succeeded", flush=True)
    for task in bad:
        print("FAILED:", task[0], flush=True)
    sys.exit(1 if bad else 0)
