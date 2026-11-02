#!/usr/bin/env python3
"""Regression check for scripts/test-workers.py: each budget must still limit the count.

    python3 scripts/test_test_workers.py

The script reads the CPU affinity, a cgroup's CPU quota, the host's
MemAvailable and a cgroup's memory limit, usage and reclaimable cache. Here it
reads synthetic copies of those files in a temporary directory, so the answer
for a 2-CPU, 7 GiB container does not depend on the machine that runs the
check. Standard library only: it runs on the host, where `make lint` lives.
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

GIB = 1024**3
SPEC = importlib.util.spec_from_file_location(
    'test_workers', Path(__file__).with_name('test-workers.py')
)
assert SPEC and SPEC.loader
tw = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tw)


class Machine(unittest.TestCase):
    """A fake machine: affinity, /proc/meminfo and a cgroup tree, all in a temp dir."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.cgroup = self.root / 'cgroup'
        self.cgroup.mkdir()
        self.meminfo = self.root / 'meminfo'
        self.affinity = 16
        self.host_free = 64 * GIB
        for patch in (
            mock.patch.object(tw, '_CGROUP', self.cgroup),
            mock.patch.object(tw, '_MEMINFO', self.meminfo),
            mock.patch.object(
                tw.os, 'sched_getaffinity', lambda _pid: range(self.affinity)
            ),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.write_meminfo()

    def write_meminfo(self) -> None:
        self.meminfo.write_text(
            f'MemTotal: {self.host_free * 2 // 1024} kB\n'
            f'MemAvailable: {self.host_free // 1024} kB\n'
        )

    def put(self, relative: str, text: str) -> None:
        path = self.cgroup / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + '\n')

    def v2(self, *, cpus: str | None, memory: int | str, used: int, inactive: int = 0):
        if cpus is not None:
            self.put('cpu.max', cpus)
        self.put('memory.max', str(memory))
        self.put('memory.current', str(used))
        self.put('memory.stat', f'anon 1\ninactive_file {inactive}')

    def v1(self, *, quota: int, memory: int, used: int, inactive: int = 0):
        self.put('cpu/cpu.cfs_quota_us', str(quota))
        self.put('cpu/cpu.cfs_period_us', '100000')
        self.put('memory/memory.limit_in_bytes', str(memory))
        self.put('memory/memory.usage_in_bytes', str(used))
        self.put('memory/memory.stat', f'total_inactive_file {inactive}')


class TestCores(Machine):
    def test_affinity_is_the_count_without_a_cgroup(self) -> None:
        self.affinity = 6
        self.assertEqual(tw.cores(), 6)

    def test_a_v2_quota_caps_the_affinity(self) -> None:
        self.put('cpu.max', '200000 100000')
        self.assertEqual(tw.cores(), 2)

    def test_a_fractional_v2_quota_rounds_up(self) -> None:
        self.put('cpu.max', '150000 100000')
        self.assertEqual(tw.cores(), 2)

    def test_an_unlimited_v2_quota_leaves_the_affinity(self) -> None:
        self.put('cpu.max', 'max 100000')
        self.assertEqual(tw.cores(), 16)

    def test_a_v1_quota_caps_the_affinity(self) -> None:
        self.v1(quota=300000, memory=GIB, used=0)
        self.assertEqual(tw.cores(), 3)

    def test_an_unlimited_v1_quota_leaves_the_affinity(self) -> None:
        self.v1(quota=-1, memory=GIB, used=0)
        self.assertEqual(tw.cores(), 16)

    def test_a_quota_above_the_affinity_does_not_raise_it(self) -> None:
        self.affinity = 2
        self.put('cpu.max', '800000 100000')
        self.assertEqual(tw.cores(), 2)

    def test_a_machine_always_has_a_core(self) -> None:
        self.affinity = 0
        self.assertEqual(tw.cores(), 1)


class TestAvailableMemory(Machine):
    def test_the_host_figure_stands_without_a_cgroup(self) -> None:
        self.assertEqual(tw.available_memory(), 64 * GIB)

    def test_a_v2_limit_less_usage_caps_the_host_figure(self) -> None:
        self.v2(cpus=None, memory=7 * GIB, used=GIB // 2)
        self.assertEqual(tw.available_memory(), 7 * GIB - GIB // 2)

    def test_inactive_file_cache_counts_as_available(self) -> None:
        self.v2(cpus=None, memory=7 * GIB, used=GIB, inactive=GIB // 2)
        self.assertEqual(tw.available_memory(), 6 * GIB + GIB // 2)

    def test_an_unlimited_v2_group_leaves_the_host_figure(self) -> None:
        self.v2(cpus=None, memory='max', used=GIB)
        self.assertEqual(tw.available_memory(), 64 * GIB)

    def test_the_host_figure_caps_a_roomier_group(self) -> None:
        self.host_free = 2 * GIB
        self.write_meminfo()
        self.v2(cpus=None, memory=7 * GIB, used=0)
        self.assertEqual(tw.available_memory(), 2 * GIB)

    def test_a_v1_group_is_read_with_its_own_names(self) -> None:
        self.v1(quota=-1, memory=4 * GIB, used=GIB, inactive=GIB // 4)
        self.assertEqual(tw.available_memory(), 3 * GIB + GIB // 4)


class TestWorkers(Machine):
    """The budget that decides the count, one limit at a time."""

    def container(self, *, cpus: int, memory: int, used: int) -> None:
        self.v2(cpus=f'{cpus * 100000} 100000', memory=memory, used=used)

    def test_a_two_cpu_seven_gib_container_gets_six_and_two(self) -> None:
        self.container(cpus=2, memory=7 * GIB, used=GIB // 2)
        self.assertEqual(tw.workers('pytest'), 6)
        self.assertEqual(tw.workers('playwright'), 2)

    def test_one_gib_available_leaves_one_worker_each(self) -> None:
        self.container(cpus=2, memory=7 * GIB, used=6 * GIB)
        self.assertEqual(tw.workers('pytest'), 1)
        self.assertEqual(tw.workers('playwright'), 1)

    def test_cpu_alone_limits_when_memory_is_plentiful(self) -> None:
        self.container(cpus=1, memory=64 * GIB, used=0)
        self.assertEqual(tw.workers('pytest'), 4)
        self.assertEqual(tw.workers('playwright'), 1)

    def test_memory_alone_limits_when_cpus_are_plentiful(self) -> None:
        self.host_free = 3 * GIB
        self.write_meminfo()
        self.assertEqual(tw.workers('pytest'), 3)
        self.assertEqual(tw.workers('playwright'), 2)

    def test_the_ceilings_hold_on_a_large_machine(self) -> None:
        self.assertEqual(tw.workers('pytest'), 12)
        self.assertEqual(tw.workers('playwright'), 8)

    def test_a_starved_machine_still_gets_one_worker(self) -> None:
        self.host_free = 0
        self.write_meminfo()
        self.assertEqual(tw.workers('pytest'), 1)
        self.assertEqual(tw.workers('playwright'), 1)


if __name__ == '__main__':
    unittest.main()
