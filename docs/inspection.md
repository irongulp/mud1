# Remote read-only inspection

Use these commands in an SSH session on the installed server. They extend
`mud86ctl`; the original MUD executable and gameplay source are unchanged.

```sh
sudo mud86ctl personas
sudo mud86ctl personas --search grob
sudo mud86ctl persona Grobble
sudo mud86ctl personas --json

sudo mud86ctl files
sudo mud86ctl files --json
sudo mud86ctl file MUD.WIZ

sudo mud86ctl logs runtime --lines 100
sudo mud86ctl logs gateway --follow
sudo mud86ctl logs runtime --since "1 hour ago" --lines 500
sudo mud86ctl logs game --lines 100

sudo mud86ctl errors
sudo mud86ctl errors --since "1 week ago" --context 3
sudo mud86ctl errors --follow
sudo mud86ctl errors --json
```

Every command has `--help`. `--json` uses schema `version: 1`. Journal log
commands emit one JSON object per journal entry; following error scans emit one
report per recognised finding. Successful queries/scans exit 0, failed queries
exit 1, invalid CLI usage exits 2, and an interrupted follower exits 130.
Finding an error is a successful scan: use the JSON findings for automation.

## Installing the readers

The normal `setup.sh` update installs and verifies two separate BCPL companion
programs, `MVPER` and `MVTXT`, after archwizard provisioning and before opening
the gateway. As with other setup updates, this restarts the game: use the
normal maintenance window described in [deployment.md](deployment.md).

An updated application installation can install/reinstall just the companions:

```sh
sudo mud86ctl inspection-install
```

This requires the runtime to be running. It writes only the companion source,
REL and EXE files in the guest game directory, then runs read-only checks.
Ordinary queries never install or compile programs. An older installation's
`mud86ctl` will not recognise these commands until its application is updated.
No new runtime image needs to be published, and existing game disks are retained.

## Architecture and saved personas

`tools/inspect_game.py` uses a short-lived maintenance terminal on loopback
port 2020, logs into the existing RICHARD operating-system account, runs the
companion, and performs KJOB before disconnecting. It does not enter the game
as a persona. Host journals are read directly with `journalctl`, even if the
emulator is down. No browser admin endpoint or extra listening service is added.

`MVPER.BCL` reads `MUD..PM` using native file I/O and the same file-associated
ENQ resource used by the original game. It snapshots records under the lock,
explicitly DEQs and closes the file, then emits only the selected fields. Native
ENQ **waits** when another job holds the resource; this was verified with an
independent lock holder. The host bounds each response at 90 seconds and 4 MiB;
on timeout its cleanup interrupts the maintenance program and attempts KJOB.
Failed logout is reported. Queries share the installer/maintenance lock through
`mud86ctl`; journal readers and followers do not hold that lock.

Persona fields are saved name, score, games played, strength, dexterity,
stamina/maximum, last-play guest day and day fraction, raw state flags, sex bit,
and whether a password is set. Password words are never emitted. The native
reader also checks the stored name length before printing it. Single-persona
output shows the detailed fields; list output shows name, score, games and
password status. JSON includes all fields.

These are **saved records**, not a live player-memory view. Deleted records are
counted separately. Last-play values are the two raw halves of the historical
universal date/time word, not converted host dates; the restored clock and
historical date encoding must not be mistaken for modern wall time. File dates
are likewise preserved as guest strings. The current snapshot limit is 2,048
records including deleted slots; larger or malformed files fail explicitly.

## Files and historical logs

There are two explicit areas:

| Area | Native location | Commands |
|---|---|---|
| `game` (default) | `DSKB:[2011,2776]` | `files`, `file MUD.WIZ` |
| `logs` | `DSKB:[2600,2776]` | `files --area logs`, `file MUD.LOG --area logs` |

The log PPN comes from `MPPN = #2600002776` in `source/DUNGEN.GET`.
`MUDLIB.BCL`'s `entered()` appends entry/exit and score information there.
`logs game` is a shortcut for reading that `MUD.LOG`, **not** a player command
transcript and not a complete engine-error log.

**The historical log file is missing or inaccessible on the tested
first-playable baseline.** The reader reports this as a failed query, rather
than an empty log. It does not create the directory, change permissions, or
silently redirect the engine's logging. Host runtime/gateway logs remain
available independently. Inspect the remote installation to establish whether
it has historical log data.

Directory JSON includes parsed filenames, block counts, protection strings,
guest date strings and the original listing. The leading dot in native data
extensions is retained: the persona filename is `MUD..PM`.

Text reads accept single alphanumeric 6.3 filenames with extensions TXT, LOG,
WIZ, BCL, GET, MAC, DBA, INI, MIC or CMD. Binary persona/executable files use the
decoded inspector rather than text reads. Text is transmitted as framed octal
data, so a file containing a monitor-looking dot or control character cannot
end the query. Human-readable output escapes terminal control characters.

The native text reader scans up to 4 MiB and retains the final 65,536 characters.
Larger retained output is explicitly marked `truncated`; files exceeding the
scan limit fail rather than returning a misleading complete result. There is
no lock-held slow terminal transfer. A file being appended to can change during
the read, so text reads are best-effort observations, not transactional log
snapshots. `logs game --lines N` selects the last N lines from that retained
tail. `--since` and `--follow` apply to host journals only.

## Finding errors

`errors` scans the runtime and gateway journals, including guest console output
captured by the runtime, for the last 24 hours by default. It combines actual
journal priorities with specific message signatures:

- Unexpected emulator exit and incomplete guest shutdown: **error**.
- Python traceback and systemd service failures: **error**.
- Explicit Python `ERROR:`/`CRITICAL:` messages: **error**, even when the
  journal records their stdout/stderr stream at a lower severity. Other explicit
  Python `WARNING:` messages are **warning**, rather than unknown diagnostics.
