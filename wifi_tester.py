#!/usr/bin/env python3
"""
Study-space visit logger (WSL).

Automatically measures everything in the Wi-Fi / network section (network name,
RSSI, band, download, upload, ping, packet loss, drops, outage times, cellular
signal, GPS) and appends one row per visit to a CSV containing ALL columns from
your data-collection plan. Observation columns (people, behaviour, materials,
context...) are left blank unless you use --interactive.

Setup:   pip install speedtest-cli
Usage:   python3 network_diagnostics.py
         python3 network_diagnostics.py --space "Library 3F East" --interactive
"""
import argparse
import csv
import json
import math
import os
import re
import statistics
import subprocess
import time
import urllib.request
from datetime import datetime

try:
    import speedtest  # pip install speedtest-cli
except ImportError:
    speedtest = None

# --------------------------------------------------------------------------
# Columns (in the order of your plan)
# --------------------------------------------------------------------------
SPACE = [
    "Floor", "Room / specific area", "Pin on floor plan / grid reference",
    "Number of seats", "Number of electrical outlets", "Outlet locations",
    "Seating arrangement", "Lighting conditions",
    "Wi-Fi signage / network instructions / QR codes",
    "Signs designating study areas",
    "Network type available (eduroam, guest, other)",
]
TIME = ["Visit ID", "Date", "Day of week", "Start time", "End time", "Busy/quiet period"]
WIFI = [
    "Network connected to", "Signal strength (RSSI)", "Frequency/band",
    "Download speed", "Upload speed", "Latency/ping", "Packet loss",
    "Connection drops", "Time of any outage", "Cellular signal strength",
    "Location (GPS coordinates)", "Location source/accuracy",
    "Connected access point (BSSID)", "Number of access points visible",
    "Wi-Fi fingerprint (BSSID=signal%)",
]
HUMAN = [
    "Number of people present", "Approximate occupancy percentage",
    "Number working individually", "Number working in groups",
    "Number using laptops", "Number using tablets", "Number using phones",
    "Number using physical books/paper", "Number with headphones",
    "Number with no study materials out (eating, sleeping, talking only)",
]
STUDY = [
    "Reading (paper)", "Writing/typing", "Screen-based work",
    "Video conferencing", "Group discussion", "Printing/scanning", "Other",
]
SPATIAL = [
    "Where people choose to sit", "Distance from walls/windows",
    "Distance from outlets", "Distance from other people",
    "Clustering around particular areas", "Seats left unused",
    "People arriving", "People leaving", "Furniture being moved",
    "People sitting on floors/alternative surfaces",
]
MATERIAL = [
    "Posters", "Wear patterns around frequently used areas",
    "Abandoned/forgotten charging accessories",
    "Evidence of users modifying the space", "Furniture arrangement changes",
    "Replaced or removed signs", "Tape residue or other signs of past setups",
]
PHOTO = ["Image ID", "Linked Visit ID", "Description"]
CONTEXT = [
    "Weather", "Temperature", "Noise level", "Major exams/deadlines",
    "Time in semester", "Construction/noise", "Special events",
]

ALL_COLUMNS = SPACE + TIME + WIFI + HUMAN + STUDY + SPATIAL + MATERIAL + PHOTO + CONTEXT

# Sections asked about in --interactive mode (title, fields)
MANUAL_SECTIONS = [
    ("Time data", ["Busy/quiet period"]),
    ("Human occupation", HUMAN),
    ("Study behaviour", STUDY),
    ("Spatial behaviour", SPATIAL),
    ("Material traces (note condition, new/old, change since last visit)", MATERIAL),
    ("Photo and sketch log (separate several with ';')", ["Image ID", "Description"]),
    ("Contextual variables", CONTEXT),
]

