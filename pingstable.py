#!/usr/bin/env python3
"""Chẩn đoán và giảm lag khi chơi game server ở xa (vd. TFT PBE từ Việt Nam) trên macOS và Windows."""

import argparse
import ipaddress
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

__version__ = "0.2.0"
PROG = "pingstable"
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# Riot ping endpoint của NA; PBE chạy ở cụm NA nên dùng làm mốc khi chưa bắt được IP trận thật.
DEFAULT_TARGET = "104.160.131.3"
RIOT_PREFIXES = ["104.160.128.0/19"]
STATE_DIR = os.environ.get("PINGSTABLE_HOME") or os.path.join(os.path.expanduser("~"), ".pingstable")

PING_RE = re.compile(r"time=([\d.]+) ms")
# Windows dịch chữ "time" theo ngôn ngữ máy, nên neo vào "ms TTL=" vốn không đổi.
WIN_PING_RE = re.compile(r"([=<])\s*(\d+)\s*ms\s+TTL=", re.I)
HOP_RE = re.compile(r"^\s*(\d+)\s+(\S+)\s+([\d.]+) ms")
WIN_HOP_RE = re.compile(r"^\s*(\d+)\s+(.+?)\s+(\d+\.\d+\.\d+\.\d+)\s*$")


def run(cmd, timeout=None):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def parse_ping(out):
    times = [float(t) for t in PING_RE.findall(out)]
    times += [0.5 if op == "<" else float(ms) for op, ms in WIN_PING_RE.findall(out)]
    return times


def ping_times(host, count=30, interval=0.2):
    if IS_WIN:
        cmd, timeout = ["ping", "-n", str(count), "-w", "1000", host], count * 2 + 10
    else:
        cmd, timeout = ["ping", "-c", str(count), "-i", str(interval), "-W", "1000", host], count * interval + 10
    return parse_ping(run(cmd, timeout=timeout))


def ping(host, count=30, interval=0.2):
    return summarize(ping_times(host, count, interval), count)


def summarize(times, sent):
    if not times:
        return {"loss": 100.0}
    jitter = statistics.mean(abs(a - b) for a, b in zip(times, times[1:])) if len(times) > 1 else 0.0
    srt = sorted(times)
    return {
        "loss": 100.0 * (sent - len(times)) / sent,
        "min": srt[0],
        "avg": statistics.mean(times),
        "p95": srt[min(len(srt) - 1, int(len(srt) * 0.95))],
        "max": srt[-1],
        "jitter": jitter,
    }


def fmt(s):
    if s["loss"] >= 100:
        return "không phản hồi (100% loss)"
    return (f"avg {s['avg']:.0f}ms  min {s['min']:.0f}  p95 {s['p95']:.0f}  max {s['max']:.0f}  "
            f"jitter {s['jitter']:.1f}ms  loss {s['loss']:.0f}%")


WIN_ROUTE_PS = (
    "$r = Get-NetRoute -DestinationPrefix 0.0.0.0/0 -ErrorAction SilentlyContinue | "
    "Sort-Object RouteMetric | Select-Object -First 1; "
    "if ($r) { $a = Get-NetAdapter -InterfaceIndex $r.ifIndex; \"$($r.NextHop)|$($a.Name)|$($a.MediaType)\" }"
)


def network():
    """Gateway, tên card mạng và loại kết nối (Wi-Fi/Ethernet) của đường mạng mặc định."""
    if IS_WIN:
        parts = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", WIN_ROUTE_PS], timeout=20).strip().split("|")
        if len(parts) != 3:
            return None, None, "?"
        media = parts[2]
        kind = "Wi-Fi" if "802.11" in media else "Ethernet" if "802.3" in media else media or "?"
        return parts[0], parts[1], kind
    out = run(["route", "-n", "get", "default"])
    gw = re.search(r"gateway: (\S+)", out)
    iface = re.search(r"interface: (\S+)", out)
    if not iface:
        return (gw.group(1) if gw else None), None, "?"
    kind = "?"
    for block in run(["networksetup", "-listallhardwareports"]).split("\n\n"):
        if f"Device: {iface.group(1)}" in block:
            m = re.search(r"Hardware Port: (.+)", block)
            kind = m.group(1) if m else "?"
    return (gw.group(1) if gw else None), iface.group(1), kind


