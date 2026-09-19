'use strict';

// Approximate asynchronous serial framing: eight data bits, start and stop bits.
const SERIAL_BITS_PER_CHARACTER = 10;
const SERIAL_TICK_MS = 20;

class SerialPacer {
    constructor(deliver, baud) {
        this.deliver = deliver;
        this.baud = baud;
        this.reset();
    }

    reset() {
        clearTimeout(this.timer);
        this.timer = null;
        this.pending = '';
        this.credit = 0;
        this.last = performance.now();
    }

    setBaud(baud) {
        this.flush();
        this.baud = baud;
    }

    enqueue(data) {
        if (!data) return;
        if (!this.pending) {
            this.last = performance.now();
            this.credit = 0;
        }
        this.pending += data;
        this.schedule();
    }

    schedule() {
        if (this.timer === null && this.pending) {
            this.timer = setTimeout(() => {
                this.timer = null;
                this.flush();
                this.schedule();
            }, SERIAL_TICK_MS);
        }
    }

    flush() {
        const now = performance.now();
        // Accumulate bit-milliseconds to avoid rounding individual characters.
        this.credit += (now - this.last) * this.baud;
        this.last = now;
        const count = Math.min(this.pending.length,
            Math.floor(this.credit / (1000 * SERIAL_BITS_PER_CHARACTER)));
        if (count) {
            const data = this.pending.slice(0, count);
            this.pending = this.pending.slice(count);
            this.credit -= count * 1000 * SERIAL_BITS_PER_CHARACTER;
            this.deliver(data);
        }
    }
}
