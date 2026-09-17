"""Read-only desktop alchemy monitor; animation never redraws the mentor face."""

from __future__ import annotations

import math
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

import alchemy_assets
from console_ui import (MonitorClient, PHASE_LABELS, effective_runs, format_number,
                        gpu_slot_rows, phase_for, progress_percent)


BG = "#101823"
CARD = "#1b2838"
INK = "#e9edf4"
MUTED = "#9eafc4"
CYAN = "#53d5ec"
ACTIVE = {"training", "preparing", "validating", "saving"}


def effective_gateway_bind(local_bind, cloudflare_enabled):
    """Keep a Cloudflare-backed relay reachable only from this computer."""

    if cloudflare_enabled:
        return "127.0.0.1"
    return str(local_bind or "0.0.0.0").strip()


def station_models(state):
    """Map each physical GPU to every associated run, including shared/DDP jobs."""
    runs = effective_runs(state)
    slots = gpu_slot_rows(state)
    known = {str(gpu["id"]) for gpu in slots}

    def ids(run):
        return {str(value) for value in (run.get("gpu_ids") or
                ([run["gpu_id"]] if run.get("gpu_id") is not None else []))}

    result = [(gpu, [run for run in runs if str(gpu["id"]) in ids(run)]) for gpu in slots]
    unbound = [run for run in runs if not ids(run) or not ids(run).issubset(known)]
    if unbound:
        result.append(({"id": "未绑定", "name": "CPU / 未识别设备"}, unbound))
    return result


def mentor_phase(runs):
    phases = [phase_for(run) for run in runs]
    for phase in ("training", "validating", "saving", "preparing", "error",
                  "stalled", "paused", "stopped", "finished"):
        if phase in phases:
            return phase
    return "idle"


def demo_state(count, tick, phase="training"):
    runs = []
    for index in range(count):
        if index % 3 == 2:
            continue
        runs.append({"run_id": "demo-model-" + str(index + 1),
                     "status": phase if phase in {"stopped", "finished", "paused", "error"} else "training",
                     "phase": phase, "epoch": 100 if phase == "finished" else int(tick + index * 13) % 100,
                     "total_epochs": 100, "loss": round(1 / (1 + tick / 20 + index), 4),
                     "gpu_ids": [str(index)], "updated_at": datetime.now().isoformat()})
    return {"runs": runs, "hardware": {"source": "demo", "count": count,
            "gpus": [{"id": str(i), "name": "演示 GPU", "utilization_percent":
                      (72 + i * 3) % 100 if i % 3 != 2 and phase in ACTIVE else 0,
                      "memory_used_mib": 8192 if i % 3 != 2 else 0,
                      "memory_total_mib": 24576} for i in range(count)]}}


