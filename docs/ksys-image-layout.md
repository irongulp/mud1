# KSYS executable and halted-job layout qualification

This follows the [KSYS source trace](terminal-lifecycle.md). The original offline
milestone below qualified candidate executable layouts. The follow-up section
records monitor identification and halted-job mapping work. Neither milestone
is a native shutdown fix or a release acceptance run.

## Media and exact byte matches

The local `runtime/release-v1/mud86-runtime.tar.gz` was checked against
`deploy/runtime.json` before reading its `guest.dsk` member:

- Archive SHA-256:
  `505708614b57fade39572dada365394a988433d637217ed041b17f79f38325bf`.
- Disk SHA-256:
  `23baaf1c2eeb0fe6633601d1e706e4835557def2410e87e2629c849de69a669c`.
- Distribution CUSP tape compressed SHA-256:
  `4c29361324c5ca7c55fb88b9c892a8e3e8e0ef2384982957a2dfb4a05a76b3b6`.
- Its decompressed `t10cusp1.tap` SHA-256:
  `1f8b39e010f620148814e6c3e6af4ce047d0d1ce1e76c41590c9e5d02e924e0d`.

The decompressed tape was compared byte-for-byte with the verified compressed
file's decompression. Its source is
<https://pdp-10.trailing-edge.com/tapes/cuspbinsrc_1of2_bb-x128c-sb.tap.bz2>.

`tapeutils` revision `c5da89fc472f3dfa560d75fe07d61f8210c504ef` lists:

| Tape file | Name | Byte size | Logical words |
| --- | --- | --- | --- |
| 352 | `dskb:10_7.galaxy.batcon..batcon.exe` | 36 | 16,384 |
| 481 | `dskb:10_7.galaxy.quasar..quasar.exe` | 36 | 53,248 |

Both files retain legacy `.JBSYM` RADIX50 tables. QUASAR's accompanying
`QUASAR.CTL:48–54` links with `/LOCALS /SYMSEG:LOW`.

Extraction used `t10backup -x -v -f <t10cusp1.tap> quasar.exe batcon.exe
quasar.ctl batcon.ctl qsrmac.unv`. Its `pars_5chars` encoding retains all36 bits,
including the low bit in the fifth character's high bit. `WriteBlock` removes
up to four trailing zero characters, including for binary files. Both extracted
executables were four bytes short of their complete word encoding.

The first strict decoder call rejected that incomplete word. A separate
read-only scan of the original SIMH tape records selected the two numbered
files and decoded each original36-bit word directly. It verified the lengths
above and equality with the extracted data plus exactly four zero bytes.
Those verified complete encodings—not guessed padding—were used below.
`backup_words()` continues to reject incomplete words.

Each **entire** executable, converted to the disk's little-endian64-bit word
storage, occurs twice in the release disk:

| Image | Complete sequence byte offsets in disk | SHA-256 of complete little-endian words |
| --- | --- | --- |
| BATCON | 84,255,744; 264,397,824 | `16251f4a72cb421f93d9deda64484c62be8243441bdde52ab858a397ae49dd46` |
| QUASAR | 96,308,224; 266,732,544 | `f50cc22815e66a4d464ec62529a23666496ca04e434ee6b5ac82f30c5da67a7d` |

This is stronger than matching separate blocks or a version label. It does not
identify directory ownership, active SYS files or a resident job. The two
matches are retained separately; neither is automatically selected.

## Decoder and independent validation

`tests/ksys_image.py` is offline fixture tooling. It has no runtime imports or
guest-control operations. It implements:

- Strict complete-word conversion from `t10backup` character encoding.
- EXE directory-based page loading, including zero pages and noncontiguous
  virtual addresses; malformed blocks, overlaps and missing pages fail.
- Legacy negative-count `.JBSYM` tables, with bounds checks and separate
  RADIX50 name/DDT flags. Missing or ambiguous typed symbols fail.
- Whole-sequence, word-aligned disk matching that returns every occurrence.

References:

- SIMH revision `47b7ddabbe5b548cfc32f2fd45f7bed238ff7921`,
  `PDP10/pdp10_sys.c:294–393` (`load_exe`).
