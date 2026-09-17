"""Exercise the native dashboard and save a window-only visual QA capture."""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import tkinter as tk
from PIL import Image
import ctypes
from ctypes import wintypes
import pixel_window
from pixel_window import PixelWindow, demo_dashboard

root = tk.Tk()
names_dir = tempfile.TemporaryDirectory()
app = PixelWindow(root, '', '', demo=True,
                  names_path=str(Path(names_dir.name) / 'monitor.names.json'))
root.geometry('1488x1058+0+0')
root.update()


def capture():
    app.canvas.update()
    target = Path(__file__).resolve().parents[1] / 'ui-preview' / 'pixel-dashboard-qa.png'
    c = app.canvas
    user = ctypes.windll.user32
    gdi = ctypes.windll.gdi32
    user.GetDC.restype = ctypes.c_void_p
    gdi.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    gdi.CreateCompatibleBitmap.restype = ctypes.c_void_p
    gdi.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi.SelectObject.restype = ctypes.c_void_p
    user.PrintWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.UINT]
    class Header(ctypes.Structure):
        _fields_ = [('size',wintypes.DWORD),('width',wintypes.LONG),('height',wintypes.LONG),
                    ('planes',wintypes.WORD),('bits',wintypes.WORD),('compression',wintypes.DWORD),
                    ('image_size',wintypes.DWORD),('xppm',wintypes.LONG),('yppm',wintypes.LONG),
                    ('used',wintypes.DWORD),('important',wintypes.DWORD)]
    handle=user.GetParent(root.winfo_id())
    bounds=wintypes.RECT();user.GetWindowRect(handle,ctypes.byref(bounds))
    width,height=bounds.right-bounds.left,bounds.bottom-bounds.top
    dc=user.GetDC(handle);mem=gdi.CreateCompatibleDC(dc)
    bitmap=gdi.CreateCompatibleBitmap(dc,width,height);old=gdi.SelectObject(mem,bitmap)
    assert user.PrintWindow(handle,mem,2), 'PrintWindow failed'
    header=Header(ctypes.sizeof(Header),width,-height,1,32,0,0,0,0,0,0)
    buffer=ctypes.create_string_buffer(width*height*4)
    gdi.GetDIBits.argtypes=[ctypes.c_void_p,ctypes.c_void_p,wintypes.UINT,wintypes.UINT,ctypes.c_void_p,ctypes.c_void_p,wintypes.UINT]
    gdi.SelectObject(mem,old)
    assert gdi.GetDIBits(mem,bitmap,0,height,buffer,ctypes.byref(header),0)
    captured=Image.frombuffer('RGB',(width,height),buffer,'raw','BGRX',0,1)
    captured.save(target)
    gdi.DeleteObject.argtypes=[ctypes.c_void_p];gdi.DeleteDC.argtypes=[ctypes.c_void_p]
    user.ReleaseDC.argtypes=[wintypes.HWND,ctypes.c_void_p]
    gdi.DeleteObject(bitmap);gdi.DeleteDC(mem);user.ReleaseDC(handle,dc)
    app.move_selection(1)
    assert app.selected == 'experiment-b'
    for count in (0, 1, 8, 32):
        app.state = demo_dashboard(count, 0, 'auto')
        app.draw()
        assert len(app.state['hardware']['gpus']) == count
    assert len(app.mentor_frames) == 16, 'Missing mentor source frames'
    assert len(app.stir_frames) == 4, 'Missing main stirring strip frames'
    assert 'fan' not in app.action_groups, 'Fan action is still mapped into the mentor sequence'
    assert 'ladle' not in app.action_groups, 'Fourth sample action is still mapped into the mentor sequence'
    assert len(app.mentor_action_sequence) == 12, 'Mentor runtime should contain three four-frame stages'
    assert set(app.mentor_action_sequence).issubset(set(range(12))), 'Fourth action frames are still reachable'
    assert pixel_window.MENTOR_FRAME_HOLD == 4, 'Mentor action pacing is too fast'
    active_cells = [app.mentor_frames[index] for index in set(app.mentor_action_sequence)]
    assert all(cell.size == (384, 512) for cell in active_cells), 'Mentor cells lost the fixed canvas size'
    active_boxes = [cell.getchannel('A').getbbox() for cell in active_cells]
    assert all(box for box in active_boxes), 'Mentor action cell is empty'
    assert len({(box[0], box[2], box[3]) for box in active_boxes}) == 1, 'Mentor/cauldron baseline is not stable'
    stir_boxes = [cell.getchannel('A').getbbox() for cell in app.stir_frames]
    assert all(stir_boxes), 'Main stirring frame is empty'
    assert len({(box[1], box[3]) for box in stir_boxes}) == 1, 'Main stirring frame height/baseline is not stable'
    assert len(app.assistant_frames) == 16, 'Missing unique apprentice frames'
    assert len({frame.tobytes() for frame in app.assistant_frames}) == 16, 'Apprentice cells contain duplicates'
    app.state = demo_dashboard(8, 0, 'training')
    assistant_keys = set()
    assistant_ids = set()
    for frame in (0, 3):
        app.frame = frame
        app.draw()
        for key, _, _ in app.cache:
            key = str(key)
            if key.startswith('assistant:'):
                assistant_keys.add(key)
                assistant_ids.add(key.split(':')[1])
    assert len(assistant_ids) == 8, 'GPU cards did not receive unique apprentices'
    assert len(assistant_keys) >= 16, 'Apprentice animation did not expose both frames'
    app.state = demo_dashboard(2, 0, 'finished')
    app.selected = 'experiment-a'
    app.draw()
    assert any(item[-1] == 'experiment-a' for item in app.dismiss_hitboxes), 'Finished run has no red dismiss control'
    original_askstring = pixel_window.simpledialog.askstring
    pixel_window.simpledialog.askstring = lambda *args, **kwargs: 'unit1'
    app.rename_selected()
    pixel_window.simpledialog.askstring = original_askstring
    assert app.display_name({'run_id': 'experiment-a'}) == 'unit1', 'Rename did not update display label'
    assert app.name_aliases.path.is_file(), 'Rename file was not persisted'
    app.dismiss_run('experiment-a')
    assert app.name_aliases.is_dismissed('experiment-a'), 'Dismissal was not persisted'
    assert all(run.get('run_id') != 'experiment-a' for run in app.visible_runs()), 'Dismissed run is still visible'
    app.state = demo_dashboard(1, 0, 'training')
    app.draw()
    assert not app.name_aliases.is_dismissed('experiment-a'), 'Reused active run ID did not restore'
    app.state = demo_dashboard(1, 0, 'training')
    app.cache.clear()
    keys = set()
    for frame in range(0, 4 * pixel_window.MAIN_STIR_FRAME_HOLD, pixel_window.MAIN_STIR_FRAME_HOLD):
        app.frame = frame
        app.draw()
        keys.update(k[0] for k in app.cache if str(k[0]).startswith('stir:'))
    expected_keys = {'stir:' + str(index) for index in range(4)}
    assert keys == expected_keys, 'Main stirring animation did not expose all four frames'
    app.state = demo_dashboard(4, 0, 'stopped')
    app.error = 'OFFLINE'
    app.draw()
    print('Pixel window verified: selection, 0/1/8/32 GPUs, stopped and offline; screenshot:', target)
    app.close()


root.after(1200, capture)
root.mainloop()
names_dir.cleanup()