def awdl_active():
    return IS_MAC and "status: active" in run(["ifconfig", "awdl0"])


WIFI_CH_RE = re.compile(r"Channel: (\d+) \((\d)GHz, (\d+)MHz\)")
DFS_CHANNELS = range(52, 145)


def channel_span(ch, band, width):
    """Các kênh 20MHz mà một mạng chiếm, để tính chồng lấn giữa các mạng."""
    if band == "2":
        return {(band, c) for c in range(ch - 2, ch + 3)}
    base = 1 if band == "6" else 36 if ch < 100 else 100 if ch < 149 else 149
    n = max(1, (width or 80) // 20)
    start = base + (ch - base) // (4 * n) * 4 * n
    return {(band, start + 4 * i) for i in range(n)}


def band_of(ch, label=None):
    if label:
        return "2" if label.startswith("2") else label[0]
    return "2" if ch <= 14 else "5"


def wifi_info():
    return wifi_info_windows() if IS_WIN else wifi_info_mac()


def wifi_info_mac():
    out = run(["system_profiler", "SPAirPortDataType"], timeout=30)
    if "Current Network Information:" not in out:
        return None
    cur, _, others = out.partition("Current Network Information:")[2].partition("Other Local Wi-Fi Networks:")
    ch = WIFI_CH_RE.search(cur)
    sig = re.search(r"Signal / Noise: (-?\d+) dBm / (-?\d+) dBm", cur)
    mcs = re.search(r"MCS Index: (\d+)", cur)
    rate = re.search(r"Transmit Rate: (\d+)", cur)
    phy = re.search(r"PHY Mode: (\S+)", cur)
    if not ch:
        return None
    return {
        "phy": phy.group(1) if phy else "?",
        "channel": int(ch.group(1)), "band": ch.group(2), "width": int(ch.group(3)),
        "rssi": int(sig.group(1)) if sig else None,
        "noise": int(sig.group(2)) if sig else None,
        "mcs": int(mcs.group(1)) if mcs else None,
        "rate": int(rate.group(1)) if rate else None,
        "neighbors": [(int(c), b, int(w)) for c, b, w in WIFI_CH_RE.findall(others)],
    }


def wifi_info_windows():
    """netsh không cho biết độ rộng kênh và nhiễu, nên các giá trị đó để trống."""
    cur = run(["netsh", "wlan", "show", "interfaces"], timeout=15)
    ch = re.search(r"^\s*Channel\s*:\s*(\d+)", cur, re.M)
    if not ch:
        return None
    channel = int(ch.group(1))
    band = re.search(r"^\s*Band\s*:\s*([\d.]+)\s*GHz", cur, re.M)
    rssi = re.search(r"^\s*Rssi\s*:\s*(-\d+)", cur, re.M)
    pct = re.search(r":\s*(\d+)%", cur)
    rate = re.search(r"Transmit rate \(Mbps\)\s*:\s*([\d.]+)", cur)
    phy = re.search(r"Radio type\s*:\s*(\S+)", cur)

    nearby = run(["netsh", "wlan", "show", "networks", "mode=bssid"], timeout=15)
    neighbors = [(int(c), band_of(int(c)), None) for c in re.findall(r"^\s*Channel\s*:\s*(\d+)", nearby, re.M)]
    own = next((n for n in neighbors if n[0] == channel), None)
    if own:
        neighbors.remove(own)
    return {
        "phy": phy.group(1) if phy else "?",
        "channel": channel, "band": band_of(channel, band.group(1) if band else None), "width": None,
        "rssi": int(rssi.group(1)) if rssi else (int(pct.group(1)) // 2 - 100 if pct else None),
        "noise": None, "mcs": None,
        "rate": int(float(rate.group(1))) if rate else None,
        "neighbors": neighbors,
    }


def overlapping(span, neighbors):
    return sum(1 for c, b, w in neighbors if span & channel_span(c, b, w))


def best_channel(info):
    """Kênh non-DFS ít mạng hàng xóm đè lên nhất."""
    if info["band"] == "2":
        options = [(c, 20) for c in (1, 6, 11)]
    else:
        options = [(36, 80), (149, 80)]
    band = "2" if info["band"] == "2" else "5"
    return min((overlapping(channel_span(c, band, w), info["neighbors"]), c, w) for c, w in options)


def top_talkers(seconds=3, n=5):
    """Các tiến trình đang dùng mạng nhiều nhất trên máy (bytes/giây); chỉ có trên macOS."""
    if not IS_MAC:
        return []
    out = run(["nettop", "-P", "-L", "2", "-s", str(seconds), "-d", "-J", "bytes_in,bytes_out", "-x"],
              timeout=seconds + 10)
    rows = []
    for line in out.split(",bytes_in,bytes_out,")[-1].splitlines():
        parts = line.split(",")
        if len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
            rows.append(((int(parts[1]) + int(parts[2])) / seconds, parts[0].rsplit(".", 1)[0]))
    return sorted(rows, reverse=True)[:n]


def wifi_issues(info, gw, talkers):
    issues = []
    if awdl_active():
        issues.append("awdl0 (AirDrop/Handoff) đang bật, gây spike ping định kỳ trên Wi-Fi. "
                      f"Chạy: sudo {PROG} fix")
    for rate, name in talkers:
        if rate > 500_000:
            issues.append(f"{name} đang dùng {rate / 1e6:.1f} MB/s: chiếm băng thông, làm ping vọt lên. Tắt khi chơi.")
    if not info:
        return issues
    rssi, noise, mcs, width = info["rssi"], info["noise"], info["mcs"], info["width"]
    if info["band"] == "2":
        issues.append("Đang ở băng 2.4GHz (chậm, nhiễu nhiều). Kết nối vào mạng 5GHz của router.")
    if rssi is not None:
        if rssi < -70:
            issues.append(f"Sóng yếu ({rssi} dBm). Lại gần router, bớt tường/vật cản, hoặc thêm mesh/repeater có dây.")
        elif rssi < -65:
            issues.append(f"Sóng trung bình ({rssi} dBm). Gần router hơn sẽ ổn định hơn.")
        if noise is not None and rssi - noise < 25:
            issues.append(f"SNR thấp ({rssi - noise} dB): nhiễu nhiều so với tín hiệu.")
        if mcs is not None and mcs <= 4 and rssi >= -65:
            issues.append(f"Sóng mạnh nhưng MCS chỉ {mcs}: dấu hiệu bị nhiễu từ các mạng xung quanh.")
    span = channel_span(info["channel"], info["band"], width)
    crowd = overlapping(span, info["neighbors"])
    dfs = info["band"] == "5" and info["channel"] in DFS_CHANNELS
    if crowd >= 2:
        issues.append(f"{crowd} mạng hàng xóm đè lên kênh {info['channel']} của bạn.")
    if width and width >= 160:
        issues.append("Kênh 160MHz dễ đè hàng xóm và dao động; game chỉ cần vài trăm kbps, 80MHz ổn định hơn.")
    if dfs:
        issues.append(f"Kênh {info['channel']} là kênh DFS: router phải đổi kênh khi phát hiện radar, "
                      "có thể rớt mạng vài giây giữa trận.")
    if crowd >= 2 or (width and width >= 160) or dfs:
        n, ch, w = best_channel(info)
        issues.append(f"Gợi ý: vào trang quản trị router (http://{gw}) đặt kênh {ch}, độ rộng {w}MHz "
                      f"({n} mạng xung quanh đang dùng). Sau khi đổi, chạy lại: {PROG} wifi")
    return issues


def cmd_wifi(a):
    gw, _, _ = network()
    info = wifi_info()
    if info:
        snr = info["rssi"] - info["noise"] if info["rssi"] is not None and info["noise"] is not None else "?"
        width = f"{info['width']}MHz" if info["width"] else "độ rộng ?"
        print(f"Wi-Fi : {info['phy']}, kênh {info['channel']} ({info['band']}GHz, {width}), "
              f"tín hiệu {info['rssi']} dBm, SNR {snr} dB, MCS {info['mcs'] if info['mcs'] is not None else '?'}, "
              f"{info['rate']} Mbps")
        print(f"        {len(info['neighbors'])} mạng xung quanh")
    else:
        print("Không đọc được thông tin Wi-Fi (có thể đang không dùng Wi-Fi).")
        if IS_WIN:
            print("        Trên Windows 11 bản mới, có thể cần bật Location (Settings > Privacy > Location) để netsh đọc được Wi-Fi.")
    print(f"Router: {fmt(ping(gw, a.count)) if gw else 'không có gateway'}")
    talkers = top_talkers()
    if IS_MAC:
        print("Dùng mạng nhiều nhất:", ", ".join(f"{name} {rate / 1e3:.0f}KB/s" for rate, name in talkers) or "-")
    print("\nKết luận:")
    for i in wifi_issues(info, gw, talkers) or ["Wi-Fi ổn."]:
        print(f"  - {i}")


def detect_game_server():
    """Trả về IP server trận đấu đang kết nối (UDP) của client League, nếu đang trong trận; chỉ có trên macOS."""
    if not IS_MAC:
        return None
    out = run(["lsof", "-nP", "-iUDP", "-c", "League"])
    ips = [(ip, port) for ip, port in re.findall(r"->(\d+\.\d+\.\d+\.\d+):(\d+)", out)
           if 5000 <= int(port) <= 5500]
    return ips[0] if ips else None


def remember_target(ip):
    """Lưu IP server game công khai để đo lại được khi đã thoát trận."""
    try:
        if not ipaddress.ip_address(ip).is_global:
            return
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(os.path.join(STATE_DIR, "last_target"), "w") as f:
            f.write(ip)
    except (ValueError, OSError):
        pass


def last_target():
    try:
        with open(os.path.join(STATE_DIR, "last_target")) as f:
            return f.read().strip() or None
    except OSError:
        return None


def resolve_target(arg):
    if arg:
        remember_target(arg)
        return arg
    found = detect_game_server()
    if found:
        print(f"• Bắt được server trận: {found[0]}:{found[1]}")
        remember_target(found[0])
        return found[0]
    saved = last_target()
    if saved:
        print(f"• Không thấy trận đang chạy, dùng server trận gần nhất {saved}")
        return saved
    if IS_WIN:
        print("• Windows: xem IP trận trong Resource Monitor (resmon) > Network > League of Legends.exe, "
              "rồi truyền --target <ip>.")
    print(f"• Không thấy trận đang chạy, dùng mốc NA/PBE {DEFAULT_TARGET}")
    return DEFAULT_TARGET


def traceroute(host):
    if IS_WIN:
        out = run(["tracert", "-d", "-h", "30", "-w", "1000", host], timeout=200)
        hops = []
        for m in map(WIN_HOP_RE.match, out.splitlines()):
            times = [float(t) for t in re.findall(r"(\d+)\s*ms", m.group(2))] if m else []
            if times:
                hops.append((int(m.group(1)), m.group(3), min(times)))
        return hops
    out = run(["traceroute", "-n", "-q", "1", "-w", "2", "-m", "30", host], timeout=120)
    return [(int(n), ip, float(ms)) for n, ip, ms in
            (m.groups() for m in map(HOP_RE.match, out.splitlines()) if m)]


def cmd_diagnose(a):
    target = resolve_target(a.target)
    gw, iface, kind = network()
    print(f"• Mạng đang dùng: {iface} ({kind}), gateway {gw}\n")

    with ThreadPoolExecutor(2) as pool:
        local = pool.submit(ping, gw, a.count) if gw else None
        remote = pool.submit(ping, target, a.count)
        local = local.result() if local else {"loss": 100.0}
        remote = remote.result()
    print(f"Router nhà  : {fmt(local)}")
    print(f"Server game : {fmt(remote)}\n")

    print("Đang traceroute (có thể mất 1-3 phút)...")
    hops = traceroute(target)
    jump = None
    prev = 0.0
    for n, ip, ms in hops:
        delta = ms - prev
        mark = "  <-- tăng mạnh" if delta > 60 else ""
        if jump is None or delta > jump[2]:
            jump = (n, ip, delta)
        print(f"  {n:>2}  {ip:<16} {ms:7.1f} ms{mark}")
        prev = ms
    print()

    issues = []
    if local.get("loss", 0) > 0 or local.get("jitter", 0) > 5 or local.get("p95", 0) > 20:
        issues.append("Mạng trong nhà không ổn định (Wi-Fi yếu/nhiễu). Cắm dây LAN hoặc ngồi gần router.")
    if "Wi-Fi" in kind:
        issues.append("Đang dùng Wi-Fi: dây LAN thường giảm jitter rõ rệt.")
        issues += wifi_issues(wifi_info(), gw, top_talkers())
    if remote["loss"] >= 100:
        issues.append("Server không trả ping (có thể chặn ICMP). Chạy lại khi đang trong trận để tool bắt đúng IP, "
                      "hoặc truyền --target <ip>.")
    if remote.get("jitter", 0) > 10 or remote.get("loss", 0) > 1:
        issues.append(f"Đường quốc tế chập chờn (jitter/loss cao). Thử relay qua VPS: {PROG} relay ...")
    if remote.get("min", 0) > 180:
        issues.append(f"Ping tối thiểu {remote['min']:.0f}ms: phần lớn là khoảng cách vật lý VN→Bắc Mỹ, "
                      "không tool nào hạ dưới mức đó; chỉ có thể chọn tuyến ngắn/ổn định hơn.")
    if jump and jump[2] > 60:
        issues.append(f"Độ trễ tăng nhiều nhất ở hop {jump[0]} ({jump[1]}, +{jump[2]:.0f}ms): "
                      "thường là đoạn cáp biển của nhà mạng. Đổi nhà mạng/relay sẽ đổi đoạn này.")
    print("Kết luận:")
    for i in issues or ["Không thấy vấn đề rõ rệt."]:
        print(f"  - {i}")


def cmd_monitor(a):
    target = resolve_target(a.target)
    print(f"Theo dõi {target} (Ctrl+C để dừng)\n")
    times, sent = [], 0
    recent = deque(maxlen=120)
    try:
        while a.duration is None or sent < a.duration * 2:
            started = time.monotonic()
            got = ping_times(target, 1)
            cur = got[0] if got else None
            sent += 1
            recent.append(cur)
            if cur is not None:
                times.append(cur)
            window = [t for t in recent if t is not None]
            s = summarize(window, len(recent))
            spike = "  SPIKE" if cur and window and cur > s["avg"] + 40 else ""
            now = f"{cur:.0f}ms" if cur is not None else "MẤT GÓI"
            print(f"\r[{time.strftime('%H:%M:%S')}] {now:>8} | {fmt(s)}{spike}   ", end="", flush=True)
            if spike or cur is None:
                print()
            time.sleep(max(0.0, 0.5 - (time.monotonic() - started)))
    except KeyboardInterrupt:
        pass
    print("\n\nTổng kết:", fmt(summarize(times, max(sent, 1))))


def cmd_fix(a):
    if not IS_MAC:
        sys.exit("Lệnh fix chỉ dành cho macOS. Trên Windows: cắm dây LAN hoặc đổi kênh Wi-Fi theo gợi ý của lệnh wifi.")
    if os.geteuid() != 0:
        sys.exit(f"Cần quyền root: sudo {PROG} fix")
    if a.revert:
        run(["ifconfig", "awdl0", "up"])
        print("Đã bật lại awdl0 (AirDrop/Handoff).")
        return
    if awdl_active():
        run(["ifconfig", "awdl0", "down"])
        print("Đã tắt awdl0. AirDrop/Handoff tạm ngưng; macOS có thể tự bật lại khi bạn dùng AirDrop.")
        print(f"Khôi phục: sudo {PROG} fix --revert")
    else:
        print("awdl0 đã tắt sẵn, không cần làm gì.")


def cmd_relay(a):
    """So sánh đi thẳng với đi vòng qua các VPS (ước lượng = ping tới VPS + ping VPS→server)."""
    target = resolve_target(a.target)
    direct = ping(target, a.count)
    print(f"\nĐi thẳng           : {fmt(direct)}")
    results = []
    for host in a.hosts:
        addr = host.split("@")[-1]
        leg1 = ping(addr, a.count)
        out = run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host,
                   f"ping -c {a.count} -i 0.2 {target}"], timeout=a.count + 30)
        leg2 = summarize(parse_ping(out), a.count)
        if leg1["loss"] >= 100 or leg2["loss"] >= 100:
            print(f"Qua {host:<15}: không đo được (kiểm tra SSH / ICMP)")
            continue
        total = leg1["avg"] + leg2["avg"]
        jitter = leg1["jitter"] + leg2["jitter"]
        results.append((total, host))
        print(f"Qua {host:<15}: ~{total:.0f}ms (tới VPS {leg1['avg']:.0f} + VPS→game {leg2['avg']:.0f}), "
              f"jitter ~{jitter:.1f}ms")
    if not results:
        return
    best, host = min(results)
    if direct["loss"] < 100 and best >= direct["avg"] - 5:
        print("\nĐi thẳng đang tốt nhất, relay không giúp được.")
        return
    print(f"\nTốt nhất: {host}. Dùng WireGuard chỉ cho traffic Riot (split tunnel):\n")
    print(wg_client_template(host.split("@")[-1], target))


