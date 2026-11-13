"""Addendum 7e3: hard wall-clock deadline for one HTTP call (connect + headers + body).
`requests`' timeout is per socket read; a server that trickles bytes can keep a call alive forever.
DeadlineSession.post(url, ..., timeout=T) enforces T seconds total (T = the already-specified per-call timeout),
closes the connection on expiry and raises requests.exceptions.ReadTimeout (recorded as transport_error/ReadTimeout
by the unchanged callers). Values and request bodies are not changed."""
from __future__ import annotations
import socket, threading, time
import requests


def _total(timeout):
    if isinstance(timeout, (tuple, list)):
        return float(sum(x for x in timeout if x))
    return float(timeout)


def _kill(resp, sess):
    try:
        conn = getattr(resp.raw, "_connection", None) if resp is not None else None
        sock = getattr(conn, "sock", None) if conn is not None else None
        if sock is None and resp is not None:
            fp = getattr(resp.raw, "_fp", None)
            sock = getattr(getattr(getattr(fp, "fp", None), "raw", None), "_sock", None)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
    except Exception:
        pass
    for x in (resp, sess):
        try:
            if x is not None:
                x.close()
        except Exception:
            pass


class DeadlineSession:
    """Drop-in for the `requests.Session().post` used by post_once / sol_review.post / probe3."""

    def __init__(self, grace_s: float = 0.0):
        self.grace_s = grace_s
        self.n_deadline = 0

    def post(self, url, json=None, headers=None, timeout=120, allow_redirects=False, **kw):
        deadline = _total(timeout) + self.grace_s
        t0 = time.monotonic()
        box: dict = {}
        sess = requests.Session()
        expired = threading.Event()

        def run():
            try:
                r = sess.post(url, json=json, headers=headers, timeout=timeout, allow_redirects=allow_redirects,
                              stream=True, **kw)
                box["resp"] = r
                chunks = []
                for c in r.iter_content(chunk_size=1024):
                    if expired.is_set() or time.monotonic() - t0 > deadline:
                        raise TimeoutError("wall_clock_deadline")
                    if c:
                        chunks.append(c)
                r._content = b"".join(chunks)
                r._content_consumed = True
                box["ok"] = r
            except BaseException as e:  # noqa: BLE001 - re-raised in the caller thread
                box["err"] = e

        th = threading.Thread(target=run, name="deadline_http", daemon=True)
        th.start()
        th.join(max(0.0, deadline - (time.monotonic() - t0)))
        if th.is_alive() or isinstance(box.get("err"), TimeoutError):
            expired.set()
            _kill(box.get("resp"), sess)
            th.join(2.0)
            self.n_deadline += 1
            raise requests.exceptions.ReadTimeout(f"wall_clock_deadline_{deadline:.0f}s")
        sess.close()
        if "err" in box:
            raise box["err"]
        return box["ok"]
