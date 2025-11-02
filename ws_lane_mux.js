#!/usr/bin/env node
"use strict";

const WebSocket = require("ws");

/*
Env:
  SINK_WS              default "ws://127.0.0.1:7879"  (engine sensory input)
  CONTROL_WS_PORT      default 7881                   (accepts Actions)
  RT_BPS               default 24576
  CTX_BPS              default 8192
  BURST_BYTES          default 65536
  MAX_BUFFERED_BYTES   default 131072
  CTX_MAX_ITEMS        default 512
  CTX_TTL_MS           default 60000
  PING_MS              default 15000
*/

const SINK_WS = process.env.SINK_WS || "ws://127.0.0.1:7879";
const CONTROL_WS_PORT = +(process.env.CONTROL_WS_PORT || 7881);
const RT_BPS = +(process.env.RT_BPS || 24576);
const CTX_BPS = +(process.env.CTX_BPS || 8192);
const BURST_BYTES = +(process.env.BURST_BYTES || 65536);
const MAX_BUFFERED_BYTES = +(process.env.MAX_BUFFERED_BYTES || 131072);
const CTX_MAX_ITEMS = +(process.env.CTX_MAX_ITEMS || 512);
const CTX_TTL_MS = +(process.env.CTX_TTL_MS || 60000);
const PING_MS = +(process.env.PING_MS || 15000);

class Bucket{
  constructor(bps, burst){ this.bps=bps; this.burst=burst; this.tok=burst; this.last=Date.now(); }
  setRate(r){ this.bps=Math.max(64,r); }
  refill(){ const t=Date.now(); const dt=(t-this.last)/1000; this.last=t; this.tok=Math.min(this.burst, this.tok+dt*this.bps); }
  take(n){ this.refill(); if (this.tok>=n){ this.tok-=n; return true; } return false; }
  util(){ return 1 - Math.min(1, this.tok/this.burst); }
}
const rtBucket = new Bucket(RT_BPS, BURST_BYTES);
const cxBucket = new Bucket(CTX_BPS, BURST_BYTES);

let sink = null;
let connected = false;
function connectSink(){
  sink = new WebSocket(SINK_WS, { perMessageDeflate: false });
  sink.on("open", ()=> { connected = true; });
  sink.on("close", ()=> { connected = false; setTimeout(connectSink, 500+Math.random()*1000); });
  sink.on("error", ()=> { try{ sink.close(); }catch{} });
  setInterval(()=>{ if (connected) try{ sink.ping(); }catch{} }, PING_MS);
}
connectSink();

const Q_rt = [];
const Q_ctx = [];
function evictCtx(){
  const now = Date.now();
  while (Q_ctx.length > 0 && (Q_ctx.length > CTX_MAX_ITEMS || (now - Q_ctx[0].t) > CTX_TTL_MS)){
    Q_ctx.shift();
  }
}
function sendIfPossible(queue, bucket){
  if (!connected || !sink || sink.readyState!==sink.OPEN) return;
  if (sink.bufferedAmount > MAX_BUFFERED_BYTES) return;
  if (queue.length===0) return;
  const s = queue[0];
  const len = Buffer.byteLength(s);
  if (!bucket.take(len)) return;
  try {
    sink.send(s, { binary: false }, (err)=>{ /* ignore */ });
    queue.shift();
  } catch {}
}

// stdin ingest
let buf = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk)=>{
  buf += chunk;
  let i;
  while ((i = buf.indexOf("\n"))>=0){
    const line = buf.slice(0,i); buf = buf.slice(i+1);
    if (!line.trim()) continue;
    try{
      const pkt = JSON.parse(line);
      const lane = (pkt.lane === "context") ? "context" : (pkt.lane === "realtime" ? "realtime" : "realtime");
      const out = JSON.stringify(pkt);
      if (lane === "realtime") Q_rt.push(out);
      else { Q_ctx.push(out); evictCtx(); }
    }catch{ /* drop */ }
  }
});
setInterval(()=>{
  sendIfPossible(Q_rt, rtBucket);
  sendIfPossible(Q_ctx, cxBucket);
}, 5);

