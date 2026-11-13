import importlib.util
import shlex
import sys
import tempfile
import time
import unittest
from pathlib import Path

from absa.run_jobs import run_all

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_kaggle_kernel", ROOT / "scripts" / "build_kaggle_kernel.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def py(code: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


class RunAllTest(unittest.TestCase):
    def test_each_gpu_sees_only_its_own_device_and_runs_in_parallel(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = (
                "import os, sys, time, pathlib; time.sleep(0.5); "
                f"pathlib.Path({tmp!r}, sys.argv[1]).write_text(os.environ['CUDA_VISIBLE_DEVICES'])"
            )
            tasks = [[py(code) + f" {name}"] for name in "ab"]
            started = time.time()
            self.assertEqual(run_all(tasks, ["0", "1"]), [])
            self.assertLess(time.time() - started, 0.95)
            seen = {(Path(tmp) / name).read_text() for name in "ab"}
        self.assertEqual(seen, {"0", "1"})

    def test_failure_skips_rest_of_task_but_not_other_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            touch = lambda name: py(f"import pathlib; pathlib.Path({tmp!r}, {name!r}).touch()")
            bad = [py("raise SystemExit(3)"), touch("after_failure")]
            good = [touch("other_task")]
            failed = run_all([bad, good], ["0"])
            self.assertEqual(failed, [bad])
            self.assertFalse((Path(tmp) / "after_failure").exists())
            self.assertTrue((Path(tmp) / "other_task").exists())


class CoreJobTest(unittest.TestCase):
    def test_p0_matches_the_protocol(self):
        tasks = builder.JOBS["p0"]["tasks"]
        self.assertEqual(len(tasks), 21)
        names = [t[0].split("--run-name ")[1] for t in tasks]
        self.assertEqual(len(set(names)), 21)
        for seed in (42, 43, 44):
            self.assertEqual(sum(n.endswith(f"seed{seed}") for n in names), 7)
        self.assertEqual(sum("BamiBERT" in t[0] for t in tasks), 6)

    def test_p0_never_scores_test_and_uses_protocol_defaults(self):
        for task in builder.JOBS["p0"]["tasks"]:
            self.assertEqual(len(task), 2)
            self.assertNotIn("--test", task[1])
            self.assertNotIn("--beta", task[0])
            self.assertNotIn("legacy", task[0])

    def test_p0_requires_a_data_hash(self):
        self.assertIsNone(builder.JOBS["p0"]["expected_data_hash"])
        self.assertIsNone(builder.JOBS["p0"]["dataset_sources"])


if __name__ == "__main__":
    unittest.main()
