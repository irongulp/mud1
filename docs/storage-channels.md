# Storage bridge channel ownership and allocation

## Result and decision

The standalone bridge now works under **MUDGUEST [2653,2653]**, including native
terminal allocation and release. The recommended first adapter design is a
**small pool of reserved secondary terminals, claimed per storage operation or
short transaction**, rather than one terminal permanently reserved per player.

This follows the [transport probe](storage-bridge-probe.md). The new evidence is
in `runtime/storage-channels-permissions-green/` (2026-09-26). It verifies the
guest-side allocation primitive, not a production allocator/service or a patch
to MUD. The read-only record contract is in
[persona-read-protocol.md](persona-read-protocol.md).

The later [native R1 milestone](persona-read-native.md) verifies complete
synthetic records and challenge-bound handover on this pool, including reuse
after a job is killed mid-record and replay after a clean emulator reboot.

## Native mechanism

1. Operator setup reserves DZ lines 6 and 7 on separate raw loopback listeners
   and marks their corresponding TOPS-10 terminals SLAVE. The existing verified
   CR bootstrap and monitor-level NO ECHO setup still apply.
2. A guest program attempts native `OPEN` on the configured pool members in
   order. A successful OPEN obtains a program-owned device/channel. It does
   not require a prior monitor `ASSIGN` in that guest job.
3. If every candidate fails, return `NO_CHANNEL` promptly. Do not queue while
   holding a persona lock, interpret the failure as NOT_FOUND, or fall back to
   `.PM`. OPEN failure alone does not distinguish contention from configuration
   or channel errors; the controlled exhaustion test establishes contention
   only for its known-good fixture.
4. Use `TRMOP.` on the selected terminal for the exchange.
5. Explicit `RELEASE` returns it to the pool on success and handled failure.
   KJOB recovers program-owned terminals after job termination. Ctrl-C alone
   stops a program but is not a substitute for the tested KJOB cleanup.

The pool scan is bounded by its configured size; ownership arbitration is done
by the monitor, not by a Python check-then-assign table. Simultaneous claims by
two MUDGUEST jobs obtained different lines. The jobs share a PPN but not device
ownership: foreign-terminal TRMOP reads, writes and settings returned protection
error 1 while the owner held the line.

The local monitor source agrees with these results: `TREDOK`, `TWRTOK` and
`MYTTY` in `build/monitor/dskb:10_7.mon..scnser.mac:7391–7419` compare the DDB's
owner job before considering additional privileges. Same-account access is not
automatically same-job access.

## Probe implementation and reproduction

`tools/fixtures/BRGP.BCL` retains its original manually assigned-line mode and
adds three **diagnostic** modes, selected on its controlling terminal:

| First argument | Second argument | Action |
|---|---|---|
| 0–7 | B1 session ID | Original preassigned-line PING/PONG probe |
| 8 | B1 session ID | Claim a pool member, exchange 40 words, release |
| 9 | Nonzero placeholder | Claim and hold until controlling-terminal input, with a 30-second diagnostic bound, then release |
| 10 | Pool line number | Attempt foreign-terminal settings, output and input for the ownership test |

The probe prints the native job number, actual GETPPN value and chosen line for
each claim, and a RELEASED marker after explicit release. `stopprobe()` releases
the claimed channel before exiting on a handled error. The original mode does
not release a monitor assignment it did not acquire.

This standalone fixture reserves I/O channel **17 octal** for OPEN. The future
MUD adapter must use the library's channel allocation rather than assume 17 is
free while game files and logs are open. Also, OPEN needs the address of the
argument vector: the embedded assembly must load its pointer and use `0(AC)`,
not pass the stack slot containing that pointer as the argument block.

Run:

```sh
.venv/bin/python -m tests.integration_storage_channels
```

Or use `--output runtime/<fresh-directory>`. The runner:

- Copies the stopped baseline and boots with the original tape, private ports,
  NOIDLE / 5M / SPEED=*8; it does not touch a live emulator or configuration.
