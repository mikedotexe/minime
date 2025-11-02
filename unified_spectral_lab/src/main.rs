use anyhow::Result;
use fastrand::Rng;
use metal::*;
use serde::Serialize;
use std::{env, mem, slice, time::Instant};

#[derive(Clone, Copy, PartialEq)]
enum Algo { Power, Block, Cheby }

#[derive(Serialize)]
struct Report {
    algo: String,
    n: usize,
    k: usize,
    m_cheby: usize,
    iters: usize,
    matvecs: usize,
    ms_total: f64,
    iters_per_s: f64,
    matvecs_per_s: f64,
    lambda_rayleigh: f64,
    residual: f64,
    seed: u64,
}

fn parse_env<T: std::str::FromStr>(key: &str, default: T) -> T {
    env::var(key).ok().and_then(|s| s.parse::<T>().ok()).unwrap_or(default)
}

fn main() -> Result<()> {
    let n      = parse_env("N", 1024usize);
    let iters  = parse_env("ITERS", 12usize);
    let k      = parse_env("K", 4usize).min(16);
    let m_cheb = parse_env("CHEBY_M", 3usize); // degree for Chebyshev
    let algo_s = env::var("ALGO").unwrap_or_else(|_| "block".into());
    let seed   = parse_env("SEED", 0xC0FFEE_u64);
    let algo = match algo_s.as_str() {
        "power" => Algo::Power, "cheby" => Algo::Cheby, _ => Algo::Block
    };

    // --- Metal setup
    let dev = Device::system_default().expect("no Metal");
    let q   = dev.new_command_queue();
    let lib = dev.new_library_with_source(include_str!("../shaders/spectral.metal"), &CompileOptions::new())
        .map_err(|e| anyhow::anyhow!("MSL: {e}"))?;
    let f_mv  = lib.get_function("matvec_tiled", None).unwrap();
    let pso_mv= dev.new_compute_pipeline_state_with_function(&f_mv)
        .map_err(|e| anyhow::anyhow!("PSO mv: {e}"))?;
    let f_bmv = lib.get_function("block_matvec_tiled", None).unwrap();
    let pso_bm= dev.new_compute_pipeline_state_with_function(&f_bmv)
        .map_err(|e| anyhow::anyhow!("PSO block: {e}"))?;

    // --- Buffers (Shared = zero-copy)
    let bytes_m = (n*n*mem::size_of::<f32>()) as u64;
    let bytes_v = (n*mem::size_of::<f32>()) as u64;
    let bytes_xk= (n*k*mem::size_of::<f32>()) as u64;

    let m_buf = dev.new_buffer(bytes_m, MTLResourceOptions::StorageModeShared);
    let x_buf = dev.new_buffer(bytes_v, MTLResourceOptions::StorageModeShared);
    let y_buf = dev.new_buffer(bytes_v, MTLResourceOptions::StorageModeShared);
    let xk_buf= dev.new_buffer(bytes_xk, MTLResourceOptions::StorageModeShared);
    let yk_buf= dev.new_buffer(bytes_xk, MTLResourceOptions::StorageModeShared);
    let n_buf = dev.new_buffer(mem::size_of::<u32>() as u64, MTLResourceOptions::StorageModeShared);
    let k_buf = dev.new_buffer(mem::size_of::<u32>() as u64, MTLResourceOptions::StorageModeShared);
    unsafe { *(n_buf.contents() as *mut u32) = n as u32; *(k_buf.contents() as *mut u32) = k as u32; }

    // --- Initialize A (SPD-ish) and initial vectors
    let mut rng = Rng::with_seed(seed);
    {
        let a = unsafe { slice::from_raw_parts_mut(m_buf.contents() as *mut f32, n*n) };
        for i in 0..n { for j in 0..n {
            let base = if i==j { 1.5 } else { 0.15 };
            a[i*n + j] = (rng.f32()-0.5)*base;
        }}
        // Diagonal dominance to ensure nice behavior
        for i in 0..n { a[i*n+i] += n as f32; }
    }
    {
        let x = unsafe { slice::from_raw_parts_mut(x_buf.contents() as *mut f32, n) };
        for v in x.iter_mut() { *v = rng.f32() - 0.5; }
        l2_normalize(x);
    }
    {
        let xk = unsafe { slice::from_raw_parts_mut(xk_buf.contents() as *mut f32, n*k) };
        for i in 0..n*k { xk[i] = rng.f32() - 0.5; }
        gs_orthonormalize_colmajor(xk, n, k);
    }

    let grid = MTLSize::new(n as u64, 1, 1);
    let tg   = MTLSize::new(256u64.min(n as u64), 1, 1);

    let t0 = Instant::now();
    let mut matvecs = 0usize;

    match algo {
        Algo::Power => {
            for _ in 0..iters {
                matvec(&q, &pso_mv, &m_buf, &x_buf, &y_buf, &n_buf, grid, tg);
                matvecs += 1;
                // CPU normalize: y -> x
                let y = unsafe { slice::from_raw_parts(y_buf.contents() as *const f32, n) };
                let x = unsafe { slice::from_raw_parts_mut(x_buf.contents() as *mut f32, n) };
                x.copy_from_slice(y);
                l2_normalize(x);
            }
        }
        Algo::Cheby => {
            // Simple Chebyshev acceleration: scale A by alpha≈diag_mean to keep eigeninterval near [0,2)
            let a = unsafe { slice::from_raw_parts(m_buf.contents() as *const f32, n*n) };
            let mut dmean = 0.0f64;
            for i in 0..n { dmean += a[i*n+i] as f64; }
            let alpha = (dmean / n as f64) as f32;

            // t0=x, t1 = (A/alpha) x
            let mut t_prev = vec![0.0f32; n];
            let mut t_curr = unsafe { slice::from_raw_parts(x_buf.contents() as *const f32, n) }.to_vec();

            for _ in 0..iters {
                // compute t1
                unsafe { slice::from_raw_parts_mut(x_buf.contents() as *mut f32, n).copy_from_slice(&t_curr); }
                matvec(&q, &pso_mv, &m_buf, &x_buf, &y_buf, &n_buf, grid, tg);
                matvecs += 1;
                let y = unsafe { slice::from_raw_parts(y_buf.contents() as *const f32, n) };
                let mut t1 = y.iter().map(|v| *v / alpha).collect::<Vec<f32>>();

                // Chebyshev recurrence of degree m_cheb
                let mut tm1 = t_prev.clone();      // T_{k-1}
                let mut tk  = t1.clone();          // T_k
                for _deg in 1..m_cheb {
                    // next = 2*(A/alpha)*tk - tm1
                    unsafe { slice::from_raw_parts_mut(x_buf.contents() as *mut f32, n).copy_from_slice(&tk); }
                    matvec(&q, &pso_mv, &m_buf, &x_buf, &y_buf, &n_buf, grid, tg);
                    matvecs += 1;
                    let ay = unsafe { slice::from_raw_parts(y_buf.contents() as *const f32, n) };
                    let next: Vec<f32> = ay.iter().zip(tm1.iter()).map(|(a, b)| 2.0*(*a/alpha) - *b).collect();
                    tm1 = tk;
                    tk  = next;
                }
                // normalize tk and set t_prev,t_curr
                let nrm = (tk.iter().map(|v| (*v as f64)*(*v as f64)).sum::<f64>()).sqrt().max(1e-12) as f32;
                for v in tk.iter_mut() { *v /= nrm; }
                t_prev = t_curr; t_curr = tk;
            }
            // write back to x_buf for residual/λ calc
            unsafe { slice::from_raw_parts_mut(x_buf.contents() as *mut f32, n).copy_from_slice(&t_curr); }
        }
        Algo::Block => {
            for _ in 0..iters {
                block_matvec(&q, &pso_bm, &m_buf, &xk_buf, &yk_buf, &n_buf, &k_buf, grid, tg);
                matvecs += k;
                // CPU Gram–Schmidt on Y -> overwrite X
                let yk = unsafe { slice::from_raw_parts(yk_buf.contents() as *const f32, n*k) };
                let xk = unsafe { slice::from_raw_parts_mut(xk_buf.contents() as *mut f32, n*k) };
                xk.copy_from_slice(yk);
                gs_orthonormalize_colmajor(xk, n, k);
            }
            // collapse to best single vector: use first column of X for residual check
            let xk = unsafe { slice::from_raw_parts(xk_buf.contents() as *const f32, n*k) };
            let x = unsafe { slice::from_raw_parts_mut(x_buf.contents() as *mut f32, n) };
            for i in 0..n { x[i] = xk[i]; }
            l2_normalize(x);
        }
    }

    let ms_total = t0.elapsed().as_secs_f64()*1e3;

    // Residual and Rayleigh λ (CPU check)
    let a  = unsafe { slice::from_raw_parts(m_buf.contents() as *const f32, n*n) };
    let x  = unsafe { slice::from_raw_parts(x_buf.contents() as *const f32, n) };
    let mut ax = vec![0.0f32; n];
    for i in 0..n {
        let row = &a[i*n..(i+1)*n];
        ax[i] = dot(row, x);
    }
    let lam = dot(&ax, x) / dot(x, x).max(1e-12);
    let mut rnum = 0.0f64; let mut rden = 0.0f64;
    for i in 0..n {
        let ri = (ax[i] - lam*x[i]) as f64;
        rnum += ri*ri; rden += (ax[i] as f64)*(ax[i] as f64);
    }
    let residual = (rnum.sqrt() / rden.sqrt().max(1e-12)) as f64;

    let rep = Report {
        algo: match algo { Algo::Power=>"power", Algo::Block=>"block", Algo::Cheby=>"cheby" }.into(),
        n, k, m_cheby: m_cheb, iters, matvecs,
        ms_total,
        iters_per_s: (iters as f64)/(ms_total/1e3),
        matvecs_per_s: (matvecs as f64)/(ms_total/1e3),
        lambda_rayleigh: lam as f64,
        residual,
        seed,
    };
    println!("{}", serde_json::to_string(&rep)?);
    Ok(())
}