- Tapeutils revision above, `t10backup.c:153–220,427–450`.
- Pinned Stacken DDT blob `cc66c00022f73deb2626f31bab2a42d2abd2a31f`,
  `DDT.MAC:2238–2243`: global/local/program-name/delete-input/delete-output
  flags. The decoded four-bit flags1 and2 mean global/local;12 octal is a
  local with output suppressed. Equal local names in different modules must
  not be silently merged.

Seven unit tests first failed with the missing module, then passed. They
exercise all36 individual bits, malformed EXE/table cases, name/type ambiguity,
and rejection of partial/unaligned image matches. No historical binary fixture
is committed.

An independent offline invocation of the local SIMH binary performed only
`LOAD`, `EXAMINE` and `QUIT`, with no attached disks, listeners, boot or guest
instruction execution. Its binary SHA-256 is
`f813e22023347141d0618e5cdcfb3d37a49928b17e3d3938d2e8945cc50beec1`.
All15,872 mapped BATCON words and52,736 mapped QUASAR words matched the Python
decoder exactly. SIMH compresses repeated examination values as `thru ...
same as above`; the initial comparison omitted those rows and failed. The
corrected comparison expanded only that explicit syntax and compared every
address/value. The first output is retained.

## Candidate layouts

All addresses and values here are **octal user virtual addresses**, not
physical memory addresses. They are valid for the byte-identified images above.
No current CI job identity has been bound to them.

| Image | Symbol | DDT type | Address |
| --- | --- | --- | --- |
| BATCON | `G$KSYS` | global | `457` |
| BATCON | `KSYCNT` | local | `553` |
| BATCON | `KSYMAP` | local | `562` |
| BATCON | `KSYFIN` | local | `1605` |
| BATCON | `KSYJOB` | local | `2673` |
| QUASAR | `HDRPSB` | global | `60035` |
| QUASAR | `G$NOW` | global | `102624` |
| QUASAR | `G$KSYS` | global | `102647` |
| QUASAR | `G$WTIM` | global | `102754` |
| QUASAR | `A$HELL` | global | `333` |
| QUASAR | `A$PSBC` | global | `4601` |
| QUASAR | `KSYS2A` | local | `77643` |
| QUASAR | `I$SKSM` | global | `77731` |

BATCON's `.JBVER` is `010500005027`, its symbol table has2,299 entries;
QUASAR's is `000500001512`, with7,907 entries. Their `.JBSYM` words are
`767012026007` and `741072107077`, respectively.

QUASAR constants in the table give PSB offsets `PSBPID=1`, `PSBNAM=2`,
`PSBFLG=4`, `PSBUDT=5`, and states `PS.RUN=0`, `PS.WAT=1`, `PS.FIR=2`,
`PS.KSY=3`. These are field values/offsets, not standalone addresses.
Several constants repeat in module tables; these observations do not relax
the decoder's unique-symbol lookup.

Independent disassembly of the byte-matched image corroborates specific source
boundaries:

- `77701–77710` deposits status3, clears retry count, obtains time, adds the
  literal at `102333`, and stores PSB offset5. That literal is `132` octal,
  decimal90 UDT units (~30 guest seconds).
- `77731–77745` takes PID from PSB offset1 and constructs/sends message type
  `66` octal (`.QOKSY`).
- `4605` starts the PSB traversal from `60036` (`HDRPSB+.QHLNK`); `4622–4624`
  compares the PSB deadline against `102624` (`G$NOW`).

This corroborates those routines in the candidate image, not full source/binary
equivalence. It cannot explain the previously captured monitor PC354741.

## Original live-mapping gate

The source addresses above are enough to describe a targeted capture **after
identifying and mapping the actual jobs**. The current diagnostic has no
validated mapping from the deployed monitor's job table/UPTs to those virtual
pages. `t10mon.tap`'s directory offers no monitor MAP/SYM or built monitor EXE
with which to establish that mapping. The earlier monitor scope correction
fingerprints a different, limited code boundary and does not establish job-table
addresses.

Before adding failure-time reads:

1. Bind the actual monitor layout and job/context identity to its page tables.
   The halted CPU's UBR alone may belong to another job.
2. Validate the target jobs' code pages against the identified executable,
   accounting explicitly for load-time changes. Reject missing, nonresident,
   stale or ambiguous mappings.
3. Only then traverse the bounded QUASAR PSB list and read the named BATCON
   state. A missing mapping must remain unknown, not “BATCON absent”.
