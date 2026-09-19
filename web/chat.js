'use strict';

// xterm remains the stream parser (including CR, rubout, and VT erase commands).
// Chat projects the selected style's buffer into document rows, not a viewport.
class ChatView {
    static FOLLOW_DISTANCE = 24;
    static PROMPT_WINDOW = 512;
    static MAX_COMMAND_LENGTH = 8191; // Gateway's 8192-character frame limit, less CR.

    constructor(terminal, send, settings) {
        this.terminal = terminal;
        this.send = send;
        this.panel = document.getElementById('chat-panel');
        this.frame = this.panel.closest('main');
        this.output = document.getElementById('chat-output');
        this.form = document.getElementById('chat-form');
        this.input = document.getElementById('chat-command');
        this.input.maxLength = ChatView.MAX_COMMAND_LENGTH;
        this.active = false;
        this.recent = '';
        this.baseY = 0;
        terminal.onWriteParsed(() => { if (this.active) this.render(); });
        window.addEventListener('scroll', () => this.layoutInput(), { passive: true });
        window.addEventListener('resize', () => this.layoutInput());
        this.form.addEventListener('submit', event => {
            event.preventDefault();
            if (!this.active || this.input.disabled) return;
            const line = this.input.value;
            this.input.value = '';
            this.recent = '';
            // No local echo or command history: only the engine echoes commands.
            this.send(line + '\r');
        });
        this.input.addEventListener('keydown', event => {
            if (event.key === 'Enter' && (event.repeat || event.isComposing)) event.preventDefault();
            if (event.key === 'Tab' && !event.ctrlKey && !event.altKey && !event.metaKey) {
                event.preventDefault();
                settings();
            }
            if (event.key.toLowerCase() === 'c' && event.ctrlKey && !this.input.value) {
                event.preventDefault();
                this.send('\x03');
            }
        });
    }

    activate(active) {
        this.active = active;
        this.panel.hidden = !active;
        document.getElementById('terminal').hidden = active;
        document.documentElement.classList.toggle('chat-mode', active);
        if (active) this.render(true);
    }

    configure(preset) {
        this.panel.style.fontFamily = preset.fontFamily;
        this.panel.style.fontSize = `${preset.fontSize}px`;
        this.panel.style.color = preset.theme.foreground;
        this.panel.style.setProperty('--chat-columns', this.terminal.cols);
        this.panel.style.setProperty('--chat-background', preset.theme.background);
        this.panel.style.setProperty('--chat-caret', preset.theme.cursor);
        this.layoutInput();
    }

    atBottom() {
        return document.documentElement.scrollHeight - innerHeight - scrollY <= ChatView.FOLLOW_DISTANCE;
    }

    layoutInput() {
        if (!this.active || !this.output.lastElementChild) return;
        const row = this.output.lastElementChild;
        const lineHeight = row.getBoundingClientRect().height;
        // Reserve one input row inside the display frame in both layouts. This
        // keeps scrolling stable when the input moves between inline and docked.
        this.frame.style.setProperty('--chat-line-height', `${lineHeight}px`);
        const cursor = this.terminal.buffer.active.cursorX;
        const nextRow = cursor >= this.terminal.cols - 1;
        const column = nextRow ? 0 : cursor;
        this.form.style.setProperty('--input-left', `${column}ch`);
        this.form.style.setProperty('--input-top', `${row.offsetTop + (nextRow ? lineHeight : 0)}px`);
        this.panel.style.paddingBottom = nextRow ? `${lineHeight}px` : '0px';
        const fillsScreen = this.panel.getBoundingClientRect().bottom + scrollY >= innerHeight;
        const frame = this.frame.getBoundingClientRect();
        this.form.style.setProperty('--dock-left', `${frame.left}px`);
        this.form.style.setProperty('--dock-width', `${frame.width}px`);
        this.form.style.setProperty('--dock-bottom', `${Math.max(0, innerHeight - frame.bottom)}px`);
        // The same input stays in the DOM: layout changes cannot lose its draft,
        // selection, password type or focus, and must not scroll the reader down.
        this.form.classList.toggle('docked', fillsScreen && this.atBottom());
    }

    connection(ready) {
        this.input.disabled = !ready;
        if (!ready) {
            this.input.value = '';
            this.input.type = 'text';
            this.recent = '';
        }
    }

    focus() { this.input.focus(); }

    insertTab() {
        // Unlike a terminal, the draft has not yet been sent to the game.
        const start = this.input.selectionStart;
        const end = this.input.selectionEnd;
        this.input.value = this.input.value.slice(0, start) + '\t' + this.input.value.slice(end);
        this.input.setSelectionRange(start + 1, start + 1);
    }

    observe(data) {
        this.recent = (this.recent + data).slice(-ChatView.PROMPT_WINDOW);
        const passwordPrompt = /(?:what's the password\?|(?:Give me a password for this persona|No password on this persona - give me one) of up to \d+ letters, please\.|What is your present password\?|New password for persona - up to \d+ letters please\.|Enter it again to make sure it's correct, please\.)/;
        if (passwordPrompt.test(this.recent)) {
            this.input.type = 'password';
            this.recent = '';
        } else if (/Hello(?: again)?,|Your password will be updated|password remains unchanged|Sorry, incorrect\.|\r\nNo!/.test(this.recent)) {
            this.input.type = 'text';
            this.recent = '';
        }
    }

    render(full = false) {
        const follow = this.atBottom();
        const buffer = this.terminal.buffer.active;
        const count = buffer.baseY + buffer.cursorY + 1;
        // Settled scrollback does not change until the bounded xterm buffer trims.
        // In that case compare all rows; otherwise inspect only the previous screen.
        const atCapacity = buffer.baseY >= this.terminal.options.scrollback;
        const start = full || atCapacity ? 0 : Math.min(this.baseY, buffer.baseY, this.output.children.length);
        while (this.output.children.length > count) this.output.lastElementChild.remove();
        for (let i = start; i < count; i++) {
            const text = buffer.getLine(i).translateToString(true);
            let row = this.output.children[i];
            if (!row) {
                row = document.createElement('div');
                this.output.appendChild(row);
            }
            if (row.textContent !== text) row.textContent = text;
        }
        this.baseY = buffer.baseY;
        this.layoutInput();
        if (follow || full) window.scrollTo(0, document.documentElement.scrollHeight);
        this.layoutInput();
    }
}
