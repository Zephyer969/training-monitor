"""Dependency-free Linux collector. Reads processes, GPU counters and log files."""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import time
from datetime import datetime
from openmmlab_log import parse_openmmlab_line, parse_total_from_line

STEP = re.compile(r'(?:Epoch(?:\([^)]*\))?\s*\[\s*\d+\s*\]|Iter(?:\([^)]*\))?)\s*\[\s*(\d+)\s*/\s*(\d+)\s*\]', re.I)


def command(args):
    try:
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                universal_newlines=True, timeout=4)
        return result.stdout if result.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''


def gpu_snapshot():
    raw = command(['nvidia-smi', '--query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw', '--format=csv,noheader,nounits'])
    gpus, uuids = [], {}
    for row in csv.reader(io.StringIO(raw)):
        if len(row) != 8:
            continue
        row = [s.strip() for s in row]
        gpu = dict(id=row[0], name=row[2])
        uuids[row[1]] = row[0]
        for key, value in zip(('utilization_percent', 'memory_used_mib', 'memory_total_mib', 'temperature_c', 'power_w'), row[3:]):
            try:
                gpu[key] = float(value)
            except ValueError:
                gpu[key] = None
        gpus.append(gpu)
    bindings = {}
    raw = command(['nvidia-smi', '--query-compute-apps=pid,gpu_uuid', '--format=csv,noheader,nounits'])
    for row in csv.reader(io.StringIO(raw)):
        if len(row) == 2 and row[1].strip() in uuids:
            bindings.setdefault(row[0].strip(), []).append(uuids[row[1].strip()])
    return dict(source='nvidia-smi', count=len(gpus), gpus=gpus,
                error=None if gpus else '未发现 GPU 或 nvidia-smi 不可用'), bindings


def discover(bindings):
    """Only scan running training processes and their work directories, never all disks."""
    found = {}
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            args = [a.decode(errors='replace') for a in (proc/'cmdline').read_bytes().split(b'\0') if a]
            if not any(Path(a).name in ('train.py', 'train', 'training.py') or a.endswith('.train') for a in args):
                continue
            cwd = (proc/'cwd').resolve()
            roots, logs = [], []
            for i, arg in enumerate(args):
                if arg == '--work-dir' and i+1 < len(args):
                    roots.append(Path(args[i+1]) if Path(args[i+1]).is_absolute() else cwd/args[i+1])
                elif arg.startswith('--work-dir='):
                    roots.append(cwd/arg.split('=', 1)[1])
                elif arg.endswith('.py') and Path(arg).name not in ('train.py', 'training.py'):
                    config = Path(arg) if Path(arg).is_absolute() else cwd/arg
                    if 'work_dirs' in config.parts:
                        roots.append(config.parent)
                    else:
                        roots.append(cwd/'work_dirs'/config.stem)
            for fd in (proc/'fd').iterdir():
                try:
                    target = fd.resolve()
                    if target.suffix in ('.log', '.jsonl') and target.is_file():
                        logs.append(target)
                except OSError:
                    pass
            if not logs:
                for directory in roots:
                    if directory.is_dir():
                        logs.extend(directory.glob('*.log'))
                        logs.extend(directory.glob('*/*.log'))
            if not logs:
                continue
            # Reject historical experiments older than this process (allow logging startup delay).
            start_ticks = int((proc/'stat').read_text().rsplit(')', 1)[1].split()[19])
            boot = time.time() - float(Path('/proc/uptime').read_text().split()[0])
            started = boot + start_ticks/os.sysconf('SC_CLK_TCK')
            logs = [p for p in logs if p.stat().st_mtime >= started-10]
            if not logs:
                continue
            log = max(logs, key=lambda p:p.stat().st_mtime).resolve()
            item = found.setdefault(str(log), {'path': str(log), 'gpu_ids': [], 'pids': []})
            item['pids'].append(proc.name)
            item['gpu_ids'] = sorted(set(item['gpu_ids'] + bindings.get(proc.name, [])))
        except (OSError, ValueError, IndexError):
            continue
    return list(found.values())