4. Qualify that mapping in a separate known-healthy disposable fixture before
   relying on it after a failed KSYS. The failure capture still must not resume
   the guest or submit another KSYS.

No new CI run, runtime instrumentation or monitor change was made. The previous
shutdown remains unclean and the logout-timing question remains open.

## Private evidence and reproduction

Evidence is local to the isolated diagnostic worktree's `build/ksys-layout/`:
verified release disk copy, original extractions, complete character encodings,
`layout-report.json`, `simh-decoder-check.json`, full examination outputs and
`quasar-ksys-disassembly.txt`. `resident_job_verified` remains false.
Historical images are neither committed nor published.

With those verified private files available:

```python
from pathlib import Path
from tests.ksys_image import backup_words, load_exe, symbols, unique_symbol, disk_matches

root = Path("build/ksys-layout")
words = backup_words((root / "quasar.complete-characters").read_bytes())
memory = load_exe(words)
assert unique_symbol(symbols(memory), "HDRPSB", flags=1) == 0o60035
assert disk_matches((root / "release-guest.dsk").read_bytes(), words) == [
    96308224, 266732544,
]
```

Host validation: `python -m unittest tests.test_ksys_image` plus the existing
guest-control/deployment/lifecycle diagnostic regressions: **96 tests passed**.
No post-green refactor was needed; the reader remains separate from runtime
capture.

## Monitor and job-mapping follow-up

A read-only scan of the verified release disk found five monitor EXE candidates
with embedded symbols. The image at byte offset **293919744** matches all eight
existing `server.monitor_scope.FINGERPRINTS`. Candidates at289690624,295189504,
300801024 and302091264 do not. Selection therefore uses code fingerprints,
not the shared version label or job count.

The selected complete little-endian word image is158208 words, SHA-256
`be33ce5412bc18289cfa88afdd3feb0135b03180372bea4535e4b3c5f4e6d0fb`.
Its `.JBVER` is `070400033461`;22473 symbol entries include these octal values:

| Symbol | Value | Meaning |
| --- | --- | --- |
| `JOBMAX` | `43` | Highest job number (35 decimal) |
| `JBTSTS` | `10061` | Job status table; LH `JNA=40000` means allocated |
| `JBTADR` | `10346` | Resident low-segment core descriptor |
| `JBTPRG` / `JBTNAM` | `12106` | SIXBIT program-name table |
| `JBTPDB` | `12502` | Job PDB pointer, **not UPT page number** |
| `JBTUPM` | `14174` | RH is physical UPT page number |
| `.UPJOB` | `322` | Job backlink within UPT |
| `SECTAB` | `540` | Section-zero pointer offset |
| `PIDTAB` | `15735` | IPCF PID-entry table |
| `%IPCPM` / `%IPCMP` | `16101` / `16102` | Addresses of PID index mask/table limit |
| `.PDSAC` / `.PDCTC` | `71` / `72` | PDB context-chain/current-context offsets |

Independent SIMH disassembly confirms `MKADD350715` reads `JBTUPM` before
`WRUBR`, and `VALPID454553` checks PID index/generation before extracting a
**job/context handle**, not a bare job number. `JBCHCT403450` and
`FNDPDB406553` corroborate current-context lookup. `PCTXNO402030` is
`001111000000`: low9 bits of context-block word0. With no context chain,
`JBCHCT` accepts context1; otherwise the requested context must be located and
compared with `.PDCTC`. This decoder rejects non-current contexts.

Source provenance is the original `t10mon.tap`'s `APRSER.MAC1559–1656`,
`IPCSER.MAC326–344` and `CTXSER.MAC1328–1398`, corroborated at the byte-identified
monitor boundaries above. No replacement historical executable was produced.

### Read-only decoder boundary

`tests/ksys_mapping.py` takes memory-reader callbacks; it issues no guest or
simulator commands. The caller must establish the monitor fingerprints and keep
the guest halted throughout. It follows pinned SIMH `pdp10_pag.c:447–545` for
immediate/shared/indirect section-zero backing, rejects missing/nonresident/
unsupported/cyclic/out-of-range mappings, and bounds indirection.

This is **resident backing translation**, not an execution-permission or
CST-age validator. It deliberately avoids virtual console examination:
`cpu_ex` calls `conmap`, whose page walk can write CST entries. Only physical
reads and register examination are used in the healthy fixture. The mapper
does not modify CST, UBR, EBR or page tables. Two independent synthetic SIMH
oracle cases (immediate and shared/indirect) returned the same words without
booting or executing guest instructions.

