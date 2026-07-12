// WhatsApp bridge sidecar — Baileys <-> Django ingest.
// Runs on :3001. See CONTRACTS.md for the pinned interfaces.

import express from "express";
import pino from "pino";
import QRCode from "qrcode";
import baileys, {
  DisconnectReason,
  useMultiFileAuthState,
} from "@whiskeysockets/baileys";

const makeWASocket = baileys.makeWASocket ?? baileys;

const PORT = 3001;
const INGEST_URL = "http://localhost:8000/api/ingest/whatsapp";
const INGEST_SECRET = process.env.INGEST_SECRET || "dev-ingest-secret";
const AUTH_DIR = new URL("./auth_state", import.meta.url).pathname;

const logger = pino({ level: process.env.LOG_LEVEL || "info" });

// ---- state -----------------------------------------------------------------
let latestQR = null; // raw QR string from Baileys
let connected = false;
let sock = null;

// In-memory store of history-synced messages (from messaging-history.set).
// Keyed by `${chat_jid}:${external_id}` to dedupe across sync batches.
const historyStore = new Map();
const HISTORY_STORE_MAX = 20000;

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

// Map a Baileys WAMessage to an IngestMessage per CONTRACTS.md.
// Returns null for messages that should be skipped.
function mapMessage(msg) {
  const key = msg.key;
  if (!key || !key.remoteJid || !key.id) return null;
  const jid = key.remoteJid;
  // Skip groups and status broadcasts.
  if (jid.endsWith("@g.us") || jid === "status@broadcast" || jid.endsWith("@broadcast")) {
    return null;
  }
  const body = extractBody(msg.message);
  if (!body || !body.trim()) return null;

  const tsSec = toTimestampSeconds(msg.messageTimestamp);
  const ts = new Date((tsSec ?? Math.floor(Date.now() / 1000)) * 1000)
    .toISOString()
    .replace(/\.\d{3}Z$/, "Z");

  return {
    external_id: key.id,
    chat_jid: jid,
    sender_name: msg.pushName || jid,
    phone: jidToPhone(jid),
    body,
    ts,
    direction: key.fromMe ? "out" : "in",
  };
}

function storeHistoryMessage(msg) {
  const mapped = mapMessage(msg);
  if (!mapped) return;
  const k = `${mapped.chat_jid}:${mapped.external_id}`;
  if (historyStore.size >= HISTORY_STORE_MAX && !historyStore.has(k)) return;
  historyStore.set(k, mapped);
}

// ---- forward live messages to Django ---------------------------------------
async function forwardToIngest(messages) {
  if (!messages.length) return;
  try {
    const res = await fetch(INGEST_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Ingest-Secret": INGEST_SECRET,
      },
      body: JSON.stringify({ messages }),
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      logger.warn({ status: res.status, text }, "ingest POST failed");
    } else {
      const data = await res.json().catch(() => ({}));
      logger.info({ count: messages.length, ...data }, "forwarded to ingest");
    }
  } catch (err) {
    logger.warn({ err: err?.message }, "ingest POST error (Django down?)");
  }
}

// ---- Baileys socket ---------------------------------------------------------
async function startSocket() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);

  sock = makeWASocket({
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
      latestQR = null;
      logger.info("WhatsApp connection open");
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
        logger.error("logged out — delete sidecar/auth_state and re-pair");
      }
    }
  });

  // Buffer history sync batches into the in-memory store.
  sock.ev.on("messaging-history.set", ({ messages }) => {
    if (!Array.isArray(messages)) return;
    for (const msg of messages) {
      try {
        storeHistoryMessage(msg);
      } catch (err) {
        logger.warn({ err: err?.message }, "failed to store history message");
      }
    }
    logger.info(
      { batch: messages.length, stored: historyStore.size },
      "history sync batch"
    );
  });

  // Live messages -> POST to Django ingest.
  sock.ev.on("messages.upsert", ({ messages, type }) => {
    if (type !== "notify" || !Array.isArray(messages)) return;
    const mapped = [];
    for (const msg of messages) {
      try {
        const m = mapMessage(msg);
        if (m) {
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
  res.json({ connected });
});

app.get("/qr", async (_req, res) => {
  try {
    if (!latestQR) return res.json({ qr: null });
    const dataUrl = await QRCode.toDataURL(latestQR);
    res.json({ qr: dataUrl });
  } catch (err) {
    logger.warn({ err: err?.message }, "QR encode failed");
    res.json({ qr: null });
  }
});

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
