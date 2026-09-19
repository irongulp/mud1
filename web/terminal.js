'use strict';

const monochrome = { background: '#000000', foreground: '#dddddd', cursor: '#eeeeee' };
const styles = {
    original: { cols: 80, rows: 30, fontSize: 16, fontFamily: 'Menlo, Consolas, monospace',
        theme: { background: '#101611', foreground: '#c0e3bf', cursor: '#dfefd5' } },
    vt220: { cols: 80, rows: 24, fontSize: 20, fontFamily: 'GlassTTY, monospace', theme: monochrome },
    vt52: { cols: 80, rows: 24, fontSize: 15, fontFamily: 'VT52, monospace', theme: monochrome },
    mda: { cols: 80, rows: 25, fontSize: 14, fontFamily: 'IBMMDA, monospace',
        theme: { background: '#000000', foreground: '#80ff80', cursor: '#aaffaa' } },
    cga: { cols: 80, rows: 25, fontSize: 16, fontFamily: 'IBMCGA, monospace',
        theme: { background: '#000000', foreground: '#aaaaaa', cursor: '#ffffff' } },
    bbc40: { cols: 40, rows: 25, fontSize: 20, fontFamily: 'Bedstead, monospace', theme: monochrome },
    bbc0: { cols: 80, rows: 32, fontSize: 16, fontFamily: 'BBCBitmap, monospace', theme: monochrome }
};
const styleKey = 'mud86-terminal-style';
const chatKey = 'mud86-chat-mode';
let selectedStyle = 'original';
let chatEnabled = false;
try {
    chatEnabled = localStorage.getItem(chatKey) === 'true';
    let saved = localStorage.getItem(styleKey);
    if (saved === 'chat') {
        saved = 'original';
        chatEnabled = true;
        localStorage.setItem(chatKey, 'true');
        localStorage.setItem(styleKey, saved);
    }
    if (saved === 'bbc80') {
        saved = 'bbc0';
        localStorage.setItem(styleKey, saved);
    }
    if (Object.hasOwn(styles, saved)) selectedStyle = saved;
} catch (_) { /* Storage can be unavailable in private browser contexts. */ }
const terminal = new Terminal({
    ...styles[selectedStyle],
    cursorBlink: true,
    scrollback: 10000,
    screenReaderMode: true
});
const styleSelect = document.getElementById('terminal-style');
const chatToggle = document.getElementById('chat-mode');
styleSelect.value = selectedStyle;
chatToggle.checked = chatEnabled;
document.documentElement.dataset.style = selectedStyle;
styleSelect.disabled = true;
const terminalReady = Promise.all([
    document.fonts.load('20px "GlassTTY"').catch(() => []),
    document.fonts.load('20px "Bedstead"').catch(() => []),
    document.fonts.load('16px "BBCBitmap"').catch(() => []),
    document.fonts.load('15px "VT52"').catch(() => []),
    document.fonts.load('14px "IBMMDA"').catch(() => []),
    document.fonts.load('16px "IBMCGA"').catch(() => [])
]).then(() => {
    terminal.open(document.getElementById('terminal'));
    styleSelect.disabled = false;
    chatToggle.disabled = false;
    settingsButton.disabled = false;
    start();
});
let socket;
const controls = document.getElementById('controls');
const settingsButton = document.getElementById('settings-shortcut');
const confirmStyle = document.getElementById('confirm-style');
let proposedSettings;
let settingsControl;
let restartRequested = false;
const speed = document.getElementById('speed');
let wrapping = false;
const wrappedOutput = new WordWrappedOutput(data => terminal.write(data), styles.bbc40.cols);
const incoming = new SerialPacer(data => {
    if (wrapping) wrappedOutput.push(data);
    else terminal.write(data);
}, 9600);
const outgoing = new SerialPacer(data => {
    if (!restartRequested && socket && socket.readyState === WebSocket.OPEN) socket.send(data);
}, 9600);
const chat = new ChatView(terminal, data => {
    if (!restartRequested && socket && socket.readyState === WebSocket.OPEN) outgoing.enqueue(data);
}, toggleControls);

function focusInput() {
    if (chat.active) chat.focus();
    else terminal.focus();
}

function applyStyle(resize) {
    const preset = styles[selectedStyle];
    terminal.options.fontFamily = preset.fontFamily;
    terminal.options.fontSize = preset.fontSize;
    terminal.options.theme = preset.theme;
    document.documentElement.dataset.style = selectedStyle;
    if (resize) {
        terminal.resize(preset.cols, preset.rows);
    }
    chat.configure(preset);
    if (resize) {
        if (chat.active !== chatEnabled) chat.activate(chatEnabled);
        else if (chat.active) chat.render();
    }
}

function saveSettings(style, enabled) {
    selectedStyle = style;
    chatEnabled = enabled;
    try {
        localStorage.setItem(styleKey, selectedStyle);
        localStorage.setItem(chatKey, String(chatEnabled));
    } catch (_) { /* Optional persistence. */ }
}

function requestRestart() {
    if (socket && socket.readyState === WebSocket.OPEN) {
        // Binary frames carry browser controls; text frames remain game input.
        socket.send(new TextEncoder().encode('restart'));
    }
}

