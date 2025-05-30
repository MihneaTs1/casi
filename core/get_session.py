import os
import argparse
import subprocess
import json
import mss


def get_windows():
    """
    Returns list of windows with id, desktop, x, y, w, h, title via wmctrl -lG.
    Requires wmctrl installed.
    """
    try:
        out = subprocess.check_output(['wmctrl', '-lG'], stderr=subprocess.DEVNULL).decode('utf-8')
    except subprocess.CalledProcessError as e:
        print(f"Error running wmctrl: {e}")
        return []
    windows = []
    for line in out.splitlines():
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        win_id = parts[0]
        desktop = parts[1]
        x, y, w, h = map(int, parts[2:6])
        title = parts[7]
        windows.append({
            'id': win_id,
            'desktop': desktop,
            'x': x,
            'y': y,
            'w': w,
            'h': h,
            'title': title
        })
    return windows


def get_map_state(win_id: str) -> str:
    """
    Returns the map state of a window via xwininfo: 'IsViewable' or other.
    Requires xwininfo installed.
    """
    try:
        info = subprocess.check_output(['xwininfo', '-id', win_id], stderr=subprocess.DEVNULL).decode('utf-8')
        for line in info.splitlines():
            if 'Map State:' in line:
                return line.split(':', 1)[1].strip()
    except subprocess.CalledProcessError:
        pass
    return 'Unknown'


def sanitize_filename(s: str) -> str:
    """Safe filename component."""
    safe = ''.join(c for c in s if c.isalnum() or c in (' ', '_', '-')).rstrip()
    return safe.replace(' ', '_')[:50]


from PIL import Image

def is_image_valid(path: str) -> bool:
    """Checks if an image file is valid (non-corrupt)."""
    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:
        return False


def capture_region(geom: dict, save_path: str) -> bool:
    """Fallback: captures visible region via mss"""
    try:
        import mss
        img = mss.mss().grab({
            'left': geom['x'], 'top': geom['y'],
            'width': geom['w'], 'height': geom['h']
        })
        Image.frombytes('RGB', img.size, img.rgb).save(save_path)
        return True
    except Exception:
        return False


def capture_window(win_id: str, save_path: str, geom: dict) -> bool:
    """
    Attempts to capture a window pixmap via xwd. Falls back to screen grab if corrupt.
    """
    from subprocess import Popen
    try:
        xwd = Popen(['xwd', '-silent', '-id', win_id], stdout=subprocess.PIPE)
        with open(save_path, 'wb') as out:
            conv = Popen(['magick', 'xwd:-', 'png:-'], stdin=xwd.stdout, stdout=out)
            if xwd.stdout is not None:
                xwd.stdout.close()
            conv.communicate()
        if conv.returncode == 0 and is_image_valid(save_path):
            return True
    except Exception:
        pass
    # fallback to visible region capture
    print(f"Falling back to visible-grab for window {win_id}")
    return capture_region(geom, save_path)


def save_window_map():
    out_dir = "window_map"
    os.makedirs(out_dir, exist_ok=True)

    # Enumerate windows
    windows = get_windows()
    if not windows:
        print('No windows found. Ensure wmctrl is installed.')
        return

    # Determine full-screen size
    with mss.mss() as sct:
        mon = sct.monitors[1]
        screen_w, screen_h = mon['width'], mon['height']

    # Filter out full-desktop and root windows
    filtered = []
    for w in windows:
        title = w['title'] or ''
        if not title.strip() or title.lower() in ('desktop', 'root'):
            continue
        if w['w'] == screen_w and w['h'] == screen_h:
            continue
        filtered.append(w)
    windows = filtered

    window_entries = []
    for w in windows:
        map_state = get_map_state(w['id'])
        hidden = (map_state != 'IsViewable')
        title_sn = sanitize_filename(w['title']) or 'no_title'
        filename = f"{w['id']}_{title_sn}.png"
        path = os.path.join(out_dir, filename)
        success = capture_window(w['id'], path, w)
        entry = {
            'id': w['id'],
            'title': w['title'],
            'desktop': w['desktop'],
            'geometry': {'x': w['x'], 'y': w['y'], 'w': w['w'], 'h': w['h']},
            'map_state': map_state,
            'hidden': hidden,
            'screenshot': filename if success else None
        }
        window_entries.append(entry)
        print(f"Processed {w['id']} ({'hidden' if hidden else 'visible'}) -> {entry['screenshot']}")

    # Save JSON
    json_path = os.path.join(out_dir, 'window_map.json')
    with open(json_path, 'w') as jf:
        json.dump(window_entries, jf, indent=2)
    print(f"Saved JSON map to {json_path}")