from datetime import datetime
import time
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
# CAMERA / TIMING SETTINGS
# -------------------------------
SYSTEM_WARMUP_S = 2
LIGHT_SETTLE_S = 2.0
AUTO_SETTLE_S = 4.0
POST_LOCK_WAIT_S = 0.6

# -------------------------------
# FILE SETTINGS
# -------------------------------
OUTPUT_DIR = "test_captures"
SAVE_NPY = True

# -------------------------------
# BRIGHTNESS SAFETY CHECK
# -------------------------------
MEAN_BRIGHTNESS_ABORT_THRESHOLD = 245


def brightness_to_5bit(b):
    b = max(0, min(100, int(b)))
    return round(b * 31 / 100)


def led_bytes(r, g, b, brightness):
    return [0xE0 | brightness_to_5bit(brightness), b, g, r]


def lights_on():
    payload = []
    for _ in range(NUM_LEDS):
        # full white; brightness controlled by LIGHT_BRIGHTNESS
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
    b, g, r_val, _ = cv2.mean(img, mask=mask)
    return b, g, r_val


def mean_bgr_in_rect(img, top_left, bottom_right):
    x1, y1 = top_left
    x2, y2 = bottom_right
    roi = img[y1:y2, x1:x2]
    b, g, r_val, _ = cv2.mean(roi)
    return b, g, r_val


def draw_preview(img):
    out = img.copy()

    # draw well ROIs
    for i, (x, y) in enumerate(WELLS, start=1):
        cv2.circle(out, (x, y), ROI_RADIUS, (0, 255, 0), 2)
        cv2.circle(out, (x, y), 3, (0, 255, 255), -1)
        cv2.putText(
            out,
            f"W{i}",
            (x - 20, y - ROI_RADIUS - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 255),
            2
        )

    # draw background rectangle ROI
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

    # draw swatch ROIs
    swatch_box_colors = {
        "SW_WHITE": (255, 255, 255),
        "SW_GRAY": (180, 180, 180),
        "SW_BLACK": (0, 255, 255),   # yellow-ish so it shows up
    }

    for sw in SWATCHES:
        label = sw["label"]
        tl = sw["top_left"]
        br = sw["bottom_right"]
        color = swatch_box_colors.get(label, (255, 255, 0))

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


