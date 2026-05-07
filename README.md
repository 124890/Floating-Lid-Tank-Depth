# Floating-Lid-Tank-Depth

MV to determine inventory levels of oil based on MV analysis of tank shadows.

## Fill-level estimation script

This repository now includes `estimate_fill_level.py`, which estimates floating-roof tank fill percentage from:

1. A calibrated image
2. Tank geometry
3. Sun position (timestamp + GPS)
4. Shadow height on the inner tank wall

### Install

```bash
pip install -r requirements.txt
```

### Run

```bash
python estimate_fill_level.py \
  --image tank.jpg \
  --tank-height 22.0 \
  --tank-diameter 80.0 \
  --latitude 51.5074 \
  --longitude -0.1278 \
  --timestamp-utc 2026-05-07T14:30:00
```

Optional flags:

- `--pixels-per-metre` (default: `52.0`)
- `--output-image` to save an annotated result image
- `--no-display` for headless execution
