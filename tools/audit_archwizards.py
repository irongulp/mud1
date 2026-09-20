"""Test original archwizard passwords on a disposable, private-port runtime.

Creates only test credentials. Rebuilds the existing availability-only variant
unless --historical is selected; no authentication code is modified. It uses a
separate read-only BCPL program to inspect native PSWD fields. Not an installer.
"""
import argparse
import base64
import json
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

from tools.benchmark_idle import Emulator

ROOT = Path(__file__).resolve().parents[1]
ARCHWIZARDS = ("Richard", "Roy", "Brian", "Ronan", "Friday", "Yawn", "Debugger")
CONTROL = "Authtest"
WORD_MASK = (1 << 36) - 1
TIMEOUT = 15
MAX_BOOT_ATTEMPTS = 3


def parse_personas(text):
    total = re.search(r"^PSAUDIT_TOTAL (\d+)\s*$", text, re.M)
    if not total or "PSAUDIT_BAD_HEADER" in text or "PSAUDIT_OPEN_FAILED" in text:
        raise ValueError("Missing/invalid native persona diagnostic: " + text)
    records = {}
    for name, password, games in re.findall(r"^PSAUDIT ([A-Za-z]+) (-?[0-7]+) (\d+)\s*$", text, re.M):
        key = name.lower()
        if key in records:
            raise ValueError("Duplicate persona diagnostic: " + name)
        records[key] = {"password_word": int(password, 8) & WORD_MASK, "games": int(games)}
    deleted = len(re.findall(r"^PSAUDIT_DELETED\s*$", text, re.M))
    if len(records) + deleted != int(total[1]):
        raise ValueError("Incomplete persona diagnostic")
    return records


def password_result(text, name):
    if re.search(r"(?:^|[\r\n])No!\r?\n", text):
        return "rejected"
    greeting = re.search(r"Hello(?: again)?, " + re.escape(name) + r"(?: the arch-wizard)?!", text)
    if greeting and re.search(r"\n(?:----)?\*", text[greeting.end():]):
        return "accepted"
    return "incomplete"


def test_password():
    while True:
        value = base64.b64encode(secrets.token_bytes(6)).decode("ascii")
        if re.fullmatch(r"[a-z0-9]{8}", value):
            return value


class Guest:
    def __init__(self, port, account, transcript, connection=None):
        import telnetlib  # This integration tool runs on Python 3.9–3.12.

        self.connection = connection or telnetlib.Telnet("127.0.0.1", port, TIMEOUT)
        self.transcript = transcript
        self.accepted = False
        self.at_monitor = False
        # The DZ carrier transition clears typeahead. Wait for SIMH's banner
        # before sending the wake-up CR, rather than losing it in that transition.
        if connection is None:
            self.expect(b"device, line ")
            self.expect(b"\n")
            time.sleep(0.25)
            self.send("")
            self.expect(b".")
            self.send("set tty width 255")
            self.expect(b"\n.")
            self.send("login " + account)
            if account == "richard":
                self.expect(b"\n.")
                self.send("run mud")
        else:
            self.send("run mud[2011,2776]")
        self.expect(b"By what name shall I call you?")
        self.expect(b"*")

    def send(self, text):
        self.connection.write(text.encode("ascii") + b"\r")

    def expect(self, marker):
        data = self.connection.read_until(marker, TIMEOUT)
        text = data.decode("ascii", errors="replace")
        self.transcript.append(text)
        if marker not in data:
            raise TimeoutError(f"Expected {marker!r}, received {text!r}")
        return text

    def authenticate(self, name, password, creating=False):
        self.send(name)
        if creating:
            if name not in ARCHWIZARDS:
                self.expect(b"What sex do you wish to be?")
                self.expect(b"*")
                self.connection.write(b"m")
            self.expect(b"letters, please.")
        else:
            self.expect(b"This persona already exists - what's the password?")
        self.expect(b"*")
        self.send(password)
        data = bytearray()
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline:
            data.extend(self.connection.read_very_eager())
            outcome = password_result(data.decode("ascii", errors="replace"), name)
            if outcome != "incomplete":
                text = data.decode("ascii", errors="replace")
                self.transcript.append(text)
                self.accepted = outcome == "accepted"
                if not self.accepted:
                    if not re.search(r"\n\.", text):
                        # The preceding newline may already be in data while
                        # the monitor's dot arrives in the next TCP fragment.
                        self.expect(b".")
                    self.at_monitor = True
                return self.accepted
            time.sleep(0.02)
        raise TimeoutError("No unambiguous authentication result: " + repr(bytes(data)))

    def save(self, name):
        self.send("save")
        output = self.expect(b" saved.")
        if not re.search(re.escape(name) + r"(?: the arch-wizard)? saved\.", output):
            raise AssertionError("SAVE did not identify the expected persona: " + output)
        self.expect(b"*")

    def attach(self, name, password):
        self.send("attach " + name)
        index, _, data = self.connection.expect(
            [rb"What's the password for this persona\?\r?\n", rb"\n----\*"], TIMEOUT)
        text = data.decode("ascii", errors="replace")
        self.transcript.append(text)
        if index < 0:
            raise TimeoutError("No attachment prompt or result: " + repr(text))
        prompted = index == 0
        if prompted:
            # ATTACH sets pretend=true: its password question has no '*' prompt.
            self.send(password)
            text = self.expect(b"\n----*")
        accepted = bool(re.search(r"(?:^|\n)Attaching to " + re.escape(name)
                                  + r"(?: the arch-wizard)?\.\r?\n", text))
        rejected = re.search(r"(?:^|\n)(?:Wrong!|Not to " + re.escape(name)
                             + r" you don't!)\r?\n", text)
        if not accepted and not rejected:
            raise AssertionError("No unambiguous attachment result: " + repr(text))
        return {"prompted": prompted, "accepted": accepted}

    def close(self):
        if self.accepted:
            self.send("quit")
            self.expect(b"\n.")
            self.at_monitor = True
        self.accepted = False
        # Each attempt runs a fresh MUD process in the same authenticated OS
        # account. Avoid repeated unlogged-in intervals/TTY-stomper races.


