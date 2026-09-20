# Archwizard password audit

## Verified result

**Ordinary saved passwords work for six archwizard names, but not for Richard.**
Richard can be created and saved with a password; the same password is then
rejected on re-entry. The stored password word does not change during the
rejected attempts.

The result was the same in:

- The historical executable in the first-playable checkpoint.
- A private rebuild with the existing availability-only 24/7 patch.
- Entry using the ordinary MUDGUEST operating-system account.
- Entry using the RICHARD maintenance operating-system account.

| Persona | Correct saved password | Ordinary wrong passwords | Stored PSWD |
|---|---|---|---|
| Richard | Rejected | Rejected | Unchanged |
| Roy | Accepted | Rejected | Unchanged |
| Brian | Accepted | Rejected | Unchanged |
| Ronan | Accepted | Rejected | Unchanged |
| Friday | Accepted | Rejected | Unchanged |
| Yawn | Accepted | Rejected | Unchanged |
| Debugger | Accepted | Rejected | Unchanged |
| Authtest (ordinary control) | Accepted | Rejected | Unchanged |

Uppercase versions of correct passwords also worked for the six archwizards
and the ordinary control, as expected from the engine's case folding. They
were rejected for Richard.

## Method

The audit used disposable copies of the stopped baseline disk, separate SIMH
processes and private loopback Telnet ports. It did not pause, reconfigure or
change the live game or its personas.

Each fixture password was generated as six random bytes encoded with Base64,
rejecting candidates outside `[a-z0-9]{8}`. These are **disposable test
credentials**, not installation credentials. Each persona was created using
the original game, explicitly SAVEd, and quit.

For each of eight personas, in each of two operating-system account contexts,
the audit checked:

1. An unrelated wrong password before a successful login.
2. A one-character variation of the correct password.
3. The correct password with case changed.
4. The correct password, followed by SAVE and QUIT if accepted.
5. The correct password again, without resetting the stored record.
6. The wrong password after the preceding sequence.

That is **96 authentication attempts per executable variant**, 192 across
the completed historical and 24/7 runs. For each build, Richard's six expected
successful authentications were rejected; the other 90 outcomes matched the
ordinary authentication expectation. `all_password_checks_passed: false` in
the reports is therefore an intentional finding, not a claim that the audit
could not finish.

A saved copy of the private persona file was restored before independent test
sequences. The completed 24/7 run used fresh MUD processes in persistent,
logged-in OS sessions to avoid carrier-drop and TTY-stomper races unrelated to
authentication. It booted the private disk again after provisioning, so the
fixtures survived an emulator restart before those checks. The historical
control used fresh OS jobs and produced the same password results.

Some preliminary runs hit the known startup/terminal lifecycle problems and
were interrupted. They are retained as diagnostics but are not treated as
password rejections. Rejection requires the original `No!` response; acceptance
requires the expected greeting and play prompt. The completed reports below
contain all 96 cases each.

## Inspecting the stored password

`tools/fixtures/AUDPWD.BCL` is a **separate, read-only diagnostic program**. It
reads the persona file with the original BCPL library and prints the native
`PSWD` word and game count for each record. It uses the documented layout in
`source/DUNGEN.GET`: 256 header words, 12 words per record, password at offset 8.

The helper is compiled separately from MUD. No debug prints or additional
objects are linked into the game, so the audit does not move MUD's variables
and thereby alter Richard's address-dependent check. The standalone library's
DOFILE takes 15 arguments; MUD implements its own 11-argument wrapper, which
must not be used as the standalone diagnostic's calling convention.

The 24/7 test image was relinked using M24LIB in the documented object order;
the code ended at `.HIGH. 502577`. Its data was regenerated with the original
DBASE, reporting 25247 words. Authentication source was not modified.

For successful logins, the audit inspected PSWD both after explicit SAVE and
after QUIT. All inspected words remained stable. For Richard, re-entry failed
before another in-game SAVE was possible; rejected attempts left his original
stored word intact.

## Same-password control for Richard

A further check on the 24/7 test image assigned **the very same password** to
Richard and a newly created ordinary persona, `Rcontrol`:

