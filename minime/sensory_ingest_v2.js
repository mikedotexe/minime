#!/usr/bin/env node
"use strict";

// Control-aware sensory ingest that monitors engine state via WebSocket

const { spawn } = require("child_process");
const WebSocket = require("ws");
const readline = require("readline");

const WS_MONITOR_URL = process.env.MONITOR_WS || "ws://127.0.0.1:7878";
const WS_CONTROL_URL = process.env.CONTROL_WS || "ws://127.0.0.1:7881";
const BASE_COOLDOWN_MS = +(process.env.BASE_COOLDOWN_MS || 5);
const MAX_COOLDOWN_MS = +(process.env.MAX_COOLDOWN_MS || 1000);

// Subsampled Randomized Hadamard Transform
function srht(vec, outDim) {
    const n = vec.length;
    if (n === 0 || (n & (n - 1)) !== 0) throw new Error("Input size must be power of 2");

    // In-place WHT
    for (let h = 1; h < n; h <<= 1) {
        for (let i = 0; i < n; i += h << 1) {
            for (let j = i; j < i + h; j++) {
                const x = vec[j];
                const y = vec[j + h];
                vec[j] = x + y;
                vec[j + h] = x - y;
            }
        }
    }

    // Normalize
    const scale = 1.0 / Math.sqrt(n);
    for (let i = 0; i < n; i++) vec[i] *= scale;

    // Subsample
    const step = Math.floor(n / outDim);
    const result = [];
    for (let i = 0; i < outDim; i++) {
        result.push(vec[i * step]);
    }
    return result;
}

class TokenBucket {
    constructor(ratePerSec, burstSize) {
        this.ratePerSec = ratePerSec;
        this.burstSize = burstSize;
        this.tokens = burstSize;
        this.lastRefill = Date.now();
    }

    tryConsume(n = 1) {
        const now = Date.now();
        const elapsed = (now - this.lastRefill) / 1000;
        this.tokens = Math.min(this.burstSize, this.tokens + elapsed * this.ratePerSec);
        this.lastRefill = now;

        if (this.tokens >= n) {
            this.tokens -= n;
            return true;
        }
        return false;
    }

    setRate(newRate) {
        this.ratePerSec = Math.max(0.1, newRate);
    }
}

class ControlAwareIngest {
    constructor() {
        this.bucket = new TokenBucket(200, 1000); // 200 msgs/sec, burst 1000
        this.cooldownMs = BASE_COOLDOWN_MS;
        this.lastSend = 0;
        this.gateValue = 1.0;
        this.fillPct = 0;
        this.multiplier = 1.0;
        this.enabled = true;

        this.monitorWs = null;
        this.controlWs = null;
        this.connectMonitor();
        this.connectControl();

        // Feature channels
        this.audioFeatures = new Float32Array(32);
        this.videoFeatures = new Float32Array(32);
        this.lastVideoFrame = null;

        // Start processing
        this.setupStdinReader();
        this.startVideoCapture();
        setInterval(() => this.processPending(), 5);
    }

    connectMonitor() {
        this.monitorWs = new WebSocket(WS_MONITOR_URL);
        this.monitorWs.on('open', () => console.error('[ingest] Connected to monitor'));
        this.monitorWs.on('message', (data) => {
            try {
                const msg = JSON.parse(data.toString());
                if (msg.t_ms && typeof msg.gate === 'number' && typeof msg.fill === 'number') {
                    this.gateValue = msg.gate;
                    this.fillPct = msg.fill;

                    // Dynamic rate adjustment based on gate
                    const baseRate = 200;
                    const adaptedRate = baseRate * this.gateValue * this.multiplier;
                    this.bucket.setRate(adaptedRate);

                    // Dynamic cooldown based on fill
                    if (this.fillPct > 80) {
                        this.cooldownMs = MAX_COOLDOWN_MS;
                    } else if (this.fillPct > 60) {
                        this.cooldownMs = BASE_COOLDOWN_MS * 10;
                    } else {
                        this.cooldownMs = BASE_COOLDOWN_MS;
                    }
                }
            } catch (e) {
                console.error('[ingest] Monitor parse error:', e);
            }
        });
        this.monitorWs.on('close', () => {
            console.error('[ingest] Monitor disconnected, reconnecting...');
            setTimeout(() => this.connectMonitor(), 1000);
        });
        this.monitorWs.on('error', () => {});
    }