def logoff(connection):
    try:
        connection.write(b"kjob\r")
        data = connection.read_until(b"Logged-off", TIMEOUT)
        if b"Logged-off" not in data:
            raise TimeoutError("Private test account did not log off")
    finally:
        connection.close()


def checked_command(machine, command, prompt=r"\n\."):
    output = machine.command(command, prompt)
    if re.search(r"(?m)^\?(?!\?)|% .*Error|undefined global", output):
        raise RuntimeError(output)
    return output


def prepare_machine(machine, historical):
    checked_command(machine, "kjob")
    checked_command(machine, "login richard")
    checked_command(machine, "assign dsk: bcl:")
    checked_command(machine, "set tty no altmode")
    if not historical:
        print("Building availability-only MUD variant in the private guest", flush=True)
        checked_command(machine, "r teco", r"\n\*")
        commands = (
            'ERMUDLIB.BCL\x1bEWM24LIB.BCL\x1bY',
            'Nand timeok(low)=\x1b0L.UASand overload(low)=\x1b0LQA,.K',
            'I// Local 24/7 build: preserve HOURS data and the original load checks.\r'
            'and timeok(low)=demo\\/~overload(numbargs()->low, low1)\r\x1bEX\x1b\x1b',
        )
        for text in commands:
            machine.child.send(text)
        machine.child.expect(r"\n\.")
        checked_command(machine, "r bcpl", r"\n\*")
        checked_command(machine, "m24lib/o", r"\n\*")
        machine.child.sendcontrol("z")
        machine.child.expect(r"\n\.")
        checked_command(machine, "r link", r"\n\*")
        checked_command(machine, "mud0,mud1,mud2,mud3,mud4,mud5,mud6,mud7,mud8,m24lib,mboots/COUNTER/set:.high.:502700", r"\n\*")
        checked_command(machine, "dbadat/g")
        checked_command(machine, "ssave mud24")
        checked_command(machine, "copy mud.exe=mud24.exe")
        checked_command(machine, "dir mud.dmp")
        # Regenerate the private world's data with the original compiler rather
        # than depend on a build-time dump retained in the old checkpoint.
        machine.child.send("run dbase\r")
        machine.child.expect_exact("Total space used 25247")
        machine.child.expect_exact("MUD saved")
        machine.child.expect(r"\n\.")
        checked_command(machine, "protect mud.exe<055>")
    # A companion diagnostic, compiled separately so MUD's addresses do not move.
    machine.child.send("copy audpwd.bcl=tty:\r")
    machine.child.expect_exact("copy audpwd.bcl=tty:")
    for line in (ROOT / "tools/fixtures/AUDPWD.BCL").read_text().splitlines():
        machine.child.send(line + "\r")
    machine.child.sendcontrol("z")
    machine.child.expect(r"\n\.")
    checked_command(machine, "r bcpl", r"\n\*")
    checked_command(machine, "audpwd/o", r"\n\*")
    machine.child.sendcontrol("z")
    machine.child.expect(r"\n\.")
    checked_command(machine, "r link", r"\n\*")
    checked_command(machine, "audpwd/g")
    checked_command(machine, "save audpwd")