def image_mean_brightness(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(np.mean(gray))


def autosettle_and_lock_once(picam2):
    """
    Let camera AE/AWB settle under the real lit scene,
    then lock the resulting settings for this capture.
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

    # lock them
    picam2.set_controls({
        "AeEnable": False,
        "AwbEnable": False,
        "ExposureTime": exposure_time,
        "AnalogueGain": analogue_gain,
        "ColourGains": colour_gains
    })

    time.sleep(POST_LOCK_WAIT_S)
    return exposure_time, analogue_gain, colour_gains


def safe_ratio(num, den):
    return num / den if den != 0 else float("nan")


def print_table_row(label, b, g, r, bg_b=None, bg_g=None, bg_r=None):
    b_minus_r = b - r
    b_over_r = safe_ratio(b, r)

    if bg_b is None:
        print(
            f"{label:<10}"
            f"{b:>9.2f}{g:>9.2f}{r:>9.2f}"
            f"{b_minus_r:>10.2f}{b_over_r:>10.4f}"
        )
    else:
        db = b - bg_b
        dg = g - bg_g
        dr = r - bg_r
        d_b_minus_r = db - dr

        print(
            f"{label:<10}"
            f"{b:>9.2f}{g:>9.2f}{r:>9.2f}"
            f"{b_minus_r:>10.2f}{b_over_r:>10.4f}"
            f"{db:>10.2f}{dg:>10.2f}{dr:>10.2f}"
            f"{d_b_minus_r:>12.2f}"
        )


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("Starting camera...")

    picam2 = Picamera2()
    config = picam2.create_still_configuration(
        main={"size": (2592, 1944), "format": "RGB888"}
    )

    picam2.configure(config)
    picam2.start()
    time.sleep(SYSTEM_WARMUP_S)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    image_name = os.path.join(OUTPUT_DIR, f"capture_{timestamp}.png")
    preview_name = os.path.join(OUTPUT_DIR, f"roi_preview_{timestamp}.png")
    npy_name = os.path.join(OUTPUT_DIR, f"capture_{timestamp}.npy")

    try:
        print("Turning lights on")
        lights_on()

        print(f"Waiting {LIGHT_SETTLE_S:.1f} seconds for light settle")
        time.sleep(LIGHT_SETTLE_S)

        print("Auto-settling and locking camera once...")
        exposure_time, analogue_gain, colour_gains = autosettle_and_lock_once(picam2)

        print(
            f"Locked -> ExposureTime={exposure_time}, "
            f"AnalogueGain={analogue_gain:.4f}, "
            f"ColourGains=({colour_gains[0]:.4f}, {colour_gains[1]:.4f})"
        )

        print("Capturing image...")
        img = picam2.capture_array("main")

        # Save PNG
        cv2.imwrite(image_name, img)

        # Save NPY
        if SAVE_NPY:
            np.save(npy_name, img)

        mean_brightness = image_mean_brightness(img)
        print(f"\nImage mean brightness: {mean_brightness:.2f}")

        if mean_brightness >= MEAN_BRIGHTNESS_ABORT_THRESHOLD:
            print("WARNING: image may be overexposed; consider lowering LIGHT_BRIGHTNESS.")

        # measure background rectangle first
        bg_b, bg_g, bg_r = mean_bgr_in_rect(img, RECT_TOP_LEFT, RECT_BOTTOM_RIGHT)

        # measure wells
        well_results = []
        for i, (x, y) in enumerate(WELLS, start=1):
            b, g, r = mean_bgr_in_circle(img, x, y, ROI_RADIUS)
            well_results.append({
                "label": f"W{i}",
                "x": x,
                "y": y,
                "b": b,
                "g": g,
                "r": r
            })

        # measure swatches
        swatch_results = []
        for sw in SWATCHES:
            b, g, r = mean_bgr_in_rect(img, sw["top_left"], sw["bottom_right"])
            swatch_results.append({
                "label": sw["label"],
                "top_left": sw["top_left"],
                "bottom_right": sw["bottom_right"],
                "b": b,
                "g": g,
                "r": r
            })

        # preview image
        preview = draw_preview(img)
        cv2.imwrite(preview_name, preview)

        print("\nROI / Background / Swatch Table")
        print(
            f"{'Label':<10}"
            f"{'B':>9}{'G':>9}{'R':>9}"
            f"{'B-R':>10}{'B/R':>10}"
            f"{'dB':>10}{'dG':>10}{'dR':>10}"
            f"{'d(B-R)':>12}"
        )
        print("-" * 108)

        # print BG rectangle row
        print_table_row("BG_RECT", bg_b, bg_g, bg_r)

        # print swatches with background-subtracted columns
        for row in swatch_results:
            print_table_row(
                row["label"],
                row["b"], row["g"], row["r"],
                bg_b, bg_g, bg_r
            )

        # print wells with background-subtracted columns
        for row in well_results:
            print_table_row(
                row["label"],
                row["b"], row["g"], row["r"],
                bg_b, bg_g, bg_r
            )

        # average W1-W3 only
        rxn_b = np.mean([well_results[0]["b"], well_results[1]["b"], well_results[2]["b"]])
        rxn_g = np.mean([well_results[0]["g"], well_results[1]["g"], well_results[2]["g"]])
        rxn_r = np.mean([well_results[0]["r"], well_results[1]["r"], well_results[2]["r"]])

        print("-" * 108)
        print_table_row("AVG_W1-3", rxn_b, rxn_g, rxn_r, bg_b, bg_g, bg_r)

        # blank-vs-background summary too
        blank_b = well_results[3]["b"]
        blank_g = well_results[3]["g"]
        blank_r = well_results[3]["r"]

        # swatch quick refs
        sw_white = next((s for s in swatch_results if s["label"] == "SW_WHITE"), None)
        sw_gray = next((s for s in swatch_results if s["label"] == "SW_GRAY"), None)
        sw_black = next((s for s in swatch_results if s["label"] == "SW_BLACK"), None)

        print("\nQuick summary:")
        print(
            f"AVG_W1-3 raw:      B={rxn_b:.2f}  G={rxn_g:.2f}  R={rxn_r:.2f}  "
            f"B-R={rxn_b-rxn_r:.2f}  B/R={safe_ratio(rxn_b, rxn_r):.4f}"
        )
        print(
            f"AVG_W1-3 minus BG: dB={rxn_b-bg_b:.2f}  dG={rxn_g-bg_g:.2f}  "
            f"dR={rxn_r-bg_r:.2f}  d(B-R)={(rxn_b-bg_b) - (rxn_r-bg_r):.2f}"
        )
        print(
            f"W4 blank minus BG: dB={blank_b-bg_b:.2f}  dG={blank_g-bg_g:.2f}  "
            f"dR={blank_r-bg_r:.2f}  d(B-R)={(blank_b-bg_b) - (blank_r-bg_r):.2f}"
        )

        if sw_white and sw_gray and sw_black:
            print(
                f"SW_WHITE raw:      B={sw_white['b']:.2f}  G={sw_white['g']:.2f}  R={sw_white['r']:.2f}"
            )
            print(
                f"SW_GRAY raw:       B={sw_gray['b']:.2f}  G={sw_gray['g']:.2f}  R={sw_gray['r']:.2f}"
            )
            print(
                f"SW_BLACK raw:      B={sw_black['b']:.2f}  G={sw_black['g']:.2f}  R={sw_black['r']:.2f}"
            )

        print(f"\nSaved capture: {image_name}")
        if SAVE_NPY:
            print(f"Saved NPY: {npy_name}")
        print(f"Saved ROI preview: {preview_name}")

    finally:
        print("Turning lights off")
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