Job selection requires a unique exact name, allocated/resident table entries
and matching UPT job backlink. Callers then compare `.JBVER` and selected
immutable code ranges with the identified BATCON/QUASAR images before reading
state. This is a selected-code signature check, not a whole resident-image hash.
PSB traversal is bounded at64 entries. PID generation, job number and current
context must all agree; missing mapping remains unknown.

### First two native captures and decoder correction

Private `build/ksys-layout/healthy-map.py` used fresh copies of the verified
release disk, the checksum-verified local `active-tick-v1` emulator, original
tape boot, existing monitor scope correction and per-boot DAYTIME batch proof.
No browser/persona was admitted. A pre-halt SYSTAT supplied an independent job
roster; the healthy halt has a30-second/128-physical-page bound and is followed
by resume and normal single-dispatch KSYS shutdown.

`runtime/ksys-map-01` and `ksys-map-02` both verified QUASAR job7/BATCON job12,
their UPT backlinks, version words and selected code ranges. Ten monitor code
ranges matched, excluding the scope installer's three intentionally replaced
entry instructions. Both stopped at the PSB ownership check and subsequently
completed native clean shutdown/process exit. These failed reports are retained.
Run02's capture lasted1.746 host seconds.

Run02 retained the exact failed operands:

```
PSB                147174
PSBPID      400017001002
PID mask            177
PID limit           110
PID index             2
PIDTAB[2]   400017001014
BATCON job           14
```

The generation comparison is zero (matching), and the entry's job number is14
octal/12 decimal. The incorrect check compared the entire RH `1014` with `14`;
the additional `1000` is **context1**, confirmed by the monitor's handle layout.
This was a decoder rejection, not evidence of stale BATCON registration.
Run01 did not retain those operands, so its identical error alone is less
specific evidence. The corrected tests include these witnessed values plus
wrong-generation, wrong-job, non-current, missing, duplicate and cyclic context
cases. The first tests failed before implementation; all107 focused decoder/
guest-control/deployment/lifecycle tests now pass.

Failure-time capture integration remains separate. Its original deadline and
halt must precede reads, and it must never resume or issue another KSYS.

### Third capture: inaccessible signature page

`runtime/ksys-map-03` matched all13 monitor signature ranges, including context
lookup, then rejected QUASAR virtual address77643. The targeted physical words
replay that failure offline: page-table entry at physical360077 contains
`044400000445`, a **type-zero/no-access** pointer. Its nonzero software fields
do not authorize reading a guessed physical page. No state interpretation
passed. This captures an inaccessible KSYS code page, not an absent QUASAR job
or a demonstrated registration fault. Normal KSYS/process exit were clean.

Unlike01/02, this run retains only individually requested physical operands in
0600 `targeted-words.json`, not whole memory pages. Capture lasted1.342 seconds.
SYSTAT independently listed QUASAR job7 and BATCON job11; job numbers are found
anew, never inherited from earlier runs.

The corrected identity signature uses QUASAR `A$HELL333–400` and BATCON
`TOPLVL652–707`, with `.JBVER` still mandatory. All38 QUASAR and30 BATCON code
words are compared against checksum-pinned images. Independent source and
disassembly corroborate those fixed page-zero routines (`QSRADM139–181`,
`BATCON271–303` at the pinned Stacken commit). No instruction in these ranges
is treated as mutable or skipped. This avoids requiring unused shutdown code
to be resident; an inaccessible identity **or state** page still rejects the
observation. Tests retain03's exact no-access operand and reject version-only,
missing-code and altered-code matches.

### Healthy mapping qualified

`runtime/ksys-map-04` passed the corrected capture and normal shutdown:

- 13 monitor code ranges matched; existing scope installation and current-boot
  DAYTIME probe passed.
- Independent SYSTAT and halted table reads identified QUASAR job7/UPT487 and
  BATCON job12/UPT576 (these page numbers are decimal).
- Both UPT job backlinks, `.JBVER` values and complete page-zero code signatures
  matched. QUASAR's sole PSB identified BATCON, with generation/job/current
  **context1** verified through the monitor PID table and a nonempty context
  chain. The no-context-chain fallback remains host/source-tested.
