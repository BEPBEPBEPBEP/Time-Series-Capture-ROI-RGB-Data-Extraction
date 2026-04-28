from datetime import datetime
import time
import csv
import os

import cv2
import numpy as np
from picamera2 import Picamera2
from smbus2 import SMBus, i2c_msg

# -------------------------------
# LIGHT SETTINGS
# -------------------------------
ADDR = 0x36
BUS = 1
NUM_LEDS = 8

# use brightness control only here
LIGHT_BRIGHTNESS = 30

# -------------------------------
# FIXED ROI SETTINGS
# -------------------------------
WELLS = [
    (1290, 675),   # W1
    (1290, 675),  # W2
    (1290, 675),  # W3
    (1290, 675)   # W4 blank/control
]

ROI_RADIUS = 45

# rectangular background ROI
RECT_TOP_LEFT = (700, 935)
RECT_BOTTOM_RIGHT = (1925, 1035)

# color swatch ROIs (left -> right: white, gray, black)
SWATCHES = [
    {
        "label": "SW_WHITE",
        "top_left": (755, 1220),
        "bottom_right": (950, 1460)
    },
    {
        "label": "SW_GRAY",
        "top_left": (1200, 1220),
        "bottom_right": (1395, 1460)
    },
    {
        "label": "SW_BLACK",
        "top_left": (1670, 1220),
        "bottom_right": (1865, 1460)
    }
]

# -------------------------------
# TIME SERIES SETTINGS
# -------------------------------
INTERVAL_S = 15
TOTAL_DURATION_S = 120   # 4 minutes
NUM_CAPTURES = TOTAL_DURATION_S // INTERVAL_S + 1

# -------------------------------
# CAMERA TIMING
# -------------------------------
AUTO_SETTLE_S = 4.0
POST_LOCK_WAIT_S = 0.6
LIGHT_SETTLE_S = 2.0
SYSTEM_WARMUP_S = 2

# -------------------------------
# BRIGHTNESS SAFETY CHECK
# -------------------------------
MEAN_BRIGHTNESS_ABORT_THRESHOLD = 245

# -------------------------------
# FILE SETTINGS
# -------------------------------
OUTPUT_DIR = "timeseries_output"
SAVE_NPY = True


def brightness_to_5bit(b):
    b = max(0, min(100, int(b)))
    return round(b * 31 / 100)


def led_bytes(r, g, b, brightness):
    return [0xE0 | brightness_to_5bit(brightness), b, g, r]


def lights_on():
    payload = []
    for _ in range(NUM_LEDS):
        # full white, brightness controlled only by LIGHT_BRIGHTNESS
        payload.extend(led_bytes(255, 255, 255, LIGHT_BRIGHTNESS))
    with SMBus(BUS) as bus:
        bus.i2c_rdwr(i2c_msg.write(ADDR, payload))


def lights_off():
    payload = []
    for _ in range(NUM_LEDS):
        payload.extend([0xE0, 0, 0, 0])
    with SMBus(BUS) as bus:
        bus.i2c_rdwr(i2c_msg.write(ADDR, payload))


def mean_bgr_in_circle(img, x, y, r):
    mask = np.zeros(img.shape[:2], dtype=np.uint8)
    cv2.circle(mask, (x, y), r, 255, -1)
    b, g, rr, _ = cv2.mean(img, mask=mask)
    return b, g, rr


def mean_bgr_in_rect(img, top_left, bottom_right):
    x1, y1 = top_left
    x2, y2 = bottom_right
    roi = img[y1:y2, x1:x2]
    b, g, r, _ = cv2.mean(roi)
    return b, g, r


