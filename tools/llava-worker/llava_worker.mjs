#!/usr/bin/env node
/**
 * Lightweight LLaVA streaming proxy
 *
 * Starts an HTTP server (default http://127.0.0.1:3031) that accepts POST /describe
 * requests with `{ imageBase64, prompt }` and relays them to Ollama with
 * `stream: true`. The JSON-line stream from Ollama is re-emitted as Server-Sent
 * Events so clients can consume tokens as they arrive.
 *
 * Usage:
 *   node llava_worker.mjs
 *
 * Environment overrides:
 *   PORT            Listening port (default 3031)
 *   HOST            Bind host (default 127.0.0.1)
 *   OLLAMA_URL      Ollama endpoint (default http://127.0.0.1:11434/api/generate)
 *   OLLAMA_MODEL    Vision model to request (default llava:7b)
 */

import http from "node:http";
import { TextDecoder } from "node:util";

const HOST = process.env.HOST ?? "127.0.0.1";
const PORT = Number(process.env.PORT ?? 3031);
const OLLAMA_URL = process.env.OLLAMA_URL ?? "http://127.0.0.1:11434/api/generate";
const OLLAMA_MODEL = process.env.OLLAMA_MODEL ?? "llava:7b";

const decoder = new TextDecoder();

const server = http.createServer(async (req, res) => {
  if (req.method === "POST" && req.url === "/describe") {
    try {
      const body = await readJsonBody(req);
      const { imageBase64, prompt } = body ?? {};
      if (!imageBase64 || !prompt) {
        return sendJson(res, 400, { error: "Missing imageBase64 or prompt" });
      }

      res.writeHead(200, {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
      });

      // Initial comment so clients know stream started
      res.write(`: streaming from ${OLLAMA_MODEL}\n\n`);

      const controller = new AbortController();
      req.on("close", () => controller.abort());

      const ollamaResponse = await fetch(OLLAMA_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: OLLAMA_MODEL,
          prompt,
          images: [imageBase64],
          stream: true,
        }),
        signal: controller.signal,
      });

      if (!ollamaResponse.ok || !ollamaResponse.body) {
        throw new Error(`Ollama request failed: ${ollamaResponse.status}`);
      }

      await streamOllamaToSSE(ollamaResponse.body, res);
      res.write(`data: {"done":true}\n\n`);
      res.end();
    } catch (err) {
      if (!res.headersSent) {
        sendJson(res, 500, { error: err?.message ?? "Internal error" });
      } else {
        res.write(`data: {"error":"${escapeSSE(err?.message ?? "error")}"}\n\n`);
        res.end();
      }
    }
    return;
  }

  if (req.method === "GET" && req.url === "/healthz") {
    return sendJson(res, 200, { ok: true });
  }

  sendJson(res, 404, { error: "Not found" });
});

server.listen(PORT, HOST, () => {
  console.log(`LLaVA SSE proxy listening on http://${HOST}:${PORT}`);
  console.log(`Forwarding to ${OLLAMA_URL} (model ${OLLAMA_MODEL})`);
});

async function readJsonBody(req) {
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(chunk);
  }
  if (!chunks.length) return null;
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch (err) {
    throw new Error(`Invalid JSON body: ${err.message}`);
  }
}

async function streamOllamaToSSE(readable, res) {
  const reader = readable.getReader();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let newlineIndex;
    while ((newlineIndex = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, newlineIndex).trim();
      buffer = buffer.slice(newlineIndex + 1);
      if (!line) continue;
      try {
        const payload = JSON.parse(line);
        if (payload.done) {
          res.write(`data: {"done":true}\n\n`);
          return;
        }
        const token = payload.response ?? payload.token ?? "";
        if (token) {
          res.write(`data: {"token":"${escapeSSE(token)}"}\n\n`);
        }
      } catch (err) {
        res.write(`data: {"error":"${escapeSSE(err.message)}"}\n\n`);
      }
    }
  }
}

function sendJson(res, status, body) {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
}

function escapeSSE(str) {
  return String(str).replace(/"/g, '\\"');
}


