"""The supervisor: `python -m core` runs this small parent, which runs the real core as its child.

Like a hardware watchdog, something very simple watches the complicated thing. The child is
`python -m core serve`; it touches a heartbeat file every few seconds and shares this console
(stdin and stdout are passed through, so the CLI works as before). Its stderr is copied to ours and
the last lines are kept, so a crash can be explained.

When the child exits:
* 0: stop (Ctrl-C, `systemctl stop`, `--idle-exit`); the supervisor exits too.
* 75 (RESTART): it asked to be restarted (`$admin restart`); start a fresh one at once.
* anything else: a crash; start a fresh one after 1, 5, 30, then 60 s, and give up after
  `max_crashes` crashes within `window_s` rather than loop forever.
A child whose heartbeat stops for `hang_s` (or that never beats within `grace_s` of starting) is hung:
it is killed with everything it started, and restarted like a crash.

Before starting the next child the supervisor writes why (`reason.json`: requested, crash or hang,
when, the exit code, the end of the error) for it to report to the owner once it is connected. The
supervisor itself never talks to any platform and imports nothing from the core.

Nothing the core starts outlives it. The core carries a mark in its environment (`CORE_TREE`), and so does
everything it starts; whenever a core has exited, whatever still carries the mark is ended. What a module starts
for the person at this computer (a document opened, the clipboard served) is started without it
(`contracts.handed_over`). One install runs one supervisor: a lock says so, and the first thing a supervisor does
is end what an earlier run of this install left behind (one killed outright, say).

`--lifeline` is for an app that runs the core (the desktop app): it holds the other end of this process's stdin,
and when that ends, however the app ended, the core is stopped. A stop is also asked of the core through a file
(`CORE_STOP`), which is how it stops cleanly on Windows, where there is no SIGTERM.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from typing import Sequence

RESTART = 75
ALREADY = 73  # this install already runs a supervisor: nothing was started
BACKOFF = (1, 5, 30, 60)
TREE = "CORE_TREE"  # the mark the core and everything it starts carry (contracts.handed_over leaves it out)
ROOT = Path(__file__).resolve().parents[1]


def say(text: str) -> None:
    print(f"[supervisor] {text}", file=sys.stderr, flush=True)


def kill_tree(process: subprocess.Popen, grace_s: float) -> None:
    """Ask the child to stop, then end it and everything it started (shells, ffmpeg) if it does not."""
    try:
        import psutil
        descendants = psutil.Process(process.pid).children(recursive=True)
    except Exception:
        descendants = []
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(grace_s)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    for child in descendants:
        try:
            child.kill()
        except Exception:
            pass


def mark_of(arguments: Sequence[str], root: Path = ROOT) -> str:
    """Which install and configuration this is: the folder the core is in and the --config given."""
    config = ""
    for index, item in enumerate(arguments):
        if item == "--config" and index + 1 < len(arguments):
            config = arguments[index + 1]
        elif item.startswith("--config="):
            config = item.split("=", 1)[1]
    text = f"{root.resolve()}|{Path(config).resolve() if config else ''}"
    return "core-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def marked(mark: str) -> list:
    """This user's processes that carry `mark`: the core, and whatever it started that is still running."""
    try:
        import psutil
    except ImportError:
        return []
    found = []
    for process in psutil.process_iter():
        if process.pid == os.getpid():
            continue
        try:
            if process.environ().get(TREE) == mark:
                found.append(process)
        except (psutil.Error, OSError):  # another user's, or already gone
            continue
    return found


def end(processes: list, grace_s: float) -> None:
    """Ask each to stop, and end those that have not within `grace_s`."""
    if not processes:
        return
    import psutil
    for process in processes:
        try:
            process.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(processes, timeout=grace_s)
    for process in alive:
        try:
            process.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(alive, timeout=grace_s)


class Lock:
    """An OS lock on a file, which the OS lets go of however this process ends; beside it, who holds it."""

    def __init__(self, mark: str, folder: Path | None = None):
        folder = folder or Path(tempfile.gettempdir())
        self.path, self.holder_path = folder / f"{mark}.lock", folder / f"{mark}.pid"
        self.handle = None

    def take(self) -> bool:
        handle = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.handle = handle
        self.holder_path.write_text(str(os.getpid()), encoding="utf-8")
        return True

    def holder(self) -> str:
        try:
            return self.holder_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def release(self) -> None:
        if self.handle is not None:
            self.holder_path.unlink(missing_ok=True)
            self.handle.close()  # (closing lets go of the lock)
            self.handle = None


