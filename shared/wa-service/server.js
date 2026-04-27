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
const { execSync } = require("child_process");

const QR_TXT  = "/tmp/wa_qr.txt";
const QR_PNG  = "/tmp/wa_qr.png";

const PORT     = 3131;
const SESSION  = "/home/work/fraqtoos/shared/wa-service/session";

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
});

client.on("disconnected", (reason) => {
    state = "disconnected";
    console.error("[wa-service] Disconnected:", reason);
    // Auto-reconnect after 10 s
    setTimeout(() => {
        console.log("[wa-service] Reconnecting…");
        state = "initializing";
        client.initialize();
    }, 10_000);
});

client.initialize();

// ── Send helper ────────────────────────────────────────────────────────────
async function doSend(phone, message, res) {
    try {
        // Normalise: strip leading +, ensure @c.us suffix
        const clean = phone.replace(/^\+/, "").replace(/\s/g, "");
        const chatId = `${clean}@c.us`;
        await client.sendMessage(chatId, message);
        console.log(`[wa-service] Sent to ${clean}`);
        if (res) res.json({ ok: true });
    } catch (err) {
        console.error("[wa-service] Send error:", err.message);
        if (res) res.status(500).json({ ok: false, error: err.message });
    }
}

// ── HTTP API ───────────────────────────────────────────────────────────────
const app = express();
app.use(express.json());

app.get("/status", (_req, res) => res.json({ state }));

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
        // Queue and respond once ready (up to 120 s)
        const timer = setTimeout(() => {
            msgQueue = msgQueue.filter(i => i.res !== res);
            res.status(503).json({ ok: false, error: `WA not ready (state: ${state})` });
        }, 120_000);
        msgQueue.push({
            phone, message,
            res: {
                json: (body) => { clearTimeout(timer); res.json(body); },
                status: (code) => ({ json: (body) => { clearTimeout(timer); res.status(code).json(body); } }),
            },
        });
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
        await client.sendMessage(chatId, media, { caption: caption || "" });
        console.log(`[wa-service] File sent to ${clean}: ${path.basename(file_path)}`);
        res.json({ ok: true });
    } catch (err) {
        console.error("[wa-service] Send-file error:", err.message);
        res.status(500).json({ ok: false, error: err.message });
    }
});

app.listen(PORT, "127.0.0.1", () => {
    console.log(`[wa-service] Listening on http://127.0.0.1:${PORT}`);
});
