import http.server, socketserver, urllib.request, urllib.error, re, os, json, subprocess

PORT = int(os.environ.get("MC_PORT", "9120"))
DASH = "http://127.0.0.1:9119"
ROOT = os.path.dirname(os.path.abspath(__file__))
HTML = os.path.join(ROOT, "mission-control-standalone.html")
PROXY = ("/api/", "/dashboard-plugins/")

# Editable memory/context files surfaced in the Memory & Context view.
HERMES_HOME = os.path.expanduser("~/.hermes")

def profile_home(profile):
    # Hermes stores each profile as an isolated instance under
    # ~/.hermes/profiles/<name> (its own config, skills, memory, cron).
    if not profile or profile == "default":
        return HERMES_HOME
    return os.path.join(HERMES_HOME, "profiles", profile)

def editable_paths(profile):
    home = profile_home(profile)
    return {
        "soul": os.path.join(home, "SOUL.md"),
        "memory": os.path.join(home, "memories", "MEMORY.md"),
        "user": os.path.join(home, "memories", "USER.md"),
    }

def read_editable(key, profile="default"):
    paths = editable_paths(profile)
    path = paths.get(key)
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""
    except Exception:
        return None

def write_editable(key, text, profile="default"):
    paths = editable_paths(profile)
    path = paths.get(key)
    if not path:
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return True

def config_path(profile):
    # Hermes stores config at ~/.hermes/config.yaml (default) or
    # ~/.hermes/profiles/<name>/config.yaml (per profile).
    home = profile_home(profile)
    return os.path.join(home, "config.yaml")

def modify_config(profile, op, payload):
    """Hermes-native config edit: read-modify-write config.yaml.
    op 'set_model' -> set top-level 'model'.
    op 'add_provider' -> append to 'custom_providers' list (dedupe by name)."""
    try:
        import yaml
    except ImportError:
        raise RuntimeError("PyYAML not installed in this Python; cannot edit config.yaml")
    path = config_path(profile)
    cfg = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    if op == "set_model":
        cfg["model"] = payload.get("model")
    elif op == "add_provider":
        cp = cfg.get("custom_providers") or []
        entry = {k: payload.get(k) for k in ("name", "api_mode", "base_url", "model") if payload.get(k) is not None}
        cp = [e for e in cp if e.get("name") != entry.get("name")]
        cp.append(entry)
        cfg["custom_providers"] = cp
    else:
        raise ValueError("unknown op: " + str(op))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, default_flow_style=False)
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
            # GET /mc-files?key=soul|memory|user[&profile=name]
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            key = (q.get("key") or [""])[0]
            profile = (q.get("profile") or ["default"])[0]
            paths = editable_paths(profile)
            content = read_editable(key, profile)
            if content is None:
                self.send_error(404, "Unknown or unreadable file key")
                return
            body = ('{"key": "%s", "profile": "%s", "path": "%s", "content": %s}'
                    % (key, profile, paths.get(key, ""), json.dumps(content))).encode("utf-8")
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
        if self.path.startswith("/mc-profile"):
            # POST /mc-profile  body {"name","clone","clone_all","description"}
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            ln = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(ln) if ln else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                payload = {}
            name = (payload.get("name") or "").strip()
            import re
            if not re.match(r"^[a-z0-9][a-z0-9_-]*$", name):
                self.send_error(400, "Invalid profile name (lowercase letters, numbers, - and _)")
                return
            import subprocess
            hermes = os.path.join(HERMES_HOME, "hermes-agent", "venv", "bin", "hermes")
            if not os.path.exists(hermes):
                hermes = "hermes"
            cmd = [hermes, "profile", "create", name]
            if payload.get("clone_all"):
                cmd.append("--clone-all")
            elif payload.get("clone"):
                cmd.append("--clone")
            if payload.get("description"):
                cmd += ["--description", payload["description"]]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            except Exception as e:
                self.send_error(500, "failed to run hermes: %s" % e)
                return
            if res.returncode != 0:
                self.send_error(500, (res.stderr or res.stdout or "create failed").strip())
                return
            body = ('{"ok": true, "name": "%s"}' % name).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith(PROXY):
            return proxy(self, "POST")
        self.send_error(405)

    def do_PUT(self):
        if self.path.startswith("/mc-config"):
            # PUT /mc-config?op=set_model&model=X[&profile=P]
            # PUT /mc-config?op=add_provider[&profile=P]  body {name,api_mode,base_url,model}
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            op = (q.get("op") or [""])[0]
            profile = (q.get("profile") or ["default"])[0]
            ln = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(ln) if ln else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                payload = {}
            if op == "set_model":
                payload = {"model": (q.get("model") or [""])[0] or payload.get("model")}
            try:
                modify_config(profile, op, payload)
            except Exception as e:
                self.send_error(500, "config edit failed: %s" % e)
                return
            if op == "set_model" and profile == "default":
                # Reflect into the running default profile via hermes CLI (best-effort).
                try:
                    hermes = os.path.join(HERMES_HOME, "hermes-agent", "venv", "bin", "hermes")
                    if not os.path.exists(hermes):
                        hermes = "hermes"
                    mdl = payload.get("model") or ""
                    if mdl:
                        subprocess.run([hermes, "config", "set", "model", mdl], capture_output=True, text=True, timeout=30)
                except Exception:
                    pass
            body = ('{"ok": true, "op": "%s"}' % op).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/mc-files"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            key = (q.get("key") or [""])[0]
            profile = (q.get("profile") or ["default"])[0]
            ln = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(ln) if ln else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                payload = {}
            text = payload.get("content", "")
            ok = write_editable(key, text, profile)
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
