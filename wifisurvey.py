"""
Click-to-record Wi-Fi survey.
Usage: python wifi_survey.py floorplan.png survey.csv
Stand at a spot, click that spot on the plan, wait for the dot. Close the window when done.
"""
import csv, re, sys, time, platform, subprocess
import matplotlib.pyplot as plt

SAMPLES, DELAY = 5, 0.5  # readings per point, seconds between them

def get_rssi():
    os_name = platform.system()
    if os_name == "Linux":
        out = subprocess.run(["iw", "dev", "wlan0", "link"], capture_output=True, text=True).stdout
        m = re.search(r"signal:\s*(-?\d+)", out)
    elif os_name == "Darwin":  # needs sudo
        out = subprocess.run(["sudo", "wdutil", "info"], capture_output=True, text=True).stdout
        m = re.search(r"RSSI\s*:\s*(-?\d+)", out)
    else:  # Windows reports %, convert roughly to dBm
        out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True).stdout
        m = re.search(r"Signal\s*:\s*(\d+)%", out)
        return int(m.group(1)) / 2 - 100 if m else None
    return int(m.group(1)) if m else None

def sample():
    vals = []
    for _ in range(SAMPLES):
        v = get_rssi()
        if v is not None:
            vals.append(v)
        time.sleep(DELAY)
    return sum(vals) / len(vals) if vals else None

def main(plan, out_csv):
    fig, ax = plt.subplots()
    ax.imshow(plt.imread(plan))
    ax.set_title("Click your current position")
    f = open(out_csv, "a", newline="")
    writer = csv.writer(f)

    def on_click(event):
        if event.inaxes != ax or event.button != 1:
            return
        x, y = event.xdata, event.ydata
        ax.set_title("Sampling...")
        fig.canvas.draw_idle(); plt.pause(0.01)
        rssi = sample()
        if rssi is None:
            ax.set_title("No reading - connected to Wi-Fi? Click again")
        else:
            writer.writerow([round(x), round(y), round(rssi, 1)]); f.flush()
            ax.plot(x, y, "o", color="red")
            ax.annotate(f"{rssi:.0f}", (x, y), xytext=(4, 4), textcoords="offset points", fontsize=8)
            ax.set_title(f"Saved ({x:.0f}, {y:.0f}) = {rssi:.1f} dBm")
        fig.canvas.draw_idle()

    fig.canvas.mpl_connect("button_press_event", on_click)
    plt.show()
    f.close()

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "survey.csv")