def inspect(machine):
    return parse_personas(checked_command(machine, "run audpwd"))


def richard_control_probe(output):
    """Use the same actual password on Richard and a fresh ordinary persona."""
    reference = json.loads((output / "completed-report.json").read_text())
    if not reference["complete"]:
        raise ValueError("The main audit must be complete first")
    fixture = json.loads((output / "test-fixtures.json").read_text())["Richard"]
    result = {"complete": False, "availability": reference["availability"],
              "control": "Rcontrol", "same_plaintext_password": True}
    machine = None
    wire = None
    try:
        for attempt in range(MAX_BOOT_ATTEMPTS):
            print(f"Same-password control: boot {attempt + 1}", flush=True)
            machine = Emulator(output / reference["machine_directory"], "noidle", reuse=True, speed_factor=8)
            try:
                machine.boot()
                break
            except Exception:
                machine.stop()
                machine = None
                if attempt + 1 == MAX_BOOT_ATTEMPTS:
                    raise
        checked_command(machine, "kjob")
        checked_command(machine, "login richard")
        checked_command(machine, "copy mud.*=auth0.?pm")
        original = inspect(machine)["richard"]["password_word"]
        transcript = []
        control = Guest(machine.port, "mudguest", transcript)
        wire = control.connection
        if not control.authenticate("Rcontrol", fixture["correct"], creating=True):
            raise AssertionError("Control creation failed")
        control.save("Rcontrol")
        control.close()
        stored = inspect(machine)
        result["richard_word"] = original
        result["control_word"] = stored["rcontrol"]["password_word"]
        result["stored_words_equal"] = original == result["control_word"]
        for name, label, password in (("Rcontrol", "control_correct", fixture["correct"]),
                                       ("Richard", "richard_correct", fixture["correct"]),
                                       ("Rcontrol", "control_wrong", fixture["wrong"])):
            player = Guest(machine.port, "mudguest", transcript, wire)
            result[label + "_accepted"] = player.authenticate(name, password)
            player.close()
        result["richard_word_unchanged"] = inspect(machine)["richard"]["password_word"] == original
        result["complete"] = True
        logoff(wire)
        wire = None
        (output / "same-password-sessions.json").write_text(json.dumps(transcript, indent=2) + "\n")
        print(json.dumps(result, indent=2), flush=True)
    except BaseException as error:
        result["error"] = repr(error)
        raise
    finally:
        (output / "same-password-report.json").write_text(json.dumps(result, indent=2) + "\n")
        if wire is not None:
            wire.close()
        if machine is not None:
            machine.stop()


