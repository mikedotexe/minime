# LLaVA SSE Worker

Lightweight proxy that streams Ollama's LLaVA responses as Server-Sent Events for faster first-token latency.

## Quick start

```bash
cd tools/llava-worker
node llava_worker.mjs
# or override defaults
OLLAMA_URL=http://127.0.0.1:11434/api/generate PORT=3031 node llava_worker.mjs
```

The server listens on `http://127.0.0.1:3031` by default and exposes:

- `POST /describe` – body `{ "imageBase64": "...", "prompt": "..." }`; emits `data: {"token":"…"}` lines followed by `{"done":true}`.
- `GET /healthz` – readiness probe.

Point `minime.py` at the worker with:

```bash
export LLAVA_SSE_URL=http://127.0.0.1:3031
```

If the environment variable is unset, the Python stack falls back to the direct Ollama REST call.

## Why SSE?

- Streams individual tokens immediately for lower perceived latency.
- Keeps Ollama integration untouched; only the proxy speaks SSE.
- Simple to integrate with existing logs, UIs, or TTS pipelines.

## Monitoring Tips

- Log `firstTokenMs` and `totalMs` in clients for p95 budgeting (<20 s recommended).
- Use the `/healthz` endpoint in supervision scripts to confirm availability before starting the consciousness loop.

