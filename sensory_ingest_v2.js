#!/usr/bin/env node
"use strict";

const { spawn } = require("child_process");
const WebSocket = require("ws");

/*
Env:
  VIDEO_IN          default "-f lavfi -i testsrc=size=320x240:rate=1"
  AUDIO_IN          default "-f lavfi -i sine=frequency=220:sample_rate=16000"
  VIDEO_FPS         default 1
  VIDEO_SIZE        default "64x64" (SRHT expects power of two; 64 ok)
  AUDIO_HZ          default 16000
  HOP_MS            default 125
  NOVELTY_T         default 0.10
  KEEPALIVE_MS      default 2000
  BASE_BPS          default 32768     (pre-gate)
  BURST_BYTES       default 65536
  TARGET_PCT        default 0.80
  HYSTERESIS        default 0.10
  GATE_SOURCE_WS    default "ws://127.0.0.1:7878"  (engine telemetry)
  GATE_EXP          default 1.5
  SRHT_M            default 128       (output dims)
  SRHT_SEED         default "42"      (Rademacher signs & permutation)
  OUT_MODE          "stdout" or "ws"  default "stdout"
  OUT_WS            e.g. "ws://127.0.0.1:7879" when OUT_MODE="ws"
*/

const VIDEO_IN = process.env.VIDEO_IN || "-f lavfi -i testsrc=size=320x240:rate=1";
const AUDIO_IN = process.env.AUDIO_IN || "-f lavfi -i sine=frequency=220:sample_rate=16000";
const VIDEO_FPS = +(process.env.VIDEO_FPS || 1);
const VIDEO_SIZE = (process.env.VIDEO_SIZE || "64x64").split("x").map(Number);
const AUDIO_HZ = +(process.env.AUDIO_HZ || 16000);
const HOP_MS = +(process.env.HOP_MS || 125);
const NOVELTY_T = +(process.env.NOVELTY_T || 0.10);
const KEEPALIVE_MS = +(process.env.KEEPALIVE_MS || 2000);
const BASE_BPS = +(process.env.BASE_BPS || 32768);
const BURST_BYTES = +(process.env.BURST_BYTES || 65536);
const TARGET_PCT = +(process.env.TARGET_PCT || 0.80);
const HYSTERESIS = +(process.env.HYSTERESIS || 0.10);
const GATE_SOURCE_WS = process.env.GATE_SOURCE_WS || "ws://127.0.0.1:7878";
const GATE_EXP = +(process.env.GATE_EXP || 1.5);
const SRHT_M = +(process.env.SRHT_M || 128);
const SRHT_SEED = process.env.SRHT_SEED || "42";
const OUT_MODE = process.env.OUT_MODE || "stdout";
const OUT_WS = process.env.OUT_WS || "ws://127.0.0.1:7879";

