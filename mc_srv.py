import http.server, socketserver, urllib.request, urllib.error, re, os, json

PORT = int(os.environ.get("MC_PORT", "9120"))
DASH = "http://127.0.0.1:9119"
ROOT = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(ROOT, "mission-control-standalone.html")
PROXY = ("/api/", "/dashboard-plugins/")

# Editable memory/context files surfaced in the Memory & Context view.
HERMES_HOME = os.path.expanduser("~/.hermes")
EDITABLE_FILES = {
    "soul": os.path.join(HERMES_HOME, "SOUL.md"),
    "memory": os.path.join(HERMES_HOME, "memories", "MEMORY.md"),
    "user": os.path.join(HERMES_HOME, "memories", "USER.md"),
}

def read_editable(key):
    path = EDITABLE_FILES.get(key)
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""
    except Exception:
        return None

def write_editable(key, text):
    path = EDITABLE_FILES.get(key)
    if not path:
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return True

def get_token():
    try:
        with urllib.request.urlopen(DASH + "/", timeout=3) as r:
            html = r.read().decode("utf-8", "ignore")
        m = re.search(r'window\.__HERMES_SESSION_TOKEN__="([^"]*)"', html)
        return m.group(1) if m else ""
    except Exception:
        return ""

def proxy(self, method):
    target = DASH + self.path
    body = None
    if method in ("POST", "PUT", "DELETE"):
        ln = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(ln) if ln else None
    req = urllib.request.Request(target, data=body, method=method)
    for k in ("Content-Type", "X-Hermes-Session-Token"):
        v = self.headers.get(k)
        if v:
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            self.send_response(resp.status)
            for h in ("Content-Type", "Content-Length"):
                if h in resp.headers:
                    self.send_header(h, resp.headers[h])
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
    except urllib.error.HTTPError as e:
        data = e.read()
        self.send_response(e.code)
        if "Content-Type" in e.headers:
            self.send_header("Content-Type", e.headers["Content-Type"])
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    except Exception as e:
        self.send_error(502, str(e))

class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def _page(self):
        try:
            tok = get_token()
            with open(HTML, "r", encoding="utf-8") as f:
                page = f.read()
            page = page.replace("__MC_TOKEN__", tok).replace(
                "__MC_BASE__", "http://127.0.0.1:" + str(PORT))
            body = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_error(500, str(e))

    def do_GET(self):
        if self.path.startswith("/vendor/"):
            return super().do_GET()
        if self.path == "/mc-token" or self.path.startswith("/mc-token"):
            tok = get_token()
            body = ('{"token": "%s"}' % tok).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/mc-files"):
            # GET /mc-files?key=soul|memory|user  -> {"key":..,"path":..,"content":..}
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            key = (q.get("key") or [""])[0]
            content = read_editable(key)
            if content is None:
                self.send_error(404, "Unknown or unreadable file key")
                return
            body = ('{"key": "%s", "path": "%s", "content": %s}'
                    % (key, EDITABLE_FILES.get(key, ""), json.dumps(content))).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/mission-control" or self.path.startswith("/mission-control"):
            return self._page()
        if self.path.startswith(PROXY):
            return proxy(self, "GET")
        if self.path in ("/", "/index.html"):
            self.send_response(302)
            self.send_header("Location", "/mission-control")
            self.end_headers()
            return
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith(PROXY):
            return proxy(self, "POST")
        self.send_error(405)

    def do_PUT(self):
        if self.path.startswith("/mc-files"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            key = (q.get("key") or [""])[0]
            ln = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(ln) if ln else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                payload = {}
            text = payload.get("content", "")
            ok = write_editable(key, text)
            body = ('{"ok": %s}' % ("true" if ok else "false")).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith(PROXY):
            return proxy(self, "PUT")
        self.send_error(405)

    def do_DELETE(self):
        if self.path.startswith(PROXY):
            return proxy(self, "DELETE")
        self.send_error(405)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Hermes-Session-Token")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def log_message(self, *a):
        pass

class S(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

if __name__ == "__main__":
    with S(("127.0.0.1", PORT), H) as httpd:
        print(f"Mission Control -> http://127.0.0.1:{PORT}/mission-control", flush=True)
        httpd.serve_forever()