- The verified TOPS-10 illegal-memory-reference diagnostic: **error**.
- Boot retries, incomplete logout and unexpected terminal connection endings:
  **warning**. An isolated disconnect can be transient.
- Unknown diagnostic-looking native messages: **review**, not an asserted fault.

It does not classify arbitrary occurrences of the word “error” as faults.
Normal `%SIM-INFO:` startup lines (such as the Telnet listener and tape-format
messages) are not review findings. Other diagnostics in the same journal entry
and explicit warning/error journal priorities are still considered.
Reports group known repeated conditions per service and show occurrence counts,
first/last host timestamps, an example message and an inspection suggestion.
Counts are matching journal messages, not necessarily separate incidents: one
forced stop can produce both “Main process exited” and “Failed with result”.
`--context N` adds up to N preceding journal entries. In follow mode findings
are emitted individually with preceding context; use a finite scan for grouped
counts. For tracebacks split over multiple journal entries, use `logs runtime`
or `logs gateway` around the reported timestamp to read the complete exception.

Coverage includes the requested time range, optional `--lines` limit, number
of entries read and services observed. Missing/rotated history cannot be
reconstructed. No entries for a service are reported explicitly; failed or
malformed journal queries exit unsuccessfully without printing a clean result.
“No recognised errors in the inspected logs and time range” is deliberately
limited to that coverage. Runtime console capture does not include every
player's private TTY output, and the error scanner does not inspect MUD.LOG.

No automatic repair, reset, persona edit or service restart is performed by
inspection commands. Future write actions should have distinct handlers and
native coordination; they can reuse the maintenance transport.

### Gateway shutdown timeout

`State 'stop-sigterm' timed out. Killing.` followed by `status=9/KILL` means
systemd forcibly stopped the browser gateway after its 45-second shutdown
deadline. These are real shutdown failures, but historical messages do not
establish that the service is currently unhealthy. Check current status with
`sudo mud86ctl status`, and read nearby gateway journal entries for context.

Older gateway versions had no application shutdown hook for active WebSocket
sessions. aiohttp could wait 60 seconds for them, exceeding the unit's deadline.
The gateway now ends active handlers in its shutdown hook so they run the normal
QUIT/KJOB cleanup concurrently. A logout already in progress is allowed to finish.
Regression tests cover two connected browsers and shutdown during an existing
logout. This is a host gateway fix; no original engine changes are involved.

### Connection-close exceptions

The September 20–22 remote logs identified two separate gateway-side problems:

- `telnetlib3.BaseClient._process_rx` could try to deliver queued data after
  `feed_eof`, raising `AssertionError: feed_data after feed_eof`. The adapter in
  `server/gateway.py` now stops the pending receive task and parses queued bytes
  before forwarding connection loss to the pinned library. This preserves final
  output and `Logged-off` acknowledgements. It also handles Telnet commands split
  across chunks, ignores callbacks after closure and prevents negotiation from
  starting after an early close. Normal upstream reset errors remain visible.
- A failed browser send could enter the upstream-error handler, which then tried
  to send an unavailable message through the same closing WebSocket. Browser-send
  failures now have a separate handling path, with normal guest cleanup and an
  informational log message. A genuine upstream failure still produces a warning;
  notification to the browser is best-effort if it disconnects at that point.

Upstream warnings now include the exception type, so a `TimeoutError` with an
empty message is identifiable. The fixes do not retroactively establish the
cause of every historical connection warning. To check recurrence after an
update, choose a `--since` time after that update rather than rescanning the
same older failures.

The adapter deliberately targets pinned telnetlib3 2.0.8; review its receive-task
and parser overrides if upgrading that dependency. The upstream implementation
inspected during this fix clears queued bytes on closure, which is insufficient
for the final-output preservation checked here. No dependency version changed.

```sh
.venv/bin/python -m unittest tests.test_simh_client tests.test_gateway tests.test_inspect_game tests.test_deployment -v
```

All 58 tests passed on macOS/Python 3.9 and in a disposable AlmaLinux ARM container
with Python 3.12 and the deployment dependency pins. They include deterministic
EOF ordering, fragmented commands, final-output preservation, browser send
failures during introduction/gameplay/error notification, guest cleanup, session
restart, and shutdown with connected browsers. These checks use controlled
Telnet peers; this follow-up has not yet been deployed or verified on the VPS.

## Validation

```sh
.venv/bin/python -m unittest tests.test_inspect_game tests.test_deployment tests.test_provision_archwizards -v
.venv/bin/python -m tests.integration_inspection
.venv/bin/python -m tests.integration_inspection_logs --image mud86-alma9-arm:latest
```

The native acceptance test uses a disposable first-playable disk and private
port. It verifies companion compilation, empty/saved personas, file metadata,
framed text, bounded large-file tails, missing files, CLI JSON, actual lock
contention and a concurrent original SAVE. FILCOM /B confirms byte-identical
persona files across inspection, the independent password audit confirms
unchanged credentials, and original source hashes remain unchanged. Its private
evidence is under `runtime/inspection-check-final/`; the emulator is stopped
on completion. The final run needed one boot retry, consistent with the known
baseline cold-start instability.

The journal acceptance test creates and removes its own AlmaLinux systemd
container. It verifies actual journal parsing, error signatures, service filters,
time filters and execution through the deployment command dispatcher. It passed
on native ARM Linux. The deployment acceptance driver also checks the installed
`mud86ctl` persona/file/error commands; a full new native x86 installer run and
the actual remote-server update have not been performed in this session.