function splitArgs(s){ return s.trim().length? s.match(/(?:[^\s"]+|"[^"]*")+/g).map(t=>t.replace(/^"(.*)"$/,"$1")):[]; }

// Token bucket
class Bucket {
  constructor(bps, burst){ this.base_bps=bps; this.bps=bps; this.burst=burst; this.tok=burst; this.last=Date.now(); }
  setRate(r){ this.bps = Math.max(64, r); } // floor
  refill(){ const t=Date.now(); const dt=(t-this.last)/1000; this.last=t; this.tok=Math.min(this.burst, this.tok+dt*this.bps); }
  take(n){ this.refill(); if(this.tok>=n){ this.tok-=n; return true; } return false; }
  util(){ return 1 - Math.min(1, this.tok/this.burst); }
  effBps(){ return this.bps; }
}
const bucket = new Bucket(BASE_BPS, BURST_BYTES);

// Output wire (stdout or single WS)
let wsOut = null;
let outConnected = false;
let outBuf = [];
let awaitDrain = false;
const PING_MS = 15000;

function connectOutWS(){
  if (OUT_MODE !== "ws") return;
  wsOut = new WebSocket(OUT_WS, { perMessageDeflate: false });
  wsOut.on("open", ()=>{ outConnected = true; });
  wsOut.on("close", ()=>{ outConnected = false; setTimeout(connectOutWS, 500+Math.random()*500); });
  wsOut.on("error", ()=>{ try{ wsOut.close(); }catch{} });
  setInterval(()=>{ if(outConnected) try{ wsOut.ping(); }catch{} }, PING_MS);
}
if (OUT_MODE === "ws") connectOutWS();

function outWrite(s){
  const bufLen = Buffer.byteLength(s);
  const upper = TARGET_PCT + HYSTERESIS*0.5;
  if (bucket.util() >= upper) return;
  if (!bucket.take(bufLen)) return;
  if (OUT_MODE === "stdout"){
    if (!awaitDrain){
      if (!process.stdout.write(s)) awaitDrain = true;
    }
  } else {
    if (outConnected && wsOut && wsOut.readyState === wsOut.OPEN && wsOut.bufferedAmount < 2*BURST_BYTES){
      try { wsOut.send(s); } catch {}
    }
  }
}
process.stdout.on("drain", ()=>{ awaitDrain=false; });

// Control subscriber (parse fill/gate from engine logs or JSON)
let gate = 1.0;
let lastFill = null;

function applyGate(newGate){
  gate = Math.max(0, Math.min(1, newGate));
  const scaled = BASE_BPS * Math.max(0.05, Math.pow(gate, GATE_EXP));
  bucket.setRate(scaled);
}
applyGate(0.7); // conservative start

function connectControl(){
  const ws = new WebSocket(GATE_SOURCE_WS, { perMessageDeflate: false });
  ws.on("open", ()=>{ /* noop */ });
  ws.on("message", (data)=>{
    const txt = data.toString();
    // Try JSON first
    let g=null, f=null, df=null;
    try {
      const j = JSON.parse(txt);
      if (typeof j.gate === "number") g = j.gate;
      if (typeof j.fill === "number") f = j.fill;
      if (typeof j.dfill_dt === "number") df = j.dfill_dt;
    } catch {
      // Parse log line like: homeostat,...,fill=25.47%,...,gate=1.000,...
      const mFill = txt.match(/fill\s*=\s*([0-9.]+)%/i);
      const mGate = txt.match(/gate\s*=\s*([0-9.]+)/i);
      if (mFill) f = parseFloat(mFill[1])/100.0;
      if (mGate) g = parseFloat(mGate[1]);
    }
    if (f!=null) lastFill = f;
    if (g!=null){
      // When fill > target, bias gate downward; when below, allow reported gate
      const target = 0.55;
      let adj = g;
      if (lastFill!=null && lastFill > target){
        const r = target / Math.max(1e-6, lastFill);
        adj = Math.min(adj, Math.max(0.05, Math.pow(r, 1.5)));
      }
      applyGate(adj);
    }
  });
  ws.on("close", ()=> setTimeout(connectControl, 500+Math.random()*1500));
  ws.on("error", ()=> { try{ ws.close(); }catch{} });
}
connectControl();

// FFT (real) magnitude for audio, small
function fftMagReal(signal){
  const N = signal.length;
  const re = new Float64Array(N);
  const im = new Float64Array(N);
  for (let i=0;i<N;i++){ re[i]=signal[i]; im[i]=0; }
  for (let i=1,j=0;i<N;i++){
    let bit=N>>1;
    for(; j & bit; bit>>=1) j&=~bit;
    j|=bit;
    if (i<j){ let tr=re[i]; re[i]=re[j]; re[j]=tr; tr=im[i]; im[i]=im[j]; im[j]=tr; }
  }
  for (let len=2; len<=N; len<<=1){
    const ang = -2*Math.PI/len;
    const cw = Math.cos(ang), sw=Math.sin(ang);
    for (let i=0;i<N;i+=len){
      let wr=1, wi=0;
      for (let j=0;j<(len>>1);j++){
        const u_r=re[i+j], u_i=im[i+j];
        const v_r=re[i+j+(len>>1)]*wr - im[i+j+(len>>1)]*wi;
        const v_i=re[i+j+(len>>1)]*wi + im[i+j+(len>>1)]*wr;
        re[i+j]=u_r+v_r; im[i+j]=u_i+v_i;
        re[i+j+(len>>1)]=u_r-v_r; im[i+j+(len>>1)]=u_i-v_i;
        const nwr = wr*cw - wi*sw;
        const nwi = wr*sw + wi*cw;
        wr=nwr; wi=nwi;
      }
    }
  }
  const mags = new Float64Array(N/2);
  for (let k=0;k<N/2;k++){ mags[k]=Math.hypot(re[k], im[k]); }
  return mags;
}

// SRHT (Subsampled Randomized Hadamard Transform)
function rng(seed){
  let h = 2166136261 >>> 0;
  for (let i=0;i<seed.length;i++){ h ^= seed.charCodeAt(i); h = Math.imul(h, 16777619); }
  return ()=> (h = (h+0x6D2B79F5)>>>0, h/0x100000000);
}
function fwht(a){ // in-place FWHT, len power-of-two
  for (let step=1; step<a.length; step<<=1){
    for (let i=0; i<a.length; i+= (step<<1)){
      for (let j=0;j<step;j++){
        const u=a[i+j], v=a[i+j+step];
        a[i+j] = u+v;
        a[i+j+step] = u-v;
      }
    }
  }
}
function srht64x64_to_m(gray64x64_uint8, m, seed){
  const w=64, h=64, n=w*h; // 4096
  const v = new Float64Array(n);
  for (let i=0;i<n;i++) v[i] = gray64x64_uint8[i]/255;
  const R = rng(seed);
  // Rademacher signs
  for (let i=0;i<n;i++){ const s = R()<0.5 ? -1 : 1; v[i]*=s; }
  // Hadamard
  fwht(v);
  // Permutation (Fisher–Yates)
  const idx = new Uint32Array(n);
  for (let i=0;i<n;i++) idx[i]=i;
  for (let i=n-1;i>0;i--){
    const j = Math.floor(R()*(i+1));
    const t=idx[i]; idx[i]=idx[j]; idx[j]=t;
  }
  const out = new Float32Array(m);
  const scale = Math.sqrt(n/m);
  for (let i=0;i<m;i++) out[i] = v[idx[i]]*scale;
  return out;
}

// Video
const vw = VIDEO_SIZE[0]|0, vh = VIDEO_SIZE[1]|0, vpx = vw*vh;
let prevFrame = null, motionEMA = 0;
function startVideo(){
  const args = [].concat(
    ["-hide_banner","-loglevel","error","-nostats"],
    splitArgs(VIDEO_IN),
    ["-vf", `scale=${vw}:${vh},fps=${VIDEO_FPS},format=gray`, "-pix_fmt","gray","-f","rawvideo","pipe:1"]
  );
  const ff = spawn("ffmpeg", args, { stdio: ["ignore","pipe","inherit"] });
  let frameBuf = Buffer.alloc(0);
  ff.stdout.on("data", (chunk)=>{
    frameBuf = Buffer.concat([frameBuf, chunk]);
    while (frameBuf.length >= vpx){
      const f = frameBuf.subarray(0, vpx);
      frameBuf = frameBuf.subarray(vpx);
      processVideoFrame(f);
    }
  });
}

function processVideoFrame(buf){
  const now = Date.now();
  const gray = new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength);
  let mean=0; for (let i=0;i<vpx;i++) mean += gray[i];
  mean/=vpx;
  let varsum=0; for (let i=0;i<vpx;i++){ const d=gray[i]-mean; varsum+=d*d; }
  const stdev = Math.sqrt(varsum/vpx);
  let motion = 0;
  if (prevFrame){ for (let i=0;i<vpx;i++) motion += Math.abs(gray[i]-prevFrame[i]); motion/=(255*vpx); }
  prevFrame = new Uint8Array(gray);
  motionEMA = 0.8*motionEMA + 0.2*motion;
  const brightness = mean/255;
  const contrast = stdev/128;

  // SRHT footprint for context lane
  const footprint = (vw===64 && vh===64) ? Array.from(srht64x64_to_m(gray, SRHT_M, SRHT_SEED)) : null;

  const novelty = 0.6*motion + 0.2*Math.abs(contrast-0.25) + 0.2*Math.abs(brightness-0.5);
  emitSensoryPacket(now, { video:{ brightness, contrast, motion, motionEMA } }, footprint, novelty);
}

// Audio
const hop = Math.max(16, Math.floor((HOP_MS/1000)*AUDIO_HZ));
const win = 512;
let audioBuf = new Float32Array(0);
let rmsEMA=0, centroidEMA=0;
function startAudio(){
  const args = [].concat(
    ["-hide_banner","-loglevel","error","-nostats"],
    splitArgs(AUDIO_IN),
    ["-ac","1","-ar", String(AUDIO_HZ), "-f","f32le","pipe:1"]
  );
  const ff = spawn("ffmpeg", args, { stdio: ["ignore","pipe","inherit"] });
  let chunkBuf = Buffer.alloc(0);
  ff.stdout.on("data", (chunk)=>{
    chunkBuf = Buffer.concat([chunkBuf, chunk]);
    const samples = Math.floor(chunkBuf.length/4);
    if (samples>0){
      const view = new Float32Array(chunkBuf.buffer, chunkBuf.byteOffset, samples);
      const merged = new Float32Array(audioBuf.length + view.length);
      merged.set(audioBuf, 0); merged.set(view, audioBuf.length);
      audioBuf = merged;
      chunkBuf = chunkBuf.subarray(samples*4);
      processAudio();
    }
  });
}
function processAudio(){
  const now = Date.now();
  while (audioBuf.length >= win){
    const frame = audioBuf.subarray(0, win);
    audioBuf = audioBuf.subarray(Math.min(hop, audioBuf.length));
    const w = new Float32Array(win);
    for (let i=0;i<win;i++) w[i]=0.5*(1-Math.cos(2*Math.PI*i/(win-1)));
    const xw = new Float32Array(win);
    for (let i=0;i<win;i++) xw[i]=frame[i]*w[i];
    const mags = fftMagReal(xw);
    let rms=0; for (let i=0;i<win;i++) rms += frame[i]*frame[i]; rms=Math.sqrt(rms/win);
    let sum=0,wsum=0;
    for (let k=1;k<mags.length;k++){ const f=(k*AUDIO_HZ)/win; const m=mags[k]; sum+=m; wsum+=m*f; }
    const centroid = sum>0? (wsum/sum):0;
    rmsEMA=0.8*rmsEMA+0.2*rms; centroidEMA=0.8*centroidEMA+0.2*centroid;
    const anovel = 0.6*Math.tanh(8*Math.abs(rms-rmsEMA)) + 0.4*Math.tanh(Math.abs(centroid-centroidEMA)/500);
    emitSensoryPacket(now, { audio:{ rms, centroid } }, null, anovel);
  }
}

// Fusion & emission
let lastEmit = 0;
let lastRealtime = {};
function emitSensoryPacket(now, update, footprintOrNull, novelty){
  const need = now - lastEmit >= KEEPALIVE_MS;
  const high = novelty >= NOVELTY_T;
  if (!(need || high)) return;

  // realtime lane (low‑dim)
  lastRealtime = { ...lastRealtime, ...update };
  const rt = { t: now, lane: "realtime", ...lastRealtime };
  outWrite(JSON.stringify(rt)+"\n");

  // context lane (SRHT footprint) — emit rarely; defer heavy items if budget tight
  if (footprintOrNull && bucket.util() < (TARGET_PCT - HYSTERESIS*0.5)){
    const cx = { t: now, lane: "context", footprint: { srht_m: SRHT_M, dims: footprintOrNull } };
    outWrite(JSON.stringify(cx)+"\n");
  }

  lastEmit = now;
}

// Start
startVideo();
startAudio();
setInterval(()=>{
  const util = bucket.util();
  const pkt = { t: Date.now(), lane: "status", util, eff_bps: bucket.effBps(), gate };
  const lower = Math.max(0, TARGET_PCT - HYSTERESIS*0.5);
  if (util < lower) outWrite(JSON.stringify(pkt)+"\n");
}, 1000);