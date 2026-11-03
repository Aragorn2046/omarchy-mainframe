#!/usr/bin/env python3
"""Capture the real Mainframe UI with an isolated theme and fixture data."""
import struct
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import theme_manager

with tempfile.TemporaryDirectory(prefix='mainframe-theme-smoke-') as tmp:
    folder = Path(tmp)
    (folder / 'colors.toml').write_text('background = "#101820"\nforeground = "#f0e0c0"\naccent = "#00aaff"\n')
    output = folder / 'preview.png'
    theme_manager.render_theme(folder, output)
    data = output.read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    assert struct.unpack('>II', data[16:24]) == (1600, 1000)
    # The top-left window pixel is the forced theme background.
    chunks = []
    offset = 8
    while offset < len(data):
        length = struct.unpack('>I', data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        if kind == b'IDAT':
            chunks.append(data[offset + 8:offset + 8 + length])
        offset += 12 + length
    assert data[24] == 8 and data[25] in (2, 6) and data[28] == 0
    channels = 3 if data[25] == 2 else 4
    raw = zlib.decompress(b''.join(chunks))
    stride = 1600 * channels
    previous = bytearray(stride)
    different = sampled = 0
    for y in range(1000):
        offset = y * (stride + 1)
        mode = raw[offset]
        row = bytearray(raw[offset + 1:offset + 1 + stride])
        for i in range(stride):
            left = row[i - channels] if i >= channels else 0
            up = previous[i]
            upper_left = previous[i - channels] if i >= channels else 0
            if mode == 1: predictor = left
            elif mode == 2: predictor = up
            elif mode == 3: predictor = (left + up) // 2
            elif mode == 4:
                p = left + up - upper_left
                distances = (abs(p - left), abs(p - up), abs(p - upper_left))
                predictor = (left, up, upper_left)[distances.index(min(distances))]
            else:
                assert mode == 0
                predictor = 0
            row[i] = (row[i] + predictor) & 255
        if y == 0:
            assert row[:3] == bytes.fromhex('101820'), row[:3].hex()
        if 50 <= y < 950 and y % 5 == 0:
            for x in range(50, 1550, 5):
                pixel = row[x * channels:x * channels + 3]
                sampled += 1
                different += pixel != bytes.fromhex('101820')
        previous = row
    assert different >= sampled * .02, (different, sampled)
    print(f'theme preview: PNG 1600x1000, {different}/{sampled} sampled content pixels differ from background')
