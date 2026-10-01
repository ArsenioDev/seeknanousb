"""Reassemble control transfers + decode vendor requests against libseek Request enum."""
import pickle
import os
import struct
from collections import Counter

OUT_DIR = r"C:\Users\Arsenio\Downloads\ApkTool\SeekUSBDEBUG\analysis"

REQ_NAMES = {
    53: "GET_ERROR_CODE", 54: "READ_CHIP_ID", 55: "TOGGLE_SHUTTER",
    56: "SET_SHUTTER_POLARITY", 57: "GET_SHUTTER_POLARITY", 58: "SET_BIT_DATA_OFFSET",
    59: "GET_BIT_DATA", 60: "SET_OPERATION_MODE", 61: "GET_OPERATION_MODE",
    62: "SET_IMAGE_PROCESSING_MODE", 63: "GET_IMAGE_PROCESSING_MODE",
    64: "SET_DATA_PAGE", 65: "GET_DATA_PAGE", 66: "SET_CURRENT_COMMAND_ARRAY_SIZE",
    67: "SET_CURRENT_COMMAND_ARRAY", 68: "GET_CURRENT_COMMAND_ARRAY",
    69: "SET_DEFAULT_COMMAND_ARRAY_SIZE", 70: "SET_DEFAULT_COMMAND_ARRAY",
    71: "GET_DEFAULT_COMMAND_ARRAY", 72: "SET_VDAC_ARRAY_OFFSET_AND_ITEMS",
    73: "SET_VDAC_ARRAY", 74: "GET_VDAC_ARRAY", 75: "SET_RDAC_ARRAY_OFFSET_AND_ITEMS",
    76: "SET_RDAC_ARRAY", 77: "GET_RDAC_ARRAY", 78: "GET_FIRMWARE_INFO",
    79: "UPLOAD_FIRMWARE_ROW_SIZE", 80: "WRITE_MEMORY_DATA",
    81: "COMPLETE_MEMORY_WRITE", 82: "BEGIN_MEMORY_WRITE", 83: "START_GET_IMAGE_TRANSFER",
    84: "TARGET_PLATFORM", 85: "SET_FIRMWARE_INFO_FEATURES",
    86: "SET_FACTORY_SETTINGS_FEATURES", 87: "SET_FACTORY_SETTINGS",
    88: "GET_FACTORY_SETTINGS", 89: "RESET_DEVICE",
}
STD_REQ = {0: "GET_STATUS", 1: "CLEAR_FEATURE", 3: "SET_FEATURE", 5: "SET_ADDRESS",
           6: "GET_DESCRIPTOR", 7: "SET_DESCRIPTOR", 8: "GET_CONFIGURATION",
           9: "SET_CONFIGURATION", 10: "GET_INTERFACE", 11: "SET_INTERFACE"}


def crc5(data_bits):
    """USB CRC5 over list of bits (LSB-first per field)."""
    reg = 0x1F
    for b in data_bits:
        inv = b ^ (reg & 1)
        reg >>= 1
        if inv:
            reg ^= 0x14  # x^5+x^2+1 taps (bit-reversed form)
    return (~reg) & 0x1F


def check_crc5():
    """Determine b2 layout: candidates (crc<<3)|ep etc. for (addr,ep) pairs."""
    def bits(v, n):
        return [(v >> i) & 1 for i in range(n)]
    obs = {(0, 0): 0x10, (1, 0): 0xE8, (1, 1): 0x58}
    for addr, ep in obs:
        b = bits(addr, 11) + bits(ep, 4)
        c = crc5(b)
        print(f"addr={addr} ep={ep}: computed CRC5={c:#04x} ({c:05b}), observed b2={obs[(addr,ep)]:#04x} ({obs[(addr,ep)]:08b})")


def load_records():
    return pickle.load(open(os.path.join(OUT_DIR, "records.pkl"), "rb"))


