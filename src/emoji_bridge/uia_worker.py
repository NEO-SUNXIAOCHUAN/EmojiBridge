"""Short-lived UIA helper: one per operation, no service or cached UI handles."""
import json
import queue
import subprocess
from .client_sources import powershell_executable
import threading
import time

from .windows import StopAutomation

UIA_FAILURES=frozenset(('uia_worker_stopped_no_retry','uia_startup_timeout','uia_helper_exited',
                       'uia_response_timeout','uia_protocol_error','uia_helper_io_error'))

class UIAWorker:
    def __init__(self,script):
        self.process=subprocess.Popen([
            str(powershell_executable()),'-NoProfile',
            '-ExecutionPolicy','Bypass','-File',str(script),'-Server'],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW,bufsize=1)
        self.responses=queue.Queue()
        self.ready=False
        def receive():
            try:
                for line in self.process.stdout:self.responses.put(line)
            finally:self.responses.put(None)
        self.thread=threading.Thread(target=receive,daemon=True);self.thread.start()

    def _response(self,cancel_check,timeout_seconds,timeout_reason):
        deadline=time.monotonic()+timeout_seconds
        while True:
            if cancel_check:cancel_check()
            remaining=deadline-time.monotonic()
            if remaining<=0:raise StopAutomation(timeout_reason)
            try:line=self.responses.get(timeout=min(.05,remaining));break
            except queue.Empty:continue
        if cancel_check:cancel_check()
        if line is None:raise StopAutomation('uia_helper_exited')
        try:value=json.loads(line.lstrip('\ufeff'))
        except (ValueError,TypeError):raise StopAutomation('uia_protocol_error') from None
        if not isinstance(value,dict):raise StopAutomation('uia_protocol_error')
        return value

    def request(self,cancel_check=None,timeout_seconds=15,**payload):
        try:
            if cancel_check:cancel_check()
            # PowerShell/Add-Type startup is separate from a control operation.
            # No action is queued until startup completes; neither is retried.
            if not getattr(self,'ready',True):
                ready=self._response(cancel_check,15,'uia_startup_timeout')
                if ready!={'worker_ready':True}:raise StopAutomation('uia_protocol_error')
                self.ready=True
            self.process.stdin.write(json.dumps(payload,ensure_ascii=True)+'\n');self.process.stdin.flush()
            return self._response(cancel_check,timeout_seconds,'uia_response_timeout')
        except StopAutomation:
            # Discard the in-flight helper response; never reuse it for another
            # request. This terminates our helper only, not the client process.
            self.close();raise
        except (OSError,ValueError):
            self.close();raise StopAutomation('uia_helper_io_error') from None

    def close(self):
        try:
            if self.process.stdin and not self.process.stdin.closed:self.process.stdin.close()
        except OSError:pass
        try:self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.process.terminate();self.process.wait(timeout=2)
        self.thread.join(timeout=1)
        if self.process.stdout and not self.process.stdout.closed:self.process.stdout.close()
