"""
Seek Thermal Nano300 - bare matplotlib viewer
Data is on EP 0x81 (Interface 0 iAP bulk IN), NOT EP 0x82.

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

# ── read frame ────────────────────────────────────────────────────────────────
def read_frame():
    ctrl_out(0x53, b'\x58\x5B\x01\x00')   # heartbeat triggers next frame
    buf = bytearray()
    for _ in range(200):
        try:
            chunk = dev.read(EP_IN, 1024, TIMEOUT)
            chunklen = len(chunk)
            #print(f'Read Chunk Length: {chunklen}')
            buf.extend(chunk)
            if len(chunk) < 512:
                break
        except usb.core.USBTimeoutError:
            break
    return np.frombuffer(bytes(buf), dtype=np.uint16).astype(np.float32)

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

axes[0].set_title("Full buffer", color='#aaa', fontsize=10)
axes[1].set_title("320x240 (calib stripped)", color='#aaa', fontsize=10)
info_txt = fig.text(0.5, 0.01, '', ha='center', color='#666', fontsize=8)

im0 = im1 = None
frame_n = [0]

def update(_):
    global im0, im1
    raw = read_frame()
    frame_n[0] += 1
    nbytes = int(len(raw) * 2)

    if len(raw) < 320:
        info_txt.set_text(f"frame #{frame_n[0]}  {nbytes} bytes (too small)")
        return

    n_rows = len(raw) // 320
    mat = raw[:n_rows * 320].reshape(n_rows, 320)

    # column FPN correction
    col_mean = mat.mean(axis=0)
    mat = mat + (col_mean.mean() - col_mean)

    # strip calibration rows (std < 50)
    row_std = mat.std(axis=1)
    img_mat = mat[row_std >= 50]
    if len(img_mat) > 240:
        img_mat = img_mat[:240]
    elif len(img_mat) == 0:
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
        f"frame #{frame_n[0]}  |  {nbytes} B  |  "
        f"full {320}x{n_rows}  |  crop {320}x{len(img_mat)}  |  "
        f"range {int(mat.min())}-{int(mat.max())}  mean {int(mat.mean())}"
    )
    return im0, im1, info_txt

ani = animation.FuncAnimation(
    fig, update, interval=100, blit=False, cache_frame_data=False
)
plt.tight_layout(rect=[0, 0.04, 1, 1])
plt.show()
usb.util.dispose_resources(dev)