- PSB status0 (`PS.RUN`), QUASAR `G$KSYS=0`, BATCON `G$KSYS=0` and `KSYCNT=0`
  were read. This is normal registered/idle state, not an observed KSYS
  message-dispatch or logout-work transition.
- 27 physical pages were read in1.930 seconds; the retained407 individually
  requested words replay the exact job binding/signatures/state offline.
  `targeted-words.json` is0600, SHA-256
  `af05e8ef942c94bc01a569ed1416d10b9a16ace3d2f4fda7a9f314a6edfe6e26`.
- Native KSYS, simulator Goodbye and actual process exit passed. All four
  local experiment processes/emulators have exited; failed01–03 captures remain.

Final validation is **109 focused tests**, including13 new mapping/identity/
context/state tests, plus diff checks and the native/offline evidence above.
Blue cleanup extracted SIXBIT encoding and reusable code-signature verification;
no production runtime/controller changes were made.

### Next failure-only experiment boundary

Healthy job/page/current-context binding is now locally qualified on this
checksum-pinned release profile. The proposed next experiment is one deployment
diagnostic with targeted reads only after the original KSYS failure deadline
and already-established SCP halt:

1. Require the known monitor layout and job code signatures again at that
   halt; use physical/register reads only and the existing bounded diagnostic
   budget. A swapped/unmapped job or state page stays unknown.
2. Preserve QUASAR PSB status/PID/deadline as separately identified QUASAR data.
   A zero/stale PID must not prevent reporting those raw registration fields,
   nor be associated with a current BATCON job. The current healthy helper is
   stricter: it returns state only for a fully bound current PID. Failure-mode
   partial-evidence reporting still needs its own red/green tests.
3. When BATCON is independently identified, capture its KSYS/count fields
   separately; label whether the PSB binds to that job/context. The result can
   distinguish unregistered/waiting, registered-but-not-accepted, and accepted
   shutdown-work states without implying a cause from one snapshot.
4. Keep the original failed-stop result, never resume or replay KSYS, and allow
   the existing fixture teardown to finish. A capture cannot authorize backup
   or turn an unclean stop into a clean one.

This experiment has **not** been integrated or dispatched. No new CI run was
launched, no intermittent failure was reproduced by these four healthy fixtures,
and no root cause or shutdown fix is claimed. Both full uninstrumented release
acceptance jobs on intended main remain required before `v1.1.0`.

## Failure-only integration

The subsequent implementation adds `tests/ksys_capture.py` to the installed
diagnostic launcher only, enabled by `MUD86_KSYS_MAPPING=1` in the disposable
`shutdown-capture.conf`. Full acceptance/production launchers do not use it.
The observer records whether the original KSYS command's deadline was exhausted
**when that command failed**, before spending diagnostic time. Early failures
cannot become eligible merely because the later halt takes time.

After the existing SCP halt and DZ report, the decoder shares the original
ten-second diagnostic deadline (no reset/extension), with at most128 physical
pages. It never resumes, deposits memory/registers, issues a guest command,
retries a read after transport uncertainty, or overrides the original shutdown
result. Required scope verification and13 monitor hash ranges precede any
job interpretation. Pinned code digests/version values establish each job
independently without needing historical binaries in the diagnostic checkout.

`registration()` now reads QUASAR's bounded PSB list independently of
`bind_pid()`. `shutdown_state()` retains its original strict healthy contract.
The capture report keeps separate:

- verified job identities (name/table/UPT backlink/version/code signature);
- QUASAR-owned PSB flags/status/PID/deadline, even with zero/stale PID;
- individually readable QUASAR and BATCON named state words;
- PID/current-context binding, explicitly `unknown` unless it verifies;
- controlled mapping errors or transport error types, never terminal buffers.

A `complete` capture means its mappings/fields/binding decoded successfully,
not that KSYS completed. A missing or inaccessible job remains unknown, not
absent. Report values are raw unsigned36-bit words; signed counters and UDT
differences require their source interpretation.

Raw physical pages remain only in a bounded in-process cache. The existing
`private_console()` suppresses transcript logging; a transport exception
propagates through that context so logging remains suppressed during teardown
if memory output is still queued. Reports are published at0600 and contain
only named state/identity fields, registers and controlled error metadata.