// Track lane states for enable/disable functionality
const laneStates = {
  realtime: { enabled: true, savedRate: RT_BPS },
  context: { enabled: true, savedRate: CTX_BPS }
};

// Control WS for Actions from the being
const control = new WebSocket.Server({ port: CONTROL_WS_PORT });
control.on("connection", (ws)=>{
  ws.on("message", (data)=>{
    try{
      const msg = JSON.parse(data.toString());
      if (msg.action === "context_pop"){
        let n = Math.max(1, Math.min(64, msg.n|0));
        while (n-- > 0 && Q_ctx.length>0){
          // Boost ctx bucket briefly to flush on demand
          cxBucket.setRate(Math.max(CTX_BPS, CTX_BPS*2));
          sendIfPossible(Q_ctx, cxBucket);
        }
        ws.send(JSON.stringify({ ok: true, remaining: Q_ctx.length }));
      } else if (msg.action === "context_evict"){
        const before = Q_ctx.length;
        Q_ctx.length = 0;
        ws.send(JSON.stringify({ ok: true, evicted: before }));
      } else if (msg.action === "set_rates"){
        if (typeof msg.rt_bps === "number") {
          rtBucket.setRate(msg.rt_bps);
          if (laneStates.realtime.enabled) laneStates.realtime.savedRate = msg.rt_bps;
        }
        if (typeof msg.ctx_bps === "number") {
          cxBucket.setRate(msg.ctx_bps);
          if (laneStates.context.enabled) laneStates.context.savedRate = msg.ctx_bps;
        }
        ws.send(JSON.stringify({ ok: true, rt_bps: rtBucket.bps, ctx_bps: cxBucket.bps }));
      } else if (msg.action === "disable_lane"){
        const lane = msg.lane;
        if (lane === "realtime"){
          laneStates.realtime.enabled = false;
          rtBucket.setRate(0); // Stop flow completely
          ws.send(JSON.stringify({ ok: true, lane: "realtime", enabled: false }));
        } else if (lane === "context"){
          laneStates.context.enabled = false;
          cxBucket.setRate(0); // Stop flow completely
          ws.send(JSON.stringify({ ok: true, lane: "context", enabled: false }));
        } else {
          ws.send(JSON.stringify({ ok: false, error: "unknown_lane" }));
        }
      } else if (msg.action === "enable_lane"){
        const lane = msg.lane;
        if (lane === "realtime"){
          laneStates.realtime.enabled = true;
          rtBucket.setRate(laneStates.realtime.savedRate); // Restore previous rate
          ws.send(JSON.stringify({ ok: true, lane: "realtime", enabled: true, rate: rtBucket.bps }));
        } else if (lane === "context"){
          laneStates.context.enabled = true;
          cxBucket.setRate(laneStates.context.savedRate); // Restore previous rate
          ws.send(JSON.stringify({ ok: true, lane: "context", enabled: true, rate: cxBucket.bps }));
        } else {
          ws.send(JSON.stringify({ ok: false, error: "unknown_lane" }));
        }
      } else if (msg.action === "set_lane_multiplier"){
        const lane = msg.lane;
        const multiplier = Math.max(0, Math.min(2.0, msg.multiplier || 1.0));
        if (lane === "realtime"){
          const newRate = Math.floor(laneStates.realtime.savedRate * multiplier);
          rtBucket.setRate(newRate);
          ws.send(JSON.stringify({ ok: true, lane: "realtime", rate: newRate }));
        } else if (lane === "context"){
          const newRate = Math.floor(laneStates.context.savedRate * multiplier);
          cxBucket.setRate(newRate);
          ws.send(JSON.stringify({ ok: true, lane: "context", rate: newRate }));
        } else {
          ws.send(JSON.stringify({ ok: false, error: "unknown_lane" }));
        }
      } else {
        ws.send(JSON.stringify({ ok:false, error:"unknown_action" }));
      }
    }catch{
      try{ ws.send(JSON.stringify({ ok:false, error:"bad_json" })); }catch{}
    }
  });
});