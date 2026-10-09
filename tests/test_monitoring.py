import unittest
from unittest.mock import Mock, patch

import psutil

from gostream_monitor import count_streams, format_memory, format_rate, network_rates, server_sample, cpu_rate


class MonitoringTests(unittest.TestCase):
    @staticmethod
    def network(seconds, sent, received, identity="namespace"):
        return {"time": seconds, "interfaces": {"eth0": (sent, received)}, "identity": identity}

    def test_network_converts_byte_deltas_to_bits_per_second(self):
        self.assertEqual(network_rates(self.network(10, 100, 200), self.network(12, 250100, 125200)), (1000000, 500000))
        self.assertEqual(format_rate(1000000), "1.00 Mbps")
        self.assertEqual(format_rate(500000), "500.00 Kbps")

    def test_no_misleading_rate_before_sample_or_after_counter_reset(self):
        self.assertIsNone(network_rates(None, self.network(10, 100, 200)))
        self.assertIsNone(network_rates(self.network(10, 100, 200), None))
        self.assertIsNone(network_rates(self.network(10, 100, 200), self.network(10, 100, 200)))
        self.assertIsNone(network_rates(self.network(10, 100, 200), self.network(12, 10, 20)))
        self.assertEqual(network_rates(self.network(10, 100, 200), self.network(12, 100, 200)), (0, 0))

    def test_new_network_interface_does_not_create_a_rate_spike(self):
        previous, current = self.network(10, 100, 200), self.network(12, 110, 220)
        current['interfaces']['eth1'] = (10**12, 10**12)
        self.assertEqual(network_rates(previous, current), (40, 80))
        current['identity'] = 'other namespace'
        self.assertIsNone(network_rates(previous, current))

    def test_cpu_uses_elapsed_cpu_seconds_not_host_percent(self):
        previous = {'time': 10, 'cpu': {'scope': 'container', 'counters': {'group': 100}}}
        current = {'time': 12, 'cpu': {'scope': 'container', 'counters': {'group': 101}}}
        self.assertEqual(cpu_rate(previous, current), 0.5)
        current['cpu']['counters']['group'] = 0
        self.assertIsNone(cpu_rate(previous, current))
        current['cpu']['scope'] = 'proses'
        self.assertIsNone(cpu_rate(previous, current))

    def test_binary_memory_units_are_explicit(self):
        self.assertEqual(format_memory(1024 ** 3), "1.00 GiB")

    @staticmethod
    def process(name, command, status=psutil.STATUS_RUNNING):
        child = Mock()
        child.name.return_value = name
        child.cmdline.return_value = command
        child.status.return_value = status
        return child

    @patch("gostream_monitor.psutil.Process")
    def test_counts_only_live_rtmp_ffmpeg_children(self, process):
        stream = self.process("ffmpeg.exe", ["ffmpeg", "-i", "video.mp4", "rtmp://test.invalid/live/secret"])
        convert = self.process("ffmpeg", ["ffmpeg", "-i", "video.mp4", "out.mp4"])
        unrelated = self.process("python", ["python", "rtmp://test.invalid"])
        dead = self.process("ffmpeg", ["ffmpeg", "rtmp://test.invalid"], psutil.STATUS_ZOMBIE)
        vanished = Mock()
        vanished.name.side_effect = psutil.NoSuchProcess(123)
        process.return_value.children.return_value = [stream, convert, unrelated, dead, vanished]
        self.assertEqual(count_streams(), 1)
        process.return_value.children.assert_called_once_with(recursive=True)
        stream.terminate.assert_not_called()
        stream.kill.assert_not_called()

    @patch("gostream_monitor.psutil.Process")
    def test_denied_process_data_is_unknown_not_zero(self, process):
        process.return_value.children.side_effect = psutil.AccessDenied(123)
        self.assertIsNone(count_streams())

    def test_unavailable_metrics_do_not_break_the_dashboard(self):
        server_sample.clear()
        with patch("gostream_monitor.count_streams", return_value=None), \
             patch("gostream_monitor.container_resources", return_value={'cpu': None, 'memory': None}), \
             patch("gostream_monitor.process_resources", return_value={'cpu': None, 'memory': None}), \
             patch("gostream_monitor.storage_sample", return_value=None), \
             patch("gostream_monitor.network_sample", return_value=None):
            result = server_sample()
            result.pop('time')
            self.assertEqual(result, {"streams": None, "cpu": None, "memory": None, "network": None, 'storage': None})
        server_sample.clear()


if __name__ == "__main__":
    unittest.main()
