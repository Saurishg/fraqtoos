#!/usr/bin/env node
/**
 * FraqtoOS WhatsApp Service
 * Persistent session via whatsapp-web.js (multi-device).
 * Exposes POST /send  { phone, message }
 * GET  /status  → ready | initializing | qr_pending | disconnected
 * GET  /qr      → text QR for terminal scan
 */

const { Client, LocalAuth, MessageMedia } = require("whatsapp-web.js");
const qrcode   = require("qrcode-terminal");
const express  = require("express");
const fs       = require("fs");
const path     = require("path");
const { execSync, execFile } = require("child_process");

const QR_TXT  = "/tmp/wa_qr.txt";
const QR_PNG  = "/tmp/wa_qr.png";

const PORT     = 3131;
const SESSION  = "/home/work/fraqtoos/shared/wa-service/session";
const COMMANDS_FILE = path.join(__dirname, "commands.json");

// Inbound command registry: { owners:[num...], commands:{ keyword:{cmd,cwd,timeout_ms} } }
// Reloaded on each message so edits take effect without a restart.
function loadCommands() {
    try { return JSON.parse(fs.readFileSync(COMMANDS_FILE, "utf8")); }
    catch (e) { return { owners: [], commands: {} }; }
}
const stripId = (s) => (s || "").replace(/@c\.us$/, "").replace(/^\+/, "");

// ── State ──────────────────────────────────────────────────────────────────
let state   = "initializing";   // initializing | qr_pending | ready | disconnected
let lastQr  = null;
let msgQueue = [];               // { phone, message, res } buffered while not ready

// ── WhatsApp Client ────────────────────────────────────────────────────────
const client = new Client({
    authStrategy: new LocalAuth({ dataPath: SESSION }),
    puppeteer: {
        headless: true,
        args: [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ],
    },
});

client.on("qr", (qr) => {
    state  = "qr_pending";
    lastQr = qr;
    console.log("[wa-service] Scan QR to log in:");
    qrcode.generate(qr, { small: true });
    // Save QR as PNG so user can open and scan at their own pace
    try {
        fs.writeFileSync(QR_TXT, qr);
        execSync(`qrencode -o ${QR_PNG} -s 10 < ${QR_TXT}`);
        console.log(`[wa-service] QR saved to ${QR_PNG} — open it and scan`);
    } catch(e) { console.error("[wa-service] qrencode error:", e.message); }
});

client.on("ready", () => {
    state  = "ready";
    lastQr = null;
    console.log("[wa-service] WhatsApp ready ✓");
    // Drain any queued messages
    for (const item of msgQueue) {
        doSend(item.phone, item.message, item.res);
    }
    msgQueue = [];
});

client.on("auth_failure", (msg) => {
    state = "disconnected";
    console.error("[wa-service] Auth failure:", msg);
    // Re-init so a QR is offered again instead of staying disconnected forever
    setTimeout(() => { state = "initializing"; safeInitialize(); }, 30_000);
});

client.on("disconnected", (reason) => {
    state = "disconnected";
    console.error("[wa-service] Disconnected:", reason);
    // Auto-reconnect after 10 s
    setTimeout(() => {
        console.log("[wa-service] Reconnecting…");
        state = "initializing";
        safeInitialize();
    }, 10_000);
});

// ── Inbound command router ──────────────────────────────────────────────────
// Reply only when an authorised owner sends a known keyword (e.g. "arb"). All
// other inbound text is ignored — the service never messages unprompted. The
// keyword only *selects* a fixed command from commands.json; the message body is
// never interpolated into the shell, so there's no injection surface.
client.on("message_create", (msg) => {
    try {
        const body = (msg.body || "").trim().toLowerCase();
        if (!body) return;
        const cfg = loadCommands();
        const cmd = cfg.commands && cfg.commands[body];
        if (!cmd) return;                                   // unknown text → ignore
        const me       = stripId(client.info && client.info.wid && client.info.wid._serialized);
        const sender   = stripId(msg.from);
        const owners   = cfg.owners || [];
        const selfChat = msg.fromMe && stripId(msg.to) === me;   // user typed in their own self-chat
        if (!(owners.includes(sender) || selfChat)) {
            console.log(`[wa-service] cmd '${body}' from ${sender} ignored (not an owner)`);
            return;
        }
        console.log(`[wa-service] cmd '${body}' from ${sender} → ${cmd.cmd}`);
        execFile("/bin/bash", ["-lc", cmd.cmd],
            { cwd: cmd.cwd || undefined, timeout: cmd.timeout_ms || 60000, maxBuffer: 2 * 1024 * 1024 },
            async (err, stdout, stderr) => {
                let out = (stdout || "").trim();
                if (!out) out = err ? `⚠️ command failed: ${(stderr || err.message || "").trim().slice(0, 300)}`
                                    : "(no output)";
                if (out.length > 3500) out = out.slice(0, 3500) + "\n… (truncated)";
                try { await client.sendMessage(msg.from, out); }
                catch (e) { console.error("[wa-service] reply error:", e.message); }
            });
    } catch (e) {
        console.error("[wa-service] inbound handler error:", e.message);
    }
});

