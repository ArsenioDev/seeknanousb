"""Full reassembly: control transfers (both directions) + bulk IN stream.

State machine over wire-level records. Outputs:
  ctrl.pkl  - list of control transfers with setup fields + data_in/data_out
  bulk.pkl  - concatenated bulk IN stream + offset/timestamp index
"""
import pickle
import os
import struct

OUT_DIR = r"C:\Users\Arsenio\Downloads\ApkTool\SeekUSBDEBUG\analysis"


def main():
    recs = pickle.load(open(os.path.join(OUT_DIR, "records.pkl"), "rb"))
    n = len(recs)
    print(f"{n} records")

    ctrl = []
    bulk_stream = bytearray()
    bulk_index = []          # (stream_offset, ts, rec_idx) at each data packet
    cur_bulk_start_ts = None
    last_bulk_end_ts = None
    bulk_bursts = []         # contiguous bursts (offset_start, offset_end, t_start, t_end)

    i = 0
    pending_setup = None     # dict while control transfer active
    expect = None            # 'setup_data' | 'data_in' | 'data_out' | 'status_out' | 'status_in'
    data_in = bytearray()
    data_out = bytearray()
    got_status_zlp = False

    def close_ctrl(ts):
        nonlocal pending_setup, data_in, data_out, expect, got_status_zlp
        if pending_setup is not None:
            ctrl.append(dict(idx=pending_setup["idx"], ts=pending_setup["ts"],
                             bm=pending_setup["bm"], br=pending_setup["br"],
                             wv=pending_setup["wv"], wi=pending_setup["wi"],
                             wl=pending_setup["wl"],
                             data_in=bytes(data_in[:pending_setup["wl"]] if pending_setup["wl"] else b""),
                             data_out=bytes(data_out),
                             status_zlp=got_status_zlp))
        pending_setup = None
        data_in = bytearray()
        data_out = bytearray()
        expect = None
        got_status_zlp = False

    def flush_bulk(ts):
        nonlocal bulk_bursts, cur_bulk_start_ts, last_bulk_end_ts
        pass

    while i < n:
        r = recs[i]
        p = r["pid"]

        if p == "SETUP":
            close_ctrl(r["ts"])
            d0 = None
            j = i + 1
            # find the DATA0 right after (skip nothing else should intervene)
            while j < n and recs[j]["pid"] == "DATA0":
                d0 = recs[j].get("data")
                break
            if d0 and len(d0) >= 8 and pending_setup is None:
                bm, br = d0[0], d0[1]
                wv, wi, wl = struct.unpack_from("<HHH", d0, 2)
                pending_setup = dict(idx=r["idx"], ts=r["ts"], bm=bm, br=br,
                                     wv=wv, wi=wi, wl=wl)
                expect = "stage"
                i = j + 1
                continue
            i += 1
            continue

        if p == "IN":
            # determine target: if bit7 of raw[1] set -> bulk IN (addr>=1); else control data stage
            tgt = r["raw"][1]
            if tgt & 0x80:
                # bulk IN poll
                j = i + 1
                if j < n and recs[j]["pid"] in ("DATA0", "DATA1") and "data" in recs[j]:
                    q = recs[j]
                    off = len(bulk_stream)
                    if cur_bulk_start_ts is None:
                        cur_bulk_start_ts = q["ts"]
                    bulk_stream += q["data"]
                    bulk_index.append((off, q["ts"], q["idx"], len(q["data"])))
                    last_bulk_end_ts = q["ts"]
                    i = j + 1
                    continue
                i += 1
                continue
            else:
                # control data stage IN
                j = i + 1
                while j < n and recs[j]["pid"] in ("DATA0", "DATA1"):
                    if "data" in recs[j]:
                        data_in += recs[j]["data"]
                    j += 1
                i = j
                continue

        if p == "OUT":
            j = i + 1
            while j < n and recs[j]["pid"] in ("DATA0", "DATA1"):
                if "data" in recs[j]:
                    data_out += recs[j]["data"]
                j += 1
            i = j
            continue

        if p == "ACK":
            # heuristic end-of-transfer: if we have setup + (in or out data complete) + zlp seen
            if pending_setup is not None:
                wl = pending_setup["wl"]
                done_in = wl > 0 and len(data_in) >= min(wl, 512) or (wl > 0 and 0 < len(data_in) < 512)
                done_out = wl == 0 and len(data_out) >= 0 and data_out is not None
                # detect status stage completion: an ACK following an OUT zlp when wl==0,
                # or ACK following OUT zlp after IN data when wl>0
                pass
            i += 1
            continue

        if p in ("STALL", "NYET"):
            i += 1
            continue

        i += 1

    close_ctrl(recs[-1]["ts"])

    print(f"control transfers: {len(ctrl)}")
    print(f"bulk stream: {len(bulk_stream):,} bytes in {len(bulk_index)} packets")

    # split bulk stream into bursts separated by idle gaps (>50ms without bulk data)
    bursts = []
    prev_end = None
    burst_start = None
    for k, (off, ts, idx, ln) in enumerate(bulk_index):
        if prev_end is not None and ts - prev_end > 0.05:
            bursts.append((burst_start, off, burst_ts, prev_end))
            burst_start = None
        if burst_start is None:
            burst_start = off
            burst_ts = ts
        prev_end = ts
        last_off = off + ln
    if burst_start is not None:
        bursts.append((burst_start, last_off, burst_ts, prev_end))
    print(f"\n{len(bursts)} bulk bursts:")
    for b0, b1, t0, t1 in bursts:
        print(f"  offset {b0:>10,}..{b1:>10,}  ({b1-b0:>10,} B)  t={t0:.3f}s..{t1:.3f}s")

    with open(os.path.join(OUT_DIR, "ctrl.pkl"), "wb") as f:
        pickle.dump(ctrl, f)
    with open(os.path.join(OUT_DIR, "bulk_stream.bin"), "wb") as f:
        f.write(bulk_stream)
    with open(os.path.join(OUT_DIR, "bulk_index.pkl"), "wb") as f:
        pickle.dump(bulk_index, f)
    with open(os.path.join(OUT_DIR, "bursts.pkl"), "wb") as f:
        pickle.dump(bursts, f)
    print("\nsaved ctrl.pkl, bulk_stream.bin, bulk_index.pkl, bursts.pkl")


if __name__ == "__main__":
    main()
