import os
import json
import platform
from PIL import Image, ImageGrab

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

def capture_region(geom: dict, path: str) -> bool:
    system = platform.system()
    try:
        if system == 'Linux':
            import mss
            with mss.mss() as sct:
                img = sct.grab({
                    'left': geom['x'], 'top': geom['y'],
                    'width': geom['w'], 'height': geom['h']
                })
                Image.frombytes('RGB', img.size, img.rgb).save(path)
        else:
            img = ImageGrab.grab(bbox=(geom['x'], geom['y'], geom['x'] + geom['w'], geom['y'] + geom['h']))
            img.save(path)
        return is_image_valid(path)
    except Exception:
        return False

# --- Platform-specific window info ---

def get_windows_linux():
    import subprocess
    try:
        out = subprocess.check_output(['wmctrl', '-lG'], stderr=subprocess.DEVNULL).decode('utf-8')
    except subprocess.CalledProcessError:
        return []
    wins = []
    for line in out.splitlines():
        parts = line.split(None, 7)
        if len(parts) < 8: continue
        win_id, desktop, x, y, w, h, _, title = parts
        wins.append({
            'id': win_id,
            'title': title,
            'geometry': {'x': int(x), 'y': int(y), 'w': int(w), 'h': int(h)},
            'desktop': desktop,
            'hidden': get_map_state_linux(win_id) != 'IsViewable'
        })
    return wins

def get_map_state_linux(win_id: str) -> str:
    import subprocess
    try:
        info = subprocess.check_output(['xwininfo', '-id', win_id], stderr=subprocess.DEVNULL).decode()
        for line in info.splitlines():
            if 'Map State:' in line:
                return line.split(':', 1)[1].strip()
    except subprocess.CalledProcessError:
        pass
    return 'Unknown'

def get_windows_macos():
    from Quartz import CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly, kCGNullWindowID
    wins = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
    out = []
    for w in wins:
        bounds = w.get("kCGWindowBounds", {})
        if not bounds or not w.get("kCGWindowName"): continue
        out.append({
            'id': str(w.get("kCGWindowNumber")),
            'title': w.get("kCGWindowName"),
            'geometry': {
                'x': int(bounds.get("X", 0)),
                'y': int(bounds.get("Y", 0)),
                'w': int(bounds.get("Width", 0)),
                'h': int(bounds.get("Height", 0))
            },
            'hidden': not w.get("kCGWindowIsOnscreen", True)
        })
    return out

def get_windows_windows():
    import pygetwindow as gw
    out = []
    for w in gw.getWindowsWithTitle(''):
        if not w.title or not w.isVisible: continue
        out.append({
            'id': str(w._hWnd),
            'title': w.title,
            'geometry': {'x': w.left, 'y': w.top, 'w': w.width, 'h': w.height},
            'hidden': not w.isActive
        })
    return out

# --- Main processing logic (unified) ---
def save_window_map():
    system = platform.system()
    if system == 'Linux':
        windows = get_windows_linux()
    elif system == 'Darwin':
        windows = get_windows_macos()
    elif system == 'Windows':
        windows = get_windows_windows()
    else:
        print(f"Unsupported platform: {system}")
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
            'geometry': w['geometry'],
            'hidden': w['hidden'],
            'screenshot': filename if success else None
        })
        print(f"Processed {w['id']} -> {filename if success else 'FAILED'}")

    json_path = os.path.join(out_dir, 'window_map.json')
    with open(json_path, 'w') as f:
        json.dump(entries, f, indent=2)
    print(f"Saved metadata to {json_path}")

if __name__ == "__main__":
    save_window_map()
