"""Bounded readiness for disposable loopback API processes in browser tests."""
import subprocess
import time

import requests


def wait_for_api(server, base, timeout=45):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline and server.poll() is None:
        try:
            if requests.get(base+'/events/api/health',timeout=.5).status_code==200:
                return
        except requests.RequestException:
            pass
        time.sleep(.1)
    server.terminate()
    try:server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill();server.wait(timeout=5)
    raise RuntimeError('disposable loopback API did not become ready within bounded deadline')
