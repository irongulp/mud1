# Native terminal admission/reuse

The full deployment failure42291522591 was initial guest monitor timeout during
the HTTPS smoke test. TLS/static pages worked. STOMPR had logged a TTY0 quieting
failure; this is correlation, not proof of cause.

Focused fixture `tests.integration_terminal_reuse` uses the production gateway
against one freshly extracted pinned runtime, with eight name-prompt-only
admissions at offsets0/10/20/45/65/85/105/125 seconds. It waits for handler cleanup
between connections and stops on first failure. No persona names/passwords/game
commands are sent. Bounded raw pre-admission/cleanup trace, gateway stages, native
SYSTAT and SYS:TTY.INI are retained. No terminal configuration or monitor patch
is applied. This trace must never be repurposed for credential-bearing sessions.

Native-x86 run42294879412/cf4c230 passed all eight admissions/cleanup and native
KSYS. STOMPR remained enabled; no failure was reproduced. The trace showed the
first wake-up CR at40.523s, before SIMH's line0 banner at40.815s. It survived that
ordering in this run, but the gateway had no explicit line-readiness gate.

The existing native maintenance client waits for the line banner and a250ms
carrier interval before CR. A deterministic gateway regression that discards
pre-banner typeahead failed with the old code and passes with the same ordering
applied to gateway admission. `wake_monitor()` requires the complete assigned
line, uses the250ms interval and submits one CR; missing/malformed banners and
timeouts never trigger repeated input. The existing15s admission deadline covers
the whole sequence. Gateway fixtures now model the real SIMH banner.

76 gateway/carrier/reuse/transport tests passed including real Chromium heartbeat
coverage. This is a tested input-ordering correction, not proof that STOMPR or
this race caused every historical admission failure. Native follow-up remains
required before any release-success claim.