class AlchemyWindow:
    def __init__(self, root, url, token, demo=False, gpu_count=4, interval=2):
        self.root, self.demo = root, demo
        self.interval = max(0.5, interval)
        self.client = MonitorClient(url, token)
        self.events = queue.Queue(maxsize=1)
        self.stop = threading.Event()
        self.state = {}
        self.error = ""
        self.last_received = None
        self.started = time.monotonic()
        self.frame = 0
        self.columns = 0
        self.signature = None
        self.gpu_count = tk.IntVar(value=gpu_count)
        self.demo_phase = tk.StringVar(value="training")
        root.title("炼丹训练监控 · 导师工作室")
        root.geometry("1180x800")
        root.minsize(880, 660)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=INK, rowheight=30)
        style.configure("Treeview.Heading", background="#26394f", foreground=INK)
        style.map("Treeview", background=[("selected", "#28516b")])
        self.header = tk.Label(root, text="导师炼丹工作室", font=("Microsoft YaHei UI", 21, "bold"),
                               bg=BG, fg=INK, anchor="w")
        self.header.pack(fill="x", padx=24, pady=(18, 5))
        self.connection = tk.Label(root, bg=BG, fg=MUTED, anchor="w")
        self.connection.pack(fill="x", padx=24)
        if demo:
            controls = tk.Frame(root, bg=BG)
            controls.pack(fill="x", padx=24, pady=8)
            tk.Label(controls, text="演示数据 · 显卡数量", bg=BG, fg=CYAN).pack(side="left")
            tk.Spinbox(controls, from_=0, to=32, width=4, textvariable=self.gpu_count,
                       command=self.refresh_demo).pack(side="left", padx=10)
            choices = ttk.Combobox(controls, textvariable=self.demo_phase, width=16, state="readonly",
                                  values=("training", "validating", "saving", "finished", "paused", "stopped", "error"))
            choices.pack(side="left")
            choices.bind("<<ComboboxSelected>>", lambda _: self.refresh_demo())
        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True, padx=24, pady=14)
        left = tk.Frame(body, bg=CARD, width=290)
        left.pack(side="left", fill="y", padx=(0, 18))
        left.pack_propagate(False)
        tk.Label(left, text="主炼丹师", bg=CARD, fg=INK,
                 font=("Microsoft YaHei UI", 15, "bold")).pack(pady=12)
        # Display the exact approved bitmap. Only nearest-neighbor display scaling;
        # no generated replacement heads, facial deformation, or state-sheet switching.
        asset = Path(alchemy_assets.__file__).parent / "mentor-approved.png"
        with Image.open(asset) as original:
            display = original.convert("RGBA")
            display.thumbnail((266, 400), Image.Resampling.NEAREST)
        self.portrait = ImageTk.PhotoImage(display, master=root)
        tk.Label(left, image=self.portrait, bg=CARD).pack()
        self.mentor_label = tk.Label(left, bg=CARD, fg=CYAN, font=("Microsoft YaHei UI", 14))
        self.mentor_label.pack(pady=10)
        self.fire = tk.Canvas(left, width=260, height=85, bg=CARD, highlightthickness=0)
        self.fire.pack()
        tk.Label(left, text="一位导师 · 多炉并行", bg=CARD, fg=MUTED).pack(pady=8)
        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        self.summary = tk.Label(right, bg=BG, fg=INK, anchor="w", font=("Microsoft YaHei UI", 13, "bold"))
        self.summary.pack(fill="x", pady=(0, 10))
        station_area = tk.Frame(right, bg=BG)
        station_area.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(station_area, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(station_area, orient="vertical", command=self.canvas.yview)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.stations = tk.Frame(self.canvas, bg=BG)
        self.station_window = self.canvas.create_window(0, 0, anchor="nw", window=self.stations)
        self.stations.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self.resize)
        tk.Label(right, text="模型任务", bg=BG, fg=INK, anchor="w",
                 font=("Microsoft YaHei UI", 13, "bold")).pack(fill="x", pady=(12, 6))
        self.table = ttk.Treeview(right, columns=("phase", "progress", "loss", "gpus"), height=5)
        self.table.heading("#0", text="模型 / 任务")
        self.table.column("#0", width=160, minwidth=90)
        for key, label in (("phase", "状态"), ("progress", "进度"), ("loss", "Loss"), ("gpus", "GPU")):
            self.table.heading(key, text=label)
            self.table.column(key, width=95, minwidth=60)
        self.table.pack(fill="x")
        if not demo:
            threading.Thread(target=self.poll, daemon=True).start()
        self.update()

    def close(self):
        self.stop.set()
        self.root.destroy()

    def poll(self):
        while not self.stop.is_set():
            try:
                result = (self.client.fetch(0), "")
            except Exception as exc:
                # Do not expose URLs/tokens or arbitrary response bodies in the UI.
                result = (None, "连接中断（" + type(exc).__name__ + "），自动重试中")
            try:
                self.events.put_nowait(result)
            except queue.Full:
                pass
            self.stop.wait(self.interval)

    def resize(self, event):
        self.canvas.itemconfigure(self.station_window, width=event.width)
        columns = max(1, event.width // 255)
        if columns != self.columns:
            self.columns = columns
            self.signature = None

    def refresh_demo(self):
        try:
            count = min(32, max(0, self.gpu_count.get()))
        except (ValueError, tk.TclError):
            count = 4
        self.state = demo_state(count, int(time.monotonic() - self.started), self.demo_phase.get())
        self.last_received = datetime.now().strftime("%H:%M:%S")

    def render_data(self):
        runs = effective_runs(self.state)
        models = station_models(self.state)
        physical_count = len(gpu_slot_rows(self.state))
        self.summary.configure(text=f"{physical_count} 张显卡   ·   {len(runs)} 个模型任务")
        self.connection.configure(text=("演示模式 · 数据为模拟，可调整显卡数和训练状态" if self.demo else
            self.error or ("已连接 · 更新于 " + self.last_received if self.last_received else "正在连接训练服务…")),
            fg="#ffbd78" if self.error or self.demo else MUTED)
        signature = repr((models, self.columns, self.error, [phase_for(run) for run in runs]))
        if signature != self.signature:
            self.signature = signature
            for child in self.stations.winfo_children():
                child.destroy()
            for column in range(32):
                self.stations.columnconfigure(column, weight=0)
            for column in range(max(1, self.columns)):
                self.stations.columnconfigure(column, weight=1, uniform="gpu")
            if not models:
                tk.Label(self.stations, text="等待硬件与训练数据\n请确认训练主机的监控服务已启动",
                         bg=CARD, fg=MUTED, pady=45).grid(sticky="ew")
            for index, (gpu, jobs) in enumerate(models):
                card = tk.Frame(self.stations, bg=CARD, padx=14, pady=12)
                card.grid(row=index // max(1, self.columns), column=index % max(1, self.columns),
                          sticky="nsew", padx=4, pady=4)
                active = any(phase_for(run) in ACTIVE for run in jobs) and not self.error
                lines = [f"GPU {gpu['id']}   {'● 炼丹中' if active else '○ 待命 / 停炉'}",
                         str(gpu.get("name", "GPU")),
                         f"利用率 {format_number(gpu.get('utilization_percent'), 0)}%",
                         f"显存 {format_number(gpu.get('memory_used_mib'), 0)} / {format_number(gpu.get('memory_total_mib'), 0)} MiB"]
                for line in lines:
                    tk.Label(card, text=line, bg=CARD, fg=CYAN if line == lines[0] else MUTED,
                             anchor="w", wraplength=230).pack(fill="x", pady=2)
                for run in jobs:
                    tk.Label(card, text=f"{run.get('run_id', '模型')} · {PHASE_LABELS[phase_for(run)]}",
                             bg=CARD, fg=INK, wraplength=230, anchor="w").pack(fill="x", pady=(8, 2))
                    ttk.Progressbar(card, value=progress_percent(run)).pack(fill="x")
                if not jobs:
                    tk.Label(card, text="丹炉空闲，等待模型", bg=CARD, fg=MUTED).pack(pady=12)
            self.table.delete(*self.table.get_children())
            for index, run in enumerate(runs):
                self.table.insert("", "end", iid=str(index), text=run.get("run_id", "模型"), values=(
                    PHASE_LABELS[phase_for(run)], f"{progress_percent(run):.1f}%",
                    format_number(run.get("loss", run.get("current_loss"))),
                    ", ".join(map(str, run.get("gpu_ids") or [run.get("gpu_id", "—")]))))
        phase = mentor_phase(runs)
        self.mentor_label.configure(text="等待重新连接" if self.error else PHASE_LABELS[phase])
        self.fire.delete("all")
        burning = phase in ACTIVE and not self.error
        for index in range(13):
            height = 12 + (math.sin(self.frame / 3 + index) + 1) * 20 if burning else 4
            x = 34 + index * 15
            self.fire.create_rectangle(x, 70 - height, x + 9, 70, fill=CYAN if burning else "#526074", outline="")
        self.fire.create_text(130, 12, text="炉火运转" if burning else "炉火已收", fill=MUTED)

    def update(self):
        if self.demo:
            self.refresh_demo()
        else:
            try:
                state, self.error = self.events.get_nowait()
                if state is not None:
                    self.state = state
                    self.last_received = datetime.now().strftime("%H:%M:%S")
            except queue.Empty:
                pass
        self.render_data()
        self.frame += 1
        self.root.after(160, self.update)


def run_desktop(url, token, demo=False, gpu_count=4, interval=2, client=None,
                names_path=None, local_bind='0.0.0.0', local_port=8765,
                local_token='', local_token_file='monitor.local.token',
                local_gateway_enabled=True, cloudflare_enabled=False,
                cloudflared_path=''):
    from pixel_window import PixelWindow
    from local_gateway import LocalGateway, load_or_create_local_token
    from cloudflare_tunnel import CloudflareQuickTunnel

    root = tk.Tk()
    window = PixelWindow(root, url, token, demo=demo, gpu_count=gpu_count, interval=interval,
                         client=client, names_path=names_path)
    gateway = None
    cloudflare = None
    if local_gateway_enabled:
        try:
            gateway_token = load_or_create_local_token(local_token, local_token_file)
            gateway = LocalGateway(
                bind=effective_gateway_bind(local_bind, cloudflare_enabled),
                port=local_port,
                token=gateway_token,
                token_file=local_token_file,
                snapshot_provider=window.local_snapshot,
            )
            gateway.start()
            window.local_gateway = gateway
            if cloudflare_enabled:
                cloudflare = CloudflareQuickTunnel(
                    port=gateway.port,
                    executable=cloudflared_path,
                )
                window.cloudflare_tunnel = cloudflare
                cloudflare.start()
        except OSError as exc:
            window.local_gateway_error = f'手机同步接口启动失败：{exc}'
        except (TypeError, ValueError) as exc:
            window.local_gateway_error = f'手机同步配置无效：{exc}'
    elif cloudflare_enabled:
        window.cloudflare_tunnel_error = 'Cloudflare Tunnel 需要先开启本地手机同步接口。'
    try:
        root.mainloop()
    finally:
        if cloudflare is not None:
            cloudflare.stop()
        if gateway is not None:
            gateway.stop()
