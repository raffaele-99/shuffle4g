#!/usr/bin/env python3
"""
iPod Shuffle (4th gen) volume detection + safety guardrails (macOS)

This script:
  - Detects an iPod Shuffle via USB (pyusb) connect/disconnect
  - Finds the mounted volume under /Volumes
  - Validates that the mounted disk is actually associated with the iPod's IOUSBHostDevice node
  - Enforces guardrails so you don't accidentally act on the wrong path/disk

REQUIRED (watch mode):
  pip install pyusb
  (and libusb installed, e.g. brew install libusb)

USAGE:
  python shufflewatch.py watch -v
  python shufflewatch.py validate /Volumes/IPOD -v

IMPORTANT SAFETY NOTES (for your larger app):
  1) Disk-level (destructive) operations MUST ONLY target the disk identifier returned by
     resolve_ipod_from_path(...).whole_disk (aka `safe_disk` from enforce_guardrails()).
     Never pass through a disk identifier or device path the user typed.

     Example: use /dev/{safe_disk} (e.g. /dev/disk4), NOT user-supplied "/dev/diskX".

  2) File writes MUST NOT trust the raw user path. Always:
       - validate user_path with resolve_ipod_from_path()
       - enforce_guardrails(user_path, binding)
       - build destinations under the returned mountpoint (`safe_mount`)

     Do NOT do: open(user_path + "/Music/foo.mp3", "wb")
     Do:        dst = safe_join_under_mount(safe_mount, "Music/foo.mp3")

  3) Even after validation, keep a hard deny on disk0 (and ideally log/confirm diskutil summary)
     before any erase/format code path.
"""
from __future__ import annotations

import argparse
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

DEFAULT_VID = 0x05AC
DEFAULT_PID = 0x1303

RE_KV = {
    "idVendor": re.compile(r'^\s*[\|\s]*"idVendor"\s*=\s*(0x[0-9a-fA-F]+|\d+)\s*$', re.M),
    "idProduct": re.compile(r'^\s*[\|\s]*"idProduct"\s*=\s*(0x[0-9a-fA-F]+|\d+)\s*$', re.M),
    "USB Serial Number": re.compile(r'^\s*[\|\s]*"USB Serial Number"\s*=\s*"([^"]+)"\s*$', re.M),
    "kUSBSerialNumberString": re.compile(r'^\s*[\|\s]*"kUSBSerialNumberString"\s*=\s*"([^"]+)"\s*$', re.M),
    "locationID": re.compile(r'^\s*[\|\s]*"locationID"\s*=\s*(0x[0-9a-fA-F]+|\d+)\s*$', re.M),
}

RE_IOREG_NODE_LINE = re.compile(r"^\s*[\|\s]*[+\-]?-?o\s+(.+?)\s+<class\s+IOUSBHostDevice\b", re.M)


def _run(cmd: List[str], verbose: bool) -> str:
    if verbose:
        print(f"[run] {' '.join(cmd)}")
    out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
    if verbose:
        print(f"[ok ] bytes={len(out.encode('utf-8'))}")
    return out


def _require_tool(name: str, verbose: bool) -> None:
    ok = shutil.which(name) is not None
    if verbose:
        print(f"[chk] tool {name}: {'OK' if ok else 'MISSING'}")
    if not ok:
        raise RuntimeError(f"Required tool not found in PATH: {name}")


def _df_device_and_mount(path: str, verbose: bool) -> Tuple[str, str]:
    out = _run(["df", "-P", path], verbose).strip().splitlines()
    if len(out) < 2:
        raise RuntimeError("df returned unexpected output")
    parts = out[1].split()
    if len(parts) < 6:
        raise RuntimeError("df returned unexpected output")
    device = parts[0]
    mountpoint = parts[-1]
    if verbose:
        print(f"[df ] device={device} mountpoint={mountpoint}")
    return device, mountpoint


def _diskutil_info_plist(target: str, verbose: bool) -> Dict:
    raw = _run(["diskutil", "info", "-plist", target], verbose)
    return plistlib.loads(raw.encode("utf-8"))


def _to_int(tok: str) -> int:
    tok = tok.strip()
    return int(tok, 16) if tok.lower().startswith("0x") else int(tok, 10)


def _ioreg_dump_node(node_name: str, verbose: bool) -> str:
    return _run(["ioreg", "-w0", "-r", "-n", node_name, "-l"], verbose)


def _ioreg_list_iopod_nodes(verbose: bool) -> List[str]:
    """
    Find IOUSBHostDevice nodes with names containing 'iPod@' by scanning ioreg output.
    This avoids hub noise.
    """
    out = _run(["ioreg", "-w0", "-r", "-c", "IOUSBHostDevice"], verbose=False)
    nodes = []
    for m in RE_IOREG_NODE_LINE.finditer(out):
        name = m.group(1).strip()
        if "ipod@" in name.lower():
            nodes.append(name)
    if verbose:
        print(f"[ioreg] iPod-like IOUSBHostDevice nodes={len(nodes)}")
        for n in nodes:
            print(f"  - {n!r}")
    return nodes


