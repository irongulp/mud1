# First-install archwizard provisioning

`tools/provision_archwizards.py` reserves **Richard, Roy, Brian, Ronan, Friday,
Yawn and Debugger** using the original game's persona creation and SAVE commands.
It is the standalone first-install step called by the
[AlmaLinux installer](deployment.md) after booting the restored guest and before
opening browser access.

## Run

Use Python 3.9–3.12 and an initialized restoration runtime with the original
BCPL compiler and password-free RICHARD operating-system account. The command
connects to the explicitly selected **loopback Telnet port**. Provisioning needs
exclusive maintenance access: run it before starting the browser gateway or
accepting players. The port has no implicit default.

```sh
# Set this to the Telnet port of the installation being prepared.
# The parent of the state directory must already exist.
.venv/bin/python -m tools.provision_archwizards \
  --port "$MUD_PRIVATE_TELNET_PORT" \
  --state-dir runtime/private \
  --show-credentials
```

The command compiles a separate, read-only `AUDPWD` inspector in the guest's
RICHARD directory. It does not relink MUD or change the original authentication
code. Source transfers are paced because terminal echo can run ahead of COPY's
input consumption and overflow TOPS-10 typeahead.

For every missing persona, it generates six random bytes, Base64-encodes them,
and rejects candidates outside `[a-z0-9]{8}`. The seven initial generated strings
are distinct. This respects the original alphabet, case folding and nine-character
limit. The game still uses its original legacy 36-bit password representation;
the generator is not a replacement authentication system.

Each generated credential is durably journalled **before** creating the persona.
Creation is followed by explicit SAVE and QUIT, then native inspection to confirm
a nonzero saved password. The tool completes only after all seven personas have
nonzero saved passwords.

## Credential handling

- The state directory is owner-only (`0700`), and
  `archwizard-credentials.json` is owner-only (`0600`). The command rejects
  non-private, foreign-owned or symlinked credential storage.
- Updates use an atomic replacement, with file and directory fsync. A journal
  lock prevents concurrent provisioners from using the same state directory.
- The journal contains `initial_password` and `initial_password_word`. Both are
  secret material. The latter is the original engine's stored comparison value.
- Normal output contains statuses, not passwords or password words. No TTY
  transcript is written. `--show-credentials` explicitly prints known matching
  credentials and a reminder to copy them into a password manager. Do not send
  that output to installation logs.
- The default directory is ignored `runtime/private/`; the credential filename,
  atomic-write temporary names and lock filename are also ignored globally by
  this repository. Keep the journal in private operational backups, separate
  from a stopped-disk backup. Do not publish journals or provisioned disk images.
- Build distributable starter images **before** per-install provisioning. Each
  installation should run this step with its own private state directory.

## Reruns and recovery

Use the **same state directory** on a rerun or reinstall that retains the game
disk. The native persona records are authoritative:

| State | Action |
|---|---|
| Persona absent, no journal entry | Generate, journal, create and SAVE |
| Persona absent, journal entry retained | Reuse that initial credential, create and SAVE |
| Existing nonzero password matches its journalled native value | Preserve; credential may be displayed on request |
| Existing nonzero password differs from the journalled value | Preserve; report `changed` and suppress the stale initial password |
| Existing nonzero password, no journal entry | Preserve; report `existing`, with password managed separately |
| Existing password is zero | Stop before creating any missing personas; manual protection is required |
| Journal entry pending, but the persona now exists | Stop for reconciliation of an interrupted SAVE; do not assume the candidate is verified |

An interruption before SAVE leaves the candidate password available for retry.
There is no atomic transaction spanning the host journal and the TOPS-10 persona
file: an interruption after native SAVE but before its verification checkpoint
can leave an ambiguous pending entry. Retain the journal and reconcile that
persona's credential before retrying. Do not delete the journal to force a fresh
password assignment. A malformed journal is likewise retained and rejected.

Existing passwords are never automatically reset. This includes a Richard
password replaced by the engine during attachment persistence.

## Richard is an attachment credential

The original engine rejects Richard's ordinary saved password at the normal
existing-persona login prompt. His generated credential is labelled an
**attachment password**, not a direct-login password:

1. Log into an existing saved archwizard such as Roy.
2. Enter `ATTACH Richard`.
3. Supply Richard's saved password when it differs from the session password.

If the two stored password values match, attachment omits the question. The
question has no trailing `*` prompt.

**Attached SAVE, or a QUIT that meets the game's persistence conditions, can
replace Richard's password with the originating persona's password.** This is
verified original-engine behavior. It is why the journal records *initial*
credentials and why reruns detect drift rather than restore an old password.
See [the password audit](archwizard-password-audit.md) for the evidence and
the attachment-flag overwrite that causes this behavior.

## Validation

```sh
.venv/bin/python -m unittest tests.test_provision_archwizards -v
.venv/bin/python -m tests.integration_provisioning
```

The native test clones the stopped first-playable historical baseline, boots a
separate emulator on a private port, and invokes the real provisioning CLI twice.
It checks all seven saved personas, distinct native password values, private
credential storage, unchanged credentials on rerun and absence of secrets in
default output. It verifies direct login for the other six names, Richard's
direct rejection, and successful password-protected attachment through MUDGUEST.
It then reproduces attached SAVE's password change and confirms the provisioner
preserves it and suppresses Richard's stale initial credential.

The test stops its emulator and retains disposable evidence under ignored
`runtime/provisioning-check-*`. Its deliberately altered fixture is test material,
not a release image. Earlier failed runs identified a source-transfer typeahead
overflow; the completed run uses paced transfers. Production installation and
deployment orchestration remain separate from this provisioning step.
