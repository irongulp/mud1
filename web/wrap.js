'use strict';

const TERMINAL_TAB_COLUMNS = 8;

// Reflow one logical TOPS-10 line at a time. Keep its cursor in source-column
// coordinates, so rubout/erase still work after a word has moved to a new row.
// No word is buffered waiting for a delimiter: even an unfinished prompt shows.
class WordWrappedOutput {
    constructor(write, columns) {
        this.write = write;
        this.columns = columns;
        this.reset();
    }

    reset() {
        this.line = '';
        this.cursor = 0;
        this.drawRow = 0;
        this.escape = '';
        this.carriageReturn = false;
    }

    layout() {
        const rows = [];
        let start = 0;
        while (this.line.length - start > this.columns) {
            const limit = start + this.columns;
            const space = this.line.lastIndexOf(' ', limit);
            const boundary = space > start;
            const end = boundary ? space : limit;
            rows.push({ start, text: this.line.slice(start, end) });
            start = end + (boundary ? 1 : 0);
        }
        rows.push({ start, text: this.line.slice(start) });
        return rows;
    }

    render() {
        const rows = this.layout();
        let row = 0;
        for (let i = 1; i < rows.length; i++) {
            if (rows[i].start <= this.cursor) row = i;
        }
        const column = Math.min(this.columns - 1, Math.max(0, this.cursor - rows[row].start));
        let output = this.drawRow ? `\x1b[${this.drawRow}A` : '';
        output += '\r\x1b[J' + rows.map(item => item.text).join('\r\n');
        const up = rows.length - 1 - row;
        if (up) output += `\x1b[${up}A`;
        output += `\x1b[${column + 1}G`;
        this.drawRow = row;
        return output;
    }

    control(sequence) {
        const match = /^\x1b\[(\d*)([KCDG])$/.exec(sequence);
        if (!match) return false;
        const value = Number(match[1]);
        switch (match[2]) {
        case 'K':
            if (value === 0) this.line = this.line.slice(0, this.cursor);
            else if (value === 1) this.line = ' '.repeat(this.cursor + 1) + this.line.slice(this.cursor + 1);
            else if (value === 2) this.line = '';
            break;
        case 'C': this.cursor += value || 1; break;
        case 'D': this.cursor = Math.max(0, this.cursor - (value || 1)); break;
        case 'G': this.cursor = Math.max(0, (value || 1) - 1); break;
        }
        return true;
    }

    push(data) {
        let output = '';
        let dirty = false;
        for (const ch of data) {
            if (this.escape) {
                this.escape += ch;
                if (this.escape === '\x1b[') continue;
                if (this.escape.startsWith('\x1b[') && !/[@-~]/.test(ch)) continue;
                if (this.control(this.escape)) dirty = true;
                else {
                    // Forward other VT controls intact; begin a new tracked line
                    // after screen/cursor operations outside line editing.
                    output += this.render() + this.escape;
                    this.reset();
                    dirty = false;
                }
                this.escape = '';
                continue;
            }
            if (ch === '\n') {
                // Padding on a completed source line must not occupy an extra
                // wrapped row. Keep it while editing so cursor positions agree.
                this.line = this.line.trimEnd();
                this.cursor = this.line.length;
                output += this.render() + '\r\n';
                this.reset();
                dirty = false;
                continue;
            }
            if (this.carriageReturn) {
                this.cursor = 0;
                this.carriageReturn = false;
            }
            if (ch === '\r') { this.carriageReturn = true; continue; }
            if (ch === '\x1b') { this.escape = ch; continue; }
            if (ch === '\b') this.cursor = Math.max(0, this.cursor - 1);
            else if (ch === '\t') {
                this.overwrite(' '.repeat(TERMINAL_TAB_COLUMNS - this.cursor % TERMINAL_TAB_COLUMNS));
            } else if (ch >= ' ' && ch !== '\x7f') {
                this.overwrite(ch);
            } else { output += ch; continue; }
            dirty = true;
        }
        if (dirty) output += this.render();
        if (output) this.write(output);
    }

    overwrite(text) {
        this.line = this.line.padEnd(this.cursor, ' ').slice(0, this.cursor)
            + text + this.line.slice(this.cursor + text.length);
        this.cursor += text.length;
    }
}
