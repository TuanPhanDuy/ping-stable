"""Test pingstable: parser đúng, chịu được input hỏng, và không đụng vào hệ thống ngoài lệnh fix."""

import os
import signal
import subprocess
import sys
import time
import unittest
from argparse import Namespace
from unittest import mock

import pingstable as ps

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = [sys.executable, os.path.join(HERE, "pingstable.py")]

PING_OUT = """PING 1.1.1.1 (1.1.1.1): 56 data bytes
64 bytes from 1.1.1.1: icmp_seq=0 ttl=57 time=10.0 ms
Request timeout for icmp_seq 1
64 bytes from 1.1.1.1: icmp_seq=2 ttl=57 time=30.0 ms
64 bytes from 1.1.1.1: icmp_seq=3 ttl=57 time=20.0 ms
"""

TRACE_OUT = """ 1  192.168.1.1  3.2 ms
 2  *
 3  113.171.147.253  36.6 ms
 4  203.0.113.9  210.4 ms
"""

LSOF_OUT = """COMMAND     PID USER   FD   TYPE DEVICE SIZE/OFF NODE NAME
League\\x20 123 tuan   40u  IPv4 0x1      0t0  UDP 192.168.1.5:61000->104.18.26.48:443
League\\x20 123 tuan   41u  IPv4 0x2      0t0  UDP 192.168.1.5:61001->104.160.131.77:5123
"""

PROFILER_OUT = """Wi-Fi:
      Interfaces:
        en0:
          Current Network Information:
            <redacted>:
              PHY Mode: 802.11ax
              Channel: 120 (5GHz, 160MHz)
              Signal / Noise: -58 dBm / -96 dBm
              Transmit Rate: 576
              MCS Index: 3
          Other Local Wi-Fi Networks:
            <redacted>:
              Channel: 116 (5GHz, 80MHz)
            <redacted>:
              Channel: 124 (5GHz, 40MHz)
            <redacted>:
              Channel: 157 (5GHz, 80MHz)
            <redacted>:
              Channel: 6 (2GHz, 20MHz)
"""

NETTOP_OUT = """,bytes_in,bytes_out,
Google Chrome H.925,236929233,27720688,
,bytes_in,bytes_out,
Google Chrome H.925,3000000,0,
curl.477,300,0,
"""

# Lệnh chỉ đọc mà tool được phép gọi ngoài `fix`.
READ_ONLY = {"ping", "traceroute", "route", "networksetup", "ifconfig", "lsof", "system_profiler", "nettop", "ssh",
             "netsh", "powershell", "tracert"}


def fake_run(outputs):
    calls = []

    def _run(cmd, timeout=None):
        calls.append(cmd)
        return outputs.get(cmd[0], "")
    return _run, calls