fn matvec(q: &CommandQueue, pso: &ComputePipelineState,
          a: &Buffer, x: &Buffer, y: &Buffer, n_buf: &Buffer,
          grid: MTLSize, tg: MTLSize)
{
    let cmd = q.new_command_buffer();
    let enc = cmd.new_compute_command_encoder();
    enc.set_compute_pipeline_state(pso);
    enc.set_buffer(0, Some(a), 0);
    enc.set_buffer(1, Some(x), 0);
    enc.set_buffer(2, Some(y), 0);
    enc.set_buffer(3, Some(n_buf), 0);
    enc.dispatch_thread_groups(grid, tg);
    enc.end_encoding();
    cmd.commit();
    cmd.wait_until_completed();
}

fn block_matvec(q:&CommandQueue, pso:&ComputePipelineState,
                a:&Buffer, xk:&Buffer, yk:&Buffer, n_buf:&Buffer, k_buf:&Buffer,
                grid:MTLSize, tg:MTLSize)
{
    let cmd = q.new_command_buffer();
    let enc = cmd.new_compute_command_encoder();
    enc.set_compute_pipeline_state(pso);
    enc.set_buffer(0, Some(a), 0);
    enc.set_buffer(1, Some(xk), 0);
    enc.set_buffer(2, Some(yk), 0);
    enc.set_buffer(3, Some(n_buf), 0);
    enc.set_buffer(4, Some(k_buf), 0);
    enc.dispatch_thread_groups(grid, tg);
    enc.end_encoding();
    cmd.commit();
    cmd.wait_until_completed();
}

#[inline] fn dot(a:&[f32], b:&[f32])->f32 { a.iter().zip(b).map(|(x,y)| x*y).sum() }

fn l2_normalize(x: &mut [f32]) {
    let nrm = (x.iter().map(|v| (*v as f64)*(*v as f64)).sum::<f64>()).sqrt().max(1e-18) as f32;
    for v in x { *v /= nrm; }
}

// Modified Gram–Schmidt on column-major X (N×K)
fn gs_orthonormalize_colmajor(x: &mut [f32], n: usize, k: usize) {
    for i in 0..k {
        // subtract projections on previous q_j
        for j in 0..i {
            let mut r = 0.0f32;
            for rix in 0..n { r += x[j*n + rix]*x[i*n + rix]; }
            for rix in 0..n { x[i*n + rix] -= r * x[j*n + rix]; }
        }
        // normalize
        let mut nrm2 = 0.0f64;
        for rix in 0..n { nrm2 += (x[i*n + rix] as f64)*(x[i*n + rix] as f64); }
        let nrm = nrm2.sqrt().max(1e-18) as f32;
        for rix in 0..n { x[i*n + rix] /= nrm; }
    }
}