Red/green tests cover zero/stale PID partial evidence, independent BATCON state,
bad monitor/job signatures, missing pages, halt/scope/deadline/page limits,
transport-log suppression, original-deadline eligibility, no resume/replay,
preserved failed-stop status, and installed imports without a checkout `tests`
package. Blue extraction separates registration from PID binding while keeping
the prior healthy report format.125 focused tests and actionlint pass.
The new decoder replays `ksys-map-04` exactly for the named state/binding;
`failure-decoder-replay.json` records that offline check. No new local guest
was needed for this integration.

The selected deployment experiment is **one**35-minute diagnostic on
`fix/native-terminal-lifecycle`: shutdown reproduction/fresh-mariadb,
original external sequence, passive logout observation and timed census enabled,
shutdown census/healthy census/repeated workload disabled. It preserves the
four-login/first-warning fences from44792601384 and adds only post-deadline
shutdown mapping. Decisive outcomes are (a) a readable waiting/unregistered PSB,
(b) a bound running PSB without BATCON KSYS acceptance, (c) accepted KSYS and
pending work, or (d) explicit unknown mapping/non-reproduction. A single
snapshot distinguishes boundaries, not the underlying cause. The run and
retained artifact must be recorded before treating any outcome as witnessed.

## First failure-time capture: registration expiry witnessed

