"""PM-to-launch handoff. Exact owned files only; no installation or process launch.

The accepted inventory must be produced/approved by an installer outside this
module. Exact hashes are not proof of dependency completeness or native safety.
"""
import hashlib
import json
import os
from pathlib import PurePosixPath
import re
import stat

HOST_COMMIT = "d923a5eb487a17c0a68801bba9ef0f56c81040a8"
HUD_COMMIT = "004c18a7bc54e1297833b2ceb1aec11417bfdfe9"
LOCK_SHA = "16300cf807347b7fcfa3c19963f5fe950913fdb3e41e3c649ea724bc7dc997da"
PROJECT_SHA = "ff41b097147124ff2eb51a437d5f44eddea35104900c1c79c7edfb8b7352d901"
RELEASE_JS_SHA = "c6ed9c524e3d74a6bf9e911f999f32c2f865c9dce69fdc82810935af084447d6"
CODES = frozenset(("schema", "binding", "path", "file", "facts", "runtime", "plan"))


class Refused(ValueError):
    def __init__(self, code):
        super().__init__(code if code in CODES else "binding")


def need(ok, code="binding"):
    if ok is not True:
        raise Refused(code) from None


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return type(value) is str and re.fullmatch("[a-f0-9]{64}", value) is not None


def decode(raw):
    need(type(raw) is bytes and 0 < len(raw) <= 2*1024**2, "schema")
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, "schema"); result[key] = value
        return result
    def constant(_):
        raise Refused("schema")
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except Exception:
        raise Refused("schema") from None


def relative(value):
    return (type(value) is str and 0 < len(value) <= 2048 and not value.startswith("/")
            and str(PurePosixPath(value)) == value and ".." not in PurePosixPath(value).parts
            and value != "." and all(32 <= ord(c) < 127 for c in value))


def file_stamp(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)


class BoundFiles:
    """Real no-follow FD traversal; no listdir/glob/fallback or writes.

    Each read is bounded and rechecks the leaf. It is a time-of-read observation,
    not an OS namespace lock or permission to use an unbound manifest.
    """
    def __init__(self, root, files):
        need(type(root) is str and re.fullmatch("/private/tmp/hermes-022-run-[a-f0-9]{32}", root) is not None, "path")
        need(type(files) is list and 6 <= len(files) <= 8192, "schema")
        self.root = root
        self.rows = {}
        total = 0
        for row in files:
            need(type(row) is dict and set(row) == {"path", "bytes", "sha256", "kind"}, "schema")
            need(relative(row["path"]) and row["path"].casefold() not in self.rows, "path")
            need(row["kind"] in ("text", "binary") and type(row["bytes"]) is int
                 and 0 <= row["bytes"] <= (2*1024**2 if row["kind"] == "text" else 512*1024**2)
                 and digest(row["sha256"]), "schema")
            self.rows[row["path"].casefold()] = dict(row)
            total += row["bytes"]
        need(total <= 1024**3, "schema")
        self.failed = False

    def _read(self, name, capture):
        need(not self.failed and relative(name) and name.casefold() in self.rows, "path")
        row = self.rows[name.casefold()]
        need(row["path"] == name and (not capture or row["kind"] == "text"), "path")
        dirs = []; fd = None; result = None; error = False
        try:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            directory = os.open("/", flags); dirs.append(directory)
            parts = PurePosixPath(self.root + "/" + name).parts[1:]
            for item in parts[:-1]:
                directory = os.open(item, flags, dir_fd=directory); dirs.append(directory)
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            start = os.fstat(fd)
            need(stat.S_ISREG(start.st_mode) and start.st_nlink == 1 and start.st_size == row["bytes"], "file")
            h = hashlib.sha256(); chunks = []; size = 0
            while True:
                block = os.read(fd, min(262144, row["bytes"]-size+1))
                if not block: break
                size += len(block); need(size <= row["bytes"], "file"); h.update(block)
                if capture: chunks.append(block)
            end = os.fstat(fd); named = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
            need(file_stamp(start) == file_stamp(end) == file_stamp(named)
                 and stat.S_ISREG(named.st_mode) and size == row["bytes"] and h.hexdigest() == row["sha256"], "binding")
            result = b"".join(chunks) if capture else h.hexdigest()
        except BaseException:
            error = True
        finally:
            for owned in ([fd] if fd is not None else []) + list(reversed(dirs)):
                try: os.close(owned)
                except BaseException: error = True
        if error:
            self.failed = True
            raise Refused("file") from None
        return result

    def read(self, name):
        return self._read(name, True)

    def verify_all(self):
        need(not self.failed)
        for row in self.rows.values():
            self._read(row["path"], False)
        return len(self.rows)