- Both records contained exactly the same nonzero PSWD word.
- That password authenticated `Rcontrol`.
- It did not authenticate Richard.
- The unrelated wrong password was rejected for `Rcontrol`.
- Richard's stored word remained unchanged.

This rules out an unsupported password format, a failed initial SAVE or a
different stored hash as the explanation. The failure follows the persona name.

## Verified Roy → Richard attachment

A follow-up on the private **24/7 image**, through the MUDGUEST OS account,
confirmed that a login to saved Roy can attach to saved Richard. The original
fixtures have different, nonzero native password words. Each different-password
case restores the saved fixture file and starts a fresh MUD process before
authenticating Roy.

| Case | Password prompt | Attachment | Richard's stored password afterward |
|---|---|---|---|
| Unrelated wrong password | Yes | Rejected; SAVE still identifies Roy | Original Richard value |
| Roy's password when different from Richard's | Yes | Rejected; SAVE still identifies Roy | Original Richard value |
| Richard's correct password, then QUIT without SAVE | Yes | Accepted | Original Richard value in this zero-score, one-game fixture |
| SAVE Roy, attach with Richard's correct password, then QUIT | Yes | Accepted | **Replaced by Roy's value** |
| Richard's correct password, then SAVE as Richard and QUIT | Yes | Accepted | **Replaced by Roy's value at SAVE** |
| Matching saved password values, fresh Roy login | **No** | Accepted | Matching value retained |

For successful different-password attachments, the game explicitly reports
`Attaching to Richard the arch-wizard.`, WHO includes Richard, and wizard-only
`GO WRDBE` succeeds. SCORE says `Level of experience: Novice` because the saved
fixture has zero points; experience level is calculated from score, independently
of wizard privileges. WHO also retains the detached Roy personas, so it is not
treated as proof that every listed persona has an active connection.

Inspection immediately after attachment finds Richard's original password word
and game count unchanged. **Authentication itself does not change the stored
password; subsequent persistence can.** The same-password case is established
by the preceding attached SAVE, then verified with another fresh Roy login.
The saved audit fixtures are restored afterward, and the private emulator is
stopped. The live game is not involved.

### Why attachment works and may omit the prompt

- `MUD7.BCL:164` requires `maint` for an archwizard target. Ordinary wizard mode
  alone does not grant this. Existing saved archwizard login sets `maint`
  (`MUDLIB.BCL:1132`); initial creation only sets WIZARD (`:1159`). SAVE itself
  does not set `maint`; the save/quit/relogin sequence enables the existing-persona
  path.
- `MUD7.BCL:186–205` checks the target's saved password directly with `encrypt`,
  without executing Richard's special direct-login exception.
- When the target's saved password value already matches session `ps.word`,
  there is no further password prompt. This is a native comparison-value shortcut,
  not a blanket exemption for archwizard-to-archwizard attachment.
- The password question has **no following `*` prompt** because ATTACH sets
  `pretend=true`. Integration clients must respond to the question itself.

### Correction: attached SAVE is not reliably blocked

An earlier source-only interpretation said attached personas could not SAVE and
could not be updated on QUIT. **The native test disproves that interpretation
for attachment to this saved Richard persona.**

`ATTED` is bit 4 of `STATES` (`DUNGEN.GET:368–373`). ATTACH first sets it at
`MUD7.BCL:226`, but then replaces the entire STATES word with the saved WIZD word
at `:234`. For the normal saved fixture, this clears ATTED again. Consequently,
the SAVE guard at `MUD5.BCL:262` and QUIT update guard at `MUDLIB.BCL:1224` no
longer recognize the profile as attached.

ATTACH does not replace session `ps.word` with the target password. The supplied
target password is checked through a local variable. `dumpersona()` later writes
session `ps.word` into the target's saved PSWD (`MUDLIB.BCL:1383`), which is still
Roy's value. Explicit SAVE therefore changes Richard's password to Roy's value.

QUIT also writes the profile when its normal persistence conditions hold. In
the tested one-game, zero-score Richard fixture, QUIT alone does not update it;
Saving Roy earlier in the same session leaves `savedp` set and causes QUIT after
attachment to update Richard. Other persistence conditions include more than
one game or a nonzero score, so **omitting an explicit SAVE is not a general
guarantee that attachment preserves Richard's password**.

