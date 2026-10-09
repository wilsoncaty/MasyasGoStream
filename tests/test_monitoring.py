import unittest
from unittest.mock import Mock, patch

import psutil

from gostream_monitor import count_streams, format_memory, format_rate, network_rates, server_sample


class MonitoringTests(unittest.TestCase):
    def test_network_converts_byte_deltas_to_bits_per_second(self):
        self.assertEqual(network_rates((10, 100, 200), (12, 250100, 125200)), (1000000, 500000))
        self.assertEqual(format_rate(1000000), "1.00 Mbps")
        self.assertEqual(format_rate(500000), "500.00 Kbps")

    def test_no_misleading_rate_before_sample_or_after_counter_reset(self):
        self.assertIsNone(network_rates(None, (10, 100, 200)))
        self.assertIsNone(network_rates((10, 100, 200), None))
        self.assertIsNone(network_rates((10, 100, 200), (10, 100, 200)))
        self.assertIsNone(network_rates((10, 100, 200), (12, 10, 20)))
        self.assertEqual(network_rates((10, 100, 200), (12, 100, 200)), (0, 0))

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
             patch("gostream_monitor.psutil.cpu_percent", side_effect=OSError), \
             patch("gostream_monitor.psutil.virtual_memory", side_effect=OSError), \
             patch("gostream_monitor.psutil.net_io_counters", return_value=None):
            self.assertEqual(server_sample(), {"streams": None, "cpu": None, "memory": None, "network": None})
        server_sample.clear()


if __name__ == "__main__":
    unittest.main()
