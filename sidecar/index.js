// WhatsApp bridge sidecar — Baileys <-> Django ingest.
// Runs on :3001.
//
// v2: the sidecar is a thin, persist-through bridge. Durable state lives in
// Django/Postgres (WaChat/WaMessage): history-sync batches AND live messages
// — groups included — are forwarded to /api/ingest/whatsapp, and Django
// dedupes on (chat, external_id). The in-memory store remains only to serve
// the legacy /fetch-history endpoint.

import fs from "node:fs";
import express from "express";
import pino from "pino";
import QRCode from "qrcode";
import baileys, {
  DisconnectReason,
  fetchLatestBaileysVersion,
  useMultiFileAuthState,
} from "@whiskeysockets/baileys";

const makeWASocket = baileys.makeWASocket ?? baileys;

const PORT = Number(process.env.PORT) || 3001;
const INGEST_URL =
  process.env.INGEST_URL || "http://localhost:8000/api/ingest/whatsapp";
const INGEST_SECRET = process.env.INGEST_SECRET || "dev-ingest-secret";
const AUTH_DIR = new URL("./auth_state", import.meta.url).pathname;
const INGEST_BATCH = 500;

const logger = pino({ level: process.env.LOG_LEVEL || "info" });

// ---- state -----------------------------------------------------------------
let latestQR = null; // raw QR string from Baileys
let connected = false;
let connectedAt = null; // ISO time of the current session's "open"
let sock = null;

// In-memory store of history-synced messages (from messaging-history.set).
// Keyed by `${chat_jid}:${external_id}` to dedupe across sync batches.
const historyStore = new Map();
const HISTORY_STORE_MAX = 20000;

// Chat metadata: jid -> {name, is_group}. Group subjects come from
// groupFetchAllParticipating / groups.* events; DM names from pushNames.
const chatMeta = new Map();

const looksLikeJid = (v) => !v || v.includes("@");

function rememberChat(jid, { name, isGroup, authoritative } = {}) {
  if (!jid) return;
  const meta = chatMeta.get(jid) || { name: "", is_group: jid.endsWith("@g.us") };
  // Never store a jid as a display name; real names may replace jid-ish ones.
  if (name && !looksLikeJid(name) && (!meta.name || authoritative || looksLikeJid(meta.name))) {
    meta.name = name;
  }
  if (name && meta.is_group && !looksLikeJid(name)) meta.name = name; // subjects win
  if (isGroup) meta.is_group = true;
  chatMeta.set(jid, meta);
}

function contactName(c) {
  return c?.name || c?.notify || c?.verifiedName || "";
}

// ---- message mapping -------------------------------------------------------
function extractBody(message) {
  if (!message) return "";
  // unwrap ephemeral / view-once wrappers
  const inner =
    message.ephemeralMessage?.message ||
    message.viewOnceMessage?.message ||
    message.viewOnceMessageV2?.message ||
    message;
  return (
    inner.conversation ||
    inner.extendedTextMessage?.text ||
    inner.imageMessage?.caption ||
    ""
  );
}

function jidToPhone(jid) {
  if (typeof jid === "string" && jid.endsWith("@s.whatsapp.net")) {
    const digits = jid.split("@")[0].split(":")[0].replace(/\D/g, "");
    if (digits) return `+${digits}`;
  }
  return null;
}

function toTimestampSeconds(messageTimestamp) {
  if (messageTimestamp == null) return null;
  if (typeof messageTimestamp === "number") return messageTimestamp;
  if (typeof messageTimestamp === "object") {
    // Long-like {low, high} or has toNumber()
    if (typeof messageTimestamp.toNumber === "function") {
      return messageTimestamp.toNumber();
    }
    if (typeof messageTimestamp.low === "number") {
      return messageTimestamp.low + (messageTimestamp.high || 0) * 4294967296;
    }
  }
  const n = Number(messageTimestamp);
  return Number.isFinite(n) ? n : null;
}