class LogReader:
    def __init__(self, path):
        self.path, self.offset, self.inode = Path(path), 0, None
        self.rows, self.metrics, self.metric_epochs = {}, {}, {}
        self.total, self.epoch, self.eta = 0, 0, None
        self.step, self.steps, self.phase = None, None, 'preparing'

    def read(self):
        stat = self.path.stat()
        if self.inode != stat.st_ino or stat.st_size < self.offset:
            self.__init__(str(self.path))
            self.inode = stat.st_ino
        with self.path.open('rb') as stream:
            stream.seek(self.offset)
            for raw in stream:
                if not raw.endswith(b'\n'):
                    break
                self.offset += len(raw)
                line = raw.decode('utf-8', errors='replace')
                self.total = parse_total_from_line(line) or self.total
                parsed = parse_openmmlab_line(line)
                if not parsed:
                    continue
                mode, epoch, eta, metrics = parsed
                self.epoch = epoch
                self.eta = eta if eta is not None else self.eta
                self.phase = 'validating' if mode in ('val', 'test') else 'training'
                self.metrics.update(metrics)
                self.metric_epochs.update({key:epoch for key in metrics})
                self.rows.setdefault(epoch, {}).update(metrics)
                match = STEP.search(line)
                if match:
                    self.step, self.steps = map(int, match.groups())
        history = [dict(epoch=e, metrics=m, loss=m.get('loss')) for e,m in sorted(self.rows.items())]
        best = {}
        for point in history:
            for name, value in point['metrics'].items():
                best[name] = (min if 'loss' in name.lower() else max)(best.get(name, value), value)
        return dict(epoch=self.epoch, total_epochs=self.total, step=self.step, total_steps=self.steps,
                    metrics=dict(self.metrics), metric_epochs=dict(self.metric_epochs), best_metrics=best,
                    loss=self.metrics.get('loss'), metric_name='mIoU', current_iou=self.metrics.get('mIoU'),
                    history=history[-500:], phase=self.phase, eta_seconds=self.eta,
                    updated_at=datetime.fromtimestamp(stat.st_mtime).isoformat())


class Collector:
    def __init__(self, roots=()):
        self.readers, self.known = {}, {}
        self.roots = roots

    def snapshot(self):
        hardware, bindings = gpu_snapshot()
        active = discover(bindings)
        for root in self.roots:
            path = Path(root).expanduser()
            candidates = [path] if path.is_file() else list(path.glob('*.log')) + list(path.glob('*/*.log'))
            for log in candidates:
                if str(log) not in {a['path'] for a in active}:
                    active.append(dict(path=str(log), gpu_ids=[], pids=[]))
        active_paths = {a['path'] for a in active}
        self.known.update({a['path']:a for a in active})
        runs, errors = [], []
        for path, info in self.known.items():
            try:
                reader = self.readers.setdefault(path, LogReader(path))
                run = reader.read()
                if not run['history']:
                    continue
                short = '/'.join(Path(path).parts[-3:-1])
                run.update(run_id=short+' · '+hashlib.sha1(path.encode()).hexdigest()[:5],
                           log_path=path, gpu_ids=info['gpu_ids'], pids=info['pids'], status='training')
                if path not in active_paths:
                    run.update(status='finished' if run['total_epochs'] and run['epoch'] >= run['total_epochs'] else 'stopped')
                    run['phase'] = run['status']
                runs.append(run)
            except (OSError, ValueError) as exc:
                errors.append(type(exc).__name__)
        return dict(runs=runs, hardware=hardware, discovery=dict(logs=len(runs), errors=errors),
                    updated_at=datetime.now().isoformat())


def stream(interval=3, roots=()):
    collector = Collector(roots)
    while True:
        print(json.dumps(collector.snapshot(), ensure_ascii=True, allow_nan=False), flush=True)
        time.sleep(max(1, interval))