function changeSettings(event) {
    const preset = styles[styleSelect.value];
    const needsRestart = terminal.cols !== preset.cols
        || chat.active !== chatToggle.checked;
    if (needsRestart && socket && socket.readyState < WebSocket.CLOSING) {
        proposedSettings = { style: styleSelect.value, chat: chatToggle.checked };
        settingsControl = event.currentTarget;
        confirmStyle.returnValue = '';
        confirmStyle.showModal();
        return;
    }
    saveSettings(styleSelect.value, chatToggle.checked);
    // Font, colour and row count are local presentation changes. Width changes
    // also affect upstream wrapping; retain that geometry until the next start.
    applyStyle(!socket || !needsRestart);
}
styleSelect.addEventListener('change', changeSettings);
chatToggle.addEventListener('change', changeSettings);

confirmStyle.addEventListener('close', () => {
    if (confirmStyle.returnValue !== 'confirm') {
        styleSelect.value = selectedStyle;
        chatToggle.checked = chatEnabled;
        settingsControl.focus();
        return;
    }
    saveSettings(proposedSettings.style, proposedSettings.chat);
    outgoing.reset();
    chat.connection(false);
    restartRequested = true;
    styleSelect.disabled = true;
    chatToggle.disabled = true;
    controls.close();
    requestRestart();
});

function openControls() {
    terminal.options.cursorBlink = false;
    terminal.options.cursorInactiveStyle = 'none';
    if (!controls.open) controls.showModal();
    settingsButton.setAttribute('aria-expanded', 'true');
    speed.focus();
}

function toggleControls() {
    if (controls.open) controls.close();
    else openControls();
}

settingsButton.addEventListener('click', toggleControls);
document.getElementById('close-controls').addEventListener('click', () => controls.close());
controls.addEventListener('close', () => {
    settingsButton.setAttribute('aria-expanded', 'false');
    terminal.options.cursorBlink = true;
    terminal.options.cursorInactiveStyle = 'outline';
    focusInput();
});
controls.addEventListener('keydown', event => {
    if (event.key === 'Tab' && !event.ctrlKey && !event.altKey && !event.metaKey) {
        event.preventDefault();
        event.stopPropagation();
        toggleControls();
    }
});
speed.addEventListener('change', () => {
    const [receive, send] = speed.value.split('-').map(Number);
    incoming.setBaud(receive);
    outgoing.setBaud(send);
});
document.getElementById('send-tab').addEventListener('click', () => {
    if (!restartRequested && socket && socket.readyState === WebSocket.OPEN) {
        if (chat.active) chat.insertTab();
        else outgoing.enqueue('\t');
    }
    controls.close();
});
terminal.attachCustomKeyEventHandler(event => {
    if (event.key === 'Tab' && !event.ctrlKey && !event.altKey && !event.metaKey) {
        if (event.type === 'keydown') {
            event.preventDefault();
            toggleControls();
        }
        return false;
    }
    return true;
});

const RETRY_INITIAL_MS = 1000;
const RETRY_MAX_MS = 30000;
const OUTPUT_DRAIN_POLL_MS = 50;
let retryDelay = RETRY_INITIAL_MS;
let retryTimer;

function reconnect(delay) {
    // Finish the old session at its selected baud rate before changing geometry
    // or resetting the line formatter. Flush xterm's write queue as well.
    if (incoming.pending) {
        retryTimer = setTimeout(() => reconnect(delay), OUTPUT_DRAIN_POLL_MS);
        return;
    }
    wrappedOutput.reset();
    terminal.write(`\x18\r\n[Reconnecting in ${delay / 1000}s...]\r\n`, () => {
        retryTimer = setTimeout(start, delay);
    });
}

function start() {
    if (socket && socket.readyState < WebSocket.CLOSING) return;
    clearTimeout(retryTimer);
    const firstConnection = !socket;
    restartRequested = false;
    styleSelect.disabled = false;
    chatToggle.disabled = false;
    applyStyle(true);
    incoming.reset();
    outgoing.reset();
    chat.connection(false);
    wrapping = selectedStyle === 'bbc40';
    wrappedOutput.reset();
    if (firstConnection) terminal.write('Connecting...');
    let waitingForOutput = true;
    const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
    socket = new WebSocket(`${scheme}//${location.host}/terminal?style=${selectedStyle}`);
    socket.onopen = () => {
        if (restartRequested) requestRestart();
        chat.connection(!restartRequested);
        if (!controls.open) focusInput();
    };
    socket.onmessage = event => {
        if (chat.active) chat.observe(event.data);
        if (waitingForOutput) {
            // Queue the clear after the Connecting text, even on a fast response.
            if (firstConnection) terminal.write('\x1b[2J\x1b[H');
            waitingForOutput = false;
        }
        incoming.enqueue(event.data);
    };
    socket.onclose = event => {
        outgoing.reset();
        chat.connection(false);
        if (restartRequested) retryDelay = RETRY_INITIAL_MS;
        if (event.code === 1000 && !waitingForOutput) retryDelay = RETRY_INITIAL_MS;
        const delay = retryDelay;
        if (event.code !== 1000 || waitingForOutput) {
            retryDelay = Math.min(retryDelay * 2, RETRY_MAX_MS);
        }
        reconnect(delay);
    };
    // WebSocket errors are followed by close, which owns the retry schedule.
    socket.onerror = () => {};
}

terminal.onData(data => {
    // TOPS-10 uses DEL/RUBOUT for erase, including at the persona prompts.
    if (!restartRequested && socket && socket.readyState === WebSocket.OPEN) outgoing.enqueue(data.replace(/\x08/g, '\x7f'));
});
