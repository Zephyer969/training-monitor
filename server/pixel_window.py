"""Reference-led pixel dashboard rendered with native Tk canvas widgets."""
import math
import queue
import sys
import threading
import time
import ctypes
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from PIL import Image, ImageDraw, ImageEnhance, ImageOps, ImageTk
import alchemy_assets
from console_ui import (MonitorClient, effective_runs, format_number, format_eta,
                        gpu_slot_rows, phase_for, progress_percent, metric_value)
from desktop_ui import station_models, demo_state, mentor_phase, ACTIVE
from local_gateway import is_loopback_bind
from pixel_assets import remove_checkerboard
from metric_series import series, latest_metric, best_metric
from run_aliases import RunAliasStore

BG = '#020f18'
BORDER = '#287da0'
TEXT = '#9ed6ff'
DIM = '#648097'
COLORS = {'training': '#ffcb57', 'validating': '#9283ff', 'saving': '#51caff',
          'finished': '#26edb0', 'error': '#ff557d', 'stalled': '#ff557d',
          'idle': '#71839d', 'paused': '#71839d', 'stopped': '#71839d', 'preparing': '#ffcb57'}
LABELS = {'training': 'TRAINING', 'validating': 'VALID', 'saving': 'SAVE',
          'finished': 'DONE', 'error': 'ERROR', 'stalled': 'STALE',
          'idle': 'IDLE', 'paused': 'PAUSED', 'stopped': 'STOPPED', 'preparing': 'PREPARE'}
DISMISSIBLE = {'finished', 'stopped', 'error'}
MENTOR_FRAME_HOLD = 4
MAIN_STIR_FRAME_HOLD = 5
ZOOM_MIN = 0.65
ZOOM_MAX = 2.0


def style_native_window(root):
    """Tint the Windows caption so the native frame follows the pixel palette."""

    if sys.platform != 'win32':
        return
    try:
        root.update_idletasks()
        hwnd = root.winfo_id()
        dwm = ctypes.windll.dwmapi
        set_attribute = dwm.DwmSetWindowAttribute
        set_attribute.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                  ctypes.c_void_p, ctypes.c_int]
        set_attribute.restype = ctypes.c_long
        # DWM COLORREF values are 0x00BBGGRR rather than #RRGGBB.
        caption = ctypes.c_int(0x00180F02)  # #020f18
        text = ctypes.c_int(0x00FFD69E)     # #9ed6ff
        border = ctypes.c_int(0x00A07D28)   # #287da0
        dark_mode = ctypes.c_int(1)
        for attribute, value in ((35, caption), (36, text), (34, border), (20, dark_mode)):
            set_attribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value))
    except (AttributeError, OSError, TypeError, ctypes.ArgumentError):
        # Tk remains fully usable on older Windows versions or non-Windows hosts.
        return


def clean_sprite(image):
    """Keep already-transparent assets fast while cleaning legacy RGB sheets."""

    rgba = image.convert('RGBA')
    if rgba.getchannel('A').getextrema()[0] == 0:
        return rgba
    return remove_checkerboard(rgba)


def demo_dashboard(count, tick, phase):
    state = demo_state(count, tick, phase)
    runs = []
    for i in range(count):
        p = (['training', 'validating', 'saving', 'idle'][i % 4]
             if phase == 'auto' else phase)
        epoch = [12, 4, 9, 1][i % 4]
        history = [{'epoch': n, 'loss': round(0.95 * math.exp(-n / 7) + .045 +
                    .006 * math.sin(n * 2 + i), 4), 'metric_name': 'mIoU', 'iou': round(.68 * (1 - math.exp(-n / 13)), 4)}
                   for n in range(1, 51)]
        runs.append({'run_id': 'experiment-' + (chr(97+i) if i < 26 else str(i+1)),
                     'status': p if p in {'idle','finished','error','stopped','paused'} else 'training',
                     'phase': p, 'epoch': epoch, 'total_epochs': 50 if i == 0 else 25,
                     'step': [3840,80,950,12][i % 4], 'total_steps': [4096,200,1000,100][i % 4],
                     'loss': [.087,.287,.154,1.246][i % 4], 'current_iou': [.672,.691,.612,.321][i % 4],
                     'metric_name': 'mIoU', 'history': history, 'eta_seconds': 2537,
                     'gpu_ids': [str(i)], 'updated_at': datetime.now().isoformat()})
    state['runs'] = runs
    for i,gpu in enumerate(state['hardware']['gpus']):
        gpu.update(utilization_percent=[78,72,46,8][i % 4], temperature_c=63-i % 5,
                   power_w=312-i % 4*45, memory_used_mib=[15974,14438,8909,2150][i % 4])
    return state


def step_progress(run):
    try:
        if float(run.get('total_steps') or 0) > 0:
            return max(0, min(100, float(run.get('step') or 0) / float(run['total_steps']) * 100))
    except (ValueError, TypeError):
        pass
    return progress_percent(run)


def prioritize_runs(runs):
    """Keep live work at the top while preserving order within each group."""

    def bucket(run):
        phase = phase_for(run)
        if phase in ACTIVE:
            return 0
        if phase in {'stalled', 'paused'}:
            return 1
        if phase in DISMISSIBLE:
            return 2
        return 1

    return [run for _, run in sorted(
        enumerate(runs), key=lambda item: (bucket(item[1]), item[0])
    )]