PROFILE_FILE = "space_profiles.json"
MIN_OUTAGE = 2  # consecutive lost pings that count as a "connection drop"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def run_win(args, timeout=25):
    """Run a Windows host binary from WSL; return stdout or ''."""
    try:
        return subprocess.check_output(
            args, text=True, errors="ignore", timeout=timeout,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return ""


# --------------------------------------------------------------------------
# Wi-Fi (read from the Windows host)
# --------------------------------------------------------------------------
def get_wifi_info():
    out = run_win(["netsh.exe", "wlan", "show", "interfaces"])

    def grab(key):
        m = re.search(rf"^\s*{key}\s*:\s*(.+?)\s*$", out, re.M | re.I)
        return m.group(1) if m else None

    ssid = grab("SSID")
    if not ssid:
        msg = "Not connected to Wi-Fi (or netsh.exe unavailable)"
        return {"ssid": msg, "rssi": "N/A", "band": "N/A", "bssid": "N/A"}

    # RSSI: newer Windows builds report it directly, otherwise estimate from %
    rssi_raw = grab("Rssi")
    sig = grab("Signal")
    pct = int(re.match(r"\d+", sig).group()) if sig and re.match(r"\d+", sig) else None
    rssi_match = re.match(r"-?\d+", rssi_raw) if rssi_raw else None
    if rssi_match:
        rssi = f"{rssi_match.group()} dBm"
    elif pct is not None:
        rssi = f"{round(pct / 2 - 100)} dBm (est. from {pct}%)"
    else:
        rssi = "Unknown"

    # Band: reported directly, otherwise inferred from the channel number
    band = grab("Band")
    if not band:
        ch = grab("Channel")
        if ch and ch.isdigit():
            band = "2.4 GHz" if int(ch) <= 14 else "5 GHz (or 6 GHz)"
        else:
            band = "Unknown"

    # Which access point (router) you are attached to: strongest clue to floor/room
    bssid = grab(r"(?:AP\s+)?BSSID") or "Unknown"

    return {"ssid": ssid, "rssi": rssi, "band": band, "bssid": bssid}


def get_visible_networks():
    out = run_win(["netsh.exe", "wlan", "show", "networks"])
    names = re.findall(r"^SSID\s+\d+\s*:\s*(.*)$", out, re.M)
    seen, result = set(), []
    for n in (x.strip() for x in names):
        if n and n not in seen:
            seen.add(n)
            result.append(n)
    return result


def get_wifi_fingerprint():
    """Scan every visible access point (BSSID) with its signal strength.
    Which APs you hear, and how strongly, differs between rooms and floors."""
    out = run_win(["netsh.exe", "wlan", "show", "networks", "mode=bssid"], timeout=40)
    aps = {}
    for m in re.finditer(r"^\s*BSSID\s+\d+\s*:\s*([0-9a-fA-F:]{17})\s+Signal\s*:\s*(\d+)%", out, re.M):
        mac, sig = m.group(1).lower(), int(m.group(2))
        aps[mac] = max(sig, aps.get(mac, 0))
    return aps


def parse_fingerprint(text):
    fp = {}
    for part in (text or "").split(";"):
        if "=" in part:
            mac, sig = part.split("=", 1)
            try:
                fp[mac.strip().lower()] = int(sig)
            except ValueError:
                pass
    return fp


def fingerprint_similarity(a, b):
    """Cosine similarity between two fingerprints (1.0 = identical, 0 = nothing in common)."""
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if not na or not nb:
        return 0.0
    return sum(v * b.get(k, 0) for k, v in a.items()) / (na * nb)


def find_room_match(fp, csv_path, threshold=0.85):
    """Best earlier visit (that has a Floor/Room recorded) with a similar fingerprint."""
    if not fp or not os.path.exists(csv_path):
        return None
    best = None
    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if not (r.get("Floor") or r.get("Room / specific area")):
                    continue
                sim = fingerprint_similarity(fp, parse_fingerprint(r.get("Wi-Fi fingerprint (BSSID=signal%)")))
                if sim >= threshold and (best is None or sim > best[0]):
                    best = (sim, r)
    except Exception:
        return None
    return best


def get_cellular_signal():
    out = run_win(["netsh.exe", "mbn", "show", "interfaces"])
    m = re.search(r"Signal[^:\n]*:\s*(\d+)", out, re.I)
    return f"{m.group(1)}%" if m else "N/A (no cellular modem found)"


# --------------------------------------------------------------------------
# Location
# --------------------------------------------------------------------------
def get_location():
    """Windows Location Service first (GPS/Wi-Fi positioning), IP lookup as fallback."""
    ps = (
        "Add-Type -AssemblyName System.Device;"
        "$w = New-Object System.Device.Location.GeoCoordinateWatcher("
        "[System.Device.Location.GeoPositionAccuracy]::High);"
        "$w.Start(); $t = 0;"
        "while (($w.Status -ne 'Ready') -and ($t -lt 150)) { Start-Sleep -Milliseconds 100; $t++ };"
        "$l = $w.Position.Location;"
        "if ($l.IsUnknown) { 'unknown' } else {"
        "[string]::Format([Globalization.CultureInfo]::InvariantCulture,"
        "'{0},{1},{2}', $l.Latitude, $l.Longitude, $l.HorizontalAccuracy) }"
    )
    out = run_win(["powershell.exe", "-NoProfile", "-Command", ps], timeout=40).strip()
    m = re.match(r"(-?\d+\.\d+),(-?\d+\.\d+),(\S+)", out)
    if m:
        lat, lon, acc = m.groups()
        try:
            src = f"Windows Location (±{round(float(acc))} m)"
        except ValueError:
            src = "Windows Location"
        return f"{lat}, {lon}", src

    try:  # fallback: approximate, city-level
        with urllib.request.urlopen("https://ipinfo.io/json", timeout=10) as r:
            loc = json.load(r).get("loc")
        if loc:
            return loc.replace(",", ", "), "IP-based (approximate, city-level)"
    except Exception:
        pass
    return "Unavailable", "Turn on Windows Settings > Privacy > Location"


# --------------------------------------------------------------------------
# Ping: latency, packet loss, drops and outage times from one monitoring run
# --------------------------------------------------------------------------
def ping_monitor(host, count, interval=1.0):
    start = time.time()
    try:
        res = subprocess.run(
            ["ping", "-c", str(count), "-i", str(interval), "-W", "2", host],
            capture_output=True, text=True, timeout=count * (interval + 2) + 15,
        )
        out = res.stdout  # ping exits non-zero when packets are lost, so ignore the return code
    except Exception:
        return "Error", "Error", "Error", "Error"

    replies = {}
    for m in re.finditer(r"icmp_seq=(\d+).*?time=([\d.]+)\s*ms", out):
        replies[int(m.group(1))] = float(m.group(2))

    lost = {s for s in range(1, count + 1) if s not in replies}
    loss = f"{len(lost) / count * 100:.1f}%"
    latency = f"{statistics.mean(replies.values()):.1f} ms" if replies else "No replies"

    # A drop = MIN_OUTAGE or more consecutive lost pings
    runs, run = [], []
    for s in range(1, count + 2):  # count+1 is a sentinel that closes the last run
        if s in lost:
            run.append(s)
        else:
            if len(run) >= MIN_OUTAGE:
                runs.append(run)
            run = []
    outages = [
        f"{datetime.fromtimestamp(start + (r[0] - 1) * interval):%H:%M:%S} (~{len(r) * interval:g}s)"
        for r in runs
    ]
    return latency, loss, str(len(runs)), "; ".join(outages) if outages else "None"


# --------------------------------------------------------------------------
# Speed test
# --------------------------------------------------------------------------
def run_speed_test():
    if speedtest is None:
        return "Error: run 'pip install speedtest-cli'", "Error"
    try:
        st = speedtest.Speedtest()
        st.get_best_server()
        down = round(st.download() / 1_000_000, 2)  # bits/s -> Mbps
        up = round(st.upload() / 1_000_000, 2)
        return f"{down} Mbps", f"{up} Mbps"
    except Exception as e:
        return f"Error: {e}", "Error"


# --------------------------------------------------------------------------
# Space profiles + prompts
# --------------------------------------------------------------------------
def load_profiles():
    try:
        with open(PROFILE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_profiles(profiles):
    with open(PROFILE_FILE, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2, ensure_ascii=False)


def ask_fields(fields, row):
    for field in fields:
        val = input(f"  {field}: ").strip()
        if val:
            row[field] = val


def interactive_prompts(row):
    print("\nObservations (press Enter to skip any field)")
    for title, fields in MANUAL_SECTIONS:
        if input(f"\n{title} - fill in? [Y/n]: ").strip().lower() == "n":
            continue
        ask_fields(fields, row)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description="Study-space visit logger")
    p.add_argument("--output", default="network_study_log.csv", help="CSV file to append to")
    p.add_argument("--space", help="Name of the space; its profile (section 1) is saved/reused")
    p.add_argument("--interactive", action="store_true", help="Prompt for observation fields")
    p.add_argument("--host", default="8.8.8.8", help="Ping target")
    p.add_argument("--count", type=int, default=30, help="Number of pings (1/sec) for the stability test")
    p.add_argument("--skip-speedtest", action="store_true")
    args = p.parse_args()

    start = datetime.now()
    row = {c: "" for c in ALL_COLUMNS}
    row["Visit ID"] = f"V-{start:%Y%m%d-%H%M%S}"
    row["Linked Visit ID"] = row["Visit ID"]
    row["Date"] = f"{start:%Y-%m-%d}"
    row["Day of week"] = f"{start:%A}"
    row["Start time"] = f"{start:%H:%M:%S}"

    # 1. Space profile (record once, reuse afterwards)
    if args.space:
        profiles = load_profiles()
        if args.space in profiles:
            row.update(profiles[args.space])
            print(f"Loaded saved profile for '{args.space}'.")
        elif args.interactive:
            print(f"New space '{args.space}' - describe it once (Enter to skip):")
            ask_fields(SPACE, row)
            profiles[args.space] = {k: row[k] for k in SPACE}
            save_profiles(profiles)
        else:
            print(f"No saved profile for '{args.space}'. Run once with --interactive to create it.")

    print("=" * 44)
    print(" NETWORK DIAGNOSTICS (auto-collected)")
    print("=" * 44)

    # 3. Wi-Fi / network data - all automatic
    wifi = get_wifi_info()
    row["Network connected to"] = wifi["ssid"]
    row["Signal strength (RSSI)"] = wifi["rssi"]
    row["Frequency/band"] = wifi["band"]
    print(f"• Network      : {wifi['ssid']}")
    print(f"• RSSI         : {wifi['rssi']}")
    print(f"• Band         : {wifi['band']}")
    row["Connected access point (BSSID)"] = wifi["bssid"]
    print(f"• Access point : {wifi['bssid']}")

    # Wi-Fi fingerprint: room/floor-level position that GPS can't give indoors
    print("Scanning nearby access points...")
    aps = get_wifi_fingerprint()
    ranked = sorted(aps.items(), key=lambda kv: kv[1], reverse=True)[:25]
    row["Number of access points visible"] = str(len(aps))
    row["Wi-Fi fingerprint (BSSID=signal%)"] = ";".join(f"{mac}={sig}" for mac, sig in ranked)
    print(f"• APs visible  : {len(aps)}")

    if not row["Network type available (eduroam, guest, other)"]:
        row["Network type available (eduroam, guest, other)"] = ", ".join(get_visible_networks())

    row["Cellular signal strength"] = get_cellular_signal()
    print(f"• Cellular     : {row['Cellular signal strength']}")

    print("Getting location...")
    row["Location (GPS coordinates)"], row["Location source/accuracy"] = get_location()
    print(f"• Location     : {row['Location (GPS coordinates)']}  [{row['Location source/accuracy']}]")

    # Room/floor from Wi-Fi fingerprint: reuse Floor/Room from the most similar labelled visit
    if not (row["Floor"] and row["Room / specific area"]):
        match = find_room_match(dict(ranked), args.output)
        if match:
            sim, mrow = match
            if not row["Floor"]:
                row["Floor"] = mrow.get("Floor", "")
            if not row["Room / specific area"]:
                row["Room / specific area"] = mrow.get("Room / specific area", "")
            row["Location source/accuracy"] += f" | Room/floor by Wi-Fi match to {mrow.get('Visit ID', '?')} (similarity {sim:.2f})"
            print(f"• Wi-Fi match  : Floor '{row['Floor']}', Room '{row['Room / specific area']}' (similarity {sim:.2f})")
        else:
            print("• Wi-Fi match  : no labelled visit looks similar (label this space once with --space ... --interactive)")

    print(f"Monitoring connection for ~{args.count}s (latency, loss, drops)...")
    lat, loss, drops, outages = ping_monitor(args.host, args.count)
    row["Latency/ping"], row["Packet loss"] = lat, loss
    row["Connection drops"], row["Time of any outage"] = drops, outages
    print(f"• Latency      : {lat}")
    print(f"• Packet loss  : {loss}")
    print(f"• Drops        : {drops}  ({outages})")

    if args.skip_speedtest:
        row["Download speed"] = row["Upload speed"] = "Skipped"
    else:
        print("Testing speeds (this may take a minute)...")
        row["Download speed"], row["Upload speed"] = run_speed_test()
    print(f"• Download     : {row['Download speed']}")
    print(f"• Upload       : {row['Upload speed']}")

    # Observations (optional)
    if args.interactive:
        interactive_prompts(row)

    row["End time"] = f"{datetime.now():%H:%M:%S}"

    # Append to CSV (header written once)
    exists = os.path.exists(args.output) and os.path.getsize(args.output) > 0
    if exists:
        # An older CSV with different columns would misalign the new row: keep it as a backup
        with open(args.output, newline="", encoding="utf-8-sig") as f:
            header = next(csv.reader(f), [])
        if header != ALL_COLUMNS:
            backup = f"{args.output}.old-{start:%Y%m%d-%H%M%S}"
            os.rename(args.output, backup)
            print(f"Existing CSV had different columns; kept it as {backup} and started a new one.")
            exists = False
    with open(args.output, "a", newline="", encoding="utf-8" if exists else "utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=ALL_COLUMNS)
        if not exists:
            writer.writeheader()
        writer.writerow(row)

    print("=" * 44)
    print(f"Saved visit {row['Visit ID']} to {args.output}")


if __name__ == "__main__":
    main()