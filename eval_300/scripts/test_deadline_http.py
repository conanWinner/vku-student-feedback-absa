"""Addendum 7e3 offline test: local dummy server that trickles bytes forever. No network beyond 127.0.0.1."""
import json, socket, threading, time, sys
import requests
import deadline_http as DH
import run_eval as E, run_eval2 as R
from review_pilot.client import post_once

OKBODY = json.dumps({"model": "gemini-3.8-flash-n", "choices": [{"message": {"content": json.dumps(
    {"aspects": [{"aspect": a, "decision": "absent", "evidence": ""} for a in E.ASPECTS]})}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1}}).encode()

def handle(c):
    try:
        req = b""
        while b"\r\n\r\n" not in req:
            req += c.recv(65536)
        path = req.split(b" ")[1].decode()
        if path.endswith("/ok") or path.endswith("/v1/chat/completions"):
            c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(OKBODY) + OKBODY)
        elif path.endswith("/trickle_body"):
            c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100000000\r\n\r\n")
            while True:
                c.sendall(b" "); time.sleep(0.3)
        elif path.endswith("/trickle_chunked"):
            c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n")
            while True:
                c.sendall(b"1\r\n \r\n"); time.sleep(0.3)
        elif path.endswith("/trickle_headers"):
            c.sendall(b"HTTP/1.1 200 OK\r\n")
            while True:
                c.sendall(b"X-K: v\r\n"); time.sleep(0.3)
        elif path.endswith("/silent"):
            time.sleep(3600)
    except OSError:
        pass
    finally:
        try: c.close()
        except OSError: pass

def serve(srv):
    while True:
        c, _ = srv.accept()
        threading.Thread(target=handle, args=(c,), daemon=True).start()

srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); srv.bind(("127.0.0.1", 0)); srv.listen(16)
port = srv.getsockname()[1]; base = f"http://127.0.0.1:{port}"
threading.Thread(target=serve, args=(srv,), daemon=True).start()
fails = []
def check(name, cond, detail=""):
    print(("ok  " if cond else "FAIL"), name, detail, flush=True)
    if not cond: fails.append(name)

ds = DH.DeadlineSession()
# 1. normal call passes through unchanged
r = ds.post(base + "/ok", json={"a": 1}, headers={}, timeout=3)
check("normal 200 json", r.status_code == 200 and r.json()["model"] == "gemini-3.8-flash-n" and r.text.startswith("{"))
# 2-5. trickle / silent: must raise ReadTimeout within deadline (+2 s slack)
for path in ("/trickle_body", "/trickle_chunked", "/trickle_headers", "/silent"):
    t0 = time.monotonic(); err = None
    try:
        ds.post(base + path, json={}, headers={}, timeout=3)
    except requests.exceptions.ReadTimeout as e:
        err = e
    except Exception as e:
        err = e
    dt = time.monotonic() - t0
    check(f"{path} -> ReadTimeout within deadline", isinstance(err, requests.exceptions.ReadTimeout) and dt < 5.5, f"{type(err).__name__} {dt:.1f}s")
# 6. control: plain requests with the same per-read timeout does NOT stop the trickle within 8 s (the bug)
box = {}
def plain():
    t0 = time.monotonic()
    try: requests.post(base + "/trickle_body", json={}, timeout=3)
    except Exception as e: box["e"] = type(e).__name__
    box["dt"] = time.monotonic() - t0
th = threading.Thread(target=plain, daemon=True); th.start(); th.join(8)
check("control: plain requests still hung after 8 s (bug reproduced)", th.is_alive(), str(box))
# 7. through the unchanged callers (post_once via CapSess) with URL redirected to the dummy server
class Redirect:
    def __init__(self, inner, path): self.inner, self.path = inner, path
    def post(self, url, **k):
        k["timeout"] = 3  # shrink only for the test
        return self.inner.post(base + self.path, **k)
cs = R.CapSess(); cs.s = Redirect(DH.DeadlineSession(), "/trickle_chunked")
t0 = time.monotonic(); rec = post_once(cs, "câu", "ag/gemini-3.8-flash-low", "dummy", E.PSHA).as_dict()
check("post_once trickle -> transport_error ReadTimeout", rec["status"] == "transport_error" and rec["error"] == "ReadTimeout", f"{rec['status']} {rec['error']} {time.monotonic()-t0:.1f}s")
cs.s = Redirect(DH.DeadlineSession(), "/v1/chat/completions")
rec = E.guard(post_once(cs, "câu", "ag/gemini-3.8-flash-low", "dummy", E.PSHA).as_dict(), "ag/gemini-3.8-flash-low")
check("post_once normal -> ok vote", rec["status"] == "ok" and rec["annotation"], rec["status"])
import sol_review as S
cs.s = Redirect(DH.DeadlineSession(), "/silent")
srec = S.post(cs, {"item_id": "X", "cache_key": "k", "anon_map": {}, "body": {"model": "cx/gpt-6.1-sol"}, "sentence": "câu"}, "dummy")
check("sol_review.post silent -> transport_error ReadTimeout", srec["status"] == "transport_error" and srec["error"] == "ReadTimeout", srec["status"])
print("DEADLINE_TEST_OK" if not fails else f"DEADLINE_TEST_FAIL {fails}")
sys.exit(1 if fails else 0)
