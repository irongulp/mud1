'use strict';

// Queue local edits, not network characters. Positions refer to the projected
// draft, so fast typing/backspace and typeahead after Enter stay in order even
// while the visible field is still catching up. No undo/command history is kept.
class PacedChatInput {
    constructor(input, submit, baud) {
        this.input = input;
        this.sendLine = submit;
        // Each internal token represents one typed character or deletion. The
        // tokens never go to the game; SerialPacer supplies its 10-bit clock.
        this.clock = new SerialPacer(tokens => this.deliver(tokens.length), baud);
        this.reset();
        input.addEventListener('beforeinput', event => {
            if (!event.cancelable || event.isComposing) return;
            event.preventDefault();
            if (input.disabled) return;
            this.syncSelection();
            if (event.inputType.startsWith('insert')) {
                this.insert(event.data ?? event.dataTransfer?.getData('text/plain') ?? '');
            } else if (event.inputType.startsWith('delete')) {
                this.erase(event.inputType);
            }
        });
        input.addEventListener('paste', event => {
            if (!event.clipboardData || input.disabled) return;
            event.preventDefault();
            this.syncSelection();
            this.insert(event.clipboardData.getData('text/plain'));
        });
        input.addEventListener('input', event => {
            // Autofill and committed edits that bypass cancelable beforeinput.
            if (event.isComposing || input.value === this.visible) return;
            const value = input.value;
            this.paint(this.visible, this.paintedStart, this.paintedEnd);
            this.choose(0, this.draft.length);
            if (value) this.insert(value);
            else this.erase('deleteContentBackward');
        });
        input.addEventListener('keydown', event => this.navigate(event));
        input.addEventListener('pointerup', () => this.syncSelection());
    }

    reset() {
        this.clock.reset();
        this.operations = [];
        this.draft = '';
        this.anchor = this.head = 0;
        this.paint('', 0, 0);
    }

    setBaud(baud) { this.clock.setBaud(baud); }

    paint(value, start, end = start, direction = 'forward') {
        this.visible = value;
        this.input.value = value;
        this.input.setSelectionRange(start, end, direction);
        this.paintedStart = this.input.selectionStart;
        this.paintedEnd = this.input.selectionEnd;
        this.paintedDirection = this.input.selectionDirection;
    }

    syncSelection() {
        let start = this.input.selectionStart;
        let end = this.input.selectionEnd;
        const direction = this.input.selectionDirection;
        if (start === this.paintedStart && end === this.paintedEnd
            && (start === end || direction === this.paintedDirection)) return;
        // Consume this native selection once, even if queued typing delays its
        // projection. Otherwise each subsequent keystroke replaces it again.
        this.paintedStart = start;
        this.paintedEnd = end;
        this.paintedDirection = direction;
        // Map a mouse/native selection of visible text through pending edits.
        for (const op of this.operations) {
            if (op.kind === 'submit') start = end = 0;
            if (op.kind !== 'edit') continue;
            const map = position => position <= op.start ? position
                : position >= op.end ? position + op.text.length - (op.end - op.start)
                : op.start + op.text.length;
            start = map(start);
            end = map(end);
        }
        this.choose(...(direction === 'backward' ? [end, start] : [start, end]));
    }

    choose(anchor, head) {
        this.anchor = Math.max(0, Math.min(anchor, this.draft.length));
        this.head = Math.max(0, Math.min(head, this.draft.length));
        this.operations.push({kind: 'select', start: Math.min(this.anchor, this.head),
            end: Math.max(this.anchor, this.head), direction: this.head < this.anchor ? 'backward' : 'forward'});
        this.drainControls();
    }

    edit(start, end, text) {
        this.draft = this.draft.slice(0, start) + text + this.draft.slice(end);
        this.anchor = this.head = start + text.length;
        this.operations.push({kind: 'edit', start, end, text});
        this.clock.enqueue('\0');
    }

    insert(text) {
        // Match the native single-line input's newline and maxlength behaviour.
        text = text.replace(/[\r\n]/g, '');
        const selected = Math.abs(this.anchor - this.head);
        text = text.slice(0, Math.max(0, this.input.maxLength - this.draft.length + selected));
        for (const character of text) {
            this.edit(Math.min(this.anchor, this.head), Math.max(this.anchor, this.head), character);
        }
    }

    erase(type) {
        let start = Math.min(this.anchor, this.head);
        let end = Math.max(this.anchor, this.head);
        if (start === end) {
            if (type === 'deleteWordBackward') start -= this.draft.slice(0, start).match(/\S+\s*$|\s+$/)?.[0].length || 0;
            else if (type === 'deleteWordForward') end += this.draft.slice(end).match(/^\s*\S+|^\s+/)?.[0].length || 0;
            else if (type === 'deleteSoftLineBackward') start = 0;
            else if (type === 'deleteSoftLineForward') end = this.draft.length;
            else if (type === 'deleteContentBackward') start = Math.max(0, start - 1);
            else if (type === 'deleteContentForward') end = Math.min(this.draft.length, end + 1);
        }
        if (start !== end) this.edit(start, end, '');
    }

    navigate(event) {
        if (event.isComposing || this.input.disabled) return;
        const all = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a';
        if (!all && !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        this.syncSelection();
        if (all) { this.choose(0, this.draft.length); return; }
        const left = event.key === 'ArrowLeft' || event.key === 'Home';
        let position = this.head;
        if (event.key === 'Home' || event.key === 'End' || event.metaKey) position = left ? 0 : this.draft.length;
        else if (!event.shiftKey && this.anchor !== this.head) position = left ? Math.min(this.anchor, this.head) : Math.max(this.anchor, this.head);
        else if (event.ctrlKey || event.altKey) {
            position += left ? -(this.draft.slice(0, position).match(/\S+\s*$|\s+$/)?.[0].length || 0)
                : (this.draft.slice(position).match(/^\s*\S+|^\s+/)?.[0].length || 0);
        } else position += left ? -1 : 1;
        this.choose(event.shiftKey ? this.anchor : position, position);
    }

    submit() {
        this.operations.push({kind: 'submit'});
        this.draft = '';
        this.anchor = this.head = 0;
        this.drainControls();
    }

    drainControls() {
        while (this.operations.length && this.operations[0].kind !== 'edit') {
            const op = this.operations.shift();
            if (op.kind === 'select') this.paint(this.visible, op.start, op.end, op.direction);
            else {
                const line = this.visible;
                this.paint('', 0, 0);
                this.sendLine(line);
            }
        }
    }

    deliver(count) {
        for (let i = 0; i < count; i++) {
            const op = this.operations.shift();
            this.paint(this.visible.slice(0, op.start) + op.text + this.visible.slice(op.end), op.start + op.text.length);
            this.drainControls();
        }
    }
}