    connectControl() {
        this.controlWs = new WebSocket(WS_CONTROL_URL);
        this.controlWs.on('open', () => console.error('[ingest] Connected to control'));
        this.controlWs.on('close', () => {
            console.error('[ingest] Control disconnected, reconnecting...');
            setTimeout(() => this.connectControl(), 1000);
        });
        this.controlWs.on('error', () => {});
    }

    setupStdinReader() {
        const rl = readline.createInterface({
            input: process.stdin,
            output: null,
            terminal: false
        });

        rl.on('line', (line) => {
            if (!line.trim()) return;
            try {
                const msg = JSON.parse(line);

                // Update audio features if present
                if (msg.audio && Array.isArray(msg.audio)) {
                    for (let i = 0; i < Math.min(32, msg.audio.length); i++) {
                        this.audioFeatures[i] = msg.audio[i];
                    }
                }

                // Process immediately if we have both audio and video
                if (this.lastVideoFrame) {
                    this.processPending();
                }
            } catch (e) {
                console.error('[ingest] Parse error:', e);
            }
        });
    }

    startVideoCapture() {
        // Capture 64x64 grayscale at 1 FPS
        const ffmpeg = spawn('ffmpeg', [
            '-f', 'avfoundation',
            '-framerate', '1',
            '-video_size', '64x64',
            '-i', '0',
            '-vf', 'format=gray',
            '-f', 'rawvideo',
            '-pix_fmt', 'gray',
            '-'
        ], { stdio: ['ignore', 'pipe', 'ignore'] });

        let buffer = Buffer.alloc(0);
        const frameSize = 64 * 64; // 1 byte per pixel

        ffmpeg.stdout.on('data', (chunk) => {
            buffer = Buffer.concat([buffer, chunk]);

            while (buffer.length >= frameSize) {
                const frame = buffer.subarray(0, frameSize);
                buffer = buffer.subarray(frameSize);

                // Process frame
                this.processVideoFrame(frame);
            }
        });

        ffmpeg.on('error', (err) => {
            console.error('[ingest] Video capture error:', err);
        });
    }

    processVideoFrame(frame) {
        // Convert to normalized float array
        const pixels = new Float32Array(frame.length);
        for (let i = 0; i < frame.length; i++) {
            pixels[i] = frame[i] / 255.0;
        }

        // Apply SRHT to reduce 4096 -> 128 dims
        try {
            const reduced = srht(pixels, 128);

            // Take first 32 components as video features
            for (let i = 0; i < 32; i++) {
                this.videoFeatures[i] = reduced[i] || 0;
            }

            this.lastVideoFrame = Date.now();
        } catch (e) {
            console.error('[ingest] SRHT error:', e);
        }
    }

    processPending() {
        const now = Date.now();

        // Check if we're enabled and have waited long enough
        if (!this.enabled || now - this.lastSend < this.cooldownMs) {
            return;
        }

        // Check if we have recent data
        if (!this.lastVideoFrame || now - this.lastVideoFrame > 5000) {
            return; // Video too old
        }

        // Token bucket rate limiting
        if (!this.bucket.tryConsume(1)) {
            return;
        }

        // Combine features
        const features = new Float32Array(64);
        features.set(this.audioFeatures, 0);
        features.set(this.videoFeatures, 32);

        // Calculate simple stats
        let audioRms = 0, videoVar = 0;
        for (let i = 0; i < 32; i++) {
            audioRms += this.audioFeatures[i] * this.audioFeatures[i];
        }
        audioRms = Math.sqrt(audioRms / 32);

        const videoMean = this.videoFeatures.reduce((a, b) => a + b, 0) / 32;
        for (let i = 0; i < 32; i++) {
            const d = this.videoFeatures[i] - videoMean;
            videoVar += d * d;
        }
        videoVar /= 32;

        // Send to stdout
        const packet = {
            t: now,
            lane: "realtime",
            features: Array.from(features),
            audio_rms: audioRms,
            video_var: videoVar,
            gate: this.gateValue,
            fill: this.fillPct
        };

        console.log(JSON.stringify(packet));
        this.lastSend = now;
    }
}

// Start the ingest
new ControlAwareIngest();
