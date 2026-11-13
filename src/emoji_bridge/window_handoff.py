"""Bound the existing task-start input-queue handoff in an owned process.

The parent never attaches its UI or worker thread to a client's message queue.
A hung client can only stall this disposable helper, which has a hard deadline.
"""
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import time

from .paths import APP_ROOT
from .windows import StopAutomation,guard,user


def handoff(window,exe,previous,cancel_check=None,timeout=3):
    def check():
        if cancel_check:cancel_check()
        guard(window,exe,foreground=False)
        if user.GetForegroundWindow() not in (previous,window.hwnd):
            raise StopAutomation('foreground_changed')
        if any(user.GetAsyncKeyState(k)&0x8000 for k in (1,2,16,17,18,27,91,92)):
            raise StopAutomation('user_input_in_progress')
    check()
    process=subprocess.Popen([sys.executable,str(APP_ROOT/'scripts/window_handoff.py')],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
        encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        process.stdin.write(json.dumps({'window':asdict(window),'exe':str(exe),'previous':previous})+'\n')
        process.stdin.flush();process.stdin.close()
        deadline=time.monotonic()+timeout
        while process.poll() is None:
            check()
            if time.monotonic()>=deadline:raise StopAutomation('foreground_handoff_timeout')
            time.sleep(.03)
        check()
        try:result=json.loads(process.stdout.read())
        except (ValueError,OSError):raise StopAutomation('foreground_handoff_unavailable')
        if not result.get('ok'):raise StopAutomation(result.get('reason','foreground_switch_denied'))
        guard(window,exe)
    finally:
        if process.poll() is None:
            process.terminate();process.wait(timeout=2)
        if not process.stdin.closed:process.stdin.close()
        process.stdout.close()
