#!/usr/bin/env node
import fs from 'node:fs';
const csv = fs.readFileSync(new URL('../results.csv', import.meta.url)).toString().trim().split('\n');
const rows = csv.slice(1).map(l=>l.split(',')).map(r=>({
  algo:r[0], n:+r[1], k:+r[2], m:+r[3], iters:+r[4], matvecs:+r[5],
  ms:+r[6], ips:+r[7], mps:+r[8], lambda:+r[9], resid:+r[10], seed:+r[11]
}));
const groupBy = (k, arr) => arr.reduce((m,x)=>((m[x[k]]??=[]).push(x),m),{});
const byAlgo = groupBy('algo', rows);
for (const [alg, rs] of Object.entries(byAlgo)) {
  const avg = f => rs.reduce((s,x)=>s+f(x),0)/rs.length;
  const p = (name,val)=>console.log(`${alg.padEnd(7)} ${name}: ${val}`);
  p('count', rs.length);
  p('avg it/s', avg(x=>x.ips).toFixed(2));
  p('avg mv/s', avg(x=>x.mps).toFixed(2));
  p('avg resid', avg(x=>x.resid).toExponential(3));
  p('avg λ', avg(x=>x.lambda).toFixed(3));
}
