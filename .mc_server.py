import http.server, socketserver, urllib.request, re, os, sys

PORT = int(os.environ.get("MC_PORT", "9120"))
DASH = "http://127.0.0.1:9119"
ROOT = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(ROOT, "mission-control-standalone.html")
VENDOR = os.path.join(ROOT, "vendor")

def get_token():
    try:
        with urllib.request.urlopen(DASH + "/", timeout=3) as r:
            html = r.read().decode("utf-8", "ignore")
        m = re.search(r'window\.__HERMES_SESSION_TOKEN__="([^"]*)"', html)
        return m.group(1) if m else ""
    except Exception:
        return ""

class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)
    def do_GET(self):
        if self.path.startswith("/vendor/") or self.path in ("/", "/index.html"):
            return super().do_GET()
        if self.path == "/mission-control" or self.path.startswith("/mission-control"):
            try:
                tok = get_token()
                with open(HTML, "r", encoding="utf-8") as f:
                    page = f.read()
                page = page.replace("__MC_TOKEN__", tok).replace("__MC_BASE__", DASH)
                body = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self.send_error(500, str(e))
            return
        return super().do_GET()
    def log_message(self, *a):
        pass

class S(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True

if __name__ == "__main__":
    with S(("127.0.0.1", PORT), H) as httpd:
        print(f"Mission Control -> http://127.0.0.1:{PORT}/mission-control", flush=True)
        httpd.serve_forever()