// Map a Baileys WAMessage to an IngestMessage. Groups ARE included (v2);
// only status/broadcast/newsletter traffic is skipped. Returns null for
// messages that should be skipped.
function mapMessage(msg) {
  const key = msg.key;
  if (!key || !key.remoteJid || !key.id) return null;
  const jid = key.remoteJid;
  if (
    jid === "status@broadcast" ||
    jid.endsWith("@broadcast") ||
    jid.endsWith("@newsletter")
  ) {
    return null;
  }
  const body = extractBody(msg.message);
  if (!body || !body.trim()) return null;

  const isGroup = jid.endsWith("@g.us");
  const senderJid = key.participant || (key.fromMe ? "me" : jid);
  const tsSec = toTimestampSeconds(msg.messageTimestamp);
  const ts = new Date((tsSec ?? Math.floor(Date.now() / 1000)) * 1000)
    .toISOString()
    .replace(/\.\d{3}Z$/, "Z");

  // Keep DM display names fresh from inbound pushNames.
  if (!isGroup && !key.fromMe && msg.pushName) {
    rememberChat(jid, { name: msg.pushName });
  }

  return {
    external_id: key.id,
    chat_jid: jid,
    chat_name: chatMeta.get(jid)?.name || null,
    is_group: isGroup,
    sender_jid: senderJid,
    sender_name: key.fromMe
      ? "Me"
      : msg.pushName ||
        chatMeta.get(isGroup ? senderJid : jid)?.name ||
        jidToPhone(isGroup ? senderJid : jid) ||
        "",
    phone: key.fromMe ? null : jidToPhone(isGroup ? senderJid : jid),
    body,
    ts,
    direction: key.fromMe ? "out" : "in",
  };
}

function storeHistoryMessage(mapped) {
  const k = `${mapped.chat_jid}:${mapped.external_id}`;
  if (historyStore.size >= HISTORY_STORE_MAX && !historyStore.has(k)) return;
  historyStore.set(k, mapped);
}

// ---- forward messages to Django ---------------------------------------------
async function forwardToIngest(messages) {
  if (!messages.length) return;
  for (let i = 0; i < messages.length; i += INGEST_BATCH) {
    const batch = messages.slice(i, i + INGEST_BATCH);
    try {
      const res = await fetch(INGEST_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Ingest-Secret": INGEST_SECRET,
        },
        body: JSON.stringify({ messages: batch }),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        logger.warn({ status: res.status, text }, "ingest POST failed");
      } else {
        const data = await res.json().catch(() => ({}));
        logger.info({ count: batch.length, ...data }, "forwarded to ingest");
      }
    } catch (err) {
      logger.warn({ err: err?.message }, "ingest POST error (Django down?)");
    }
  }
}

// ---- group metadata -----------------------------------------------------------
async function refreshGroups() {
  if (!sock) return;
  try {
    const groups = await sock.groupFetchAllParticipating();
    for (const [jid, meta] of Object.entries(groups || {})) {
      rememberChat(jid, { name: meta?.subject || "", isGroup: true });
    }
    logger.info({ groups: Object.keys(groups || {}).length }, "group metadata refreshed");
  } catch (err) {
    logger.warn({ err: err?.message }, "groupFetchAllParticipating failed");
  }
}