def warp_cli():
    if IS_WIN:
        path = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                            "Cloudflare", "Cloudflare WARP", "warp-cli.exe")
        if os.path.exists(path):
            return path
    return shutil.which("warp-cli")


def warp_connected(cli):
    return bool(re.search(r"\bConnected\b", run([cli, "status"], timeout=10)))


def set_warp(cli, on, wait=20):
    run([cli, "connect" if on else "disconnect"], timeout=15)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if warp_connected(cli) == on:
            time.sleep(2)  # đợi route ổn định trước khi đo
            return True
        time.sleep(1)
    return False


def route_score(s):
    """Điểm càng thấp càng tốt; jitter và mất gói gây giật nhiều hơn ping cao đều."""
    return float("inf") if s["loss"] >= 100 else s["avg"] + 2 * s["jitter"] + 10 * s["loss"]


def cmd_compare(a):
    """Đo cùng một server game qua từng tuyến mạng (WARP bật/tắt, wifi nhà/4G...) rồi chọn tuyến tốt nhất."""
    target = resolve_target(a.target)
    count = a.seconds if IS_WIN else a.seconds * 5
    cli = was_on = None
    if a.warp:
        cli = warp_cli()
        if not cli:
            sys.exit("Chưa cài Cloudflare WARP (miễn phí): https://one.one.one.one — cài xong chạy lại lệnh này.")
        was_on = warp_connected(cli)
        steps = [("Đi thẳng", False), ("Cloudflare WARP", True)]
    else:
        steps = [(label, None) for label in a.routes]

    results = []
    try:
        for i, (label, warp_on) in enumerate(steps):
            if warp_on is not None:
                print(f"• {'Bật' if warp_on else 'Tắt'} WARP...")
                if not set_warp(cli, warp_on):
                    print("  Không đổi được trạng thái WARP, bỏ qua tuyến này.")
                    continue
            elif i > 0:
                try:
                    input(f"\nChuyển mạng sang '{label}' (vd. bật hotspot 4G), đợi có mạng rồi bấm Enter...")
                except EOFError:
                    break
            print(f"• Đo {label} trong {a.seconds}s...")
            s = ping(target, count)
            print(f"  {fmt(s)}")
            if not results and s["loss"] >= 100:
                sys.exit(f"Server {target} không trả ping nên không so sánh được. Chạy khi đang trong trận "
                         "(tool tự bắt và lưu IP), hoặc truyền --target <ip>.")
            results.append((label, s))
    finally:
        if cli and warp_connected(cli) != was_on:
            set_warp(cli, was_on)
            print(f"• Đã trả WARP về trạng thái ban đầu ({'bật' if was_on else 'tắt'}).")

    if len(results) < 2:
        print("\nCần đo ít nhất 2 tuyến để so sánh.")
        return
    print(f"\n{'Tuyến':<18}{'avg':>7}{'p95':>7}{'jitter':>9}{'loss':>7}")
    for label, s in results:
        if s["loss"] >= 100:
            print(f"{label:<18}{'không phản hồi':>30}")
        else:
            print(f"{label:<18}{s['avg']:>5.0f}ms{s['p95']:>5.0f}ms{s['jitter']:>7.1f}ms{s['loss']:>6.0f}%")
    first_label, first = results[0]
    label, best = min(results, key=lambda r: route_score(r[1]))
    if label == first_label or route_score(first) - route_score(best) < 5:
        print(f"\nKết luận: '{first_label}' đang tốt nhất hoặc chênh không đáng kể, giữ nguyên.")
        return
    print(f"\nKết luận: dùng '{label}' khi chơi: avg {first['avg'] - best['avg']:+.0f}ms → {best['avg']:.0f}ms, "
          f"jitter {first['jitter']:.1f} → {best['jitter']:.1f}ms, loss {first['loss']:.0f}% → {best['loss']:.0f}%.")
    if a.warp:
        print("Bật WARP trong app 1.1.1.1 trước khi vào trận. WARP đi qua toàn bộ traffic, "
              "tắt nếu nó xung đột với VPN công ty.")