def normalize_animation_frames(frames):
    """Give every action frame one common visible height and bottom baseline."""

    boxes = [frame.getchannel('A').getbbox() for frame in frames]
    valid = [box for box in boxes if box is not None]
    if not valid:
        return list(frames)
    target_height = max(box[3] - box[1] for box in valid)
    normalized = []
    for frame, box in zip(frames, boxes):
        if box is None:
            normalized.append(frame)
            continue
        artwork = frame.crop(box)
        scale = target_height / artwork.height
        if artwork.width * scale > frame.width - 8:
            scale = (frame.width - 8) / artwork.width
        artwork = artwork.resize(
            (max(1, round(artwork.width * scale)), max(1, round(artwork.height * scale))),
            Image.Resampling.NEAREST,
        )
        fitted = Image.new('RGBA', frame.size, (0, 0, 0, 0))
        fitted.alpha_composite(
            artwork,
            ((frame.width - artwork.width) // 2, frame.height - artwork.height - 4),
        )
        normalized.append(fitted)
    return normalized


def assistant_identity(slot_index, pair_count):
    """Return a stable apprentice identity and overflow variant for one GPU card."""

    if pair_count <= 0:
        return 0, 0
    slot = max(0, int(slot_index))
    return slot % pair_count, slot // pair_count


class PixelWindow:
    def __init__(self, root, url, token, demo=False, gpu_count=4, interval=2,
                 client=None, names_path=None):
        self.root, self.demo = root, demo
        self.state, self.error, self.selected = {}, '', None
        self.events, self.stop = queue.Queue(maxsize=1), threading.Event()
        self.client, self.interval = client or MonitorClient(url, token), max(.5, interval)
        self.frame, self.last_received = 0, None
        self.first_draw = True
        self.gpu_count = tk.IntVar(value=gpu_count)
        self.demo_phase = tk.StringVar(value='auto')
        self.cache, self.images = {}, []
        self.name_aliases = RunAliasStore(names_path)
        self.local_gateway = None
        self.local_gateway_error = ''
        self.cloudflare_tunnel = None
        self.cloudflare_tunnel_error = ''
        self.scale = 1
        self.zoom = 1.0
        self.zoom_label = None
        self.borderless = False
        self.window_maximized = False
        self.restore_geometry = None
        root.title('炼丹台 · TRAINING MONITOR')
        root.geometry('1488x1058')
        root.minsize(950,680)
        root.configure(bg=BG)
        root.protocol('WM_DELETE_WINDOW', self.close)
        if sys.platform == 'win32':
            try:
                # Remove the light Windows caption.  The client-side chrome
                # below becomes the only title bar and follows the dashboard.
                style_native_window(root)
                root.overrideredirect(True)
                self.borderless = True
            except tk.TclError:
                self.borderless = False
        self.window_icon = self.make_window_icon()
        try:
            root.iconphoto(True, self.window_icon)
        except tk.TclError:
            pass

        # Client-side pixel chrome keeps the visual language consistent while
        # leaving the native frame available for reliable resize/maximize.
        chrome = tk.Frame(root, bg='#061923', height=32,
                          highlightthickness=1, highlightbackground='#153b4c')
        chrome.pack(fill='x')
        chrome.pack_propagate(False)
        self.pixel_icon(chrome, 'monitor', '#48e5fa', 3).pack(side='left', padx=(10, 5), pady=5)
        tk.Label(chrome, text='炼丹台  //  TRAINING MONITOR_', bg='#061923', fg=TEXT,
                 font=('Consolas', 10, 'bold')).pack(side='left', pady=5)
        tk.Label(chrome, text='PIXEL WORKSPACE', bg='#061923', fg=DIM,
                 font=('Consolas', 9)).pack(side='right', padx=12, pady=6)
        self.chrome_button(chrome, '×', self.close, '#ff557d')
        self.chrome_button(chrome, '□', self.toggle_maximize, '#9ed6ff')
        self.chrome_button(chrome, '—', self.minimize_window, '#9ed6ff')
        self.bind_chrome_drag(chrome)

        toolbar = tk.Frame(root,bg=BG, height=34)
        toolbar.pack(fill='x')
        toolbar.pack_propagate(False)
        self.status = tk.Label(toolbar, text='DEMO / 模拟数据' if demo else '连接中…',fg=TEXT,bg=BG)
        self.status.pack(side='left',padx=(8, 10))
        self.zoom_label = tk.Label(toolbar, text='ZOOM 100%', fg=DIM, bg=BG,
                                   font=('Consolas', 9))
        self.zoom_label.pack(side='left', padx=8)
        if demo:
            tk.Label(toolbar,text='GPUs',bg=BG,fg=TEXT).pack(side='left',padx=6)
            tk.Spinbox(toolbar,from_=0,to=32,width=3,textvariable=self.gpu_count,
                       bg=BG,fg=TEXT,buttonbackground='#132e40').pack(side='left')
            combo=ttk.Combobox(toolbar,textvariable=self.demo_phase,state='readonly',width=12,
                               values=['auto','training','validating','saving','finished','paused','stopped','error'])
            combo.pack(side='left',padx=10)
        self.rename_button=self.toolbar_button(toolbar, 'rename', 'F2 / 重命名',
                                               self.rename_selected, '#ffd77c')
        self.phone_button=self.toolbar_button(toolbar, 'phone', '手机同步',
                                              self.show_local_sync, '#48e5fa')
        tk.Label(toolbar,text='红色 ×：清除已结束任务',bg=BG,fg='#ff557d').pack(side='right',padx=(0,10))
        scroll=ttk.Scrollbar(root,orient='vertical')
        scroll.pack(side='right',fill='y')
        self.canvas=tk.Canvas(root,bg=BG,highlightthickness=0,yscrollcommand=scroll.set)
        self.canvas.pack(fill='both',expand=True)
        scroll.configure(command=self.canvas.yview)
        self.canvas.bind('<Control-MouseWheel>', self.zoom_with_ctrl)
        self.canvas.bind('<MouseWheel>',lambda e:self.canvas.yview_scroll(-int(e.delta/120),'units'))
        self.canvas.bind('<Configure>',lambda e:self.draw())
        self.canvas.bind('<Button-1>',self.click)
        self.canvas.bind('<KeyPress-Down>',lambda e:self.move_selection(1))
        self.canvas.bind('<KeyPress-Up>',lambda e:self.move_selection(-1))
        self.canvas.focus_set()
        root.bind('<F2>',lambda e:self.rename_selected())
        root.bind('<Control-KeyPress-0>', lambda e: self.set_zoom(1.0))
        root.bind('<Control-KeyPress-equal>', lambda e: self.set_zoom(self.zoom + 0.1))
        root.bind('<Control-KeyPress-minus>', lambda e: self.set_zoom(self.zoom - 0.1))
        assets=Path(alchemy_assets.__file__).parent
        self.atlas=Image.open(assets/'alchemy-rooms.png').convert('RGB')
        # Background-key only at display time: face pixels and the bundled source stay unchanged.
        self.mentor=clean_sprite(Image.open(assets/'mentor-approved.png'))
        self.mentor_frames=[]
        coherent_action_file=assets/'mentor-actions-v7-coherent-no-fan.png'
        if coherent_action_file.exists():
            action_sheets=((coherent_action_file,4,4),)
            self.coherent_actions=True
        else:
            # Backward-compatible fallback for an older installed asset bundle.
            # The fan sheet is intentionally not part of the fallback sequence.
            action_sheets=((assets/'mentor-actions-v5-large-cauldron.png',4,2),)
            self.coherent_actions=False
        for action_file, columns, rows in action_sheets:
            if not action_file.exists():
                continue
            with Image.open(action_file) as source_sheet:
                sheet=source_sheet.convert('RGBA')
                for row in range(rows):
                    for col in range(columns):
                        cell=sheet.crop((col*sheet.width//columns,row*sheet.height//rows,
                                         (col+1)*sheet.width//columns,(row+1)*sheet.height//rows))
                        self.mentor_frames.append(clean_sprite(cell))
        # The main training loop has its own four-frame strip so the rod
        # visibly travels across the whole cauldron.  Normalize the strip once
        # at load time so no frame can appear larger or smaller at runtime.
        self.stir_frames=[]
        main_stir_file=assets/'mentor-stir-main-v1.png'
        if main_stir_file.exists():
            with Image.open(main_stir_file) as source_strip:
                strip=source_strip.convert('RGBA')
                for col in range(4):
                    cell=strip.crop((col*strip.width//4, 0,
                                     (col+1)*strip.width//4, strip.height))
                    self.stir_frames.append(clean_sprite(cell))
            self.stir_frames=normalize_animation_frames(self.stir_frames)
        self.assistant_frames=[]
        assistant_file=assets/'apprentices-v1-unique.png'
        if assistant_file.exists():
            with Image.open(assistant_file) as source_sheet:
                sheet=source_sheet.convert('RGBA')
                for row in range(4):
                    for col in range(4):
                        cell=sheet.crop((col*sheet.width//4,row*sheet.height//4,
                                         (col+1)*sheet.width//4,(row+1)*sheet.height//4))
                        self.assistant_frames.append(clean_sprite(cell))
        if self.coherent_actions:
            # Two generated transition cells (1 and 5) were visibly smaller
            # than the common cauldron/mentor scale.  Keep the stable cells
            # only, and close each stage with its centered return frame.
            self.action_groups = {
                'stir': [index for index in (0, 2, 3, 0)
                         if index < len(self.mentor_frames)],
                'potion': [index for index in (4, 6, 7, 4)
                           if index < len(self.mentor_frames)],
                'herbs': [index for index in range(8, min(12, len(self.mentor_frames)))],
            }
        else:
            self.action_groups = {
                'stir': list(range(0, min(4, len(self.mentor_frames)))),
                'potion': list(range(4, min(6, len(self.mentor_frames)))),
                'herbs': list(range(6, min(8, len(self.mentor_frames)))),
            }
        self.mentor_action_sequence = (self.action_groups['stir'] +
                                       self.action_groups['potion'] +
                                       self.action_groups['herbs'])
        self.hitboxes=[]
        self.dismiss_hitboxes=[]
        if not demo:
            threading.Thread(target=self.poll,daemon=True).start()
        self.update()

    def make_window_icon(self):
        """Build a tiny block icon for the native window and taskbar."""

        image = Image.new('RGBA', (32, 32), '#020f18')
        draw = ImageDraw.Draw(image)
        cyan, yellow, green = '#48e5fa', '#ffcb57', '#21efb0'
        for x in range(4, 28):
            draw.rectangle((x, 4, x + 1, 20), fill=cyan)
        for y in range(4, 22):
            draw.rectangle((4, y, 27, y + 1), fill=cyan)
        draw.rectangle((8, 9, 10, 11), fill=green)
        draw.rectangle((12, 13, 14, 15), fill=green)
        draw.rectangle((16, 11, 18, 13), fill=green)
        draw.rectangle((20, 7, 22, 9), fill=yellow)
        draw.rectangle((8, 23, 24, 25), fill=cyan)
        draw.rectangle((12, 26, 20, 28), fill=yellow)
        return ImageTk.PhotoImage(image, master=self.root)

    def chrome_button(self, parent, label, command, color):
        button = tk.Button(
            parent, text=label, command=command, width=3, height=1,
            bg='#061923', fg=color, activebackground='#153b4c',
            activeforeground='#ffffff', relief='flat', bd=0,
            highlightthickness=0, font=('Consolas', 11, 'bold'),
        )
        button.pack(side='right', padx=1, pady=2)
        return button

    def bind_chrome_drag(self, widget):
        widget.bind('<ButtonPress-1>', self.start_window_drag, add='+')
        widget.bind('<B1-Motion>', self.drag_window, add='+')
        widget.bind('<Double-Button-1>', lambda _event: self.toggle_maximize(), add='+')
        for child in widget.winfo_children():
            if isinstance(child, tk.Button):
                continue
            child.bind('<ButtonPress-1>', self.start_window_drag, add='+')
            child.bind('<B1-Motion>', self.drag_window, add='+')
            child.bind('<Double-Button-1>', lambda _event: self.toggle_maximize(), add='+')

    def start_window_drag(self, event):
        if self.window_maximized:
            return
        self.drag_origin = (
            event.x_root,
            event.y_root,
            self.root.winfo_x(),
            self.root.winfo_y(),
        )

    def drag_window(self, event):
        origin = getattr(self, 'drag_origin', None)
        if origin is None or self.window_maximized:
            return
        start_x, start_y, window_x, window_y = origin
        self.root.geometry(f'+{window_x + event.x_root - start_x}+{window_y + event.y_root - start_y}')

    def minimize_window(self):
        try:
            self.root.iconify()
        except tk.TclError:
            self.root.withdraw()

    def toggle_maximize(self):
        if self.window_maximized:
            if self.restore_geometry:
                self.root.geometry(self.restore_geometry)
            self.window_maximized = False
            return
        self.restore_geometry = self.root.geometry()
        width = self.root.winfo_screenwidth()
        height = self.root.winfo_screenheight()
        self.root.geometry(f'{width}x{height}+0+0')
        self.window_maximized = True

    def pixel_icon(self, parent, kind, color, pixel=3):
        patterns = {
            'monitor': ('1111111', '1000001', '1011101', '1000001', '1111111', '0011100'),
            'phone': ('0111110', '0100010', '0100010', '0100010', '0111110', '0010100'),
            'rename': ('0001000', '0011000', '0110000', '1100000', '1100000', '1111000'),
            'zoom': ('0010000', '0111000', '1111100', '0111000', '0010000', '0001100'),
        }
        pattern = patterns.get(kind, patterns['monitor'])
        width = len(pattern[0]) * pixel
        height = len(pattern) * pixel
        icon = tk.Canvas(parent, width=width, height=height, bg=parent.cget('bg'),
                         highlightthickness=0)
        for row, line in enumerate(pattern):
            for col, filled in enumerate(line):
                if filled == '1':
                    icon.create_rectangle(col * pixel, row * pixel,
                                          (col + 1) * pixel - 1, (row + 1) * pixel - 1,
                                          outline=color, fill=color)
        return icon

    def toolbar_button(self, parent, kind, label, command, color):
        holder = tk.Frame(parent, bg=BG)
        holder.pack(side='right', padx=(0, 8), pady=3)
        self.pixel_icon(holder, kind, color, 2).pack(side='left', padx=(4, 3), pady=2)
        button = tk.Button(holder, text=label, command=command,
                           bg='#0b2638', fg=color, activebackground='#153b4c',
                           activeforeground='#fff4c4', relief='flat', padx=8,
                           bd=0, highlightthickness=0)
        button.pack(side='left')
        return button

    def set_zoom(self, value):
        self.zoom = max(ZOOM_MIN, min(ZOOM_MAX, float(value)))
        if self.zoom_label is not None:
            self.zoom_label.configure(text=f'ZOOM {self.zoom * 100:.0f}%')
        self.draw()

    def zoom_with_ctrl(self, event):
        delta = getattr(event, 'delta', 0)
        if delta > 0:
            self.set_zoom(self.zoom + 0.1)
        elif delta < 0:
            self.set_zoom(self.zoom - 0.1)
        return 'break'

    def close(self):
        self.stop.set()
        if hasattr(self.client,'close'):self.client.close()
        self.root.destroy()

    def local_snapshot(self):
        """Return the same read-only, aliased view that the desktop displays."""

        snapshot = deepcopy(self.state) if isinstance(self.state, dict) else {}
        visible = []
        # Do not call visible_runs() here: the gateway serves from a worker
        # thread, while that method may persist alias changes for the Tk loop.
        # Filtering a copied state keeps the relay read-only and thread-safe.
        for run in prioritize_runs(effective_runs(snapshot)):
            run_id = str(run.get('run_id') or '').strip()
            if run_id and self.name_aliases.is_dismissed(run_id) and phase_for(run) in DISMISSIBLE:
                continue
            copy = deepcopy(run)
            copy['name'] = self.display_name(run)
            visible.append(copy)
        snapshot['runs'] = visible
        if visible:
            # Direct SSH discovery returns a run-centric payload.  Mirror the
            # desktop's selected task at the root so the phone can render one
            # task exactly like the desktop even when there is only one run.
            anchor = next((run for run in visible if phase_for(run) in ACTIVE), visible[0])
            scalar_fields = (
                'run_id', 'status', 'phase', 'gpu_ids', 'gpu_id', 'epoch',
                'total_epochs', 'step', 'total_steps', 'loss', 'current_iou',
                'metric_name', 'best_iou', 'best_epoch', 'eta_seconds',
                'updated_at', 'history', 'available_metrics',
            )
            for field in scalar_fields:
                current = snapshot.get(field)
                if field not in snapshot or current in (None, '', [], {}):
                    if field in anchor:
                        snapshot[field] = deepcopy(anchor[field])
            if snapshot.get('status') in (None, '', 'idle') and anchor.get('status'):
                snapshot['status'] = anchor['status']
            if not isinstance(snapshot.get('metrics'), dict) or not snapshot['metrics']:
                metrics = dict(anchor.get('metrics') or {})
                if anchor.get('loss') is not None:
                    metrics.setdefault('loss', anchor['loss'])
                if anchor.get('current_iou') is not None:
                    metrics.setdefault(anchor.get('metric_name') or 'mIoU', anchor['current_iou'])
                snapshot['metrics'] = metrics
        snapshot.setdefault('hardware', {'count': 0, 'gpus': []})
        snapshot['source'] = 'desktop-local'
        snapshot['desktop_online'] = not bool(self.error)
        snapshot['desktop_error'] = self.error
        snapshot['desktop_last_received'] = self.last_received or ''
        return snapshot

    def rotate_local_token(self):
        """Rotate the phone relay token and reopen the sync details."""

        gateway = self.local_gateway
        if gateway is None:
            messagebox.showwarning(
                '手机同步不可用',
                self.local_gateway_error or '本地同步接口尚未启动。',
                parent=self.root,
            )
            return
        confirmed = messagebox.askyesno(
            '重置手机 Token',
            '重置后，当前手机上的旧 Token 会立即失效。\n'
            '需要把新 Token 重新填入手机 App，是否继续？',
            parent=self.root,
        )
        if not confirmed:
            return
        try:
            gateway.rotate_token()
        except (OSError, ValueError) as exc:
            self.status.configure(
                text='Token 未重置：本地令牌文件不可写（' + type(exc).__name__ + '）',
                fg='#ff557d',
            )
            return

        dialog = getattr(self, 'sync_dialog', None)
        if dialog is not None:
            try:
                if dialog.winfo_exists():
                    dialog.destroy()
            except tk.TclError:
                pass
        self.sync_dialog = None
        self.status.configure(text='手机 Token 已重置，旧 Token 已失效', fg='#26edb0')
        self.show_local_sync()

    def show_local_sync(self):
        if self.local_gateway is None:
            messagebox.showwarning(
                '手机同步不可用',
                self.local_gateway_error or '本地同步接口尚未启动。',
                parent=self.root,
            )
            return
        existing = getattr(self, 'sync_dialog', None)
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.deiconify()
                    existing.lift()
                    existing.focus_force()
                    return
            except tk.TclError:
                pass
        tunnel = self.cloudflare_tunnel
        public_url = tunnel.public_url if tunnel is not None else ''
        tunnel_status = tunnel.status if tunnel is not None else ''
        tunnel_error = tunnel.error if tunnel is not None else self.cloudflare_tunnel_error
        local_urls = self.local_gateway.access_urls()
        dialog = tk.Toplevel(self.root)
        self.sync_dialog = dialog
        dialog.title('手机同步')
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.protocol('WM_DELETE_WINDOW', dialog.destroy)

        tk.Label(dialog, text='手机只连接电脑面板', bg=BG, fg=TEXT,
                 font=('Consolas', 15, 'bold')).pack(anchor='w', padx=18, pady=(16, 4))
        tk.Label(dialog, text='外网使用 HTTPS 地址；局域网可使用电脑地址。',
                 bg=BG, fg=DIM).pack(anchor='w', padx=18, pady=(0, 12))

        fields = tk.Frame(dialog, bg=BG)
        fields.pack(fill='x', padx=18)

        tk.Label(fields, text='外网手机地址（HTTPS）', bg=BG, fg='#ffd77c',
                 font=('Consolas', 11, 'bold')).grid(row=0, column=0, sticky='w', pady=5)
        public_value = public_url or ('正在生成…' if tunnel is not None else '未启用外网隧道')
        public_entry = tk.Entry(fields, width=58, bg='#071a26', fg=TEXT,
                                insertbackground=TEXT, relief='flat')
        public_entry.insert(0, public_value)
        public_entry.configure(state='readonly')
        public_entry.grid(row=1, column=0, sticky='ew', pady=(0, 4))

        tk.Label(fields, text='本地同步 Token', bg=BG, fg='#ffd77c',
                 font=('Consolas', 11, 'bold')).grid(row=2, column=0, sticky='w', pady=5)
        token_entry = tk.Entry(fields, width=58, show='•', bg='#071a26', fg=TEXT,
                               insertbackground=TEXT, relief='flat')
        token_entry.insert(0, self.local_gateway.token)
        token_entry.configure(state='readonly')
        token_entry.grid(row=3, column=0, sticky='ew', pady=(0, 4))

        if is_loopback_bind(self.local_gateway.bind):
            local_text = '本地中继：127.0.0.1（仅本机监听；外网请使用上方 HTTPS 地址）'
        else:
            local_text = '局域网地址：' + (local_urls[0] if local_urls else '不可用')
        tk.Label(fields, text=local_text, bg=BG, fg=DIM, anchor='w').grid(
            row=4, column=0, sticky='w', pady=(3, 6)
        )
        if tunnel_error:
            tk.Label(fields, text='外网隧道提示：' + tunnel_error, bg=BG, fg='#ff557d',
                     anchor='w', wraplength=560).grid(row=5, column=0, sticky='w', pady=(0, 6))
        elif tunnel_status and tunnel_status not in {'未启动', '公网 HTTPS 地址已就绪'}:
            tk.Label(fields, text='外网隧道状态：' + tunnel_status, bg=BG, fg='#ffd77c',
                     anchor='w').grid(row=5, column=0, sticky='w', pady=(0, 6))

        buttons = tk.Frame(dialog, bg=BG)
        buttons.pack(fill='x', padx=18, pady=(8, 16))
        copy_status = tk.Label(buttons, text='复制后粘贴到手机 App 的“设置”页面。',
                               bg=BG, fg=DIM, anchor='w')
        copy_status.pack(side='left', expand=True, fill='x')

        def copy_value(value, label):
            self.root.clipboard_clear()
            self.root.clipboard_append(value)
            self.root.update()
            copy_status.configure(text=label + '已复制', fg='#26edb0')

        tk.Button(buttons, text='复制地址', command=lambda: copy_value(public_url, '外网地址'),
                  state=tk.NORMAL if public_url else tk.DISABLED,
                  bg='#0b2638', fg='#48e5fa', activebackground='#153b4c',
                  activeforeground='#b8f7ff', relief='flat', padx=10).pack(side='right', padx=(8, 0))
        tk.Button(buttons, text='复制 Token', command=lambda: copy_value(self.local_gateway.token, 'Token'),
                  bg='#0b2638', fg='#ffd77c', activebackground='#153b4c',
                  activeforeground='#fff4c4', relief='flat', padx=10).pack(side='right')
        tk.Button(buttons, text='重置 Token', command=self.rotate_local_token,
                  bg='#3a1827', fg='#ff829c', activebackground='#562338',
                  activeforeground='#ffd7df', relief='flat', padx=10).pack(side='right', padx=(8, 0))
        tk.Button(buttons, text='关闭', command=dialog.destroy,
                  bg='#162d3d', fg=TEXT, activebackground='#21475d',
                  activeforeground=TEXT, relief='flat', padx=10).pack(side='right', padx=(0, 8))

    def refresh_sync_button(self):
        """Reflect the optional public tunnel from the Tk update loop."""

        tunnel = self.cloudflare_tunnel
        if tunnel is None:
            return
        if tunnel.public_url:
            self.phone_button.configure(text='手机同步 ✓', fg='#26edb0')
        elif tunnel.error:
            self.phone_button.configure(text='手机同步 !', fg='#ff557d')
        else:
            self.phone_button.configure(text='手机同步…', fg='#48e5fa')

    def poll(self):
        while not self.stop.is_set():
            try:
                value=(self.client.fetch(200),'')
            except Exception as exc:
                value=(None,'OFFLINE / 自动重连 · '+type(exc).__name__)
            try:self.events.put_nowait(value)
            except queue.Full:pass
            self.stop.wait(self.interval)

    def text(self,x,y,value,size=17,color=TEXT,anchor='nw',bold=False):
        pixel_font=bold and size>=21
        font_size=max(9,round(size*self.scale/8)*8 if pixel_font else int(size*self.scale))
        return self.canvas.create_text(x*self.scale,y*self.scale,text=str(value),fill=color,
                anchor=anchor,font=('Terminal' if pixel_font else 'Consolas',-font_size,'bold' if bold else 'normal'))

    def rect(self,x,y,w,h,outline=BORDER,fill=BG):
        return self.canvas.create_rectangle(x*self.scale,y*self.scale,(x+w)*self.scale,(y+h)*self.scale,
                                            outline=outline,fill=fill,width=1)

    def line(self,*coords,color=BORDER,dash=None):
        return self.canvas.create_line(*[p*self.scale for p in coords],fill=color,dash=dash)

    def bar(self,x,y,w,h,percent,color):
        self.rect(x,y,w,h)
        n=max(1,int(w/16))
        for i in range(n):
            self.rect(x+2+i*(w-4)/n,y+2,(w-4)/n-2,h-4,outline='',
                      fill=color if i/n < percent/100 else '#182f43')

    def picture(self,key,x,y,w,h):
        width,height=max(1,int(w*self.scale)),max(1,int(h*self.scale))
        cache_key=(key,width,height)
        if cache_key not in self.cache:
            if key=='mentor': source=self.mentor
            elif isinstance(key,str) and key.startswith('stir:') and self.stir_frames:
                source=self.stir_frames[int(key.split(':')[1]) % len(self.stir_frames)]
            elif isinstance(key,str) and key.startswith('action:'):
                source=self.mentor_frames[int(key.split(':')[1]) % len(self.mentor_frames)]
            elif isinstance(key,str) and key.startswith('assistant:'):
                parts=key.split(':')
                pair_count=max(1,len(self.assistant_frames)//2)
                identity=int(parts[1]) % pair_count
                frame=int(parts[2]) % 2
                variant=int(parts[3]) if len(parts)>3 else 0
                source=self.assistant_frames[identity*2+frame]
                if variant:
                    if variant % 2:
                        source=ImageOps.mirror(source)
                    if variant % 3:
                        source=ImageEnhance.Color(source).enhance(1.0+0.08*(variant % 3))
            else:
                cell=int(key); aw,ah=self.atlas.size
                source=self.atlas.crop(((cell%2)*aw//2,(cell//2)*ah//2,(cell%2+1)*aw//2,(cell//2+1)*ah//2))
                if cell:
                    source=source.crop((0,int(source.height*.36),source.width,source.height))
            if isinstance(key,str):
                # Preserve body/face proportions; align every animation on one canvas.
                image=source.copy()
                image.thumbnail((width,height),Image.Resampling.NEAREST)
                fitted=Image.new('RGBA',(width,height))
                fitted.alpha_composite(image,((width-image.width)//2,height-image.height))
                image=fitted
            else:
                image=source.resize((width,height),Image.Resampling.NEAREST)
            if len(self.cache)>96:self.cache.clear()
            self.cache[cache_key]=ImageTk.PhotoImage(image,master=self.root)
        photo=self.cache[cache_key]
        self.images.append(photo)
        self.canvas.create_image(x*self.scale,y*self.scale,image=photo,anchor='nw')

    def visible_runs(self):
        """Keep dismissed terminal runs hidden, but revive reused IDs when active."""

        visible=[]
        restored=False
        for run in effective_runs(self.state):
            run_id=str(run.get('run_id') or '').strip()
            if run_id and self.name_aliases.is_dismissed(run_id):
                if phase_for(run) in DISMISSIBLE:
                    continue
                self.name_aliases.restore(run_id)
                restored=True
            visible.append(run)
        if restored:
            self.name_aliases.save()
        return prioritize_runs(visible)

    def display_name(self, run):
        run_id=str(run.get('run_id') or '').strip()
        fallback=str(run.get('name') or run_id or '模型')
        return self.name_aliases.get(run_id, fallback) if run_id else fallback

    def pixel_cross(self,x,y,color='#ff557d'):
        """Draw a small block-pixel X without adding another image asset."""

        for row,pattern in enumerate(('10001','01010','00100','01010','10001')):
            for col,filled in enumerate(pattern):
                if filled == '1':
                    self.rect(x+col*3,y+row*3,3,3,outline=color,fill=color)

    def rename_selected(self):
        runs=self.visible_runs()
        selected=next((run for run in runs if run.get('run_id')==self.selected),None)
        if not selected:
            self.status.configure(text='暂无可重命名的训练任务',fg='#ffcb57')
            return
        run_id=str(selected.get('run_id') or '').strip()
        if not run_id:
            self.status.configure(text='当前任务缺少 run_id，无法保存名称',fg='#ffcb57')
            return
        current=self.display_name(selected)
        value=simpledialog.askstring(
            '重命名训练任务',
            '输入新的显示名称（清空后恢复原始名称）：\n原始 ID：'+run_id,
            initialvalue=current,
            parent=self.root,
        )
        if value is None:
            return
        label=' '.join(str(value).replace('\r',' ').replace('\n',' ').split())[:48]
        previous=self.name_aliases.aliases.get(run_id)
        self.name_aliases.set(run_id,label)
        if not self.name_aliases.save():
            if previous is None:
                self.name_aliases.aliases.pop(run_id,None)
            else:
                self.name_aliases.aliases[run_id]=previous
            self.status.configure(text='名称未保存：本地文件不可写',fg='#ff557d')
            return
        self.status.configure(text='已改名：'+(label or run_id),fg='#26edb0')
        self.draw()

    def dismiss_run(self,run_id):
        runs=self.visible_runs()
        selected=next((run for run in runs if str(run.get('run_id'))==str(run_id)),None)
        if not selected or phase_for(selected) not in DISMISSIBLE:
            self.status.configure(text='只有已完成、已停止或异常任务可以移除',fg='#ffcb57')
            return
        key=str(run_id)
        was_dismissed=self.name_aliases.is_dismissed(key)
        self.name_aliases.dismiss(key)
        if not self.name_aliases.save():
            if not was_dismissed:
                self.name_aliases.restore(key)
            self.status.configure(text='任务未移除：本地文件不可写',fg='#ff557d')
            return
        label=self.display_name(selected)
        if self.selected == run_id:
            self.selected=None
        self.status.configure(text='已从面板移除：'+label,fg='#26edb0')
        self.draw()

    def click(self,event):
        x,y=self.canvas.canvasx(event.x)/self.scale,self.canvas.canvasy(event.y)/self.scale
        for left,top,right,bottom,run_id in self.dismiss_hitboxes:
            if left<=x<=right and top<=y<=bottom:
                self.dismiss_run(run_id)
                self.canvas.focus_set()
                return
        for left,top,right,bottom,run_id in self.hitboxes:
            if left<=x<=right and top<=y<=bottom:
                self.selected=run_id;self.draw();break
        self.canvas.focus_set()

    def move_selection(self,delta):
        runs=self.visible_runs()
        if not runs:return
        ids=[r.get('run_id') for r in runs]
        index=ids.index(self.selected) if self.selected in ids else 0
        self.selected=ids[(index+delta)%len(ids)];self.draw()

    def plot(self,x,y,w,h,run,metric=False):
        self.rect(x,y,w,h)
        name='mIoU' if metric else 'loss'
        value, observed_epoch=latest_metric(run,name)
        self.text(x+12,y+9,name if metric else 'LOSS',20,bold=True)
        self.text(x+w-12,y+9,format_number(value),20,'#21efb0' if metric else '#48e5fa',anchor='ne',bold=True)
        points=series(run,name)
        if metric:
            self.text(x+12,y+32,('VALID EPOCH '+format_number(observed_epoch,0)) if value is not None else '等待首次验证',11,DIM)
        gx,gy,gw,gh=x+50,y+46,w-68,h-79
        hi=max([v for _,v in points] or [1]);lo=min([v for _,v in points] or [0])
        if hi==lo:hi=lo+1
        for i in range(5):
            yy=gy+gh*i/4
            self.line(gx,yy,gx+gw,yy,color='#124158',dash=(2,3))
            self.text(gx-8,yy,f'{hi-(hi-lo)*i/4:.2f}',12,anchor='e')
        for i in range(6):
            xx=gx+gw*i/5
            self.line(xx,gy,xx,gy+gh,color='#124158',dash=(2,3))
            start,end=(points[0][0],points[-1][0]) if points else (0,0)
            self.text(xx,gy+gh+10,f'{start+(end-start)*i/5:.0f}',12,anchor='n')
        if len(points)>1:
            xmin,xmax=points[0][0],points[-1][0]
            coords=[]
            for epoch,val in points:coords.extend([gx+(epoch-xmin)/max(1,xmax-xmin)*gw,gy+gh-(val-lo)/(hi-lo)*gh])
            self.line(*coords,color='#21efb0' if metric else '#48e5fa')
        else:self.text(gx+gw/2,gy+gh/2,'等待历史数据',16,DIM,anchor='center')

    def draw(self):
        if not self.canvas.winfo_exists():return
        fit_scale=max(.5,self.canvas.winfo_width()/1488)
        self.scale=max(.5,min(2.4,fit_scale*self.zoom))
        self.canvas.delete('all');self.images=[];self.hitboxes=[];self.dismiss_hitboxes=[]
        runs=self.visible_runs();gpus=gpu_slot_rows(self.state)
        selected=next((r for r in runs if r.get('run_id')==self.selected),runs[0] if runs else {})
        self.selected=selected.get('run_id')
        self.text(16,10,'TRAINING MONITOR_',32,bold=True)
        active=sum(phase_for(r) in ACTIVE for r in runs)
        self.text(1470,19,f'RUNNING {active}/{len(runs)}  |  GPUS {len(gpus)}  |  '+datetime.now().strftime('%Y-%m-%d  %H:%M:%S'),17,anchor='ne')
        rows=max(1,len(runs));table_h=40+rows*33
        self.rect(16,51,1456,table_h)
        cols=[28,304,447,641,777,898,1004,1120]
        for xx,label in zip(cols,['RUNS','STATUS','STEP','EPOCH','LOSS','mIoU','GPU','TOTAL']):self.text(xx,62,label,17)
        self.text(1455,62,'×',20,'#ff557d',anchor='center',bold=True)
        for xx in [287,429,619,759,879,985,1103]:self.line(xx,51,xx,51+table_h,color='#153b4c')
        for i,r in enumerate(runs):
            yy=91+i*33;p=phase_for(r);color=COLORS.get(p,DIM)
            if r==selected:self.rect(17,yy-1,1454,32,outline='',fill='#082333')
            self.line(16,yy+32,1472,yy+32,color='#153b4c')
            gpuids=','.join(map(str,r.get('gpu_ids') or [r.get('gpu_id','—')]))
            vals=[('> ' if r==selected else '  ')+f'{i+1:02} '+self.display_name(r)[:19],LABELS.get(p,p.upper()),
                  f"{r.get('step','—')} / {r.get('total_steps','—')}",f"{r.get('epoch',0)} / {r.get('total_epochs','—')}",
                  format_number(latest_metric(r,'loss')[0]),format_number(latest_metric(r,'mIoU')[0]),gpuids[:10]]
            for j,(xx,val) in enumerate(zip(cols,vals)):self.text(xx,yy+5,val,17,color if j==1 else TEXT)
            pct=progress_percent(r);self.bar(1120,yy+7,230,17,pct,color);self.text(1370,yy+5,f'{pct:.0f}%',17,color)
            if p in DISMISSIBLE:
                self.pixel_cross(1447,yy+8)
                self.dismiss_hitboxes.append((1443,yy+4,1469,yy+28,r.get('run_id')))
            self.hitboxes.append((16,yy,1472,yy+33,r.get('run_id')))
        if not runs:
            self.text(744,51+40+16,'正在发现训练日志 · WAITING FOR RUNS',16,DIM,anchor='center')
        y=51+table_h+14;p=phase_for(selected) if selected else 'idle';color=COLORS.get(p,DIM)
        self.rect(16,y,972,450)
        selected_name=self.display_name(selected) if selected else '—'
        selected_id=str(selected.get('run_id') or '')
        self.text(34,y+16,selected_name[:28],18,bold=True)
        if selected_id and selected_id != selected_name:
            self.text(34,y+39,'ID '+selected_id[:52],11,DIM)
        self.rect(350,y+17,134,29,outline=color);self.text(417,y+31,LABELS.get(p,p),18,color,anchor='center')
        if p in DISMISSIBLE:
            self.pixel_cross(493,y+24)
            self.dismiss_hitboxes.append((489,y+20,515,y+44,selected.get('run_id')))
        self.text(38,y+61,'ETA  '+format_eta(selected.get('eta_seconds')),22,'#48e5fa')
        self.text(567,y+19,'EPOCH',16);self.text(651,y+16,f"{selected.get('epoch',0)} / {selected.get('total_epochs','—')}",34,color,bold=True)
        self.text(565,y+77,'STEP / EPOCH PROGRESS',14)
        self.bar(565,y+103,343,17,step_progress(selected),color);self.text(960,y+101,f'{step_progress(selected):.0f}%',17,color,anchor='ne')
        self.plot(29,y+140,465,213,selected)
        self.plot(506,y+140,469,213,selected,True)
        for i,(label,value) in enumerate([('LOSS (CUR)',latest_metric(selected,'loss')[0]),('LOSS (BEST)',best_metric(selected,'loss')),
                                         ('mIoU (LATEST)',latest_metric(selected,'mIoU')[0]),('mIoU (BEST)',best_metric(selected,'mIoU'))]):
            xx=29+i*239;self.rect(xx,y+365,228,73);self.text(xx+14,y+374,label,15)
            self.text(xx+14,y+394,format_number(value),32,'#21efb0' if i==2 else TEXT,bold=True)
        self.picture(0,1005,y,467,450)
        mentor_state=mentor_phase(runs) if not self.error else 'idle'
        action=(self.mentor_action_sequence[0]
                if self.mentor_action_sequence else 0)
        sprite='action:'+str(action) if self.mentor_frames else 'mentor'
        action_label='待命 · 等待开炉'
        if mentor_state in ACTIVE and self.mentor_frames:
            groups=self.action_groups
            training_actions=self.mentor_action_sequence
            if mentor_state in {'training', 'preparing'} and self.stir_frames:
                stir_index=(self.frame//MAIN_STIR_FRAME_HOLD)%len(self.stir_frames)
                sprite='stir:'+str(stir_index)
                action_label='搅拌丹液 · 主炼制程'
            elif mentor_state=='validating' and groups['herbs']:
                action=groups['herbs'][(self.frame//MENTOR_FRAME_HOLD)%len(groups['herbs'])]
                sprite='action:'+str(action)
                action_label='观察丹炉 · 等待结果'
            elif mentor_state=='saving' and groups['potion']:
                action=groups['potion'][(self.frame//MENTOR_FRAME_HOLD)%len(groups['potion'])]
                sprite='action:'+str(action)
                action_label='收丹 · 封存成果'
            elif training_actions:
                action=training_actions[(self.frame//MENTOR_FRAME_HOLD)%len(training_actions)]
                sprite='action:'+str(action)
                if action in groups['potion']:
                    action_label='添药入炉'
                elif action in groups['herbs']:
                    action_label='投放药材'
                else:
                    action_label='搅拌丹液'
        elif mentor_state=='finished' and self.mentor_frames:
            action=(self.action_groups['herbs'][-1] if self.action_groups['herbs'] else
                    self.action_groups['stir'][-1] if self.action_groups['stir'] else 0)
            action_label='炼丹完成 · 封存成果'
        self.picture(sprite,1100,y+45,278,375)
        self.text(1020,y+12,'MENTOR / 主炼丹师',18,'#ffd77c',bold=True)
        self.text(1020,y+425,action_label,16,'#ffd77c')
        self.text(1456,y+425,'OFFLINE' if self.error else LABELS[mentor_state],17,color,anchor='ne')
        y+=465
        self.text(22,y,'GPU APPRENTICES',21,bold=True);self.line(232,y+13,1472,y+13,dash=(3,3))
        visible_state=dict(self.state);visible_state['runs']=runs
        models=station_models(visible_state);y+=30
        for i,(gpu,jobs) in enumerate(models):
            xx=16+(i%4)*367;yy=y+(i//4)*197
            job=next((r for r in jobs if phase_for(r) in ACTIVE),jobs[0] if jobs else {})
            ph=phase_for(job) if job else 'idle';co=COLORS[ph]
            self.rect(xx,yy,357,185);self.text(xx+12,yy+10,'GPU '+str(gpu['id']),19,co,bold=True)
            self.text(xx+342,yy+12,LABELS[ph],15,co,anchor='ne')
            if job and ph in DISMISSIBLE:
                self.pixel_cross(xx+319,yy+8)
                self.dismiss_hitboxes.append((xx+315,yy+4,xx+341,yy+29,job.get('run_id')))
            art=1 if ph in {'training','preparing','validating'} else 2 if ph in {'saving','finished'} else 3
            bob=(self.frame//3%2) if ph in ACTIVE and not self.error else 0
            assistant_pairs=len(self.assistant_frames)//2
            if assistant_pairs:
                identity,variant=assistant_identity(i,assistant_pairs)
                motion=((self.frame//(3 if ph in ACTIVE and not self.error else 8))+i)%2
                self.rect(xx+8,yy+34,169,105,outline='#153b4c',fill='#071a26')
                self.picture(f'assistant:{identity}:{motion}:{variant}',xx+8,yy+34-bob,169,105)
                self.line(xx+16,yy+132,xx+169,yy+132,color='#18374b')
            else:
                self.picture(art,xx+8,yy+34-bob,169,105)
            self.text(xx+190,yy+39,'LOSS',14);self.text(xx+190,yy+58,format_number(latest_metric(job,'loss')[0]),20,co,bold=True)
            self.text(xx+190,yy+87,'mIoU',14)
            self.text(xx+190,yy+106,format_number(latest_metric(job,'mIoU')[0]),20,'#21efb0',bold=True)
            used,total=gpu.get('memory_used_mib'),gpu.get('memory_total_mib')
            mem=f'{used/1024:.1f}/{total/1024:.0f}GB' if isinstance(used,(int,float)) and total else 'VRAM —'
            self.text(xx+10,yy+164,format_number(gpu.get('utilization_percent'),0)+'%  '+mem,13,'#21efb0')
            self.text(xx+344,yy+164,format_number(gpu.get('temperature_c'),0)+'°C  '+format_number(gpu.get('power_w'),0)+'W',13,anchor='ne')
            self.text(xx+10,yy+144,(self.display_name(job) if job else 'IDLE')[:15],13)
            self.bar(xx+145,yy+146,154,12,progress_percent(job),co);self.text(xx+343,yy+144,f'{progress_percent(job):.0f}%',13,co,anchor='ne')
            if job:self.hitboxes.append((xx,yy,xx+357,yy+185,job.get('run_id')))
            if len(jobs)>1:self.text(xx+340,yy+125,f'+{len(jobs)-1} RUNS',12,co,anchor='ne')
        height=y+max(1,math.ceil(len(models)/4))*197
        self.canvas.configure(scrollregion=(0,0,1488*self.scale,height*self.scale))
        if self.first_draw:
            self.canvas.yview_moveto(0)
            self.first_draw = False

    def update(self):
        if self.demo:
            try:count=max(0,min(32,self.gpu_count.get()))
            except (ValueError,tk.TclError):count=4
            self.state=demo_dashboard(count,self.frame,self.demo_phase.get())
        else:
            try:
                state,self.error=self.events.get_nowait()
                if state is not None:self.state=state;self.last_received=datetime.now().strftime('%H:%M:%S')
            except queue.Empty:pass
            self.status.configure(text=self.error or ('LIVE · '+self.last_received if self.last_received else '连接中…'),fg='#ffcb57' if self.error else TEXT)
        self.draw();self.refresh_sync_button();self.frame+=1
        self.root.after(250,self.update)
