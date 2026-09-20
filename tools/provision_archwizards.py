"""Reserve the seven archwizard personas before exposing a new installation.

Connects to an explicitly selected loopback TOPS-10 Telnet port. Requires the
restored RICHARD OS account and BCPL compiler. Uses original creation/SAVE, never
edits persona records directly, and preserves existing accounts. Python 3.9–3.12 for CLI.
"""
import argparse
import base64
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import tempfile
import time

from tools.audit_archwizards import ARCHWIZARDS, Guest, TIMEOUT, WORD_MASK, parse_personas

ROOT = Path(__file__).resolve().parents[1]
CREDENTIAL_FILE = "archwizard-credentials.json"
SCHEMA_VERSION = 1
PASSWORD_BYTES = 6
SOURCE_LINE_DELAY = 0.05
PASSWORD_PATTERN = re.compile(r"[a-z0-9]{8}")


class ProvisionError(RuntimeError):
    """Operator-facing message containing neither passwords nor native output."""


def generate_password():
    while True:
        password = base64.b64encode(secrets.token_bytes(PASSWORD_BYTES)).decode("ascii")
        if PASSWORD_PATTERN.fullmatch(password):
            return password


def check_private(path, directory=False):
    info = path.lstat()
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected_type(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ProvisionError("Credential storage must be owned by this user, private, and not symlinked")


@contextmanager
def credential_journal(directory):
    directory.mkdir(mode=0o700, exist_ok=True)
    check_private(directory, directory=True)
    lock_path = directory / ".archwizard-provision.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "r+") as lock:
        check_private(lock_path)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ProvisionError("Another provisioner is using this credential journal") from None
        path = directory / CREDENTIAL_FILE
        if path.exists() or path.is_symlink():
            check_private(path)
            try:
                data = json.loads(path.read_text())
                if data["version"] != SCHEMA_VERSION or not isinstance(data["credentials"], dict):
                    raise ValueError()
                for name, entry in data["credentials"].items():
                    if name not in ARCHWIZARDS or not PASSWORD_PATTERN.fullmatch(entry["initial_password"]):
                        raise ValueError()
                    word = entry["initial_password_word"]
                    if word is not None and (type(word) is not int or not 0 < word <= WORD_MASK):
                        raise ValueError()
            except (ValueError, TypeError, KeyError):
                raise ProvisionError("Invalid credential journal; refusing to replace it") from None
        else:
            data = {"version": SCHEMA_VERSION, "credentials": {}}
        yield path, data


def write_journal(path, data):
    descriptor, temporary = tempfile.mkstemp(prefix=".archwizard-credentials-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def provision(native, directory):
    """Initialize missing personas, journalling credentials before native writes.

    Existing nonzero records are authoritative. A changed password never causes
    an automatic reset, and an interrupted SAVE is not assumed to prove a match.
    The returned rows contain credentials: use render_credentials for output.
    """
    with credential_journal(Path(directory)) as (path, journal):
        entries = journal["credentials"]
        records = native.records()
        # Preflight the whole set before creating any missing personas.
        for name in ARCHWIZARDS:
            record, entry = records.get(name.lower()), entries.get(name)
            if record is not None:
                if not record["password_word"]:
                    raise ProvisionError(f"{name} already exists with no password; manual protection is required")
                if entry and entry["initial_password_word"] is None:
                    raise ProvisionError(f"{name} exists but its journalled password is unverified; reconcile the interrupted SAVE")

        if not path.exists():
            write_journal(path, journal)
        result = []
        used = {entry["initial_password"] for entry in entries.values()}
        for name in ARCHWIZARDS:
            record, entry = records.get(name.lower()), entries.get(name)
            if record is not None:
                if not entry:
                    result.append({"name": name, "status": "existing"})
                elif entry["initial_password_word"] != record["password_word"]:
                    result.append({"name": name, "status": "changed"})
                else:
                    result.append({"name": name, "status": "preserved", "password": entry["initial_password"]})
                continue

            if entry is None:
                password = generate_password()
                while password in used:
                    password = generate_password()
                used.add(password)
                entry = {"initial_password": password, "initial_password_word": None}
                entries[name] = entry
                write_journal(path, journal)
            native.create_and_save(name, entry["initial_password"])
            record = native.records().get(name.lower())
            if record is None or not record["password_word"]:
                raise ProvisionError(f"{name} creation did not leave a nonzero saved password")
            if entry["initial_password_word"] not in (None, record["password_word"]):
                raise ProvisionError(f"{name} recreated with an unexpected password value; reconcile before continuing")
            entry["initial_password_word"] = record["password_word"]
            write_journal(path, journal)
            result.append({"name": name, "status": "created", "password": entry["initial_password"]})
        return result


def render_credentials(rows, reveal=False):
    lines = []
    if reveal:
        lines.append("Copy these credentials into your password manager. Do not publish or log this output.")
    for row in rows:
        role = "attachment password; direct login rejects it" if row["name"] == "Richard" else "login password"
        value = row.get("password", "") if reveal else ""
        detail = row["status"]
        if detail == "changed":
            detail = "changed; initial journalled password is not current"
        elif detail == "existing":
            detail = "existing; password managed separately"
        lines.append(f"{row['name']}: {value + ' — ' if value else ''}{detail} ({role})")
    lines.append("Richard: attached SAVE or a qualifying QUIT can replace his password with the originating persona's password.")
    return "\n".join(lines)


class NativePersonas:
    """A private maintenance TTY; no transcripts or diagnostic words are logged."""
    def __init__(self, port):
        self.port = port
        self.connection = None
        self.at_monitor = False
        self.stage = "connection"

    def expect(self, marker):
        data = self.connection.read_until(marker, TIMEOUT)
        if marker not in data:
            detail = " (terminal echo changed case)" if marker.lower() in data.lower() else ""
            raise ProvisionError("Native maintenance session did not reach the expected prompt during " + self.stage + detail)
        return data.decode("ascii", errors="replace")

    def send(self, text):
        self.connection.write(text.encode("ascii") + b"\r")

    def command(self, text, prompt=b"\n."):
        self.stage = text
        self.send(text)
        output = self.expect(prompt)
        if re.search(r"(?m)^\?(?!\?)|% .*Error|undefined global", output):
            raise ProvisionError("Native maintenance command failed: " + text)
        return output

    def __enter__(self):
        import telnetlib

        try:
            self.connection = telnetlib.Telnet("127.0.0.1", self.port, TIMEOUT)
            self.expect(b"device, line ")
            self.expect(b"\n")
            # Match the existing audit client's DZ carrier/typeahead settling.
            time.sleep(0.25)
            self.stage = "initial monitor wake-up"
            self.send("")
            self.expect(b".")
            self.command("set tty width 255")
            self.command("login richard")
            self.at_monitor = True
            self.command("assign dsk: bcl:")
            self.command("set tty no altmode")
            self.install_inspector()
            return self
        except BaseException as error:
            self.at_monitor = False
            self.__exit__(type(error), error, error.__traceback__)
            raise

    def install_inspector(self):
        self.stage = "inspector source transfer"
        self.send("copy audpwd.bcl=tty:")
        self.expect(b"copy audpwd.bcl=tty:\r\n")
        for number, line in enumerate((ROOT / "tools/fixtures/AUDPWD.BCL").read_text().splitlines(), 1):
            self.stage = f"inspector source line {number}"
            self.send(line)
            self.expect(b"\n")
            # TTY echo does not mean COPY has consumed the input. Match the
            # paced operator transfers rather than overflowing TOPS-10 typeahead.
            time.sleep(SOURCE_LINE_DELAY)
        self.stage = "inspector source EOF"
        self.connection.write(b"\x1a")
        self.expect(b"\n.")
        self.command("r bcpl", b"\n*")
        self.command("audpwd/o", b"\n*")
        self.connection.write(b"\x1a")
        self.expect(b"\n.")
        self.command("r link", b"\n*")
        self.command("audpwd/g")
        self.command("save audpwd")

    def records(self):
        try:
            return parse_personas(self.command("run audpwd"))
        except ValueError:
            raise ProvisionError("Native persona inspection failed; no diagnostic values were logged") from None

    def create_and_save(self, name, password):
        try:
            self.at_monitor = False
            guest = Guest(self.port, "richard", [], self.connection)
            if not guest.authenticate(name, password, creating=True):
                raise ProvisionError("Native persona creation was rejected")
            guest.save(name)
            guest.close()
            self.at_monitor = True
        except Exception:
            # The audit client's detailed errors can contain raw TTY output.
            raise ProvisionError(f"Native creation/SAVE failed for {name}; credential journal retained") from None

    def __exit__(self, exc_type, exc_value, traceback):
        if self.connection is not None:
            try:
                if not self.at_monitor:
                    self.connection.write(b"\x03\x03")
                    self.expect(b"\n.")
                self.send("kjob")
                self.expect(b"Logged-off")
            except Exception:
                if exc_type is None:
                    raise ProvisionError("Maintenance logout failed; inspect the selected private runtime") from None
            finally:
                self.connection.close()
                self.connection = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True, help="Loopback Telnet port of the private first-install runtime")
    parser.add_argument("--state-dir", type=Path, default=ROOT / "runtime/private")
    parser.add_argument("--show-credentials", action="store_true", help="Print current known credentials for copying to a password manager")
    args = parser.parse_args()
    if not 0 < args.port < 65536:
        parser.error("--port must be a valid TCP port")
    try:
        with NativePersonas(args.port) as native:
            rows = provision(native, args.state_dir)
        print("All seven archwizard personas have nonzero saved passwords.")
        print(render_credentials(rows, reveal=args.show_credentials))
        print("Private initial-credential journal:", args.state_dir / CREDENTIAL_FILE)
    except ProvisionError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Provisioning stopped ({type(error).__name__}); retain the credential journal for recovery.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
