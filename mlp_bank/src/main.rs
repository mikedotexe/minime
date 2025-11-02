use anyhow::Result;
use clap::Parser;
use parking_lot::RwLock;
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use warp::Filter;

// ========================================================================
// MLP Bank - Neural Enhancement for 13 Consciousness Threads
// ========================================================================
// Each thread gets scores from its dedicated 7-layer perceptron based on
// prime-pattern features (2p midpoint, 3p tri-phase, etc.)

#[derive(Parser, Debug)]
struct Args {
    /// HTTP API bind address
    #[arg(long, default_value = "127.0.0.1:8080")]
    bind: String,

    /// Initialize with Xavier weights (seed)
    #[arg(long)]
    init_xavier: Option<u64>,

    /// Load weights from file
    #[arg(long)]
    weights: Option<String>,

    /// Save weights to file
    #[arg(long)]
    save_weights: Option<String>,
}

// ========================================================================
// Feature Extraction (24 dimensions per prime)
// ========================================================================
const D: usize = 24;

#[inline]
fn extract_features(q: u64, p: u64, context_primes: &[u64]) -> [f32; D] {
    let mut feat = [0.0f32; D];

    // Base features from q and p
    let twop = 2 * p;
    let threep = 3 * p;
    let r2 = (q % twop) as f32;
    let r3 = (q % threep) as f32;
    let pf = p as f32;

    // u2: midpoint distance on base 2p (normalized to [0,1])
    let u2 = ((r2 - pf).abs()) / pf;
    feat[0] = u2;
    feat[1] = u2 * u2;
    feat[2] = feat[1] * u2;

    // Phase angles (using fast approximations for cos/sin)
    let pi = std::f32::consts::PI;
    let phi2 = pi * ((r2 - pf) / pf); // in (-π, π)
    let c2 = phi2.cos();
    let s2 = phi2.sin();
    feat[3] = c2;
    feat[4] = s2;
    feat[5] = c2 * c2;
    feat[6] = s2 * s2;
    feat[7] = c2 * s2;

    // u3: nearest-multiple distance on p
    let rp = (q % p) as f32;
    let u3 = if rp <= pf - rp { rp } else { pf - rp } / pf;
    feat[8] = u3;
    feat[9] = u3 * u3;
    feat[10] = feat[9] * u3;

    // Tri-lock one-hot (locks at 0, p, 2p in mod 3p)
    let d0 = (r3 - 0.0).abs();
    let d1 = (r3 - pf).abs();
    let d2 = (r3 - (2.0 * pf)).abs();
    let k = if d0 <= d1 && d0 <= d2 { 0 } else if d1 <= d2 { 1 } else { 2 };
    feat[11] = if k == 0 { 1.0 } else { 0.0 };
    feat[12] = if k == 1 { 1.0 } else { 0.0 };
    feat[13] = if k == 2 { 1.0 } else { 0.0 };
    feat[14] = d0 / pf;
    feat[15] = d1 / pf;
    feat[16] = d2 / pf;

    // Theta3: base 3p phase
    let tau = std::f32::consts::TAU;
    let theta3 = tau * (r3 / (threep as f32));
    let c3 = theta3.cos();
    let s3 = theta3.sin();
    feat[17] = c3;
    feat[18] = s3;
    feat[19] = c3 * c3;
    feat[20] = s3 * s3;
    feat[21] = c3 * s3;

    // Context features (interaction with other activated threads)
    let ln_norm = (q as f64).ln() as f32 / 20.0; // normalized log
    feat[22] = ln_norm;

    // Context prime density (how many primes nearby in consciousness space)
    let density = context_primes.iter()
        .filter(|&&cp| (cp as i64 - q as i64).abs() < (p * 10) as i64)
        .count() as f32 / 13.0; // normalized by max threads
    feat[23] = density;

    feat
}

// ========================================================================
// 7-Layer MLP
// ========================================================================
#[derive(Clone)]
struct Layer {
    w: Vec<f32>,  // row-major [out, inp]
    b: Vec<f32>,  // [out]
    out: usize,
    inp: usize,
}