def _subtree_contains_bsd(ioreg_dump: str, bsd_candidates: List[str]) -> bool:
    for bsd in bsd_candidates:
        if f"\"BSD Name\" = \"{bsd}\"" in ioreg_dump:
            return True
    return False


@dataclass(frozen=True)
class IpodBinding:
    mountpoint: str
    fs_device: str
    fs_identifier: str
    whole_disk: str
    usb_obj_name: str
    usb_vid: Optional[int]
    usb_pid: Optional[int]
    usb_location_id: Optional[int]
    usb_serial: Optional[str]


# ----------------------- Guardrails (NEW) -----------------------

def _real(p: str) -> str:
    return os.path.realpath(os.path.expanduser(p))


def enforce_guardrails(user_path: str, binding: IpodBinding) -> Tuple[str, str]:
    """
    Guardrails:
      1) Only ever target binding.whole_disk for disk-level operations
      2) Ensure user_path is within binding.mountpoint (or equal)
    Returns (safe_mountpoint, safe_whole_disk) or raises ValueError.
    """
    safe_mount = _real(binding.mountpoint)
    safe_disk = binding.whole_disk  # <-- ONLY disk you should operate on

    up = _real(user_path)
    if up != safe_mount and not up.startswith(safe_mount + os.sep):
        raise ValueError(f"path {up!r} is not within iPod mountpoint {safe_mount!r}")

    if safe_disk == "disk0":
        raise ValueError("refusing to target disk0")

    return safe_mount, safe_disk


def safe_join_under_mount(mountpoint: str, relpath: str) -> str:
    """
    Build a destination path under mountpoint safely.
    Rejects absolute paths and path traversal.
    """
    if os.path.isabs(relpath):
        raise ValueError("relative path required (got absolute path)")
    base = _real(mountpoint)
    dst = _real(os.path.join(base, relpath))
    if dst != base and not dst.startswith(base + os.sep):
        raise ValueError("refusing path traversal outside mountpoint")
    return dst


# ----------------------- Core resolver -----------------------

def resolve_ipod_from_path(
    user_path: str,
    *,
    expect_vid: int = DEFAULT_VID,
    expect_pid: int = DEFAULT_PID,
    verbose: bool = False,
) -> IpodBinding:
    if sys.platform != "darwin":
        raise RuntimeError("macOS only")

    for t in ("df", "diskutil", "ioreg"):
        _require_tool(t, verbose)

    p = _real(user_path)
    if verbose:
        print(f"[chk] input={user_path!r}")
        print(f"[chk] resolved={p!r}")
    if not os.path.exists(p):
        raise ValueError(f"path does not exist: {p}")

    fs_device, mountpoint = _df_device_and_mount(p, verbose)
    info = _diskutil_info_plist(fs_device, verbose)

    fs_identifier = str(info.get("DeviceIdentifier") or os.path.basename(fs_device))
    whole_disk = str(info.get("ParentWholeDisk") or fs_identifier.split("s", 1)[0])
    if verbose:
        print(f"[chk] fs_identifier={fs_identifier} whole_disk={whole_disk}")

    # Safety checks (already present)
    if info.get("Internal") is True:
        raise ValueError("refusing: target disk is marked Internal")
    if info.get("RemovableMedia") is False:
        raise ValueError("refusing: target disk is not marked RemovableMedia")
    if info.get("Ejectable") is False:
        raise ValueError("refusing: target disk is not marked Ejectable")
    bus_proto = str(info.get("BusProtocol") or info.get("Protocol") or "")
    if bus_proto and "usb" not in bus_proto.lower():
        raise ValueError(f"refusing: bus/protocol is not USB (got {bus_proto!r})")
    if whole_disk == "disk0":
        raise ValueError("refusing: whole disk is disk0")

    bsd_candidates = [fs_identifier, whole_disk]

    ipod_nodes = _ioreg_list_iopod_nodes(verbose=verbose)
    if not ipod_nodes:
        raise ValueError("no IOUSBHostDevice named like iPod@... found in ioreg")

    bound_any = False
    reasons: List[str] = []

    for node in ipod_nodes:
        dump = _ioreg_dump_node(node, verbose=False)

        if not _subtree_contains_bsd(dump, bsd_candidates):
            if verbose:
                print(f"[bind] {node!r} does NOT reference BSD Name in {bsd_candidates}")
            reasons.append(f"{node!r}: subtree did not reference {bsd_candidates}")
            continue

        bound_any = True

        vid_m = RE_KV["idVendor"].search(dump)
        pid_m = RE_KV["idProduct"].search(dump)
        vid = _to_int(vid_m.group(1)) if vid_m else None
        pid = _to_int(pid_m.group(1)) if pid_m else None

        loc_m = RE_KV["locationID"].search(dump)
        loc = _to_int(loc_m.group(1)) if loc_m else None

        ser = None
        for k in ("USB Serial Number", "kUSBSerialNumberString"):
            m = RE_KV[k].search(dump)
            if m:
                ser = m.group(1)
                break

        if verbose:
            v = f"0x{vid:04X}" if vid is not None else "?"
            p_ = f"0x{pid:04X}" if pid is not None else "?"
            print(f"[bind] {node!r} references {bsd_candidates}  vid={v} pid={p_}")

        if vid == expect_vid and pid == expect_pid:
            return IpodBinding(
                mountpoint=mountpoint,
                fs_device=fs_device,
                fs_identifier=fs_identifier,
                whole_disk=whole_disk,
                usb_obj_name=node,
                usb_vid=vid,
                usb_pid=pid,
                usb_location_id=loc,
                usb_serial=ser,
            )

        reasons.append(
            f"{node!r}: bound to disk but VID/PID was "
            f"{('0x%04X' % vid) if vid is not None else '?'} / {('0x%04X' % pid) if pid is not None else '?'}"
        )

    if bound_any:
        raise ValueError(
            f"disk {bsd_candidates} is referenced by iPod node(s) but none matched expected "
            f"VID=0x{expect_vid:04X} PID=0x{expect_pid:04X}. Details: " + "; ".join(reasons)
        )

    raise ValueError(
        f"found iPod node(s) {ipod_nodes} but none referenced BSD Name in {bsd_candidates}. "
        "Volume may not be mounted yet."
    )


