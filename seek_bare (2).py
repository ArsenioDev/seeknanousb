"""
Seek Thermal Nano300 - single frame capture to raw binary
"""
import time
import usb.core, usb.util, usb.backend.libusb1 as libusb1
import numpy as np

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
    return bytes(buf)

# prime — drain any stale data
print("Priming...")
for _ in range(3):
    ctrl_out(0x53, b'\x58\x5B\x01\x00')
    try: dev.read(EP_IN, 65536, 500)
    except: pass
time.sleep(0.2)

# ── capture single frame ──────────────────────────────────────────────────────
print("Capturing frame...")
raw_bytes = read_frame()
print(f"Captured {len(raw_bytes)} bytes")

# Save as raw binary
with open("frame_raw.bin", "wb") as f:
    f.write(raw_bytes)
print("Saved to frame_raw.bin")

# Also print some stats
arr = np.frombuffer(raw_bytes, dtype=np.uint16)
print(f"As uint16 array: {len(arr)} elements")
print(f"First 20 values: {arr[:20]}")
print(f"Last 20 values:  {arr[-20:]}")

usb.util.dispose_resources(dev)