Run [44810792691](https://github.com/irongulp/mud1/actions/runs/44810792691)
at `408f1ad` completed with failure after23m25s, within the35-minute bound.
Artifact14669540131 (`installed-shutdown-capture`,40,832 bytes) has digest
`sha256:e956d589dedce93a1b70c8bbf4395406475b79e57b0a6ba71ab915ac25a0a839`.
Downloaded evidence and workflow log are retained under
`runtime/ksys-capture-44810792691/`.

Installation, editor check, installer rerun and two browser sessions progressed;
both browser logouts completed with `recovered=False`. Backup then refused the
unclean guest stop. The sequence report retains `experiment-error`,
`phase=host-command:sudo`, `logins_submitted=2`; it is not a four-login pass.
No logout warning/census request occurred, so passive-versus-CTY logout progress
is still untested. Two earlier captured stops were clean.

### Final stop timeline

Times below are UTC host journal timestamps; guest printed times are distinct.
The authoritative file is
`artifacts/installed-shutdown-capture/deployment-ci/mud86-external-fresh/after-stop-services.log`.

| Host time | Observed evidence |
| --- | --- |
| 20:44:08 | Last boot census: job1 detached BATCON, `26+40 SL`; current-boot DAYTIME output/logoff had completed |
| 20:44:28 | Second browser logout completed |
| 20:44:31 | Empty queue response; one `SET KSYS NOW`; event queued and waiting-for-BATCON notice (guest20:44:21) |
| 20:45:10 | `BATCON failed to startup` and `Use OPSER for KSYS logouts since BATCON didn't start` (guest20:44:59) |
| 20:45:59 | Original wait failed; diagnostic halt at PC355061 octal, followed by DZ report |
| 20:46:01 | Partial mapping report, original failed-stop result, simulator Goodbye and runtime exit |

This adds decisive evidence beyond44792601384: QUASAR reached the registration
expiry reporting path. It is not merely an absent completion message, and it
does not prove that BATCON never existed (the earlier census showed it).
Pinned `QSRADM.MAC:2675–2686` compares `PSBUDT` with `G$NOW` and emits these
notices for the special KSYS waiting state. At2719–2721 it removes that PSB.
These line numbers count newline characters, not form-feed page separators.
No OPSER fallback was attempted.

### Halted state and interpretation limit

The existing physical-only capture completed21 page reads in1.442 seconds,
within the shared ten-second diagnostic budget. Monitor signatures and QUASAR
job7/UPT346 (decimal) identity/version/code verified. Report
`shutdown-capture/cff994bf85414f448639c89b5ff38482/report.json` preserves:

| Field | Decimal raw value / interpretation |
| --- | --- |
| PSB address | 52860 |
| PSB PID | 34363671042; **not bound to a current BATCON job** |
| PSB flags/status | 1310721 / 0 (`PS.RUN`) |
| PSB deadline | 16086431043 |
| QUASAR now | 16086431063 |
| QUASAR KSYS | 68719476735 (36-bit -1, set) |
| QUASAR wake | 0 |
| BATCON identity | `Missing or ambiguous job name` |
| PID/context binding | unknown |

`PS.RUN` is only the later QUASAR-owned record's value. It cannot establish
successful recovery, HELLO delivery or BATCON's acceptance of KSYS. In
particular, the source expiry path removes the waiting PSB; this snapshot does
not establish continuity with that earlier record, even if an address is reused.
The20-unit difference between the captured time/deadline words is not a host
latency measurement. BATCON KSYS/count fields were correctly omitted.

The name lookup currently discards its match count and does not inspect the
PSB PID table entry when BATCON identification fails. Thus zero matches versus
duplicate names, stale PID versus another current job/context, and a transient
program-name change remain indistinguishable in this artifact. Raw memory
pages were intentionally not retained; these missing operands cannot be
recovered offline. Do not translate this error into “BATCON absent.”

Both service units ended inactive/dead; Goodbye and fixture removal passed.
Native shutdown remained **unclean**, final verification failed, and backup
remained refused. No disk promotion, uncertain-command replay or guest resume
occurred. The capture is native-qualified for partial QUASAR evidence, not a
complete BATCON-state capture or root-cause fix.

### Next evidence gate

Before another native run, extend only the halted diagnostic to retain bounded
job-name match counts/indices and independently decode the named PSB PID entry.
Require the existing generation/allocation/current-context/code checks before
associating it with BATCON. Preserve zero/stale/other-program outcomes as raw,
unbound evidence, with red/green tests and replay against the healthy04 operands.
Then assess whether a single post-expiry snapshot can answer the remaining
launch/exit/registration question or needs a separately scoped earlier observation.
An unchanged deployment retry cannot recover the operands omitted here.

The one-run budget is complete; no second run was launched. This evidence-only
follow-up changes no implementation; the125-test/actionlint baseline remains.
Both full uninstrumented acceptance jobs on intended main still gate `v1.1.0`.

## Independent PID ownership diagnostics

The next host-only increment addresses the operands missing from44810792691:

- `job_name_matches()` completes the bounded35-slot name scan before reporting
  match indices. An unreadable scan is an error, never an empty match list.
  Zero matches and duplicates are distinct; neither alone establishes absence.
- `pid_entry()` independently reads the verified QUASAR PSB's monitor PID slot,
  retaining the mask, limit, index, raw entry, generation comparison and decoded
  job/context. It does not require a BATCON name match. Zero/invalid PID or an
  out-of-range slot remains unknown.
- `pid_job()` follows only a matching generation and in-range job number,
  retaining raw name/status/core/UPT metadata. Stale entries never authorize
  reads of the replacement job. Unallocated jobs retain their metadata but do
  not authorize current-context traversal.
- The capture reports current-context agreement separately from image binding.
  Another program, duplicate name, stale PID, context mismatch or bad code
  signature never enables BATCON state reads or a verified BATCON binding.
  Candidate metadata is explicitly not an image identity.

The strict healthy helper shares the extracted PID decoder and retains its old
report format. No failure deadline, page budget, halt policy or production
controller changed. Physical pages remain private and transient.

Six new red/green regressions cover complete/partial name scans, stale PID
operands without replacement-job reads, other-program/unallocated metadata,
PID bounds, missing/duplicate names, non-current contexts and bad image code.
Blue cleanup shares PID decoding with the strict binder. **131 focused tests**
and actionlint pass. `runtime/ksys-map-04/pid-decoder-replay.json` (0600) records
offline replay: the prior state/binding matches exactly, name matches are7/12,
and the PID entry identifies allocated job12/current context1. Replay still
uses27 physical pages; its host duration is not new native performance evidence.

### Amended experiment decision

A further post-deadline snapshot can now answer the narrow ownership question
left open by44810792691: zero versus duplicate BATCON names; stale PID versus
matching-generation owner; owner's current program/context. It cannot prove
launch/exit history, identify the earlier expired PSB by address alone, or show
where an already-exited BATCON stopped.

Select one amended35-minute diagnostic with the same original external
sequence and no pre-shutdown census, adding only these post-halt operands.
This is a new evidence question, not a retry seeking a green release result.
Keep the first-warning/four-login fences and single KSYS attempt. A successful
shutdown is non-reproduction; a partial mapping remains unknown. If the owner
has already disappeared, use this result to design an earlier observation
instead of repeatedly sampling the same late boundary. Record the new run ID
and outcome before claiming any native qualification of these added fields.
