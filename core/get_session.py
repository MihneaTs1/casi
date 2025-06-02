#!/usr/bin/env python3
"""
Cross-platform window info and screenshot utility with contextual metadata.
Captures visible (uncovered) windows, takes screenshots, and saves a JSON that includes:
- snapshot_info (timestamp, platform, hostname, active window title, mouse position)
- details of each visible window (id, title, owner, geometry, uncovered regions, screenshot filename)
"""

import os
import json
import platform
import datetime
import socket
from PIL import Image

def sanitize_filename(s: str) -> str:
    safe = ''.join(c for c in s if c.isalnum() or c in (' ', '_', '-')).rstrip()
    return safe.replace(' ', '_')[:50]

def is_image_valid(path: str) -> bool:
    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:
        return False

def rect_intersect(a, b):
    x1 = max(a['x'], b['x'])
    y1 = max(a['y'], b['y'])
    x2 = min(a['x'] + a['w'], b['x'] + b['w'])
    y2 = min(a['y'] + a['h'], b['y'] + b['h'])
    if x1 < x2 and y1 < y2:
        return {'x': x1, 'y': y1, 'w': x2 - x1, 'h': y2 - y1}
    return None

def rect_subtract(rect, covered):
    remaining = [rect]
    for c in covered:
        new_remaining = []
        for r in remaining:
            inter = rect_intersect(r, c)
            if not inter:
                new_remaining.append(r)
                continue
            x0, y0 = r['x'], r['y']
            x1, y1 = x0 + r['w'], y0 + r['h']
            ix0, iy0 = inter['x'], inter['y']
            ix1, iy1 = ix0 + inter['w'], iy0 + inter['h']
            # Top strip
            if iy0 > y0:
                new_remaining.append({
                    'x': x0,
                    'y': y0,
                    'w': r['w'],
                    'h': iy0 - y0
                })
            # Bottom strip
            if iy1 < y1:
                new_remaining.append({
                    'x': x0,
                    'y': iy1,
                    'w': r['w'],
                    'h': y1 - iy1
                })
            # Left strip
            if ix0 > x0:
                new_remaining.append({
                    'x': x0,
                    'y': max(y0, iy0),
                    'w': ix0 - x0,
                    'h': min(y1, iy1) - max(y0, iy0)
                })
            # Right strip
            if ix1 < x1:
                new_remaining.append({
                    'x': ix1,
                    'y': max(y0, iy0),
                    'w': x1 - ix1,
                    'h': min(y1, iy1) - max(y0, iy0)
                })
        remaining = [r for r in new_remaining if r['w'] > 0 and r['h'] > 0]
    return remaining

def capture_region(geom: dict, path: str) -> bool:
    system = platform.system()
    try:
        if system in ('Darwin', 'Windows'):
            from PIL import ImageGrab
            img = ImageGrab.grab(bbox=(
                geom['x'],
                geom['y'],
                geom['x'] + geom['w'],
                geom['y'] + geom['h']
            ))
            img.save(path)
        elif system == 'Linux':
            import mss
            with mss.mss() as sct:
                img = sct.grab({
                    'left': geom['x'],
                    'top': geom['y'],
                    'width': geom['w'],
                    'height': geom['h']
                })
                Image.frombytes('RGB', img.size, img.rgb).save(path)
        else:
            print(f"[WARN] Unsupported platform for screenshots: {system}")
            return False
        return is_image_valid(path)
    except Exception as e:
        print(f"[ERROR] Screenshot failed for region {geom}: {e}")
        return False

def get_mouse_position():
    system = platform.system()
    try:
        if system == 'Darwin':
            import Quartz
            loc = Quartz.NSEvent.mouseLocation()
            # Quartz’s origin is bottom-left; invert y for some frameworks if needed.
            return {'x': int(loc.x), 'y': int(loc.y)}
        elif system == 'Linux':
            # On Linux, use Xlib if installed (requires python-xlib)
            from Xlib import display
            data = display.Display().screen().root.query_pointer()._data
            return {'x': data['root_x'], 'y': data['root_y']}
        elif system == 'Windows':
            import ctypes
            pt = ctypes.wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            return {'x': pt.x, 'y': pt.y}
    except Exception:
        pass
    return None

def get_active_window_title():
    system = platform.system()
    try:
        if system == 'Darwin':
            from AppKit import NSWorkspace
            return NSWorkspace.sharedWorkspace().frontmostApplication().localizedName()
        elif system == 'Linux':
            import subprocess
            # Requires xprop and xdotool installed
            win_id = subprocess.check_output(['xdotool', 'getactivewindow']).decode().strip()
            title = subprocess.check_output(['xdotool', 'getwindowname', win_id]).decode().strip()
            return title
        elif system == 'Windows':
            import ctypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            return buff.value
    except Exception:
        pass
    return None

