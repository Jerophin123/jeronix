#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Minimal read-only ISO 9660 + Rock Ridge reader (standard library only).

Used to inspect the Ubuntu source image and to cross-check the finished
JERONIX image independently of xorriso, which builds it.

    build/iso/isoread.py IMAGE ls [PATH]
    build/iso/isoread.py IMAGE cat PATH
"""

import struct
import sys

SECTOR = 2048


class IsoImage:
    def __init__(self, path):
        self.f = open(path, "rb")
        pvd = self._read(16 * SECTOR, SECTOR)
        if pvd[0] != 1 or pvd[1:6] != b"CD001":
            raise ValueError(f"{path}: no ISO 9660 primary volume descriptor")
        self.volume_id = pvd[40:72].decode("ascii", "replace").strip()
        self.root = self._record(pvd[156:190])

    def close(self):
        self.f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _read(self, offset, size):
        self.f.seek(offset)
        return self.f.read(size)

    def _record(self, raw):
        length, = struct.unpack_from("B", raw, 0)
        extent, = struct.unpack_from("<I", raw, 2)
        size, = struct.unpack_from("<I", raw, 10)
        flags = raw[25]
        name_len = raw[32]
        iso_name = raw[33:33 + name_len]
        su = raw[33 + name_len + (1 - name_len % 2):length]
        name = self._rock_ridge_name(su) or iso_name.decode("ascii", "replace").split(";")[0].rstrip(".")
        return {"name": name, "extent": extent, "size": size, "dir": bool(flags & 2),
                "multi": bool(flags & 0x80), "raw_name": iso_name}

    @staticmethod
    def _rock_ridge_name(su):
        parts, i = [], 0
        while i + 4 <= len(su):
            sig, length = su[i:i + 2], su[i + 2]
            if length < 4:
                break
            if sig == b"NM":
                parts.append(su[i + 5:i + length].decode("utf-8", "replace"))
            i += length
        return "".join(parts) or None

    def listdir(self, directory):
        data = self._read(directory["extent"] * SECTOR, directory["size"])
        entries, pos = [], 0
        while pos < len(data):
            length = data[pos]
            if length == 0:  # records never cross sectors
                pos = (pos // SECTOR + 1) * SECTOR
                continue
            rec = self._record(data[pos:pos + length])
            pos += length
            if rec["raw_name"] in (b"\x00", b"\x01"):
                continue
            if entries and entries[-1]["multi"] and entries[-1]["name"] == rec["name"]:
                entries[-1]["size"] += rec["size"]  # later extents of a >4 GiB file
                entries[-1]["multi"] = rec["multi"]
                continue
            entries.append(rec)
        return entries

    def lookup(self, path):
        node = self.root
        for part in [p for p in path.split("/") if p]:
            match = [e for e in self.listdir(node) if e["name"] == part]
            if not match:
                raise FileNotFoundError(path)
            node = match[0]
        return node

    def exists(self, path):
        try:
            self.lookup(path)
            return True
        except FileNotFoundError:
            return False

    def read(self, path):
        node = self.lookup(path)
        if node["dir"]:
            raise IsADirectoryError(path)
        return self._read(node["extent"] * SECTOR, node["size"])


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    with IsoImage(argv[1]) as iso:
        if argv[2] == "ls":
            for e in iso.listdir(iso.lookup(argv[3] if len(argv) > 3 else "/")):
                print(f"{'d' if e['dir'] else '-'} {e['size']:>12} {e['name']}")
        elif argv[2] == "cat":
            sys.stdout.buffer.write(iso.read(argv[3]))
        else:
            print(__doc__)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