// ---- Baileys socket ---------------------------------------------------------
async function startSocket() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  // Pin to the current WhatsApp Web protocol version — a stale baked-in
  // version gets the handshake rejected with 405 and no QR is ever emitted.
  const { version } = await fetchLatestBaileysVersion();

  sock = makeWASocket({
    version,
    auth: state,
    printQRInTerminal: false,
    logger: pino({ level: "silent" }),
    syncFullHistory: true,
    markOnlineOnConnect: false,
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", (update) => {
    const { connection, lastDisconnect, qr } = update;
    if (qr) {
      latestQR = qr;
      logger.info("new QR generated");
    }
    if (connection === "open") {
      connected = true;
      connectedAt = new Date().toISOString();
      latestQR = null;
      logger.info("WhatsApp connection open");
      refreshGroups().catch(() => {});
    } else if (connection === "close") {
      connected = false;
      const statusCode = lastDisconnect?.error?.output?.statusCode;
      const loggedOut = statusCode === DisconnectReason.loggedOut;
      logger.warn({ statusCode }, "connection closed");
      if (!loggedOut) {
        setTimeout(() => {
          startSocket().catch((err) =>
            logger.error({ err: err?.message }, "reconnect failed")
          );
        }, 3000);
      } else {
        // Dead creds can't recover — wipe them and start a fresh pairing
        // session so the UI immediately gets QR/pairing codes again.
        logger.error("logged out — clearing auth_state, starting fresh session");
        try {
          fs.rmSync(AUTH_DIR, { recursive: true, force: true });
        } catch (err) {
          logger.error({ err: err?.message }, "auth_state cleanup failed");
        }
        setTimeout(() => {
          startSocket().catch((err) =>
            logger.error({ err: err?.message }, "fresh session failed")
          );
        }, 1000);
      }
    }
  });

  // Address-book / push names for DMs — the history stream rarely carries
  // pushName, so without these events DM chats end up named by their jid.
  sock.ev.on("contacts.upsert", (contacts) => {
    for (const c of contacts || []) {
      if (c?.id) rememberChat(c.id, { name: contactName(c), authoritative: true });
    }
  });
  sock.ev.on("contacts.update", (updates) => {
    for (const c of updates || []) {
      if (c?.id) rememberChat(c.id, { name: contactName(c), authoritative: true });
    }
  });

  // Track group subject changes.
  sock.ev.on("groups.upsert", (groups) => {
    for (const g of groups || []) rememberChat(g.id, { name: g.subject, isGroup: true });
  });
  sock.ev.on("groups.update", (updates) => {
    for (const g of updates || []) {
      if (g.id && g.subject) chatMeta.set(g.id, { name: g.subject, is_group: true });
    }
  });

  // History sync batches: buffer locally AND persist through to Django.
  sock.ev.on("messaging-history.set", ({ messages, chats, contacts }) => {
    for (const c of contacts || []) {
      if (c?.id) rememberChat(c.id, { name: contactName(c), authoritative: true });
    }
    for (const chat of chats || []) {
      if (chat?.id && chat.name) rememberChat(chat.id, { name: chat.name });
    }
    if (!Array.isArray(messages)) return;
    const mapped = [];
    for (const msg of messages) {
      try {
        const m = mapMessage(msg);
        if (m) {
          mapped.push(m);
          storeHistoryMessage(m);
        }
      } catch (err) {
        logger.warn({ err: err?.message }, "failed to map history message");
      }
    }
    logger.info(
      { batch: messages.length, mapped: mapped.length, stored: historyStore.size },
      "history sync batch"
    );
    forwardToIngest(mapped).catch((err) =>
      logger.warn({ err: err?.message }, "history forward failed")
    );
  });

  // Live messages -> POST to Django ingest. Tagged live:true so only these
  // chats surface in the UI directory (history stays fetchable once scoped).
  sock.ev.on("messages.upsert", ({ messages, type }) => {
    if (type !== "notify" || !Array.isArray(messages)) return;
    const mapped = [];
    for (const msg of messages) {
      try {
        const m = mapMessage(msg);
        if (m) {
          m.live = true;
          mapped.push(m);
          historyStore.set(`${m.chat_jid}:${m.external_id}`, m);
        }
      } catch (err) {
        logger.warn({ err: err?.message }, "failed to map live message");
      }
    }
    forwardToIngest(mapped).catch((err) =>
      logger.warn({ err: err?.message }, "forward failed")
    );
  });

  return sock;
}

// ---- HTTP API ----------------------------------------------------------------
const app = express();
app.use(express.json({ limit: "5mb" }));