def draw_preview(img, wells, radius):
    out = img.copy()

    # wells
    for i, (x, y) in enumerate(wells, start=1):
        cv2.circle(out, (x, y), radius, (0, 255, 0), 2)
        cv2.circle(out, (x, y), 3, (0, 255, 255), -1)
        cv2.putText(
            out,
            f"W{i}",
            (x - 20, y - radius - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 255),
            2
        )

    # background rectangle ROI
    cv2.rectangle(out, RECT_TOP_LEFT, RECT_BOTTOM_RIGHT, (255, 0, 0), 2)
    cv2.putText(
        out,
        "BG_RECT",
        (RECT_TOP_LEFT[0], RECT_TOP_LEFT[1] - 10),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 0, 0),
        2
    )

    # swatches
    swatch_colors = {
        "SW_WHITE": (255, 255, 255),
        "SW_GRAY": (220, 220, 220),
        "SW_BLACK": (0, 255, 255)   # visible on black
    }

    for sw in SWATCHES:
        label = sw["label"]
        tl = sw["top_left"]
        br = sw["bottom_right"]
        color = swatch_colors.get(label, (255, 255, 0))

        cv2.rectangle(out, tl, br, color, 2)
        cv2.putText(
            out,
            label,
            (tl[0], tl[1] - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            color,
            2
        )

    return out


def print_separator(widths):
    print("-+-".join("-" * w for w in widths))


def print_row(values, widths):
    formatted = []
    for v, w in zip(values, widths):
        formatted.append(str(v).ljust(w))
    print(" | ".join(formatted))


def image_mean_brightness(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(np.mean(gray))


def autosettle_and_lock_once(picam2):
    """
    One-time autosettle under the real lit scene.
    Then lock those settings for the whole run.
    """
    picam2.set_controls({
        "AeEnable": True,
        "AwbEnable": True
    })

    time.sleep(AUTO_SETTLE_S)

    metadata = picam2.capture_metadata()

    exposure_time = metadata.get("ExposureTime")
    analogue_gain = metadata.get("AnalogueGain")
    colour_gains = metadata.get("ColourGains")

    if exposure_time is None or analogue_gain is None or colour_gains is None:
        raise RuntimeError("Could not read metadata during auto-settle.")

    picam2.set_controls({
        "AeEnable": False,
        "AwbEnable": False,
        "ExposureTime": exposure_time,
        "AnalogueGain": analogue_gain,
        "ColourGains": colour_gains,
        "FrameDurationLimits": (exposure_time, exposure_time),
    })

    time.sleep(POST_LOCK_WAIT_S)

    return exposure_time, analogue_gain, colour_gains


def safe_ratio(num, den):
    return round(num / den, 4) if den != 0 else ""


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_name = os.path.join(OUTPUT_DIR, f"timeseries_rgb_swatches_{timestamp}.csv")
    preview_name = os.path.join(OUTPUT_DIR, f"roi_preview_{timestamp}.png")

    print("Starting camera...")
    picam2 = Picamera2()
    config = picam2.create_still_configuration(
        main={"size": (2592, 1944), "format": "RGB888"}
    )
    picam2.configure(config)
    picam2.start()
    time.sleep(SYSTEM_WARMUP_S)

    print("System warm-up...")
    lights_on()
    time.sleep(10)

    print("Auto-settling and locking camera once...")
    locked_exposure_time, locked_analogue_gain, locked_colour_gains = autosettle_and_lock_once(picam2)

    print(
        f"Locked once -> ExposureTime={locked_exposure_time}, "
        f"AnalogueGain={locked_analogue_gain:.4f}, "
        f"ColourGains=({locked_colour_gains[0]:.4f}, {locked_colour_gains[1]:.4f})"
    )

    lights_off()
    rows = []

    try:
        start_time = time.time()

        for i in range(NUM_CAPTURES):
            target_time = start_time + i * INTERVAL_S
            now = time.time()
            if now < target_time:
                time.sleep(target_time - now)

            elapsed_s = int(round(time.time() - start_time))
            image_stem = f"capture_{timestamp}_{elapsed_s:03d}s"
            image_name = os.path.join(OUTPUT_DIR, f"{image_stem}.png")
            npy_name = os.path.join(OUTPUT_DIR, f"{image_stem}.npy")

            print(f"\nTime {elapsed_s}s: turning lights on")
            lights_on()
            time.sleep(LIGHT_SETTLE_S)

            print(f"Capturing {image_name}")
            img = picam2.capture_array("main")

            # save PNG
            cv2.imwrite(image_name, img)

            # save NPY
            if SAVE_NPY:
                np.save(npy_name, img)

            print("Turning lights off")
            lights_off()

            if i == 0:
                preview = draw_preview(img, WELLS, ROI_RADIUS)
                cv2.imwrite(preview_name, preview)

                mean_brightness = image_mean_brightness(img)
                print(f"First image mean brightness: {mean_brightness:.2f}")

                if mean_brightness >= MEAN_BRIGHTNESS_ABORT_THRESHOLD:
                    raise RuntimeError(
                        "First image still appears overexposed. "
                        "Lower LIGHT_BRIGHTNESS further and rerun."
                    )

            row = {
                "time_s": elapsed_s,
                "image_png": image_name,
                "image_npy": npy_name if SAVE_NPY else "",
                "ExposureTime": locked_exposure_time,
                "AnalogueGain": round(float(locked_analogue_gain), 4),
                "ColourGain_R": round(float(locked_colour_gains[0]), 4),
                "ColourGain_B": round(float(locked_colour_gains[1]), 4),
            }

            # background rectangle
            bg_b, bg_g, bg_r = mean_bgr_in_rect(img, RECT_TOP_LEFT, RECT_BOTTOM_RIGHT)
            row["BG_R"] = round(bg_r, 2)
            row["BG_G"] = round(bg_g, 2)
            row["BG_B"] = round(bg_b, 2)
            row["BG_BminusR"] = round(bg_b - bg_r, 2)
            row["BG_BoverR"] = safe_ratio(bg_b, bg_r)

            # wells
            rgb_values = []

            for idx, (x, y) in enumerate(WELLS, start=1):
                b, g, r = mean_bgr_in_circle(img, x, y, ROI_RADIUS)

                row[f"W{idx}_R"] = round(r, 2)
                row[f"W{idx}_G"] = round(g, 2)
                row[f"W{idx}_B"] = round(b, 2)
                row[f"W{idx}_BminusR"] = round(b - r, 2)
                row[f"W{idx}_BoverR"] = safe_ratio(b, r)

                d_r = r - bg_r
                d_g = g - bg_g
                d_b = b - bg_b

                row[f"W{idx}_dR"] = round(d_r, 2)
                row[f"W{idx}_dG"] = round(d_g, 2)
                row[f"W{idx}_dB"] = round(d_b, 2)
                row[f"W{idx}_dBminusR"] = round(d_b - d_r, 2)

                rgb_values.append((r, g, b))

            # average only W1-W3
            avg_r = np.mean([rgb_values[0][0], rgb_values[1][0], rgb_values[2][0]])
            avg_g = np.mean([rgb_values[0][1], rgb_values[1][1], rgb_values[2][1]])
            avg_b = np.mean([rgb_values[0][2], rgb_values[1][2], rgb_values[2][2]])

            row["AVG123_R"] = round(avg_r, 2)
            row["AVG123_G"] = round(avg_g, 2)
            row["AVG123_B"] = round(avg_b, 2)
            row["AVG123_BminusR"] = round(avg_b - avg_r, 2)
            row["AVG123_BoverR"] = safe_ratio(avg_b, avg_r)

            avg_d_r = avg_r - bg_r
            avg_d_g = avg_g - bg_g
            avg_d_b = avg_b - bg_b

            row["AVG123_dR"] = round(avg_d_r, 2)
            row["AVG123_dG"] = round(avg_d_g, 2)
            row["AVG123_dB"] = round(avg_d_b, 2)
            row["AVG123_dBminusR"] = round(avg_d_b - avg_d_r, 2)

            # swatches
            for sw in SWATCHES:
                label = sw["label"]
                b, g, r = mean_bgr_in_rect(img, sw["top_left"], sw["bottom_right"])

                row[f"{label}_R"] = round(r, 2)
                row[f"{label}_G"] = round(g, 2)
                row[f"{label}_B"] = round(b, 2)
                row[f"{label}_BminusR"] = round(b - r, 2)
                row[f"{label}_BoverR"] = safe_ratio(b, r)

                d_r = r - bg_r
                d_g = g - bg_g
                d_b = b - bg_b

                row[f"{label}_dR"] = round(d_r, 2)
                row[f"{label}_dG"] = round(d_g, 2)
                row[f"{label}_dB"] = round(d_b, 2)
                row[f"{label}_dBminusR"] = round(d_b - d_r, 2)

            rows.append(row)

        # Save CSV
        fieldnames = [
            "time_s", "image_png", "image_npy",
            "ExposureTime", "AnalogueGain", "ColourGain_R", "ColourGain_B",

            "BG_R", "BG_G", "BG_B", "BG_BminusR", "BG_BoverR",

            "W1_R", "W1_G", "W1_B", "W1_BminusR", "W1_BoverR", "W1_dR", "W1_dG", "W1_dB", "W1_dBminusR",
            "W2_R", "W2_G", "W2_B", "W2_BminusR", "W2_BoverR", "W2_dR", "W2_dG", "W2_dB", "W2_dBminusR",
            "W3_R", "W3_G", "W3_B", "W3_BminusR", "W3_BoverR", "W3_dR", "W3_dG", "W3_dB", "W3_dBminusR",
            "W4_R", "W4_G", "W4_B", "W4_BminusR", "W4_BoverR", "W4_dR", "W4_dG", "W4_dB", "W4_dBminusR",

            "AVG123_R", "AVG123_G", "AVG123_B", "AVG123_BminusR", "AVG123_BoverR",
            "AVG123_dR", "AVG123_dG", "AVG123_dB", "AVG123_dBminusR",

            "SW_WHITE_R", "SW_WHITE_G", "SW_WHITE_B", "SW_WHITE_BminusR", "SW_WHITE_BoverR",
            "SW_WHITE_dR", "SW_WHITE_dG", "SW_WHITE_dB", "SW_WHITE_dBminusR",

            "SW_GRAY_R", "SW_GRAY_G", "SW_GRAY_B", "SW_GRAY_BminusR", "SW_GRAY_BoverR",
            "SW_GRAY_dR", "SW_GRAY_dG", "SW_GRAY_dB", "SW_GRAY_dBminusR",

            "SW_BLACK_R", "SW_BLACK_G", "SW_BLACK_B", "SW_BLACK_BminusR", "SW_BLACK_BoverR",
            "SW_BLACK_dR", "SW_BLACK_dG", "SW_BLACK_dB", "SW_BLACK_dBminusR"
        ]

        with open(csv_name, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        # -------------------------------
        # TABLE 1: CORE ASSAY
        # -------------------------------
        headers_core = [
            "Time(s)",
            "BG_R", "BG_G", "BG_B",
            "W1_R", "W1_G", "W1_B",
            "W2_R", "W2_G", "W2_B",
            "W3_R", "W3_G", "W3_B",
            "W4_R", "W4_G", "W4_B",
            "AVG123_R", "AVG123_G", "AVG123_B",
            "AVG123_B-R", "AVG123_B/R",
            "AVG123_dR", "AVG123_dG", "AVG123_dB", "AVG123_d(B-R)"
        ]

        table_rows_core = []
        for row in rows:
            table_rows_core.append([
                row["time_s"],
                row["BG_R"], row["BG_G"], row["BG_B"],
                row["W1_R"], row["W1_G"], row["W1_B"],
                row["W2_R"], row["W2_G"], row["W2_B"],
                row["W3_R"], row["W3_G"], row["W3_B"],
                row["W4_R"], row["W4_G"], row["W4_B"],
                row["AVG123_R"], row["AVG123_G"], row["AVG123_B"],
                row["AVG123_BminusR"], row["AVG123_BoverR"],
                row["AVG123_dR"], row["AVG123_dG"], row["AVG123_dB"], row["AVG123_dBminusR"]
            ])

        widths_core = []
        for col_idx in range(len(headers_core)):
            max_len = len(str(headers_core[col_idx]))
            for tr in table_rows_core:
                max_len = max(max_len, len(str(tr[col_idx])))
            widths_core.append(max_len)

        print("\nCORE ASSAY TABLE")
        print_row(headers_core, widths_core)
        print_separator(widths_core)
        for tr in table_rows_core:
            print_row(tr, widths_core)

        # -------------------------------
        # TABLE 2: SWATCHES
        # -------------------------------
        headers_sw = [
            "Time(s)",

            "SW_WHITE_R", "SW_WHITE_G", "SW_WHITE_B",
            "SW_WHITE_B-R", "SW_WHITE_B/R",
            "SW_WHITE_dR", "SW_WHITE_dG", "SW_WHITE_dB", "SW_WHITE_d(B-R)",

            "SW_GRAY_R", "SW_GRAY_G", "SW_GRAY_B",
            "SW_GRAY_B-R", "SW_GRAY_B/R",
            "SW_GRAY_dR", "SW_GRAY_dG", "SW_GRAY_dB", "SW_GRAY_d(B-R)",

            "SW_BLACK_R", "SW_BLACK_G", "SW_BLACK_B",
            "SW_BLACK_B-R", "SW_BLACK_B/R",
            "SW_BLACK_dR", "SW_BLACK_dG", "SW_BLACK_dB", "SW_BLACK_d(B-R)"
        ]

        table_rows_sw = []
        for row in rows:
            table_rows_sw.append([
                row["time_s"],

                row["SW_WHITE_R"], row["SW_WHITE_G"], row["SW_WHITE_B"],
                row["SW_WHITE_BminusR"], row["SW_WHITE_BoverR"],
                row["SW_WHITE_dR"], row["SW_WHITE_dG"], row["SW_WHITE_dB"], row["SW_WHITE_dBminusR"],

                row["SW_GRAY_R"], row["SW_GRAY_G"], row["SW_GRAY_B"],
                row["SW_GRAY_BminusR"], row["SW_GRAY_BoverR"],
                row["SW_GRAY_dR"], row["SW_GRAY_dG"], row["SW_GRAY_dB"], row["SW_GRAY_dBminusR"],

                row["SW_BLACK_R"], row["SW_BLACK_G"], row["SW_BLACK_B"],
                row["SW_BLACK_BminusR"], row["SW_BLACK_BoverR"],
                row["SW_BLACK_dR"], row["SW_BLACK_dG"], row["SW_BLACK_dB"], row["SW_BLACK_dBminusR"]
            ])

        widths_sw = []
        for col_idx in range(len(headers_sw)):
            max_len = len(str(headers_sw[col_idx]))
            for tr in table_rows_sw:
                max_len = max(max_len, len(str(tr[col_idx])))
            widths_sw.append(max_len)

        print("\nSWATCH TABLE")
        print_row(headers_sw, widths_sw)
        print_separator(widths_sw)
        for tr in table_rows_sw:
            print_row(tr, widths_sw)

        print(f"\nSaved CSV: {csv_name}")
        print(f"Saved ROI preview: {preview_name}")

    finally:
        try:
            lights_off()
        except Exception:
            pass

        try:
            picam2.stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