def assemble(recs):
    """Walk packets; yield logical events."""
    events = []
    i = 0
    n = len(recs)
    cur_ctrl = None      # dict being built
    bulk_buf = bytearray()
    bulk_start_ts = None
    bulk_events = []     # (start_idx, end_idx, ts_start, ts_end, nbytes)

    def flush_bulk():
        nonlocal bulk_buf, bulk_start_ts
        if bulk_buf:
            bulk_events.append(dict(start_i=bulk_start_ts, data=bytes(bulk_buf)))
            bulk_buf = bytearray()

    last_sof_frame = None
    sof_first = None
    while i < n:
        r = recs[i]
        p = r["pid"]
        if p == "SOF":
            if sof_first is None:
                sof_first = r["ts"]
            last_sof_frame = struct.unpack("<H", r["raw"][1:3])[0] & 0x7FF
            i += 1
            continue
        if p == "SETUP":
            # find DATA0 next
            j = i + 1
            setup_data = None
            while j < n and recs[j]["pid"] != "SETUP":
                q = recs[j]
                if q["pid"] == "DATA0" and "data" in q:
                    setup_data = q["data"]
                    break
                j += 1
            if setup_data and len(setup_data) >= 8:
                bm, br = setup_data[0], setup_data[1]
                wv, wi, wl = struct.unpack_from("<HHH", setup_data, 2)
                # collect following IN data until short packet or new SETUP
                k = j + 1
                in_data = bytearray()
                status_seen = False
                while k < n:
                    q = recs[k]
                    if q["pid"] == "SETUP":
                        break
                    if q["pid"] in ("DATA0", "DATA1") and "data" in q and q is not recs[j]:
                        # only IN-direction data (after the IN token); crude: take all data until OUT-zlp status
                        in_data += q["data"]
                        if len(q["data"]) < 512:  # short packet ends data stage
                            pass
                    if q["pid"] == "OUT":
                        status_seen = True
                        break
                    if q["pid"] == "ACK" and in_data and len(in_data) >= wl and wl > 0:
                        break
                    k += 1
                ev = dict(idx=r["idx"], ts=r["ts"], bm=bm, br=br, wv=wv, wi=wi,
                          wl=wl, data=bytes(in_data[:wl]) if wl else b"",
                          raw_setup=setup_data)
                events.append(ev)
                i = k if k > i else i + 1
                continue
            i += 1
            continue
        if p == "IN" and (r["raw"][1] & 0x80):
            # bulk IN poll: gather subsequent DATA payload
            j = i + 1
            got = bytearray()
            while j < n and recs[j]["pid"] in ("DATA0", "DATA1"):
                q = recs[j]
                if "data" in q:
                    got += q["data"]
                j += 1
                break
            if got:
                flush_bulk()
            i += 1
            continue
        i += 1

    return events


def main():
    print("=== CRC5 layout verification ===")
    check_crc5()

    recs = load_records()
    events = assemble(recs)
    print(f"\n=== {len(events)} control transfers ===")
    t0 = events[0]["ts"] if events else 0
    for e in events:
        dt = e["ts"] - t0
        d = e["data"]
        ds = d.hex() if len(d) <= 32 else d[:32].hex() + f"...({len(d)}B)"
        if e["bm"] & 0x80:
            name = REQ_NAMES.get(e["br"], STD_REQ.get(e["br"], f"?{e['br']}"))
            kind = "IN "
        else:
            name = REQ_NAMES.get(e["br"], STD_REQ.get(e["br"], f"?{e['br']}"))
            kind = "OUT"
        extra = ""
        if e["br"] == 6:
            dv = e["wv"] >> 8
            dtypes = {1: "DEVICE", 2: "CONFIG", 3: "STRING", 4: "IFACE", 5: "ENDPOINT", 6:"DEVICE_QUAL", 0xF:"OS2"}
            extra = f" desc={dtypes.get(dv, dv)} str_idx={e['wv'] & 0xFF} lang={e['wi']:#06x}"
        print(f"[{dt:9.6f}s] #{e['idx']:>8d} {kind} bm={e['bm']:#04x} req={name:<26s} wV={e['wv']:#06x} wI={e['wi']:#06x} wL={e['wl']:>3d} -> [{ds}]{extra}")

    with open(os.path.join(OUT_DIR, "ctrl_events.pkl"), "wb") as f:
        pickle.dump(events, f)


if __name__ == "__main__":
    main()