class Supervisor:
    def __init__(self, command: Sequence[str], *, hang_s: float = 60.0, grace_s: float = 180.0,
                 backoff: Sequence[float] = BACKOFF, max_crashes: int = 5, window_s: float = 600.0,
                 poll_s: float = 1.0, stop_grace_s: float = 20.0, mark: str | None = None,
                 lifeline: int | None = None, lock_folder: Path | None = None):
        """`mark`: this install's mark (`mark_of`); without one (tests), nothing is locked or swept. `lifeline`: a
        file descriptor to read until it ends, then stop (`--lifeline`: stdin)."""
        self.command = list(command)
        self.mark, self.lifeline, self.lock_folder = mark, lifeline, lock_folder
        self.hang_s, self.grace_s, self.backoff = hang_s, grace_s, tuple(backoff)
        self.max_crashes, self.window_s, self.poll_s, self.stop_grace_s = max_crashes, window_s, poll_s, stop_grace_s
        self.folder: Path | None = None  # made by run() and removed when it ends
        self.stopping = False
        self.child: subprocess.Popen | None = None

    # ---- stopping on request ----------------------------------------------------------------------
    def _stop(self, signum=None, frame=None) -> None:
        self.stopping = True
        try:
            self.stop_file.write_text("stop", encoding="utf-8")  # the core reads it within a second
        except (OSError, TypeError):
            pass
        if (os.name != "nt" and self.child is not None and self.child.poll() is None
                and signum != getattr(signal, "SIGINT", None)):
            # Ctrl-C already reached the child through the console; other signals are passed on. (On Windows
            # terminate() would kill it outright: the file asks it to stop cleanly.)
            try:
                self.child.terminate()
            except OSError:
                pass

    def _watch_lifeline(self) -> None:
        """Read the lifeline until it ends: the app holding its other end has closed it, or has ended, however
        it ended (the OS closes it then)."""
        try:
            while os.read(self.lifeline, 4096):
                pass
        except OSError:
            pass
        if not self.stopping:
            say("the app that runs me has closed; stopping")
            self._stop("lifeline")

    def _sweep(self, grace_s: float = 2.0) -> None:
        """End whatever a core of this install started and left running."""
        if self.mark:
            left = marked(self.mark)
            if left:
                say(f"ending {len(left)} process{'es' if len(left) > 1 else ''} the core left running: "
                    + ", ".join(sorted({_name(process) for process in left})))
                end(left, grace_s)

    def _install(self) -> None:
        for name in ("SIGTERM", "SIGINT", "SIGHUP"):
            if not hasattr(signal, name):
                continue
            number = getattr(signal, name)
            if signal.getsignal(number) is signal.SIG_IGN:
                continue  # `nohup` (or a shell) asked to ignore it: so do we, and so does the core after us
            try:
                signal.signal(number, self._stop)
            except (ValueError, OSError):
                pass

    # ---- one child ----------------------------------------------------------------------------------
    def _spawn(self) -> tuple[subprocess.Popen, deque, threading.Thread]:
        self.heartbeat.unlink(missing_ok=True)
        self.stop_file.unlink(missing_ok=True)
        environment = {**os.environ, "CORE_HEARTBEAT": str(self.heartbeat), "CORE_RESTART_REASON": str(self.reason),
                       "CORE_STOP": str(self.stop_file), "CORE_SUPERVISOR_PID": str(os.getpid())}
        if self.mark:
            environment[TREE] = self.mark
        # With a lifeline, stdin is the app's, not a console: the core reads nothing from it.
        child = subprocess.Popen(self.command, stderr=subprocess.PIPE, env=environment,
                                 stdin=subprocess.DEVNULL if self.lifeline is not None else None)
        tail: deque[str] = deque(maxlen=40)

        def copy():
            for line in child.stderr:
                try:
                    sys.stderr.buffer.write(line)
                    sys.stderr.flush()
                except (OSError, ValueError):
                    pass
                tail.append(line.decode("utf-8", "replace").rstrip())
        reader = threading.Thread(target=copy, name="supervisor-stderr", daemon=True)
        reader.start()
        return child, tail, reader

    def _watch(self, child: subprocess.Popen) -> str | None:
        """Wait for the child to exit. Returns "hang" if it stopped beating and was killed.

        Silence is measured on the monotonic clock, from the last time the heartbeat file's content
        changed: the wall clock can jump (a Raspberry Pi setting its time after boot, a laptop waking up)
        and must never make a healthy core look hung."""
        started = time.monotonic()
        seen, beaten = None, None
        while child.poll() is None:
            time.sleep(self.poll_s)
            if self.stopping:
                waited = time.monotonic()
                while child.poll() is None and time.monotonic() - waited < self.stop_grace_s:
                    time.sleep(self.poll_s)
                if child.poll() is None:
                    kill_tree(child, 1.0)
                return None
            try:
                content = self.heartbeat.read_text(encoding="utf-8")
            except OSError:
                content = None
            if content is not None and content != seen:
                seen, beaten = content, time.monotonic()
            silent = time.monotonic() - (beaten if beaten is not None else started)
            if silent > (self.hang_s if beaten is not None else self.grace_s):
                say(f"no heartbeat for {silent:.0f} s; the core is hung, restarting it")
                kill_tree(child, 10.0)
                return "hang"
        return None

    # ---- the loop -------------------------------------------------------------------------------------
    @property
    def heartbeat(self) -> Path:
        return self.folder / "heartbeat"

    @property
    def reason(self) -> Path:
        return self.folder / "reason.json"

    @property
    def stop_file(self) -> Path:
        return self.folder / "stop"

    def run(self) -> int:
        lock = Lock(self.mark, self.lock_folder) if self.mark else None
        if lock is not None and not lock.take():
            say(f"this install already runs (supervisor pid {lock.holder() or 'unknown'}); not starting another")
            return ALREADY
        self.folder = Path(tempfile.mkdtemp(prefix="core-supervisor-"))
        self._install()
        if self.lifeline is not None:
            threading.Thread(target=self._watch_lifeline, name="supervisor-lifeline", daemon=True).start()
        crashes: deque[float] = deque()
        try:
            self._sweep()  # what an earlier run of this install left behind (it was killed outright, say)
            while True:
                if self.stopping:
                    return 0
                child, tail, reader = self._spawn()
                self.child = child
                try:
                    hung = self._watch(child)
                except KeyboardInterrupt:  # Windows: Ctrl-C reaches both processes
                    self.stopping = True
                    hung = self._watch(child)
                code = child.wait()
                self._sweep()  # first: what it left running holds its end of the error pipe
                reader.join(timeout=2)
                if not reader.is_alive():
                    # (closing it under a reader still waiting on it would wait as long as whatever else holds
                    # the pipe, such as something handed over: the reader ends with the pipe instead)
                    child.stderr.close()
                if self.stopping or (code == 0 and not hung):
                    return 0
                if code == RESTART and not hung:
                    if not self.reason.exists():
                        self._write({"reason": "requested"})
                    say("restarting the core as requested")
                    continue
                now = time.time()
                crashes.append(now)
                while crashes and now - crashes[0] > self.window_s:
                    crashes.popleft()
                if len(crashes) >= self.max_crashes:
                    say(f"the core failed {len(crashes)} times within {self.window_s / 60:.0f} minutes; giving up. "
                        "Fix the error above, then start it again.")
                    return 1
                error = [line for line in tail if line.strip()]
                self._write({"reason": hung or "crash", "code": code, "detail": error[-3:] if error else [],
                             "restarts": len(crashes)})
                delay = self.backoff[min(len(crashes), len(self.backoff)) - 1]
                say(f"the core {'hung' if hung else f'exited with code {code}'}; starting it again in {delay:g} s")
                waited = time.time()
                while time.time() - waited < delay:
                    if self.stopping:
                        return 0
                    time.sleep(min(self.poll_s, delay))
        finally:
            if self.child is not None and self.child.poll() is None:
                kill_tree(self.child, self.stop_grace_s)
            self._sweep()
            shutil.rmtree(self.folder, ignore_errors=True)
            if lock is not None:
                lock.release()

    def _write(self, data: dict) -> None:
        data.setdefault("at", time.time())
        self.reason.write_text(json.dumps(data), encoding="utf-8")


def _name(process) -> str:
    try:
        return process.name()
    except Exception:
        return str(process.pid)


def main(arguments: Sequence[str]) -> int:
    lifeline = "--lifeline" in arguments
    arguments = [item for item in arguments if item != "--lifeline"]
    return Supervisor([sys.executable, "-m", "core", "serve", *arguments], mark=mark_of(arguments),
                      lifeline=sys.stdin.fileno() if lifeline else None).run()