def richard_attachment_probe(output):
    """Check different-password attachment on a completed, stopped private audit."""
    reference = json.loads((output / "completed-report.json").read_text())
    if not reference["complete"]:
        raise ValueError("The main audit must be complete first")
    fixtures = json.loads((output / "test-fixtures.json").read_text())
    result = {"complete": False, "availability": reference["availability"],
              "authentication_source_modified": False, "account": "mudguest",
              "source": "Roy", "target": "Richard", "cases": []}
    report_path = output / "attachment-report.json"
    if report_path.exists():
        report_path.rename(output / f"attachment-report-before-{time.time_ns()}.json")
    transcript = []
    machine = None
    wire = None
    try:
        for attempt in range(MAX_BOOT_ATTEMPTS):
            print(f"Richard attachment: boot {attempt + 1}", flush=True)
            machine = Emulator(output / reference["machine_directory"], "noidle", reuse=True, speed_factor=8)
            try:
                machine.boot()
                break
            except Exception:
                machine.stop()
                machine = None
                if attempt + 1 == MAX_BOOT_ATTEMPTS:
                    raise
        checked_command(machine, "kjob")
        checked_command(machine, "login richard")
        checked_command(machine, "copy mud.*=auth0.?pm")
        before = inspect(machine)
        result["before"] = {name: before[name] for name in ("roy", "richard")}
        words = [before[name]["password_word"] for name in ("roy", "richard")]
        if not all(words) or words[0] == words[1]:
            raise AssertionError("Attachment probe requires distinct, nonzero saved passwords")
        # Separate authentication from persistence: a loaded STATES word can
        # overwrite ATTED, and ps.word still belongs to the original persona.
        cases = (
            ("wrong", fixtures["Richard"]["wrong"], False, False, False, "richard"),
            ("roy_password", fixtures["Roy"]["correct"], False, False, False, "richard"),
            ("correct_quit", fixtures["Richard"]["correct"], True, False, False, "richard"),
            ("correct_quit_after_roy_save", fixtures["Richard"]["correct"], True, True, False, "roy"),
            ("correct_save", fixtures["Richard"]["correct"], True, False, True, "roy"),
        )
        for label, password, expected, save_source, save_target, final_password_owner in cases:
            checked_command(machine, "copy mud.*=auth0.?pm")
            guest = Guest(machine.port, "mudguest", transcript, wire)
            wire = guest.connection
            if not guest.authenticate("Roy", fixtures["Roy"]["correct"]):
                raise AssertionError("Saved Roy login failed")
            if save_source:
                guest.save("Roy")
            row = {"case": label, **guest.attach("Richard", password)}
            result["cases"].append(row)
            if row["prompted"] is not True or row["accepted"] != expected:
                raise AssertionError("Unexpected attachment outcome: " + repr(row))
            if expected:
                row["richard_after_attach"] = inspect(machine)["richard"]
                if row["richard_after_attach"] != before["richard"]:
                    raise AssertionError("Attachment itself changed Richard's inspected fields")
                guest.send("score")
                row["score"] = guest.expect(b"\n----*")
                guest.send("who")
                row["who"] = guest.expect(b"\n----*")
                if "Richard the arch-wizard" not in row["who"]:
                    raise AssertionError("Attached Richard did not appear in WHO")
                # Experience level depends on score, not wizard privileges.
                # GO to a room identifier is a real wizard-only operation.
                guest.send("go wrdbe")
                row["wizard_teleport"] = "Room WRDBE" in guest.expect(b"\n----*")
                if not row["wizard_teleport"]:
                    raise AssertionError("Attached persona could not use wizard teleportation")
                if save_target:
                    guest.save("Richard")
                    row["save_accepted"] = True
                    row["richard_after_save"] = inspect(machine)["richard"]
                    if row["richard_after_save"]["password_word"] != words[0]:
                        raise AssertionError("Attached SAVE did not store Roy's password value")
            else:
                # SAVE identifies the current persona explicitly; rejection must
                # leave us as Roy rather than perform a partial attachment.
                guest.save("Roy")
                row["still_roy"] = True
            guest.close()
            row["richard_after_quit"] = inspect(machine)["richard"]
            row["final_password_matches"] = final_password_owner
            if row["richard_after_quit"]["password_word"] != before[final_password_owner]["password_word"]:
                raise AssertionError("Unexpected Richard password value after QUIT")
            print(f"Richard attachment {label}: prompted={row['prompted']}, accepted={row['accepted']}", flush=True)

        # The preceding SAVE made the two saved password values equal. Verify
        # the same-password shortcut with a fresh authenticated Roy session.
        matched = inspect(machine)
        if matched["roy"]["password_word"] != matched["richard"]["password_word"]:
            raise AssertionError("Same-password attachment control is not established")
        guest = Guest(machine.port, "mudguest", transcript, wire)
        wire = guest.connection
        if not guest.authenticate("Roy", fixtures["Roy"]["correct"]):
            raise AssertionError("Saved Roy control login failed")
        row = {"case": "same_password", **guest.attach("Richard", fixtures["Roy"]["correct"])}
        result["cases"].append(row)
        if row["prompted"] or not row["accepted"]:
            raise AssertionError("Same-password attachment did not take the silent shortcut")
        guest.close()
        row["richard_after_quit"] = inspect(machine)["richard"]
        print("Richard attachment same_password: prompted=False, accepted=True", flush=True)
        logoff(wire)
        wire = None
        checked_command(machine, "copy mud.*=auth0.?pm")
        result["restored"] = inspect(machine)
        if any(result["restored"][name] != before[name] for name in ("roy", "richard")):
            raise AssertionError("Private fixtures were not restored")
        result["complete"] = True
        print(json.dumps(result, indent=2), flush=True)
    except BaseException as error:
        result["error"] = repr(error)
        raise
    finally:
        sessions_path = output / f"attachment-sessions-{time.time_ns()}.json"
        sessions_path.write_text(json.dumps(transcript, indent=2) + "\n")
        result["sessions"] = sessions_path.name
        report_path.write_text(json.dumps(result, indent=2) + "\n")
        if wire is not None:
            wire.close()
        if machine is not None:
            machine.stop()


