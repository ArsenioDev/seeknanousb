"""
Seek Thermal Nano300 - FINAL WORKING VERSION
Key insight: Remove ALL zero-value pixels before reshaping to 320-wide

SOLUTION:
- Zeros are packet boundaries/invalid data, not bad pixels to interpolate
- Remove all zeros from stream, then reshape to 320 columns
- Results in clean thermal image with speckle but no horizontal stripes

pip install pyusb libusb numpy matplotlib
"""
import time
import usb.core, usb.util, usb.backend.libusb1 as libusb1
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation

VID, PID  = 0x289D, 0x0011
EP_IN     = 0x81
TIMEOUT   = 2000

# ── open ──────────────────────────────────────────────────────────────────────
be  = libusb1.get_backend()
dev = usb.core.find(idVendor=VID, idProduct=PID, backend=be)
assert dev, "Device not found"
print(f"Found: {dev.product}")

try: dev.set_configuration()
except: pass

try: dev.set_interface_altsetting(interface=0, alternate_setting=0)
except: pass

def ctrl_out(cmd, data):
    dev.ctrl_transfer(0x40, cmd, 0, 0, data, TIMEOUT)

def ctrl_in(cmd, length):
    try: return bytes(dev.ctrl_transfer(0xC0, cmd, 0, 0, length, TIMEOUT))
    except: return b''

# ── init ──────────────────────────────────────────────────────────────────────
print("Init...")
ctrl_out(0x54, b'\x00\x00')
ctrl_out(0x3C, b'\x00\x00')
ctrl_in (0x3D, 2)
ctrl_out(0x3E, b'\x08\x00')
ctrl_out(0x56, b'\x08\x00\x02\x06\x00\x00')
fw = ctrl_in(0x58, 16)
print(f"FW: {fw.rstrip(b'x00')}")
ctrl_in (0x4E, 4)
ctrl_in (0x36, 12)
ctrl_out(0x55, b'\x17\x00')
ctrl_in (0x4E, 64)
ctrl_in (0x36, 12)
ctrl_out(0x37, b'\xFC\x00\x04\x00')
ctrl_out(0x3C, b'\x01\x00')
ctrl_in (0x35, 4)
ctrl_out(0x55, b'\x15\x00')
ctrl_in (0x4E, 64)
print("Init done")

def read_frame():
    """Read and process frame.

    Key insight: Zeros are packet boundaries/padding, not bad pixels.
    Remove ALL zeros before reshaping to get clean thermal data.
    """
    ctrl_out(0x53, b'\x58\x5B\x01\x00')
    buf = bytearray()
    for _ in range(200):
        try:
            chunk = dev.read(EP_IN, 1024, TIMEOUT)
            buf.extend(chunk)
            if len(chunk) < 512:
                break
        except usb.core.USBTimeoutError:
            break

    raw_bytes = bytes(buf)
    if len(raw_bytes) < 1000:
        return np.array([]).reshape(0, 320)

    # Parse as uint16
    arr = np.frombuffer(raw_bytes, dtype=np.uint16).astype(np.float32)

    # Remove ALL zeros (packet boundaries/padding)
    arr_clean = arr[arr != 0]

    # Reshape to 320 columns
    complete_rows = len(arr_clean) // 320
    if complete_rows == 0:
        return np.array([]).reshape(0, 320)

    mat = arr_clean[:complete_rows * 320].reshape(complete_rows, 320)

    # Column FPN (Fixed Pattern Noise) correction
    col_mean = mat.mean(axis=0)
    mat = mat - col_mean + col_mean.mean()

    return mat

# prime — drain any stale data
print("Priming...")
for _ in range(3):
    ctrl_out(0x53, b'\x58\x5B\x01\x00')
    try: dev.read(EP_IN, 65536, 500)
    except: pass
time.sleep(0.2)

# ── figure ────────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(13, 5))
fig.patch.set_facecolor('#111')
for ax in axes:
    ax.set_facecolor('#111')
    ax.set_xticks([]); ax.set_yticks([])

axes[0].set_title("Full frame (zeros removed)", color='#aaa', fontsize=10)
axes[1].set_title("240 rows (cropped)", color='#aaa', fontsize=10)
info_txt = fig.text(0.5, 0.01, '', ha='center', color='#666', fontsize=8)

im0 = im1 = None
frame_n = [0]

def update(_):
    global im0, im1
    mat = read_frame()
    frame_n[0] += 1

    if mat.size == 0 or mat.shape[0] < 10:
        info_txt.set_text(f"frame #{frame_n[0]} - too small/empty")
        return

    n_rows, n_cols = mat.shape

    # Crop to 240 rows if we have more
    if len(mat) > 240:
        # Take center 240 rows
        start_row = (len(mat) - 240) // 2
        img_mat = mat[start_row:start_row+240]
    else:
        img_mat = mat

    def norm(m):
        lo, hi = np.percentile(m, 1), np.percentile(m, 99)
        return np.clip((m - lo) / max(hi - lo, 1), 0, 1)

    n_full = norm(mat)
    n_crop = norm(img_mat)

    if im0 is None:
        im0 = axes[0].imshow(n_full, cmap='inferno', vmin=0, vmax=1,
                              aspect='auto', interpolation='nearest')
        im1 = axes[1].imshow(n_crop, cmap='inferno', vmin=0, vmax=1,
                              aspect='auto', interpolation='nearest')
    else:
        im0.set_data(n_full)
        im1.set_data(n_crop)

    info_txt.set_text(
        f"frame #{frame_n[0]}  |  "
        f"full {n_cols}x{n_rows}  |  crop {n_cols}x{len(img_mat)}  |  "
        f"range {int(mat.min())}-{int(mat.max())}  mean {int(mat.mean())}"
    )
    return im0, im1, info_txt

ani = animation.FuncAnimation(
    fig, update, interval=100, blit=False, cache_frame_data=False
)
plt.tight_layout(rect=[0, 0.04, 1, 1])
plt.show()
usb.util.dispose_resources(dev)