class Parsing(unittest.TestCase):
    def test_ping_stats_and_loss(self):
        with mock.patch.object(ps, "run", return_value=PING_OUT):
            s = ps.ping("1.1.1.1", count=4)
        self.assertEqual(s["loss"], 25.0)
        self.assertEqual((s["min"], s["max"], s["avg"]), (10.0, 30.0, 20.0))
        self.assertEqual(s["jitter"], 15.0)

    def test_summarize_edge_cases(self):
        self.assertEqual(ps.summarize([], 10), {"loss": 100.0})
        self.assertEqual(ps.summarize([5.0], 1)["jitter"], 0.0)
        self.assertIn("100% loss", ps.fmt({"loss": 100.0}))

    def test_traceroute_skips_silent_hops(self):
        with mock.patch.object(ps, "run", return_value=TRACE_OUT):
            hops = ps.traceroute("x")
        self.assertEqual([h[0] for h in hops], [1, 3, 4])

    def test_detect_ignores_web_traffic(self):
        with mock.patch.object(ps, "run", return_value=LSOF_OUT):
            self.assertEqual(ps.detect_game_server(), ("104.160.131.77", "5123"))
        with mock.patch.object(ps, "run", return_value=LSOF_OUT.split("\n")[0] + "\n" + LSOF_OUT.split("\n")[1]):
            self.assertIsNone(ps.detect_game_server())

    def test_wifi_info(self):
        with mock.patch.object(ps, "run", return_value=PROFILER_OUT):
            info = ps.wifi_info()
        self.assertEqual((info["channel"], info["band"], info["width"]), (120, "5", 160))
        self.assertEqual((info["rssi"], info["noise"], info["mcs"]), (-58, -96, 3))
        self.assertEqual(len(info["neighbors"]), 4)

    def test_channel_span(self):
        self.assertEqual(ps.channel_span(120, "5", 160), {("5", c) for c in range(100, 129, 4)})
        self.assertEqual(ps.channel_span(124, "5", 40), {("5", 124), ("5", 128)})
        self.assertEqual(ps.channel_span(157, "5", 80), {("5", c) for c in (149, 153, 157, 161)})
        self.assertEqual(ps.channel_span(6, "2", 20), {("2", c) for c in range(4, 9)})

    def test_wifi_issues_recommend_clean_channel(self):
        with mock.patch.object(ps, "run", return_value=PROFILER_OUT):
            info = ps.wifi_info()
        with mock.patch.object(ps, "awdl_active", return_value=False):
            issues = " ".join(ps.wifi_issues(info, "192.168.1.1", [(3e6, "Chrome")]))
        self.assertIn("2 mạng hàng xóm", issues)
        self.assertIn("DFS", issues)
        self.assertIn("MCS chỉ 3", issues)
        self.assertIn("Chrome", issues)
        # 157/80 chiếm 149-161 nên kênh sạch nhất là 36.
        self.assertIn("kênh 36, độ rộng 80MHz", issues)

    def test_top_talkers_uses_delta_sample(self):
        with mock.patch.object(ps, "run", return_value=NETTOP_OUT):
            rows = ps.top_talkers(seconds=3)
        self.assertEqual(rows[0], (1e6, "Google Chrome H"))
        self.assertEqual(len(rows), 2)


WIN_PING_OUT = """Pinging 1.1.1.1 with 32 bytes of data:
Reply from 1.1.1.1: bytes=32 time=10ms TTL=57
Request timed out.
Trả lời từ 1.1.1.1: byte=32 thời gian=30ms TTL=57
Reply from 1.1.1.1: bytes=32 time<1ms TTL=57
"""

TRACERT_OUT = """Tracing route to 1.1.1.1 over a maximum of 30 hops

  1    <1 ms    <1 ms     1 ms  192.168.1.1
  2     *        *        *     Request timed out.
  3     9 ms     *       12 ms  113.171.147.253
  4   210 ms   205 ms   220 ms  1.1.1.1

Trace complete.
"""

NETSH_IF_OUT = """There is 1 interface on the system:

    Name                   : Wi-Fi
    State                  : connected
    SSID                   : Home
    Radio type             : 802.11ax
    Band                   : 5 GHz
    Channel                : 120
    Receive rate (Mbps)    : 1201
    Transmit rate (Mbps)   : 864
    Signal                 : 84%
"""

NETSH_NETS_OUT = """SSID 1 : Home
    BSSID 1                 : aa:bb:cc:dd:ee:01
         Signal             : 84%
         Channel            : 120
SSID 2 : Neighbor
    BSSID 1                 : aa:bb:cc:dd:ee:02
         Channel            : 116
SSID 3 : Neighbor2
    BSSID 1                 : aa:bb:cc:dd:ee:03
         Channel            : 6
"""


