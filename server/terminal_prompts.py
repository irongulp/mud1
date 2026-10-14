"""Shared syntax for the witnessed TOPS-10 prompt redraw, not ANSI stripping."""
import re

_REDRAW_START = '\x12^R\x12\x7f\r'
_REDRAW_CSI = r'\x1b\[[0-9;]*[CK]'

# Only a complete redraw may grant input credit.
NATIVE_PROMPT_REDRAW = re.escape(_REDRAW_START) + '(?:' + _REDRAW_CSI + ')*'

# Password classification can latch earlier, before a long or fragmented redraw
# displaces the known question from the recognition window. These are exactly
# the complete redraw's prefixes; they do not independently grant input credit.
_START_PREFIXES = '|'.join(
    re.escape(_REDRAW_START[:end]) for end in range(1, len(_REDRAW_START)))
NATIVE_PROMPT_REDRAW_PREFIX = (
    '(?:' + _START_PREFIXES + '|' + NATIVE_PROMPT_REDRAW
    + r'(?:\x1b(?:\[[0-9;]*)?)?)')
