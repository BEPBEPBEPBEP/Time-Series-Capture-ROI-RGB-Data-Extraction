# Time-Series Capture & ROI RGB Data Extraction

Automated imaging and quantitative color analysis pipeline for microfluidic paper-based analytical devices (µPADs), using a Raspberry Pi camera system with controlled illumination.

---

## Overview

This repository contains a two-stage workflow for **reproducible colorimetric analysis**:

1. **ROI Calibration (preliminary_shot.py)**  
   Captures a single calibrated image and verifies spatial alignment of regions of interest (ROIs).

2. **Time-Series Data Extraction (timeseries_dataextrct.py)**  
   Performs automated image capture over time and extracts quantitative color data from predefined ROIs.

Together, these scripts form a complete system for **capturing, standardizing, and quantifying colorimetric signals** in µPAD-based assays.

---

## System Visualization

Below is an example of the imaging system output with defined regions of interest (ROIs):

![ROI Preview](roi_preview_20260411_190307.png)

- Circular ROIs correspond to detection wells (W1–W4)
- Rectangular region defines background normalization area
- Lower regions represent calibration swatches (white, gray, black)

## System Architecture

- Raspberry Pi + Picamera2
- I2C-controlled LED illumination array
- Fixed imaging chamber geometry
- Python-based acquisition + analysis pipeline (OpenCV + NumPy)

All image processing and pixel extraction are performed **directly on the Raspberry Pi**, with no external software required. 

---

## Workflow

### Step 1 — ROI + Lighting Calibration

Run:
```bash
python preliminary_shot.py
```


This script performs a single controlled image capture to verify system setup before running experiments.

Key functions:

- Initializes camera and LED illumination
- Performs auto-exposure and white balance settling, then locks parameters
- Captures a high-resolution image of the device
- Defines and overlays all regions of interest (ROIs):
  - Circular ROIs for wells
  - Rectangular ROI for background
  - Calibration swatches (white, gray, black)

- Extracts and prints:
  - Mean RGB values for all ROIs
  - Derived color metrics (B−R, B/R)
  - Background-corrected values (ΔRGB)

- Outputs:
  - Raw image (`.png`)
  - ROI overlay preview (`.png`)
  - Raw pixel data (`.npy`)

Purpose:
- Identify current ROI placement to allow for coordinate modification
- Verify lighting uniformity
- Check for overexposure or misalignment before time-series acquisition

---

### Step 2 - Automated Time-Series Acquisition & Data Extraction

Run:
```bash
python timeseries_dataextrct.py
```

This script performs full experimental runs by capturing and analyzing images over time.

Key functions:

- Captures images at fixed intervals for a set amount of time (default: every 15 seconds for 240 seconds)
- Controls LED illumination during each capture cycle
- Locks camera exposure and white balance once for consistency across all frames
- Extracts pixel data from all ROIs for each timepoint

- Computes:
  - Raw RGB values
  - Derived metrics (B−R, B/R)
  - Background-corrected values (ΔRGB)
  - Averaged assay signal across W1–W3

- Generates structured datasets:
  - One full data row per timepoint

- Outputs:
  - Time-series images (`.png`)
  - ROI preview (first frame)
  - Raw pixel arrays (`.npy`)
  - Full dataset (`.csv`)

- Prints:
  - Core assay table (wells + averages)
  - Swatch calibration table

Purpose:
- Track colorimetric signal evolution over time
- Generate quantitative datasets for calibration and analysis

---

## ROI-Based Pixel Extraction

Images are captured as pixel arrays and analyzed directly using OpenCV and NumPy.

Regions of interest (ROIs) are spatially defined and include:

- Circular ROIs for detection wells
- Rectangular ROI for background normalization
- Calibration swatches (white, gray, black)

For each ROI, the script computes the **mean RGB intensity** across all pixels within the region.

---

## Color Metrics & Signal Processing