These results establish a working attachment route and its persistence behavior.
They do not establish the historical author's intent, a direct Richard login,
or the behavior of every attachment/detachment state. The engine is unmodified.

## Interpretation

In `source/MUDLIB.BCL:1115–1121`, the Richard-specific branch derives a value
from `@name`, assigns `ps.word_c>>7`, and then either takes its special acceptance
path or compares that replacement value with the saved PSWD word.

This replaces the **in-memory value used for checking the entered password**;
it is not an operation that directly rewrites the password in the persona file.
The observed rejection and unchanged stored word are consistent with this
branch. The audit did not insert instrumentation to measure the intermediate
address-derived value or claim a numerical derivation of its magic condition.

The source also contains a general magic-value password acceptance path.
This audit did not derive or test an override input for it or investigate
UNVEIL. Attachment was tested separately as described above. Passing the ordinary
wrong-password cases is not a proof that all historical override mechanisms
are inaccessible.

## Consequence for fresh-install provisioning

The standalone [provisioner](archwizard-provisioning.md) now initializes missing
records for all seven names using original creation/SAVE, with private compatible
credentials and preservation of existing records on rerun. It labels Richard as
an attachment credential and suppresses stale credentials when native values change.

The compatible random passwords can be used normally by the six
archwizard personas other than Richard, subject to the original engine's
authentication limitations.

**Do not print a generated Richard password as a verified working login.**
Keeping Richard's record nonzero can prevent straightforward first-claim
behavior, but it does not enable direct login or remove the historical override
paths. Richard's saved password works for the tested attachment route, but SAVE
or a qualifying QUIT can replace it with the attaching persona's password.
Provisioning guidance must account for this before describing Richard's password
as a stable, independent credential. A functional, conventional Richard login
still needs a separate decision about handling its exception. This audit applies
no authentication or persistence fix.

## Evidence and reproduction

Completed local evidence:

- Historical: `runtime/archwizard-auth-native-control/report-before-resume-1789830695255885000.json`
- 24/7: `runtime/archwizard-auth-native-247/completed-report.json`
- Same-password control: `runtime/archwizard-auth-native-247/same-password-report.json`
- Attachment and persistence: `runtime/archwizard-auth-native-247/attachment-report.json`
  (six completed cases; the `sessions` field names the corresponding transcript).

Each directory also has console transcripts and session traces. A later
historical restart attempt failed before authentication, so its latest
`report.json` is not the completed historical report cited above. Earlier
reports are preserved before reruns.
Preliminary attachment reports are also preserved as `attachment-report-before-*.json`:
one stopped on the incorrect SCORE-level assumption, another on the incorrect
SAVE-protection assumption. The completed report records the corrected findings.

Install `requirements-dev.txt`, and use a fresh output directory:

```sh
.venv/bin/python -m unittest tests.test_archwizard_audit -v

# Rebuild the existing availability-only variant on a private copy, then audit it.
.venv/bin/python -m tools.audit_archwizards \
  --output runtime/new-archwizard-audit --background

# Historical executable control.
.venv/bin/python -m tools.audit_archwizards \
  --output runtime/new-archwizard-control --historical --background

.venv/bin/python -m tools.audit_archwizards \
  --summary runtime/new-archwizard-audit/completed-report.json

# Optional follow-up; only on an already stopped, completed private audit image.
.venv/bin/python -m tools.audit_archwizards \
  --output runtime/new-archwizard-audit --richard-control

# Roy → Richard attachment, wrong/correct/matching passwords and SAVE/QUIT effects.
# Only on a stopped, completed private audit image; restores its AUTH0 fixtures.
.venv/bin/python -m tools.audit_archwizards \
  --output runtime/new-archwizard-audit --richard-attach
```

These native integration tools currently require Python 3.9–3.12. The private
image must contain the original compiler and the baseline directory layout.
Passwords and persona files generated by the audit remain under ignored
`runtime/`; do not reuse them as real credentials or publish the disk images.