// initialize() can reject (e.g. puppeteer "auth timeout"); unhandled, that
// kills the whole process and drops every queued send with it. Catch and
// retry with backoff instead.
//
// It can also HANG silently — neither resolve nor reject, no qr/ready event
// (seen 2026-07-02: stuck "initializing" for 10h, every bot send 503'd). No
// in-process recovery is reliable once puppeteer wedges, so if we aren't
// ready/qr_pending within INIT_HANG_MS, exit and let systemd start a fresh
// process with a clean chrome.
const INIT_HANG_MS = 4 * 60_000;
let initHangTimer = null;
function armInitHangWatchdog() {
    clearTimeout(initHangTimer);
    initHangTimer = setTimeout(() => {
        if (state === "ready" || state === "qr_pending") return;
        console.error(`[wa-service] initialize hung >${INIT_HANG_MS / 60000}min (state: ${state}) — exiting for clean restart`);
        process.exit(1);
    }, INIT_HANG_MS);
}
client.on("ready", () => clearTimeout(initHangTimer));
client.on("qr", () => clearTimeout(initHangTimer));  // waiting on a human scan — don't recycle

let initAttempt = 0;
function safeInitialize() {
    armInitHangWatchdog();
    client.initialize().then(() => { initAttempt = 0; }).catch((err) => {
        initAttempt++;
        const delay = Math.min(15_000 * initAttempt, 120_000);
        console.error(`[wa-service] initialize failed (${(err && err.message) || err}); retry in ${delay / 1000}s`);
        state = "disconnected";
        setTimeout(() => { state = "initializing"; safeInitialize(); }, delay);
    });
}

// Safety net: any other stray rejection gets logged, not a process crash.
process.on("unhandledRejection", (reason) => {
    console.error("[wa-service] Unhandled rejection:", (reason && reason.message) || reason);
});

safeInitialize();

// ── Delivery confirmation ───────────────────────────────────────────────────
// client.sendMessage() resolves when the message is queued LOCALLY, not when
// WhatsApp's servers accept it. Right after a (re)link the queue can silently
// drop a send while still resolving — callers then advance their state on a
// message that never left. Wait for ACK >= 1 (ACK_SERVER) so a phantom send
// surfaces as a failure and the caller retries instead of losing the message.
function waitForAck(msg, minAck = 1, timeoutMs = 20000) {
    return new Promise((resolve) => {
        if ((msg.ack || 0) >= minAck) return resolve(true);
        const id = msg.id?._serialized;
        let done = false;
        const onAck = (m, ack) => {
            if (m.id?._serialized === id && ack >= minAck) finish(true);
        };
        const finish = (ok) => {
            if (done) return;
            done = true;
            client.removeListener("message_ack", onAck);
            clearTimeout(timer);
            resolve(ok);
        };
        const timer = setTimeout(() => finish((msg.ack || 0) >= minAck), timeoutMs);
        client.on("message_ack", onAck);
    });
}

// ── Delivered-but-threw detector ─────────────────────────────────────────────
// On some WhatsApp Web builds, whatsapp-web.js sendMessage() DELIVERS the message
// but then throws while building the return object (getMessageModel → Message.js
// `this.ack = data.ack`, with data undefined → "Cannot read properties of
// undefined (reading 'ack')"). The message is already sent. Reporting this as a
// failure makes callers retry, so the user receives duplicates — observed
// 2026-07-18 as the SAME message ×3 (send_whatsapp.py's 3 retries), and it was
// also the trigger for the chia-win-notifier flood. Treat this specific
// serialization error as a successful send.
function deliveredButModelThrew(err) {
    return /reading 'ack'|reading 'id'|getMessageModel/.test((err && err.message) || "");
}