To quantify colorimetric changes, the following metrics are computed:

- **B − R (Blue minus Red)**  
  Highlights blue-shifted reactions (e.g., Zincon complex formation)

- **B / R (Blue-to-Red ratio)**  
  Normalizes signal intensity relative to the red channel

### Background Correction

Each ROI is normalized against a background region:

- ΔR = R_ROI − R_background  
- ΔG = G_ROI − G_background  
- ΔB = B_ROI − B_background  
- Δ(B − R) = (ΔB − ΔR)

This improves robustness against lighting variation and substrate effects.

---

## Data Output

Each run generates:

### CSV File
- Timepoint (s)
- Raw RGB values for all ROIs
- Derived metrics (B−R, B/R)
- Background-corrected values
- Averaged assay signal

### Image Files
- Time-series captures (`.png`)
- ROI overlay preview (first frame)

### NumPy Arrays
- Raw image data (`.npy`)
- Enables reproducible analysis

---

## Printed Output Tables

During execution, two formatted tables are printed:

### Core Assay Table
- Background values
- Individual wells (W1–W4)
- Averaged signal (W1–W3)
- Derived metrics (B−R, B/R)
- Background-corrected values

### Swatch Calibration Table
- White, gray, and black reference regions
- Raw and normalized color values

These tables provide immediate feedback for assessing signal quality during acquisition.

---

## Application

This system is designed for quantitative colorimetric analysis in µPAD-based assays, including:

- Heavy metal detection (e.g., Zn²⁺ with Zincon)
- Reaction kinetics tracking
- Calibration curve generation
- Low-cost environmental sensing

## Notes

- ROI coordinates must be calibrated before use
- Consistent device placement is required
- Lighting uniformity significantly impacts results
- Reaction localization within wells affects measurement accuracy

---
## Software Dependencies

The imaging workflow was developed in Python and executed directly on a Raspberry Pi. The scripts use standard Python libraries and Raspberry Pi-compatible camera and hardware interfaces for image capture, ROI extraction, color analysis, and LED control.

### Required Python Libraries

- **NumPy**  
  Used for storing image arrays and calculating mean pixel intensity values from defined regions of interest (ROIs).

- **OpenCV (`cv2`)**  
  Used for image loading, ROI overlay generation, drawing circular/rectangular regions, and exporting annotated preview images.

- **time / datetime**  
  Used to control capture intervals and timestamp output files during time-series acquisition.

- **os / pathlib**  
  Used for file organization and automated output folder creation.

- **subprocess**  
  Used when calling Raspberry Pi camera utilities from within Python scripts.

### Camera Control

Image acquisition was performed using Raspberry Pi camera utilities compatible with the Arducam OV5647 camera module. Depending on the Raspberry Pi OS version, this may include:

- `libcamera`
- `rpicam-still`

The scripts were designed to capture images at fixed intervals under locked exposure and white balance settings.

### LED Control

The Modulino Pixels RGB LED module was controlled through I²C communication using the Qwiic/STEMMA QT interface. Relevant hardware interface libraries may include:

- `board`
- `busio`
- `smbus` / `smbus2`
- compatible CircuitPython or vendor-provided libraries for RGB LED control

### Output Files

The scripts generate:

- `.npy` files containing raw image array data
- `.png` files for visual inspection and ROI verification
- `.csv` files summarizing extracted RGB/grayscale values over time

### Notes

Exact package requirements may vary depending on Raspberry Pi OS version and camera configuration. Users should confirm camera functionality with `libcamera` or `rpicam-still` before running the time-series capture scripts.

---

## Author

Thomas Lau  
Fordham University — B.S. Environmental Science

## Project Context

Developed as part of a senior research project on microfluidic paper-based analytical devices (µPADs) for environmental sensing.

## Reccomendations For Future Work

- Improve ROI alignment automation  
- Integrate calibration curve generation  
- Expand to additional analytes beyond Zn²⁺  