class WindowsParsing(unittest.TestCase):
    def setUp(self):
        p = mock.patch.multiple(ps, IS_WIN=True, IS_MAC=False)
        p.start()
        self.addCleanup(p.stop)

    def test_ping_localized_and_sub_ms(self):
        self.assertEqual(ps.parse_ping(WIN_PING_OUT), [10.0, 30.0, 0.5])
        run, calls = fake_run({"ping": WIN_PING_OUT})
        with mock.patch.object(ps, "run", run):
            self.assertEqual(ps.ping("1.1.1.1", count=4)["loss"], 25.0)
        self.assertEqual(calls[0][:3], ["ping", "-n", "4"])

    def test_tracert(self):
        with mock.patch.object(ps, "run", return_value=TRACERT_OUT):
            self.assertEqual(ps.traceroute("1.1.1.1"),
                             [(1, "192.168.1.1", 1.0), (3, "113.171.147.253", 9.0), (4, "1.1.1.1", 205.0)])

    def test_network(self):
        with mock.patch.object(ps, "run", return_value="192.168.1.1|Wi-Fi|Native 802.11\r\n"):
            self.assertEqual(ps.network(), ("192.168.1.1", "Wi-Fi", "Wi-Fi"))
        with mock.patch.object(ps, "run", return_value="10.0.0.1|Ethernet|802.3"):
            self.assertEqual(ps.network()[2], "Ethernet")

    def test_wifi_info_excludes_own_ap(self):
        def run(cmd, timeout=None):
            return NETSH_NETS_OUT if "networks" in cmd else NETSH_IF_OUT
        with mock.patch.object(ps, "run", run):
            info = ps.wifi_info()
        self.assertEqual((info["channel"], info["band"], info["width"]), (120, "5", None))
        self.assertEqual(info["rssi"], -58)
        self.assertEqual(info["rate"], 864)
        self.assertEqual(sorted(info["neighbors"]), [(6, "2", None), (116, "5", None)])
        with mock.patch.object(ps, "awdl_active", return_value=False):
            issues = " ".join(ps.wifi_issues(info, "192.168.1.1", []))
        self.assertIn("DFS", issues)

    def test_mac_only_features_disabled(self):
        run, calls = fake_run({})
        with mock.patch.object(ps, "run", run):
            self.assertIsNone(ps.detect_game_server())
            self.assertEqual(ps.top_talkers(), [])
            self.assertFalse(ps.awdl_active())
            with self.assertRaises(SystemExit):
                ps.cmd_fix(Namespace(revert=False))
        self.assertEqual(calls, [])

    def test_windows_commands_are_read_only(self):
        run, calls = fake_run({"ping": WIN_PING_OUT, "tracert": TRACERT_OUT, "netsh": NETSH_IF_OUT,
                               "powershell": "192.168.1.1|Wi-Fi|Native 802.11"})
        with mock.patch.object(ps, "run", run), mock.patch("builtins.print"):
            ps.cmd_diagnose(Namespace(target=None, count=4))
            ps.cmd_wifi(Namespace(count=4))
        for cmd in calls:
            self.assertIn(cmd[0], READ_ONLY, cmd)
            if cmd[0] == "netsh":
                self.assertEqual(cmd[1:3], ["wlan", "show"])
            if cmd[0] == "powershell":
                self.assertNotRegex(cmd[-1], r"(?i)\b(Set|New|Remove|Disable|Enable)-")


class Robustness(unittest.TestCase):
    """Lệnh hệ thống lỗi, thiếu hoặc trả output lạ thì tool không được crash."""

    def test_empty_outputs(self):
        with mock.patch.object(ps, "run", return_value=""):
            self.assertIsNone(ps.wifi_info())
            self.assertEqual(ps.top_talkers(), [])
            self.assertEqual(ps.traceroute("x"), [])
            self.assertIsNone(ps.detect_game_server())
            self.assertEqual(ps.network(), (None, None, "?"))
            self.assertEqual(ps.ping("x")["loss"], 100.0)
            self.assertEqual(ps.wifi_issues(None, None, []), [])

    def test_missing_binary(self):
        self.assertEqual(ps.run(["definitely-not-a-command-xyz"]), "")

    def test_timeout(self):
        self.assertEqual(ps.run(["sleep", "5"], timeout=0.2), "")