- Compiles the independent probe through maintenance and gives its executable
  protection `<055>` for guest execution.
- Logs three ordinary MUDGUEST jobs in normally, stops at the initial persona
  name question, and runs the probe under their unchanged OS identity. No persona
  is created or saved for these experiments.
- Tests native claims and exchanges, logs guest diagnostics, checks persona
  bytes and original source hashes, then stops the disposable emulator.

The guest programs execute as MUDGUEST, but the test still uses operator actions
to configure/bootstrap the reserved terminal sockets. This does not demonstrate
unprivileged first-install setup or an unattended production channel manager.

## Acceptance results

| Scenario | Observed result |
|---|---|
| Automatic claim as MUDGUEST | Line 6 claimed, all 40 words exchanged, explicitly released |
| Another job holds line 6 | Next guest used line 7 and completed the exchange |
| Foreign same-PPN access | TRMOP SET, OUTPUT and INPUT each rejected with protection error 1 |
| Both members held | Third guest returned NO_CHANNEL within the host bound |
| Explicit release | Another guest reused the released member |
| Ctrl-C then KJOB of a holder | Both pool members could subsequently be claimed again |
| Silent responder | Native timeout in 5.133 host seconds, followed by explicit RELEASE |
| New guest after timeout | Reclaimed the member and completed all 40 exchanges |
| Simultaneous claims | Two jobs released from a host barrier claimed different pool members |
| Preservation | FILCOM `/B` found persona-file bytes identical; source SHA-256 values unchanged |

`report.json` contains the results and native exchange transcripts; `a.txt`,
`b.txt` and `c.txt` retain the guest control transcripts. The new allocation test
started red with `BRGP CONFIG`, before automatic mode existed. An intermediate
OPEN attempt returned NO_CHANNEL because the assembly used the wrong argument
address; the indexed-vector fix enabled claims. These runs are retained as
`storage-channels-red` and `storage-channels-open`.

`storage-channels-permissions-red` required separate read/write/control denial
checks that the earlier probe did not provide. The green run includes those
checks and simultaneous allocation. A separate unchanged-manual-mode regression
in `runtime/storage-channels-bridge-regression/` passed all twelve original
transport scenarios after the fixture changes.

Some exploratory runs encountered the already known cold-boot stalls, including
a halt before any probe was installed. The runner now includes DAYTIME and slave
setup in its bounded boot retry stage. This is not evidence that bridge allocation
caused those startup failures or that startup reliability is solved.

## Integration contract and remaining work

The initial pool contains two members for testing. That is not yet a production
capacity selection: each reserved line reduces the ordinary DZ connection pool.
Per-operation ownership means a player does not consume a member while typing,
answering password questions or playing without storage activity.

For a future guest adapter:

1. Obtain a channel before taking long-lived persona coordination locks. Define
   a consistent order for the channel, guest door and host transaction so a
   stalled exchange cannot deadlock acquisition in another job.
2. Establish a fresh, correlated protocol epoch before allowing a read. **OPEN
   and RELEASE do not by themselves reset a host TCP connection or invalidate
   already queued replies.** The experiment reconnects the host sockets under
   runner control. The later H1 implementation verifies explicit handover and
   retirement; unattended bootstrap/reconnect management is still required.
3. Keep one outstanding operation on a leased line initially. The R1 response
   decoder checks its expected epoch and sequence. PRREAD now verifies the guest
   counterpart with controller-provisioned fresh challenges; the MUD adapter
   must obtain equivalent freshness without relying on reused job/line numbers.
4. Release on every handled failure and preserve the existing bounded gateway
   Ctrl-C/KJOB job cleanup for abnormal exits. A stopped or lost emulator needs
   host-side invalidation as well; an old job number is not a durable identity.
5. Return pool/transport failures explicitly. Do not create a persona, acknowledge
   a save or switch authority to a native file because no channel was available.

No generated MUD adapter, external persona login, durable transaction, database
service or public deployment was implemented by this milestone.
