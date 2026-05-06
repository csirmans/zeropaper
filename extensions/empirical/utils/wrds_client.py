"""WRDS client — sends queries to the persistent wrds_server.

Usage:
    from utils.wrds_client import wrds_query, wrds_ping, wrds_start

    # Check if server is running, start if not
    wrds_start()

    # Run a query
    df = wrds_query("SELECT * FROM crsp.msf LIMIT 5")

    # List tables
    tables = wrds_list_tables("crsp")

The client connects to the local wrds_server on port 23847.
If the server isn't running, wrds_start() launches it in the background
and waits for the Duo 2FA to complete.
"""
import json
import socket
import subprocess
import time
import os
import sys

import pandas as pd
from dotenv import load_dotenv

load_dotenv(os.path.expanduser('~/.zeropaper/env'))
load_dotenv()

HOST = '127.0.0.1'
PORT = 23847
UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.expanduser(os.getenv('ZEROPAPER_RUNTIME_DIR', '~/.zeropaper'))
TOKEN_FILE = os.path.join(RUNTIME_DIR, 'wrds_server.token')
LOG_FILE = os.path.join(RUNTIME_DIR, 'wrds_server.log')
MAX_MSG = 10 * 1024 * 1024


def _read_token(required=True):
    try:
        with open(TOKEN_FILE) as f:
            token = f.read().strip()
    except FileNotFoundError:
        if required:
            raise RuntimeError("WRDS server token missing; restart the WRDS server")
        return None
    if not token and required:
        raise RuntimeError("WRDS server token file is empty; restart the WRDS server")
    return token or None


def _send_request(request, timeout=300, require_auth=True):
    """Send a request to the wrds_server and return the response."""
    if require_auth:
        request = {**request, 'token': _read_token(required=True)}
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect((HOST, PORT))

    data = json.dumps(request).encode()
    if len(data) > MAX_MSG:
        raise ValueError(f"WRDS request too large: {len(data)} bytes (max {MAX_MSG})")
    header = f"{len(data):8d}".encode()
    sock.sendall(header + data)

    # Receive response
    raw_len = sock.recv(8)
    msg_len = int(raw_len.decode().strip())
    if msg_len < 0:
        sock.close()
        raise RuntimeError(f"WRDS response length is invalid: {msg_len}")

    chunks = []
    received = 0
    while received < msg_len:
        chunk = sock.recv(min(65536, msg_len - received))
        if not chunk:
            break
        chunks.append(chunk)
        received += len(chunk)

    sock.close()
    return json.loads(b''.join(chunks).decode())

def wrds_ping():
    """Check if wrds_server is running. Returns True/False."""
    try:
        if not _read_token(required=False):
            return False
        resp = _send_request({'cmd': 'ping'}, timeout=5)
        return resp.get('status') == 'ok' and resp.get('auth') == 'token'
    except (ConnectionRefusedError, OSError, RuntimeError, ValueError):
        return False


def _shutdown_legacy_server():
    """Best-effort shutdown for a pre-token server left running after update."""
    try:
        _send_request({'cmd': 'shutdown'}, timeout=5, require_auth=False)
        time.sleep(1)
    except Exception:
        pass

def wrds_start():
    """Start the wrds_server if not already running.

    This triggers Duo 2FA exactly once. Blocks until the server is ready.
    """
    if wrds_ping():
        return True
    os.makedirs(RUNTIME_DIR, mode=0o700, exist_ok=True)

    _shutdown_legacy_server()

    # Find the server script
    server_script = os.path.join(UTILS_DIR, 'wrds_server.py')

    if not os.path.exists(server_script):
        raise FileNotFoundError(f"wrds_server.py not found at {server_script}")

    print("[wrds_client] Starting WRDS server (check Duo notification)...")
    # wrds.Connection silently drops the wrds_password kwarg, so the spawned server
    # needs PGPASSWORD in its env for libpq to authenticate.
    server_env = {**os.environ}
    wrds_pass = os.getenv('WRDS_PASS')
    if wrds_pass:
        server_env['PGPASSWORD'] = wrds_pass
    log = open(LOG_FILE, 'a')
    subprocess.Popen(
        [sys.executable, server_script],
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=server_env,
    )

    # Wait for server to be ready (Duo can take a while)
    for i in range(120):  # 2 minutes max
        time.sleep(1)
        if wrds_ping():
            print("[wrds_client] WRDS server is ready.")
            return True

    raise TimeoutError("WRDS server did not start within 2 minutes. Check Duo.")

def wrds_query(sql, timeout=300):
    """Run a SQL query against WRDS via the persistent server.

    Args:
        sql: SQL query string
        timeout: seconds to wait for response (default 5 min for large queries)

    Returns:
        pandas DataFrame
    """
    resp = _send_request({'cmd': 'query', 'sql': sql}, timeout=timeout)
    if resp['status'] == 'error':
        raise RuntimeError(f"WRDS query failed: {resp['msg']}")
    from io import StringIO
    return pd.read_json(StringIO(resp['data']), orient='split')

def wrds_list_tables(library):
    """List tables in a WRDS library."""
    resp = _send_request({'cmd': 'list_tables', 'library': library})
    if resp['status'] == 'error':
        raise RuntimeError(f"WRDS list_tables failed: {resp['msg']}")
    return resp['tables']

def wrds_describe(library, table):
    """Describe a WRDS table (columns, types, row count)."""
    resp = _send_request({'cmd': 'describe', 'library': library, 'table': table})
    if resp['status'] == 'error':
        raise RuntimeError(f"WRDS describe failed: {resp['msg']}")
    from io import StringIO
    return pd.read_json(StringIO(resp['data']), orient='split')

def wrds_shutdown():
    """Shut down the wrds_server."""
    try:
        _send_request({'cmd': 'shutdown'}, timeout=5)
    except:
        pass