# ----------------------- Watcher -----------------------

def watch_ipod_and_print_mount(
    *,
    vid: int,
    pid: int,
    interval: float,
    mount_timeout: float,
    mount_poll: float,
    verbose: bool,
) -> None:
    import usb.core  # pip install pyusb

    def is_connected() -> bool:
        return usb.core.find(idVendor=vid, idProduct=pid) is not None

    prev: Optional[bool] = None
    while True:
        cur = is_connected()
        if prev is None:
            prev = cur
            if verbose:
                print(f"[usb] initial: {'connected' if cur else 'not connected'}")
        elif cur != prev:
            if cur:
                print("iPod detected!")
                deadline = time.time() + mount_timeout
                last_err: Optional[str] = None
                first_verbose = True

                while time.time() < deadline:
                    try:
                        entries = os.listdir("/Volumes")
                    except FileNotFoundError:
                        entries = []

                    for entry in sorted(entries):
                        mp = os.path.join("/Volumes", entry)
                        if not os.path.isdir(mp) or not os.path.ismount(mp):
                            continue
                        try:
                            b = resolve_ipod_from_path(
                                mp,
                                expect_vid=vid,
                                expect_pid=pid,
                                verbose=(verbose and first_verbose),
                            )
                            # Guardrail #1/#2 enforced here (even though we're passing mp)
                            safe_mount, safe_disk = enforce_guardrails(mp, b)

                            print(f"iPod volume: {safe_mount}")
                            if verbose:
                                print(f"[safe] whole_disk={safe_disk} usb_node={b.usb_obj_name!r}")
                            break
                        except ValueError as ve:
                            last_err = str(ve)
                            continue
                    else:
                        first_verbose = False
                        time.sleep(mount_poll)
                        continue

                    break
                else:
                    print(f"iPod detected, but no bound volume found. Last reason: {last_err or 'unknown'}")
            else:
                print("iPod removed!")
            prev = cur

        time.sleep(interval)


# ----------------------- CLI -----------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vid", type=lambda s: int(s, 0), default=DEFAULT_VID)
    ap.add_argument("--pid", type=lambda s: int(s, 0), default=DEFAULT_PID)

    sub = ap.add_subparsers(dest="cmd", required=True)

    p_val = sub.add_parser("validate")
    p_val.add_argument("path")
    p_val.add_argument("-v", "--verbose", action="store_true")

    p_watch = sub.add_parser("watch")
    p_watch.add_argument("-v", "--verbose", action="store_true")
    p_watch.add_argument("--interval", type=float, default=0.5)
    p_watch.add_argument("--mount-timeout", type=float, default=10.0)
    p_watch.add_argument("--mount-poll", type=float, default=0.5)

    args = ap.parse_args()

    try:
        if args.cmd == "validate":
            b = resolve_ipod_from_path(args.path, expect_vid=args.vid, expect_pid=args.pid, verbose=args.verbose)

            # NEW: enforce guardrails for the user-provided path
            safe_mount, safe_disk = enforce_guardrails(args.path, b)

            # Keep existing behavior: print mountpoint
            print(safe_mount)
            if args.verbose:
                print(f"[safe] whole_disk={safe_disk} usb_node={b.usb_obj_name!r}")
            return 0

        if args.cmd == "watch":
            watch_ipod_and_print_mount(
                vid=args.vid,
                pid=args.pid,
                interval=args.interval,
                mount_timeout=args.mount_timeout,
                mount_poll=args.mount_poll,
                verbose=args.verbose,
            )
            return 0

        return 2
    except ValueError as e:
        print(f"NO: {e}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        msg = (e.output or "").strip()
        print(f"error: command failed: {msg if msg else e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