def run(args):
    report = {"complete": False, "availability": "historical" if args.historical else "always-open",
              "authentication_source_modified": False, "cases": [], "initial": {}, "boot_attempts": []}
    machine = None
    wire = None
    wire_account = None
    passwords = {name: test_password() for name in (*ARCHWIZARDS, CONTROL)}
    fixtures = {name: {"correct": password, "wrong": test_password(),
                       "near_wrong": password[:-1] + ("a" if password[-1] != "a" else "b")}
                for name, password in passwords.items()}
    if args.resume:
        previous = json.loads((args.output / "report.json").read_text())
        (args.output / f"report-before-resume-{time.time_ns()}.json").write_text(json.dumps(previous, indent=2) + "\n")
        if previous["availability"] != report["availability"]:
            raise ValueError("Resume must use the same availability variant")
        fixtures = json.loads((args.output / "test-fixtures.json").read_text())
        passwords = {name: fixture["correct"] for name, fixture in fixtures.items()}
        report["initial"] = previous["initial"]
        if not {name.lower() for name in passwords} <= report["initial"].keys():
            raise ValueError("Resume requires completed persona provisioning")
    else:
        (args.output / "test-fixtures.json").write_text(json.dumps(fixtures, indent=2) + "\n")

    def checkpoint():
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")

    def connect(account, transcript):
        nonlocal wire, wire_account
        if wire is not None and wire_account != account:
            logoff(wire)
            wire = None
        guest = Guest(machine.port, account, transcript, wire)
        wire, wire_account = guest.connection, account
        return guest

    try:
        for attempt in range(MAX_BOOT_ATTEMPTS):
            print(f"Booting disposable runtime (attempt {attempt + 1})", flush=True)
            directory = args.output / f"machine-{attempt + 1}"
            if args.resume:
                booted = next(item for item in reversed(previous["boot_attempts"]) if item["booted"])
                directory = args.output / previous.get("machine_directory", f"machine-{booted['attempt']}")
            machine = Emulator(directory, "noidle", reuse=args.resume, speed_factor=8)
            try:
                machine.boot()
                report["boot_attempts"].append({"attempt": attempt + 1, "booted": True})
                report["machine_directory"] = directory.name
                break
            except Exception as error:
                report["boot_attempts"].append({"attempt": attempt + 1, "booted": False, "error": repr(error)})
                checkpoint()
                machine.stop()
                machine = None
                if attempt + 1 == MAX_BOOT_ATTEMPTS:
                    raise
        if args.resume:
            checked_command(machine, "kjob")
            checked_command(machine, "login richard")
            checked_command(machine, "assign dsk: bcl:")
        else:
            prepare_machine(machine, args.historical)
            before = inspect(machine)
            if any(name.lower() in before for name in passwords):
                raise RuntimeError("Baseline already has test personas; refuse to overwrite them")
        with (args.output / "sessions.jsonl").open("a" if args.resume else "w") as log:
            for name in (() if args.resume else passwords):
                print("Create and SAVE " + name, flush=True)
                transcript = []
                guest = connect("richard", transcript)
                try:
                    if not guest.authenticate(name, passwords[name], creating=True):
                        raise AssertionError("Creation rejected: " + name)
                    guest.save(name)
                finally:
                    guest.close()
                    log.write(json.dumps({"stage": "create", "name": name, "output": transcript}) + "\n")
            if not args.resume:
                report["initial"] = inspect(machine)
            if not all(report["initial"][name.lower()]["password_word"] for name in passwords):
                raise AssertionError("A fixture has a zero password word")
            if not args.resume:
                checked_command(machine, "copy auth0.*=mud.?pm")
            checked_command(machine, "dir auth0.*")
            checkpoint()
            for account in ("mudguest", "richard"):
                for name, fixture in fixtures.items():
                    for label, credential, expected, restore in (
                        ("wrong_first", fixture["wrong"], False, True),
                        ("near_wrong", fixture["near_wrong"], False, True),
                        ("case_variant", fixture["correct"].upper(), True, True),
                        ("correct_save", fixture["correct"], True, True),
                        ("correct_again", fixture["correct"], True, False),
                        ("wrong_after_correct", fixture["wrong"], False, False),
                    ):
                        if restore:
                            checked_command(machine, "copy mud.*=auth0.?pm")
                        initial = inspect(machine)[name.lower()]
                        if restore and initial != report["initial"][name.lower()]:
                            raise AssertionError("Private persona fixture was not restored exactly")
                        transcript = []
                        guest = connect(account, transcript)
                        row = {"account": account, "name": name, "case": label,
                               "expected_acceptance": expected, "before": initial}
                        try:
                            row["accepted"] = guest.authenticate(name, credential)
                            if row["accepted"] and label == "correct_save":
                                guest.save(name)
                                row["after_save"] = inspect(machine)[name.lower()]
                        finally:
                            guest.close()
                            log.write(json.dumps({**row, "output": transcript}) + "\n")
                            log.flush()
                        row["after_quit"] = inspect(machine)[name.lower()]
                        row["matches_expected"] = row["accepted"] == expected
                        report["cases"].append(row)
                        checkpoint()
                        print(f"{account:8} {name:8} {label:20} accepted={row['accepted']} expected={expected} PSWD_changed={initial['password_word'] != row['after_quit']['password_word']}", flush=True)
        report["complete"] = True
        report["all_password_checks_passed"] = all(row["matches_expected"] for row in report["cases"])
        (args.output / "completed-report.json").write_text(json.dumps(report, indent=2) + "\n")
        logoff(wire)
        wire = None
    except BaseException as error:
        report["error"] = repr(error)
        raise
    finally:
        checkpoint()
        if wire is not None:
            wire.close()
        if machine is not None:
            machine.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", type=Path, action="append", help="Read and summarize a completed report without starting an emulator")
    parser.add_argument("--historical", action="store_true")
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Reuse a stopped, fully provisioned audit machine and rerun its matrix")
    parser.add_argument("--richard-control", action="store_true", help="Run a same-password control on a completed, stopped audit machine")
    parser.add_argument("--richard-attach", action="store_true", help="Test different-password attachment on a completed, stopped audit machine")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.summary:
        for path in args.summary:
            report = json.loads(path.read_text())
            if not report["complete"] or len(report["cases"]) != 96:
                raise ValueError("Not a complete 96-case report: " + str(path))
            print(f"{path}: {report['availability']}, {len(report['cases'])} cases")
            for name in (*ARCHWIZARDS, CONTROL):
                rows = [row for row in report["cases"] if row["name"] == name]
                correct = [row for row in rows if row["expected_acceptance"]]
                wrong = [row for row in rows if not row["expected_acceptance"]]
                stable = all(row["before"]["password_word"] == row["after_quit"]["password_word"] for row in rows)
                print(f"  {name:8}: correct accepted {sum(row['accepted'] for row in correct)}/{len(correct)}, wrong rejected {sum(not row['accepted'] for row in wrong)}/{len(wrong)}, stored PSWD unchanged={stable}")
        return
    if args.output is None:
        parser.error("--output is required to run an audit")
    args.output = args.output.resolve()
    if args.richard_attach:
        richard_attachment_probe(args.output)
        return
    if args.richard_control:
        richard_control_probe(args.output)
        return
    args.output.mkdir(parents=True, exist_ok=args.worker or args.resume)
    if args.background:
        command = [sys.executable, "-u", "-m", "tools.audit_archwizards", "--worker", "--output", str(args.output)]
        if args.historical:
            command.append("--historical")
        if args.resume:
            command.append("--resume")
        with (args.output / "driver.log").open("ab" if args.resume else "xb") as log:
            process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=log, start_new_session=True)
        print(f"Audit PID {process.pid}; progress: {args.output / 'driver.log'}")
    else:
        run(args)


if __name__ == "__main__":
    main()
