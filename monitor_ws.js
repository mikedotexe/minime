#!/usr/bin/env node
"use strict";

const WebSocket = require("ws");

// Connect to monitor WebSocket
const ws = new WebSocket("ws://127.0.0.1:7878");

ws.on('open', () => {
    console.log("Connected to monitor WebSocket");
});

ws.on('message', (data) => {
    try {
        const msg = JSON.parse(data.toString());
        const ts = new Date(msg.t_ms).toISOString().substr(11, 12);
        console.log(`[${ts}] gate=${msg.gate.toFixed(3)} fill=${msg.fill.toFixed(1)}% λ₁=${msg.lambda1?.toFixed(3) || 'N/A'}`);
    } catch (e) {
        console.log("Raw message:", data.toString());
    }
});

ws.on('close', () => {
    console.log("Disconnected from monitor WebSocket");
    process.exit();
});

ws.on('error', (err) => {
    console.error("WebSocket error:", err);
});

// Keep alive
setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) {
        ws.ping();
    }
}, 30000);