def wg_client_template(server, target):
    allowed = ", ".join(sorted(set(RIOT_PREFIXES + [f"{target}/32"])))
    return f"""[Interface]
PrivateKey = <client_private_key>
Address = 10.66.0.2/32
MTU = 1380

[Peer]
PublicKey = <server_public_key>
Endpoint = {server}:51820
AllowedIPs = {allowed}
PersistentKeepalive = 25"""


def main(argv=None):
    if IS_WIN:
        # Console/pipe Windows mặc định không phải UTF-8, in tiếng Việt sẽ lỗi.
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog=PROG, description="Giảm lag game server ở xa (TFT PBE...) trên macOS và Windows")
    p.add_argument("--version", action="version", version=f"{PROG} {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("diagnose", help="Đo ping/jitter/loss, traceroute và chỉ ra nguyên nhân lag")
    d.add_argument("--target", help="IP server; bỏ trống để tự bắt từ trận đang chơi (macOS)")
    d.add_argument("--count", type=int, default=40)
    d.set_defaults(func=cmd_diagnose)

    m = sub.add_parser("monitor", help="Theo dõi ping liên tục khi đang chơi, đánh dấu spike")
    m.add_argument("--target")
    m.add_argument("--duration", type=int, help="Số giây chạy; bỏ trống để chạy tới khi Ctrl+C")
    m.set_defaults(func=cmd_monitor)

    w = sub.add_parser("wifi", help="Phân tích Wi-Fi: sóng, nhiễu, kênh đè nhau, app ngốn mạng")
    w.add_argument("--count", type=int, default=40)
    w.set_defaults(func=cmd_wifi)

    f = sub.add_parser("fix", help="macOS: tắt awdl0 để hết spike ping trên Wi-Fi (cần sudo)")
    f.add_argument("--revert", action="store_true")
    f.set_defaults(func=cmd_fix)

    c = sub.add_parser("compare", help="So sánh các tuyến mạng miễn phí (WARP, 4G...) tới server game")
    c.add_argument("--target")
    c.add_argument("--seconds", type=int, default=60, help="Thời gian đo mỗi tuyến")
    c.add_argument("--warp", action="store_true", help="Tự bật/tắt Cloudflare WARP để so sánh, xong trả lại như cũ")
    c.add_argument("--routes", nargs="+", default=["Mạng hiện tại", "Mạng thứ 2"],
                   help="Tên các tuyến sẽ đổi tay (vd. 'Wi-Fi nhà' '4G Viettel')")
    c.set_defaults(func=cmd_compare)

    r = sub.add_parser("relay", help="So sánh đi thẳng với đi qua VPS của bạn")
    r.add_argument("hosts", nargs="+", help="user@ip của VPS (cần SSH bằng key)")
    r.add_argument("--target")
    r.add_argument("--count", type=int, default=20)
    r.set_defaults(func=cmd_relay)

    a = p.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    main()