app.get("/status", (_req, res) => {
  res.json({ connected, connected_at: connectedAt });
});

app.get("/qr", async (_req, res) => {
  try {
    if (!latestQR) return res.json({ qr: null, connected });
    const dataUrl = await QRCode.toDataURL(latestQR);
    res.json({ qr: dataUrl, connected });
  } catch (err) {
    logger.warn({ err: err?.message }, "QR encode failed");
    res.json({ qr: null, connected });
  }
});

// Unlink this device: logout triggers the logged-out close path, which wipes
// auth_state and starts a fresh pairing session automatically.
app.post("/disconnect", async (_req, res) => {
  try {
    if (sock && connected) {
      await sock.logout();
    } else {
      fs.rmSync(AUTH_DIR, { recursive: true, force: true });
    }
    res.json({ ok: true });
  } catch (err) {
    logger.warn({ err: err?.message }, "logout failed — forcing fresh session");
    try {
      fs.rmSync(AUTH_DIR, { recursive: true, force: true });
    } catch {}
    connected = false;
    startSocket().catch(() => {});
    res.json({ ok: true, forced: true });
  }
});

// Phone-number pairing code (alternative to QR): WhatsApp → Linked Devices →
// "Link with phone number instead". Requires the socket to be unregistered.
app.get("/pair-code", async (req, res) => {
  if (connected) return res.json({ code: null, connected: true });
  const phone = String(req.query.phone || "").replace(/[^0-9]/g, "");
  if (!phone) {
    return res.status(400).json({ error: "phone required (digits with country code, e.g. 9198xxxxxx)" });
  }
  try {
    if (sock?.authState?.creds?.registered) {
      return res.json({ code: null, connected });
    }
    const code = await sock.requestPairingCode(phone);
    logger.info("pairing code issued");
    res.json({ code, connected: false });
  } catch (err) {
    logger.warn({ err: err?.message }, "pairing code request failed");
    res.status(500).json({ error: "pairing code request failed — try again in a few seconds" });
  }
});

// Chat/group directory for Django's sync endpoint. Merges group metadata
// (subjects) with every chat seen in the message store.
app.get("/chats", (_req, res) => {
  if (!connected) {
    return res.status(503).json({ error: "whatsapp not connected" });
  }
  const seen = new Map(); // jid -> chat dict
  for (const [jid, meta] of chatMeta.entries()) {
    seen.set(jid, { jid, name: meta.name || "", is_group: !!meta.is_group });
  }
  for (const m of historyStore.values()) {
    if (!seen.has(m.chat_jid)) {
      seen.set(m.chat_jid, {
        jid: m.chat_jid,
        name: m.is_group ? m.chat_name || "" : m.direction === "in" ? m.sender_name : "",
        is_group: !!m.is_group,
      });
    }
  }
  res.json({ chats: [...seen.values()] });
});

// Legacy pull endpoint (in-memory window). Django's engine now reads from
// its own WaMessage store; this remains for manual debugging.
app.post("/fetch-history", (req, res) => {
  if (!connected) {
    return res.status(503).json({ error: "whatsapp not connected" });
  }
  const sinceDays = Number(req.body?.since_days) || 30;
  const cutoff = Date.now() - sinceDays * 24 * 60 * 60 * 1000;
  const messages = [...historyStore.values()].filter(
    (m) => new Date(m.ts).getTime() >= cutoff
  );
  messages.sort((a, b) => new Date(a.ts) - new Date(b.ts));
  res.json({ messages });
});

app.listen(PORT, () => {
  logger.info(`sidecar listening on http://localhost:${PORT}`);
});

startSocket().catch((err) => {
  logger.error({ err: err?.message }, "failed to start Baileys socket");
});

process.on("uncaughtException", (err) => {
  logger.error({ err: err?.message, stack: err?.stack }, "uncaughtException");
});
process.on("unhandledRejection", (err) => {
  logger.error({ err: err?.message }, "unhandledRejection");
});
