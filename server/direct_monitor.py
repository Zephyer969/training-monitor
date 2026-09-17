"""One SSH connection, in-memory collector; no remote install, API or tunnel."""
import base64
import json
from pathlib import Path
import queue
import re
import shlex
import subprocess
import threading
import zlib


def collector_source(interval=3, roots=()):
    modules = {}
    for name in ('openmmlab_log', 'discovery_agent'):
        modules[name] = (Path(__file__).parent/(name+'.py')).read_text(encoding='utf-8')
    return ('import sys, types\n'
            'sys.dont_write_bytecode = True\n'
            'sources = '+repr(modules)+'\n'
            'for name, source in sources.items():\n'
            '    module = types.ModuleType(name)\n'
            '    sys.modules[name] = module\n'
            '    exec(compile(source, name, "exec"), module.__dict__)\n'
            'sys.modules["discovery_agent"].stream('+repr(interval)+', '+repr(list(roots))+')\n')


def collector_command(interval=3, roots=()):
    """Pack the agent into the remote command so SSH stdin stays available for passwords."""

    payload = zlib.compress(collector_source(interval, roots).encode('utf-8'), 9)
    encoded = base64.b64encode(payload).decode('ascii')
    return "import base64,zlib;exec(compile(zlib.decompress(base64.b64decode(%r)),'training-monitor-agent','exec'))" % encoded


class DirectClient:
    def __init__(self, host='', python='auto', interval=3, roots=()):
        if host and (host.startswith('-') or not re.fullmatch(r'[\w.@:\-]+', host)):
            raise ValueError('Invalid SSH host')
        self.host, self.python, self.interval, self.roots = host, python or 'auto', interval, roots
        self.python_candidates = ('python3', 'python') if self.python == 'auto' else (self.python,)
        self.python_index = 0
        self.process = None
        self.events = queue.Queue(maxsize=1)
        self.closed = False
        self.collector = None

    @property
    def active_python(self):
        return self.python_candidates[self.python_index]

    def _start(self):
        remote = shlex.quote(self.active_python) + ' -u -c ' + shlex.quote(collector_command(self.interval, self.roots))
        args = ['ssh', '-T', '-o', 'ConnectTimeout=8', '-o', 'ServerAliveInterval=10',
                '-o', 'ServerAliveCountMax=2', self.host,
                remote]
        # stdin remains attached to the user's terminal for password prompts.
        try:
            self.process = subprocess.Popen(args, stdin=None, stdout=subprocess.PIPE,
                                            text=True, encoding='utf-8', bufsize=1)
        except FileNotFoundError as exc:
            raise ConnectionError('本机未找到 ssh，请安装或启用 OpenSSH 客户端') from exc
        except OSError as exc:
            raise ConnectionError(f'无法启动本机 ssh: {exc}') from exc
        process = self.process
        def receive():
            for line in process.stdout:
                try:
                    state = json.loads(line)
                    if not isinstance(state, dict) or 'hardware' not in state:
                        continue
                    try:
                        self.events.get_nowait()
                    except queue.Empty:
                        pass
                    self.events.put_nowait(state)
                except (ValueError, queue.Full):
                    pass
        threading.Thread(target=receive, daemon=True).start()

    def _try_python_fallback(self):
        """Use ``python`` when ``python3`` is not installed on the host.

        SSH authentication/transport failures use exit code 255, so they do
        not trigger a second password prompt with another interpreter name.
        """

        if self.python_index + 1 >= len(self.python_candidates):
            return False
        if self.process is None:
            return False
        return_code = self.process.poll()
        if return_code is None or return_code == 255:
            return False
        self.python_index += 1
        self._start()
        return True

    def fetch(self, history_limit=500):
        if self.closed:
            raise ConnectionError('监控已关闭')
        if not self.host:
            from discovery_agent import Collector
            if self.collector is None:
                self.collector = Collector(self.roots)
            return self.collector.snapshot()
        if self.process is None or self.process.poll() is not None:
            if not self._try_python_fallback():
                self._start()
        try:
            return self.events.get(timeout=12)
        except queue.Empty:
            if self.process.poll() is not None:
                if self._try_python_fallback():
                    try:
                        return self.events.get(timeout=12)
                    except queue.Empty:
                        pass
                raise ConnectionError('SSH 连接失败，请检查服务器地址及 SSH 登录')
            raise TimeoutError('等待 SSH 登录或服务器数据')

    def close(self):
        self.closed = True
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