class Safety(unittest.TestCase):
    """Ngoài `fix`, tool chỉ được đọc, không thay đổi cấu hình mạng."""

    def assert_read_only(self, calls):
        for cmd in calls:
            self.assertIn(cmd[0], READ_ONLY, cmd)
            if cmd[0] == "ifconfig":
                self.assertEqual(cmd, ["ifconfig", "awdl0"])

    def test_diagnose_and_wifi_are_read_only(self):
        run, calls = fake_run({"ping": PING_OUT, "traceroute": TRACE_OUT, "system_profiler": PROFILER_OUT,
                               "nettop": NETTOP_OUT, "route": "gateway: 192.168.1.1\ninterface: en0\n",
                               "networksetup": "Hardware Port: Wi-Fi\nDevice: en0\n"})
        with mock.patch.object(ps, "run", run), mock.patch("builtins.print"):
            ps.cmd_diagnose(Namespace(target=None, count=4))
            ps.cmd_wifi(Namespace(count=4))
        self.assertTrue(calls)
        self.assert_read_only(calls)

    def test_relay_never_prompts_for_password(self):
        run, calls = fake_run({"ping": PING_OUT, "ssh": PING_OUT})
        with mock.patch.object(ps, "run", run), mock.patch("builtins.print"):
            ps.cmd_relay(Namespace(target="1.1.1.1", count=4, hosts=["root@10.0.0.1"]))
        ssh = [c for c in calls if c[0] == "ssh"]
        self.assertTrue(ssh)
        self.assertIn("BatchMode=yes", ssh[0])
        self.assert_read_only(calls)

    def test_fix_refuses_without_root(self):
        if os.geteuid() == 0:
            self.skipTest("đang chạy bằng root")
        run, calls = fake_run({})
        with mock.patch.object(ps, "run", run), self.assertRaises(SystemExit):
            ps.cmd_fix(Namespace(revert=False))
        self.assertEqual(calls, [])


class LiveSmoke(unittest.TestCase):
    """Chạy thật tool trên máy hiện tại (macOS hoặc Windows): phải thoát sạch, không traceback."""

    def cli(self, *args, timeout=300):
        r = subprocess.run(TOOL + list(args), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        return r.stdout

    def test_version(self):
        self.assertIn(ps.__version__, self.cli("--version"))

    def test_wifi(self):
        self.assertIn("Kết luận", self.cli("wifi", "--count", "3"))

    def test_diagnose_localhost(self):
        self.assertIn("Kết luận", self.cli("diagnose", "--target", "127.0.0.1", "--count", "3"))

    def test_monitor_duration(self):
        self.assertIn("Tổng kết", self.cli("monitor", "--target", "127.0.0.1", "--duration", "3"))


@unittest.skipUnless(sys.platform == "darwin", "chỉ chạy trên macOS")
class LiveMac(unittest.TestCase):
    """Chạy thật trên Mac: không để lại tiến trình, không đổi trạng thái mạng."""

    @classmethod
    def setUpClass(cls):
        cls.gw = ps.network()[0]
        if not cls.gw:
            raise unittest.SkipTest("không có mạng")

    def network_state(self):
        return (ps.awdl_active(), ps.network(),
                ps.run(["scutil", "--dns"]).count("nameserver"),
                ps.run(["networksetup", "-getairportnetwork", "en0"]))

    def test_commands_leave_network_unchanged(self):
        before = self.network_state()
        for args in (["wifi", "--count", "5"], ["diagnose", "--target", self.gw, "--count", "5"]):
            r = subprocess.run(TOOL + args, capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(before, self.network_state())

    def test_monitor_stops_on_ctrl_c_without_orphans(self):
        p = subprocess.Popen(TOOL + ["monitor", "--target", self.gw], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
        time.sleep(4)
        p.send_signal(signal.SIGINT)
        out, err = p.communicate(timeout=10)
        self.assertEqual(p.returncode, 0, err)
        self.assertIn("Tổng kết", out)
        self.assertNotIn("Traceback", err)
        time.sleep(1.5)
        left = ps.run(["pgrep", "-f", f"ping -c 1 .* {self.gw}$"]).split()
        self.assertEqual(left, [], "còn tiến trình ping sau khi dừng monitor")

    def test_repeated_runs_are_stable(self):
        for _ in range(3):
            r = subprocess.run(TOOL + ["wifi", "--count", "3"], capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
