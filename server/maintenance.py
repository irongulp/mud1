"""Shared maintenance notice for the gateway and independent Nginx response."""
from pathlib import Path

MAINTENANCE_FILE = Path('/etc/mud86/maintenance')
MESSAGE = 'The game is unavailable due to scheduled maintenance. Please try again later.'
RETRY_SECONDS = 15 * 60
CLOSE_CODE = 4015
PAGE = (
    '<!doctype html><html lang="en"><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1">'
    '<title>MUD86 — Maintenance</title>'
    '<style>body{background:#000;color:#6f6;font:18px monospace;'
    'max-width:45em;margin:15vh auto;padding:1.5em}h1{font-size:1.4em}</style>'
    '<main><h1>MUD86</h1><p>' + MESSAGE + '</p>'
    '<p>Retrying in 15 minutes…</p></main>'
    '<script>setTimeout(() => location.reload(), ' + str(RETRY_SECONDS * 1000) + ');</script></html>'
)