// ── Send helper ────────────────────────────────────────────────────────────
async function doSend(phone, message, res) {
    try {
        // Normalise: strip leading +, ensure @c.us suffix
        const clean = phone.replace(/^\+/, "").replace(/\s/g, "");
        const chatId = `${clean}@c.us`;
        const msg = await client.sendMessage(chatId, message);
        const confirmed = await waitForAck(msg, 1, 20000);
        if (!confirmed) {
            console.error(`[wa-service] Send to ${clean} not confirmed (ack timeout)`);
            if (res) res.status(504).json({ ok: false, error: "send not confirmed by server (ack timeout)" });
            return;
        }
        console.log(`[wa-service] Sent to ${clean} (ack confirmed)`);
        if (res) res.json({ ok: true });
    } catch (err) {
        if (deliveredButModelThrew(err)) {
            console.warn(`[wa-service] send delivered but ack-model threw (known wwebjs bug) — treating as sent: ${err.message}`);
            if (res) res.json({ ok: true, note: "sent; ack unconfirmed (wwebjs serialization bug)" });
            return;
        }
        console.error("[wa-service] Send error:", err.message);
        if (res) res.status(500).json({ ok: false, error: err.message });
    }
}

// ── HTTP API ───────────────────────────────────────────────────────────────
const app = express();
app.use(express.json());

app.get("/status", (_req, res) => res.json({ state }));

app.get("/whoami", (_req, res) => res.json({
    wid: (client.info && client.info.wid && client.info.wid._serialized) || null,
    pushname: (client.info && client.info.pushname) || null,
}));

app.get("/qr", (_req, res) => {
    if (state !== "qr_pending" || !lastQr) {
        return res.json({ state, qr: null });
    }
    res.json({ state, qr: lastQr });
});

app.post("/send", (req, res) => {
    const { phone, message } = req.body;
    if (!phone || !message) {
        return res.status(400).json({ ok: false, error: "phone and message required" });
    }

    if (state === "ready") {
        doSend(phone, message, res);
    } else if (state === "initializing" || state === "qr_pending") {
        // Queue and respond once ready (up to 120 s). `respond` guards against
        // answering twice (timer fired AND drain later reached the item), which
        // previously crashed with ERR_HTTP_HEADERS_SENT.
        let responded = false;
        const respond = (code, body) => {
            if (responded) return;
            responded = true;
            clearTimeout(timer);
            res.status(code).json(body);
        };
        const item = {
            phone, message,
            res: {
                json: (body) => respond(200, body),
                status: (code) => ({ json: (body) => respond(code, body) }),
            },
        };
        const timer = setTimeout(() => {
            msgQueue = msgQueue.filter(i => i !== item);
            respond(503, { ok: false, error: `WA not ready (state: ${state})` });
        }, 120_000);
        msgQueue.push(item);
    } else {
        res.status(503).json({ ok: false, error: `WA disconnected` });
    }
});

// POST /send-file { phone, file_path, caption? }
app.post("/send-file", async (req, res) => {
    const { phone, file_path, caption } = req.body;
    if (!phone || !file_path) {
        return res.status(400).json({ ok: false, error: "phone and file_path required" });
    }
    if (state !== "ready") {
        return res.status(503).json({ ok: false, error: `WA not ready (state: ${state})` });
    }
    try {
        const clean  = phone.replace(/^\+/, "").replace(/\s/g, "");
        const chatId = `${clean}@c.us`;
        const media  = MessageMedia.fromFilePath(file_path);
        const msg = await client.sendMessage(chatId, media, { caption: caption || "" });
        // Media uploads are the most likely to silently fail post-relink — give
        // the upload + server ack a longer window before confirming.
        const confirmed = await waitForAck(msg, 1, 45000);
        if (!confirmed) {
            console.error(`[wa-service] File to ${clean} not confirmed (ack timeout): ${path.basename(file_path)}`);
            return res.status(504).json({ ok: false, error: "file send not confirmed by server (ack timeout)" });
        }
        console.log(`[wa-service] File sent to ${clean}: ${path.basename(file_path)} (ack confirmed)`);
        res.json({ ok: true });
    } catch (err) {
        if (deliveredButModelThrew(err)) {
            console.warn(`[wa-service] file delivered but ack-model threw (known wwebjs bug) — treating as sent: ${err.message}`);
            return res.json({ ok: true, note: "sent; ack unconfirmed (wwebjs serialization bug)" });
        }
        console.error("[wa-service] Send-file error:", err.message);
        res.status(500).json({ ok: false, error: err.message });
    }
});

app.listen(PORT, "127.0.0.1", () => {
    console.log(`[wa-service] Listening on http://127.0.0.1:${PORT}`);
});
