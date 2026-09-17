"""Capture the already-running native pixel dashboard window on Windows."""
import ctypes
from ctypes import byref, create_string_buffer, windll
from ctypes import wintypes
from pathlib import Path

from PIL import Image


class BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BitmapInfo(ctypes.Structure):
    _fields_ = [("bmiHeader", BitmapInfoHeader), ("bmiColors", wintypes.DWORD * 3)]


window = windll.user32.FindWindowW(None, "TRAINING MONITOR · 像素炼丹台")
if not window:
    raise SystemExit("running pixel window was not found")
bounds = wintypes.RECT()
windll.user32.GetWindowRect(window, byref(bounds))
width, height = bounds.right - bounds.left, bounds.bottom - bounds.top
dc = windll.user32.GetDC(window)
mem = windll.gdi32.CreateCompatibleDC(dc)
bitmap = windll.gdi32.CreateCompatibleBitmap(dc, width, height)
old = windll.gdi32.SelectObject(mem, bitmap)
if not windll.user32.PrintWindow(window, mem, 2):
    raise SystemExit("PrintWindow failed")

header = BitmapInfo()
header.bmiHeader.biSize = 40
header.bmiHeader.biWidth = width
header.bmiHeader.biHeight = -height
header.bmiHeader.biPlanes = 1
header.bmiHeader.biBitCount = 32
header.bmiHeader.biCompression = 0
buffer = create_string_buffer(width * height * 4)
windll.gdi32.GetDIBits(mem, bitmap, 0, height, buffer, byref(header), 0)
target = Path(__file__).resolve().parents[1] / "ui-preview" / "pixel-dashboard-live.png"
Image.frombuffer("RGB", (width, height), buffer, "raw", "BGRX", 0, 1).save(target)
windll.gdi32.SelectObject(mem, old)
windll.gdi32.DeleteObject(bitmap)
windll.gdi32.DeleteDC(mem)
windll.user32.ReleaseDC(window, dc)
print(target)
