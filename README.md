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