def _inspect_handoff(raw, expected_manifest_sha, root, reader_factory):
    """Validate installed records before any startup plan can be constructed."""
    need(digest(expected_manifest_sha) and type(raw) is bytes and sha(raw) == expected_manifest_sha)
    record = decode(raw)
    keys = {"schema", "host_commit", "hud_commit", "python", "platform", "facts",
            "environment", "interpreter", "entry", "files"}
    need(type(record) is dict and set(record) == keys, "schema")
    need(record["schema"] == "hermes_0222_installed_handoff_v2"
         and record["host_commit"] == HOST_COMMIT and record["hud_commit"] == HUD_COMMIT)
    need(record["python"] == "3.14.7" and record["platform"] == "darwin-x64", "runtime")
    reader = reader_factory(root, record["files"])
    key = hashlib.sha256((root + "/sdk").encode()).hexdigest()[:16]
    state = "home/.hermes/installs/" + key
    expected_facts = state + "/facts.json"
    need(record["facts"] == expected_facts, "facts")
    env = record["environment"]
    need(relative(env) and re.fullmatch(re.escape(state)+r"/environments/[a-f0-9]{32}/venv", env) is not None, "path")
    need(relative(record["interpreter"]) and record["interpreter"].startswith("home/.hermes/tools/")
         and record["entry"] == "tool/official_entry.py", "path")
    rows = {r["path"]:r for r in record["files"]}
    required = {expected_facts, env + "/pyvenv.cfg", record["interpreter"],
                record["entry"], "sdk/uv.lock", "sdk/pyproject.toml", "product/dashboard/dist/index.js"}
    need(required <= rows.keys(), "binding")
    need(rows["sdk/uv.lock"]["sha256"] == LOCK_SHA and rows["sdk/pyproject.toml"]["sha256"] == PROJECT_SHA
         and rows["product/dashboard/dist/index.js"]["sha256"] == RELEASE_JS_SHA, "binding")
    need(rows[record["interpreter"]]["kind"] == "binary" and
         all(rows[p]["kind"] == "text" for p in required-{record["interpreter"]}), "schema")
    # No arbitrary file path is taken from facts before the exact inventory check.
    reader.verify_all()
    facts = decode(reader.read(expected_facts))
    try:
        selected = facts["packages"]["venv"]["environment"]
    except (KeyError,TypeError):
        raise Refused("facts") from None
    need(type(selected) is str and selected == root + "/" + env, "facts")
    cfg = reader.read(env + "/pyvenv.cfg").decode("utf-8")
    values = {}
    for line in cfg.splitlines():
        if not line.strip() or line.lstrip().startswith("#"): continue
        need("=" in line, "runtime")
        k,v = (s.strip() for s in line.split("=",1))
        need(k not in values, "runtime"); values[k] = v
    # uv 0.12.3 writes version_info (not stdlib venv's version), plus its
    # own version and implementation. A minor-only managed-link selection
    # cannot establish the pinned patch runtime and is refused here.
    need(values.get("version_info") == "3.14.7" and "version" not in values
         and values.get("implementation") == "CPython" and values.get("uv") == "0.12.3"
         and values.get("include-system-site-packages") == "false", "runtime")
    need(values.get("home") == str(PurePosixPath(root + "/" + record["interpreter"]).parent), "runtime")
    # A caller still needs dependency/.pth/native-resource closure and review.
    return {"manifest_sha256":expected_manifest_sha, "files_checked":len(rows),
            "python_image":root+"/"+record["interpreter"], "python_sha256":rows[record["interpreter"]]["sha256"],
            "entry":root+"/"+record["entry"], "selected_environment":root+"/"+env,
            "source_root":root+"/sdk", "root":root, "runtime_verified":False,
            "dependency_completeness":"NOT_PROVEN", "native_ready":False}


