"""Extract thermal frames from the reassembled Seek Nano300 bulk stream.

Frame layout (empirically derived from SeekStartup.pcapng):
  - Wire frame period: 88,920 bytes (= 26 transport chunks of 6,840 B)
  - Frame = 260 rows x 342 u16 words, little-endian
  - Row 0: header (magic 0x0579, frame counter, status word @w2, timestamp ms @w11)
  - Row 1: config/metadata
  - Rows 2..257: pixel data (cols 0..~323); row 3 fully dark (telemetry)
  - Col 325: per-row sync marker (0x70xx)
  - Rows 258..259: zero footer
  - Status: 3=image, 1=shutter calibration, 4=gain calibration
"""
import numpy as np
import os
import pickle

OUT_DIR = r"C:\Users\Arsenio\Downloads\ApkTool\SeekUSBDEBUG\analysis"

ROWS, COLS = 260, 342
TOP, BOT = 2, 258          # image row range [2,258)
LEFT, RIGHT = 0, 320       # image col range


def load_frames():
    b16 = np.fromfile(os.path.join(OUT_DIR, "bulk_stream.bin"), dtype="<u2")
    F = ROWS * COLS
    n = len(b16) // F
    frames = b16[: n * F].reshape(n, ROWS, COLS)
    return frames


def main():
    frames = load_frames()
    n = len(frames)
    magic_ok = int((frames[:, 0, 0] == 0x0579).sum())
    counters = frames[:, 0, 1]
    status = frames[:, 0, 2].astype(int)
    ts_ms = frames[:, 0, 11].astype(np.int64)

    print(f"frames: {n}, magic ok: {magic_ok}")
    types = {1: "shutter-cal", 3: "image", 4: "gain-cal"}
    print("status distribution:")
    for s in sorted(set(status.tolist())):
        print(f"  status {s:>2} ({types.get(s, 'startup/other')}): {(status == s).sum()}")

    img_idx = np.where(status == 3)[0]
    cal_idx = np.where(status == 1)[0]
    gain_idx = np.where(status == 4)[0]

    # ---- save raw arrays ----
    images_raw = frames[img_idx][:, TOP:BOT, LEFT:RIGHT].astype(np.int32)
    np.save(os.path.join(OUT_DIR, "images_raw.npy"), images_raw)
    meta = []
    for k in img_idx:
        meta.append(dict(frame=int(k), counter=int(counters[k]), ts_ms=int(ts_ms[k])))
    pickle.dump(meta, open(os.path.join(OUT_DIR, "image_meta.pkl"), "wb"))

    # ---- calibration processing (libseek-style) ----
    calib = None
    gain_frame = None
    if len(cal_idx):
        calib = frames[cal_idx[-1]][TOP:BOT, LEFT:RIGHT].astype(np.float64)
        print(f"\nusing shutter-cal frame #{cal_idx[-1]}")
    if len(gain_idx):
        gain_frame = frames[gain_idx[-1]][TOP:BOT, LEFT:RIGHT].astype(np.float64)
        gpos = gain_frame[gain_frame > 0]
        gain_mean = gpos.mean()
        print(f"using gain-cal frame #{gain_idx[-1]}, gain_mean={gain_mean:.1f}")

    processed = []
    for i, k in enumerate(img_idx):
        img = frames[k][TOP:BOT, LEFT:RIGHT].astype(np.float64)
        out = img.copy()
        if calib is not None:
            out = img - calib
            if gain_frame is not None:
                g = np.clip(gain_mean / np.maximum(gain_frame, 1), 1.0 / 3.0, 3.0)
                out *= g
            out += 0x2000  # level shift into unsigned display range
        processed.append(out)
    processed = np.array(processed)
    np.save(os.path.join(OUT_DIR, "images_processed.npy"), processed)

    print(f"saved images_raw.npy {images_raw.shape}, images_processed.npy {processed.shape}")

    p0 = processed[0]
    print(f"processed[0]: min={p0.min():.0f} max={p0.max():.0f} std={p0.std():.1f}")


if __name__ == "__main__":
    main()
