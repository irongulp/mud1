# Verified guest control and staged terminal configuration

This is a focused prerequisite to the browser RESET-permission change. It does
not change MUD authorization, executable protection, gameplay, original source,
the emulator revision, startup retries or persistence protocols.

## Demonstrated defect

In narrowed RESET CI run38568927339 attempt3, the host sent
`copy sys:tty.ini=tty:` but TOPS-10 echoed `copy sys:tyt.ini=tty:`. The old controller
had already sent Enter. It waited for the correct echo while COPY could be
accepting file input under the wrong filename; shutdown then failed. Other
retained native transfers also lost, duplicated or reordered input.

The baseline regressions reproduce the relevant behavior without relying on
host timing: corrupted control input is executed, and active SYS:TTY.INI is
written before its replacement can be independently checked.

## Input contract

`tools.guest_control.submit_line` sends printable ASCII at an explicitly owned,
echo-enabled prompt. Every byte must be echoed exactly before the next byte;
Enter follows only the complete verified line. A single existing deadline covers
the whole operation. Dropped, duplicated, reordered, unexpected or stale output
aborts submission. Error flags distinguish whether input began and whether Enter
may have been delivered. A lost post-Enter response never triggers replay.

The controller retains explicit monitor/OPR state. Program dialogues and opaque
seed/compiler payloads retain their existing protocols. Long source transfers
retain existing line pacing and independent whole-file read-back; character echo
does not prove COPY has consumed file data.

Native companions can leave additional empty monitor prompts. Only bounded
dot/CR/LF padding before the first echo is accepted. CTY allows the exact witnessed
stomper and hourly status announcements; OPR startup/accounting notices require
the entire typed prefix to be redrawn correctly. Unknown diagnostics and partial
frames still abort. OPR resynchronization is allowed before input begins, never
after a command has been partly or fully submitted.

`NativeInspector` uses this contract for monitor requests, including TYPE/COPY
headers and DBASE launch. Custom response framing remains caller-owned. Shared
command deadlines preserve the existing longer snapshot/compile allowance.

After an unfinished COPY, runtime cleanup interrupts and witnesses a monitor
before issuing any OS command. Actual native KSYS completion remains required
for a clean marker. No synthetic clean marker or shutdown fallback is added.

## Configuration activation

The external terminal initializer setup writes `SYS:XTTY.TMP`, checks its complete
TYPE output, then retains the existing configuration as XTTY.INI and activates
the staged file. It reads back SYS:TTY.INI afterward. A bad, occupied, inaccessible
or unverifiable staging file leaves the active configuration untouched. Identical
reruns remain idempotent. The temporary filename is fixture/controller-owned;
failed evidence is preserved rather than deleted or reused blindly.

## Validation

- Baseline tests failed for corrupted COPY submission, premature active-file
  rewriting and occupied-stage handling; they pass with this implementation.
- 378 host tests passed on macOS Python3.12, including protocol, source-preparation,
  gateway and real Chromium coverage. No gateway behavior was changed.
- Fresh pinned native image:200 verified COPY/read-back rounds, staging,
  idempotence, reboot, FILCOM persona-byte preservation and two genuine clean
  shutdowns passed. Original source hashes stayed unchanged. The supplied main
  checkout's pinned unmodified SIMH was used; no timer correction was included.
- Evidence: private OpenCode directory `control-focused-native-4`. Earlier
  `control-focused-native-{1,2,3}` retain FILCOM harness syntax failures: FILCOM
  rejects wildcard/double-extension input. The final fixture copies the native
  .PM file to ordinary-named snapshots before binary comparison.

Run only against fresh disposable outputs:

```sh
python -m tests.integration_guest_control --assets /path/to/runtime-checkout \
  --output /private/new-control-check --rounds 200
```

## Review sequence

Keep the RESET fix separate. After this foundation is merged, rebase/revalidate
the RESET PR against it. Further focused work should cover complete native logout
before terminal reuse, the independently reproduced SIMH interval interpolation
defect, and bounded private startup recovery/error preservation. Batch readiness
and shutdown draining require their own review. All broader work/evidence remains
on `fix/deployment-startup-reliability`; it is not a dependency bundled here.

This fixes verified submission and activation safety, not the cause of all native
startup stalls, stalled reads or arbitrary disconnects. Existing CI failures must
be retained and classified; do not rerun indefinitely or claim one green run
establishes exhaustive reliability.
