"""Draw the staff app's icons (step 12h): a white "M" on the app's navy, with
a green band. Plain Python, no image libraries:

    python frontend/scripts/make-icons.py

writes frontend/public/icons/icon-{180,192,512}.png. The letter stays inside
the middle 60%, so Android's round and squircle masks ("maskable") don't cut it.
"""

import math
import struct
import zlib
from pathlib import Path

NAVY = (0x13, 0x28, 0x3A)
GREEN = (0x2F, 0x7A, 0x55)
WHITE = (0xFF, 0xFF, 0xFF)
OUT = Path(__file__).resolve().parent.parent / "public" / "icons"

# The "M" as four strokes, in a 0..1 square: down, in, out, down.
STROKES = [((0.28, 0.70), (0.28, 0.30)), ((0.28, 0.30), (0.50, 0.56)), ((0.50, 0.56), (0.72, 0.30)), ((0.72, 0.30), (0.72, 0.70))]
WIDTH = 0.085  # half the stroke width


def _distance(px, py, a, b):
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _colour(x, y):
    if min(_distance(x, y, a, b) for a, b in STROKES) <= WIDTH:
        return WHITE
    return GREEN if 0.78 <= y <= 0.84 and 0.28 - WIDTH <= x <= 0.72 + WIDTH else NAVY


def render(size: int, samples: int = 3) -> bytes:
    rows = []
    for j in range(size):
        row = bytearray([0])  # PNG filter type 0 for this row
        for i in range(size):
            total = [0, 0, 0]
            for sj in range(samples):  # several samples per pixel: smooth edges
                for si in range(samples):
                    c = _colour((i + (si + 0.5) / samples) / size, (j + (sj + 0.5) / samples) / size)
                    total = [t + v for t, v in zip(total, c)]
            row += bytes(round(t / samples**2) for t in total)
        rows.append(bytes(row))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b"")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (180, 192, 512):
        (OUT / f"icon-{size}.png").write_bytes(render(size))
        print(f"wrote {OUT / f'icon-{size}.png'}")
