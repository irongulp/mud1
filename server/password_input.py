"""Silent line editing for the original game's login password prompts.

MUD's NOECHO uses TOPS-10 local-copy mode. The monitor's TTVID rubout
path clears that mode and prints deleted characters. Buffering this one
input line avoids that path; the original game still checks the password.
"""
import re


class PasswordInput:
    MAX_LINE_LENGTH = 8192
    PROMPT_WINDOW = 256
    PROMPT = re.compile(
        r"(?:This persona already exists - what's the password\?|"
        r"(?:Give me a password for this persona|No password on this persona - give me one)"
        r" of up to \d+ letters, please\.)[\r\n]+\*$"
    )

    def __init__(self):
        self.active = False
        self.line = ''
        self.recent = ''

    def observe(self, data):
        self.recent = (self.recent + data)[-self.PROMPT_WINDOW:]
        if not self.active and self.PROMPT.search(self.recent):
            self.active = True
            self.line = ''
            self.recent = ''

    def feed(self, data):
        output = []
        for char in data:
            if not self.active:
                output.append(char)
            elif char in '\r\n':
                output.append(self.line + char)
                self.clear()
            elif char == '\x03':
                self.clear()
                output.append(char)
            elif char in '\x08\x7f':
                self.line = self.line[:-1]
            elif char == '\x15':  # Ctrl-U: discard the line.
                self.line = ''
            elif char == '\x17':  # Ctrl-W: discard the preceding word.
                self.line = self.line.rstrip()
                while self.line and not self.line[-1].isspace():
                    self.line = self.line[:-1]
            elif char == '\x12':  # Ctrl-R: a hidden line has nothing to redisplay.
                continue
            else:
                if len(self.line) >= self.MAX_LINE_LENGTH:
                    self.clear()
                    raise ValueError('Password input line too long')
                self.line += char
        return ''.join(output)

    def clear(self):
        self.active = False
        self.line = ''
        self.recent = ''