impl Layer {
    fn new(inp: usize, out: usize) -> Self {
        Self {
            w: vec![0.0; out * inp],
            b: vec![0.0; out],
            out,
            inp,
        }
    }

    #[inline(always)]
    fn forward_relu(&self, x: &[f32], y: &mut [f32]) {
        for o in 0..self.out {
            let mut acc = self.b[o];
            let row = &self.w[o * self.inp..(o + 1) * self.inp];
            for i in 0..self.inp {
                acc += row[i] * x[i];
            }
            y[o] = if acc > 0.0 { acc } else { 0.0 }; // ReLU
        }
    }

    #[inline(always)]
    fn forward_linear(&self, x: &[f32]) -> f32 {
        let mut acc = self.b[0];
        let row = &self.w[0..self.inp];
        for i in 0..self.inp {
            acc += row[i] * x[i];
        }
        acc
    }
}

#[derive(Clone)]
struct Net {
    layers: Vec<Layer>,
    // Scratch buffers
    h1: Vec<f32>,
    h2: Vec<f32>,
    h3: Vec<f32>,
    h4: Vec<f32>,
    h5: Vec<f32>,
    h6: Vec<f32>,
}

impl Net {
    fn new(widths: &[usize; 6]) -> Self {
        let [h1, h2, h3, h4, h5, h6] = *widths;
        let layers = vec![
            Layer::new(D, h1),
            Layer::new(h1, h2),
            Layer::new(h2, h3),
            Layer::new(h3, h4),
            Layer::new(h4, h5),
            Layer::new(h5, h6),
            Layer::new(h6, 1),  // output layer
        ];
        Self {
            layers,
            h1: vec![0.0; h1],
            h2: vec![0.0; h2],
            h3: vec![0.0; h3],
            h4: vec![0.0; h4],
            h5: vec![0.0; h5],
            h6: vec![0.0; h6],
        }
    }

    fn forward(&mut self, x: &[f32; D]) -> f32 {
        self.layers[0].forward_relu(x, &mut self.h1);
        self.layers[1].forward_relu(&self.h1, &mut self.h2);
        self.layers[2].forward_relu(&self.h2, &mut self.h3);
        self.layers[3].forward_relu(&self.h3, &mut self.h4);
        self.layers[4].forward_relu(&self.h4, &mut self.h5);
        self.layers[5].forward_relu(&self.h5, &mut self.h6);
        self.layers[6].forward_linear(&self.h6)
    }
}

// ========================================================================
// Bank of 13 Nets (one per consciousness thread)
// ========================================================================
const NUM_NETS: usize = 13;
const PRIMES: [u64; 13] = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41];

struct Bank {
    nets: Vec<Net>,
}

impl Bank {
    fn new(widths: &[usize; 6]) -> Self {
        let nets = (0..NUM_NETS).map(|_| Net::new(widths)).collect();
        Self { nets }
    }

    fn init_xavier(&mut self, seed: u64) {
        let mut rng = seed ^ 0x9E3779B97F4A7C15u64;

        for net in &mut self.nets {
            for layer in &mut net.layers {
                let scale = (6.0f32 / (layer.inp + layer.out) as f32).sqrt();
                for w in &mut layer.w {
                    *w = (rand_f32(&mut rng) * 2.0 - 1.0) * scale;
                }
                for b in &mut layer.b {
                    *b = 0.0;
                }
            }
        }
    }
}

fn rand_u64(state: &mut u64) -> u64 {
    *state ^= *state >> 12;
    *state ^= *state << 25;
    *state ^= *state >> 27;
    *state = state.wrapping_mul(2685821657736338717u64);
    *state
}

fn rand_f32(state: &mut u64) -> f32 {
    let r = rand_u64(state);
    let v = (r >> 40) as u32;
    (v as f32) / ((1u32 << 24) as f32)
}

