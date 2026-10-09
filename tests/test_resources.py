import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch, MagicMock

from gostream_resources import (cgroup_locations, container_resources, process_resources,
                               application_storage, network_sample, cpuset_count)


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    @staticmethod
    def put(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(value), encoding='utf-8')

    def test_v2_uses_container_usage_and_tightest_visible_parent_limits(self):
        mount, leaf = self.root / 'cgroup', self.root / 'cgroup/app'
        self.put(leaf / 'memory.current', 200 * 1024**2)
        self.put(leaf / 'memory.max', 'max')
        self.put(mount / 'memory.max', 1024**3)
        self.put(leaf / 'cpu.stat', 'usage_usec 2500000\nuser_usec 2000000')
        self.put(leaf / 'cpu.max', '400000 100000')
        self.put(mount / 'cpu.max', '200000 100000')
        self.put(leaf / 'cpuset.cpus.effective', '0-3')
        resources = container_resources({'v2': (leaf, mount)})
        self.assertEqual(resources['memory'], {'used': 200 * 1024**2, 'limit': 1024**3, 'scope': 'container'})
        self.assertEqual(resources['cpu']['limit'], 2)
        self.assertEqual(list(resources['cpu']['counters'].values()), [2.5])

    def test_unlimited_cgroup_never_substitutes_host_ram_or_cpu(self):
        leaf = self.root / 'group'
        self.put(leaf / 'memory.current', 200)
        self.put(leaf / 'memory.max', 'max')
        self.put(leaf / 'cpu.stat', 'usage_usec 1000')
        self.put(leaf / 'cpu.max', 'max 100000')
        self.put(leaf / 'cpuset.cpus.effective', '0-127')
        with patch('psutil.virtual_memory', side_effect=AssertionError('Host RAM must not be used')):
            resources = container_resources({'v2': (leaf, leaf)})
        self.assertIsNone(resources['memory']['limit'])
        self.assertIsNone(resources['cpu']['limit'])

    def test_v1_separate_cpu_controllers_and_unlimited_memory_sentinel(self):
        memory, cpu, acct = (self.root / name for name in ('memory', 'cpu', 'cpuacct'))
        self.put(memory / 'memory.usage_in_bytes', 500)
        self.put(memory / 'memory.limit_in_bytes', 9223372036854771712)
        self.put(cpu / 'cpu.cfs_quota_us', 50000)
        self.put(cpu / 'cpu.cfs_period_us', 100000)
        self.put(acct / 'cpuacct.usage', 3000000000)
        resources = container_resources({'memory': (memory, memory), 'cpu': (cpu, cpu), 'cpuacct': (acct, acct)})
        self.assertEqual(resources['memory']['used'], 500)
        self.assertIsNone(resources['memory']['limit'])
        self.assertEqual(resources['cpu']['limit'], 0.5)
        self.assertEqual(list(resources['cpu']['counters'].values()), [3])

    def test_mountinfo_resolves_non_root_membership_and_escaped_mount_paths(self):
        mount = self.root / 'mount with spaces'
        (mount / 'app').mkdir(parents=True)
        self.put(self.root / 'self/cgroup', '0::/service/app')
        escaped = mount.as_posix().replace(' ', r'\040')
        self.put(self.root / 'self/mountinfo', f'1 2 0:1 /service {escaped} rw - cgroup2 cgroup rw')
        self.assertEqual(cgroup_locations(self.root), {'v2': (mount / 'app', mount)})

    def test_namespace_root_mount_and_host_root_are_distinguished(self):
        mount = self.root / 'group'
        mount.mkdir()
        self.put(self.root / 'self/cgroup', '0::/')
        self.put(self.root / 'self/mountinfo', f'1 2 0:1 / {mount.as_posix()} rw - cgroup2 cgroup rw')
        self.assertEqual(cgroup_locations(self.root), {})
        self.put(mount / 'memory.current', 100)
        self.assertEqual(cgroup_locations(self.root), {'v2': (mount, mount)})

    def test_malformed_or_missing_cgroups_return_unknown(self):
        leaf = self.root / 'group'
        self.put(leaf / 'memory.current', 'not a number')
        self.put(leaf / 'cpu.stat', 'usage_usec bad')
        self.assertEqual(container_resources({'v2': (leaf, leaf)}), {'cpu': None, 'memory': None})
        self.assertEqual(cgroup_locations(self.root), {})
        self.assertEqual(cpuset_count('0-2,5,7-8'), 6)
        self.assertIsNone(cpuset_count('invalid'))

    def test_storage_counts_project_and_uploads_not_environment_or_git(self):
        self.put(self.root / 'app.py', 'abc')
        self.put(self.root / 'uploads/video.mp4', '12345')
        self.put(self.root / '.git/objects/file', 'ignore')
        self.put(self.root / '.venv/package.py', 'ignore')
        self.assertEqual(application_storage(self.root), 8)
        self.assertIsNone(application_storage(self.root / 'missing'))

    @patch('gostream_resources.psutil.Process')
    def test_local_fallback_measures_only_process_tree(self, process_class):
        parent, child = MagicMock(), MagicMock()
        process_class.return_value = parent
        parent.children.return_value = [child]
        for process, pid, rss, seconds in ((parent, 1, 100, 2), (child, 2, 300, 4)):
            process.pid = pid
            process.create_time.return_value = 50
            process.memory_info.return_value = SimpleNamespace(rss=rss)
            process.cpu_times.return_value = SimpleNamespace(user=seconds, system=1)
        result = process_resources()
        self.assertEqual(result['memory'], {'used': 400, 'limit': None, 'scope': 'proses'})
        self.assertEqual(sum(result['cpu']['counters'].values()), 8)
        self.assertIsNone(result['cpu']['limit'])

    @patch('gostream_resources.os.readlink', return_value='net:[123]')
    @patch('gostream_resources.sys.platform', 'linux')
    @patch('gostream_resources.psutil.net_io_counters')
    def test_network_counters_exclude_loopback(self, net, readlink):
        net.return_value = {'lo': SimpleNamespace(bytes_sent=9999, bytes_recv=9999),
                            'eth0': SimpleNamespace(bytes_sent=100, bytes_recv=200)}
        result = network_sample()
        self.assertEqual(result['interfaces'], {'eth0': (100, 200)})
        self.assertEqual(result['identity'], 'net:[123]')


if __name__ == '__main__':
    unittest.main()