def get_visible_windows_macos():
    try:
        import Quartz
        kCGWindowListOptionOnScreenOnly = 1
        kCGWindowListExcludeDesktopElements = 16
        kCGNullWindowID = 0
        wins = Quartz.CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements,
            kCGNullWindowID
        )
    except Exception:
        print("[ERROR] Quartz not available or unsupported macOS version.")
        return []

    covered = []
    visible_windows = []
    for w in wins:
        bounds = w.get("kCGWindowBounds", {})
        if not bounds or not w.get("kCGWindowName") or not w.get("kCGWindowIsOnscreen", True):
            continue
        geom = {
            'x': int(bounds.get("X", 0)),
            'y': int(bounds.get("Y", 0)),
            'w': int(bounds.get("Width", 0)),
            'h': int(bounds.get("Height", 0))
        }
        if geom['w'] <= 1 or geom['h'] <= 1:
            continue
        uncovered = rect_subtract(geom, covered)
        if uncovered:
            visible_windows.append({
                'id': str(w.get("kCGWindowNumber")),
                'title': w.get("kCGWindowName"),
                'geometry': geom,
                'uncovered_regions': uncovered,
                'owner': w.get("kCGWindowOwnerName", "")
            })
            covered.append(geom)
    return visible_windows

def get_visible_windows_linux():
    """Linux implementation using wmctrl + xwininfo (requires wmctrl, xwininfo)."""
    try:
        import subprocess

        # List all windows
        lines = subprocess.check_output(['wmctrl', '-lG']).decode().splitlines()
    except Exception:
        print("[ERROR] wmctrl not available or failed.")
        return []

    covered = []
    visible_windows = []
    for line in lines:
        parts = line.split(None, 6)
        if len(parts) < 7:
            continue
        win_id, desktop, x, y, w, h, title = parts
        try:
            geom = {
                'x': int(x),
                'y': int(y),
                'w': int(w),
                'h': int(h)
            }
        except ValueError:
            continue
        if geom['w'] <= 1 or geom['h'] <= 1 or title.strip() == "":
            continue

        uncovered = rect_subtract(geom, covered)
        if uncovered:
            visible_windows.append({
                'id': win_id,
                'title': title,
                'geometry': geom,
                'uncovered_regions': uncovered,
                'owner': None
            })
            covered.append(geom)

    return visible_windows

def get_visible_windows_windows():
    """Windows implementation using pygetwindow (requires pygetwindow)."""
    try:
        import pygetwindow as gw
    except ImportError:
        print("[ERROR] pygetwindow not installed.")
        return []

    covered = []
    visible_windows = []
    for w in gw.getAllWindows():
        if not w.isVisible or w.width <= 1 or w.height <= 1:
            continue
        geom = {'x': w.left, 'y': w.top, 'w': w.width, 'h': w.height}
        uncovered = rect_subtract(geom, covered)
        if uncovered:
            visible_windows.append({
                'id': str(w._hWnd),
                'title': w.title or '',
                'geometry': geom,
                'uncovered_regions': uncovered,
                'owner': None
            })
            covered.append(geom)
    return visible_windows

def get_visible_windows():
    system = platform.system()
    if system == 'Darwin':
        return get_visible_windows_macos()
    elif system == 'Linux':
        return get_visible_windows_linux()
    elif system == 'Windows':
        return get_visible_windows_windows()
    else:
        print(f"[WARN] Visible-window detection not implemented for {system}.")
        return []

def save_window_map():
    windows = get_visible_windows()
    if not windows:
        print("[INFO] No visible windows found or failed to retrieve window info.")
        return

    out_dir = "window_map"
    os.makedirs(out_dir, exist_ok=True)
    entries = []

    for w in windows:
        title_sn = sanitize_filename(w['title']) or 'no_title'
        filename = f"{w['id']}_{title_sn}.png"
        path = os.path.join(out_dir, filename)
        success = capture_region(w['geometry'], path)
        entries.append({
            'id': w['id'],
            'title': w['title'],
            'owner': w.get('owner', ''),
            'geometry': w['geometry'],
            'uncovered_regions': w['uncovered_regions'],
            'screenshot': filename if success else None
        })

    snapshot_info = {
        'timestamp': datetime.datetime.now().isoformat(),
        'platform': platform.platform(),
        'hostname': socket.gethostname(),
        'active_window': get_active_window_title(),
        'mouse_position': get_mouse_position()
    }

    metadata = {
        'snapshot_info': snapshot_info,
        'windows': entries
    }

    json_path = os.path.join(out_dir, 'window_map.json')
    with open(json_path, 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f"[INFO] Saved window map and context to {json_path}")

if __name__ == "__main__":
    save_window_map()