def inspect_handoff(raw, expected_manifest_sha, root, reader_factory=BoundFiles):
    try:
        return _inspect_handoff(raw, expected_manifest_sha, root, reader_factory)
    except Refused:
        raise
    except Exception:
        raise Refused("binding") from None


def host_plan(handoff, port, token):
    """No subprocess, environment inheritance, sys.path change or token persistence."""
    need(type(handoff) is dict and set(handoff) == {"manifest_sha256","files_checked","python_image",
         "python_sha256","entry","selected_environment","source_root","root","runtime_verified",
         "dependency_completeness","native_ready"}, "plan")
    need(handoff["runtime_verified"] is False and handoff["native_ready"] is False
         and handoff["dependency_completeness"] == "NOT_PROVEN", "plan")
    need(type(port) is int and 1024<=port<=65535 and port != 9119
         and type(token) is str and re.fullmatch("[A-Za-z0-9_-]{32,128}", token) is not None, "plan")
    root = handoff["root"]
    need(type(root) is str and re.fullmatch("/private/tmp/hermes-022-run-[a-f0-9]{32}",root) is not None, "plan")
    need(type(handoff["files_checked"]) is int and 7 <= handoff["files_checked"] <= 8192
         and handoff["source_root"] == root+"/sdk"
         and handoff["entry"] == root+"/tool/official_entry.py", "plan")
    need(all(type(handoff[k]) is str and handoff[k].startswith(root+"/")
             and str(PurePosixPath(handoff[k])) == handoff[k]
             and ".." not in PurePosixPath(handoff[k]).parts
             for k in ("python_image","entry","selected_environment","source_root"))
         and digest(handoff["manifest_sha256"]) and digest(handoff["python_sha256"]), "plan")
    key=hashlib.sha256((root+"/sdk").encode()).hexdigest()[:16]
    need(re.fullmatch(re.escape(root+"/home/.hermes/installs/"+key)+r"/environments/[a-f0-9]{32}/venv",handoff["selected_environment"]) is not None
         and handoff["python_image"].startswith(root+"/home/.hermes/tools/"), "plan")
    return {"executable":handoff["python_image"],"executable_sha256":handoff["python_sha256"],
        "argv":[handoff["python_image"],"-I","-B",handoff["entry"]],
        "cwd":root,
        "env":{"HOME":root+"/home","HERMES_HOME":root+"/home/.hermes","TMPDIR":root+"/tmp",
               "PATH":"/usr/bin:/bin:/usr/sbin:/sbin","LANG":"en_US.UTF-8","LC_CTYPE":"en_US.UTF-8","TZ":"UTC",
               "PYTHONDONTWRITEBYTECODE":"1","PYTHONNOUSERSITE":"1","XDG_CACHE_HOME":root+"/home/.cache",
               "UV_CACHE_DIR":root+"/home/.hermes/cache/uv","HERMES_DISABLE_LAZY_INSTALLS":"1",
               "HERMES_DASHBOARD_SESSION_TOKEN":token},
        "sdk_argv":[handoff["entry"],"dashboard","--host","127.0.0.1",
                    "--port",str(port),"--no-open","--skip-build","--isolated"],
        "scope":"PLAN_ONLY_NOT_NATIVE_READY","native_ready":False}