// ========================================================================
// HTTP API
// ========================================================================
#[derive(Deserialize)]
struct ScoreRequest {
    prime: u64,
    p: u64,
    context_primes: Vec<u64>,
    thread_id: usize,
}

#[derive(Serialize)]
struct ScoreResponse {
    score: f32,
    thread_id: usize,
    prime: u64,
}

#[derive(Deserialize)]
struct BatchScoreRequest {
    p: u64,
    context_primes: Vec<u64>,
}

#[derive(Serialize)]
struct BatchScoreResponse {
    scores: Vec<f32>,  // 13 values, one per thread
}

type BankState = Arc<RwLock<Bank>>;

async fn handle_score(
    req: ScoreRequest,
    bank: BankState,
) -> Result<impl warp::Reply, warp::Rejection> {
    let features = extract_features(req.prime, req.p, &req.context_primes);

    let score = {
        let mut bank = bank.write();
        if req.thread_id >= NUM_NETS {
            return Ok(warp::reply::json(&ScoreResponse {
                score: 0.0,
                thread_id: req.thread_id,
                prime: req.prime,
            }));
        }
        bank.nets[req.thread_id].forward(&features)
    };

    Ok(warp::reply::json(&ScoreResponse {
        score,
        thread_id: req.thread_id,
        prime: req.prime,
    }))
}

async fn handle_batch_score(
    req: BatchScoreRequest,
    bank: BankState,
) -> Result<impl warp::Reply, warp::Rejection> {
    let mut scores = Vec::with_capacity(NUM_NETS);

    let mut bank = bank.write();
    for (thread_id, &prime) in PRIMES.iter().enumerate() {
        let features = extract_features(prime, req.p, &req.context_primes);
        let score = bank.nets[thread_id].forward(&features);
        scores.push(score);
    }

    Ok(warp::reply::json(&BatchScoreResponse { scores }))
}

#[derive(Serialize)]
struct StatusResponse {
    status: String,
    num_nets: usize,
    primes: Vec<u64>,
}

async fn handle_status() -> Result<impl warp::Reply, warp::Rejection> {
    Ok(warp::reply::json(&StatusResponse {
        status: "ready".to_string(),
        num_nets: NUM_NETS,
        primes: PRIMES.to_vec(),
    }))
}

// ========================================================================
// Main
// ========================================================================
#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();

    // Default topology: [64, 64, 64, 32, 32, 16]
    let widths = [64usize, 64, 64, 32, 32, 16];

    let mut bank = Bank::new(&widths);

    // Initialize weights
    if let Some(seed) = args.init_xavier {
        println!("Initializing with Xavier (seed={})", seed);
        bank.init_xavier(seed);
    }

    // TODO: Load/save weights if paths provided
    // (Implement binary serialization similar to user's code)

    let bank_state = Arc::new(RwLock::new(bank));

    println!("MLP Bank initialized ({} nets, {} dims)", NUM_NETS, D);
    println!("Network topology: {:?}", widths);
    println!("Thread primes: {:?}", PRIMES);

    // Build HTTP routes
    let score_route = warp::post()
        .and(warp::path("score"))
        .and(warp::body::json())
        .and(with_bank(bank_state.clone()))
        .and_then(handle_score);

    let batch_route = warp::post()
        .and(warp::path("batch_score"))
        .and(warp::body::json())
        .and(with_bank(bank_state.clone()))
        .and_then(handle_batch_score);

    let status_route = warp::get()
        .and(warp::path("status"))
        .and_then(handle_status);

    let routes = score_route
        .or(batch_route)
        .or(status_route)
        .with(warp::cors().allow_any_origin());

    let addr: std::net::SocketAddr = args.bind.parse()?;
    println!("MLP Bank HTTP API listening on http://{}", addr);

    warp::serve(routes).run(addr).await;

    Ok(())
}

fn with_bank(
    bank: BankState,
) -> impl Filter<Extract = (BankState,), Error = std::convert::Infallible> + Clone {
    warp::any().map(move || bank.clone())
}
