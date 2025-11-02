use std::env;
use std::io::{Read, Write, BufWriter, stdout};
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex, mpsc};
use std::thread;
use std::time::{Duration, Instant};

/// ---------- Simple helpers ----------
fn parse_u<T: std::str::FromStr>(s: &str, d: T) -> T { s.parse().ok().unwrap_or(d) }
fn clamp01(x: f32) -> f32 { if x < 0.0 { 0.0 } else if x > 1.0 { 1.0 } else { x } }

/// ---------- Video feature extraction ----------
#[derive(Clone, Default)]
struct VideoFeat {
    ts_ms: u128,
    motion: f32,      // 0..1 (avg abs diff / 255)
    mean: f32,        // 0..1 (avg brightness)
    var: f32,         // 0..1 (brightness variance normalized)
    grid16: [f32; 16] // 4x4 grid avg brightness (0..1)
}

/// ---------- Audio feature extraction ----------
#[derive(Clone, Default)]
struct AudioFeat {
    ts_ms: u128,
    rms: f32,          // 0..1 (normalized)
    zcr: f32,          // 0..1 (normalized)
    centroid: f32,     // 0..1 (spectral centroid normalized to Nyquist)
    band_energy: [f32; 8],  // 8 coarse bands, normalized
}

/// ---------- Combined sensory tick ----------
#[derive(Clone, Default)]
struct SensoryTick {
    ts_ms: u128,
    v: VideoFeat,
    a: AudioFeat,
    score: f32,        // gating score 0..1
}

/// ---------- Lightweight 128-pt DFT for audio (real input) ----------
fn dft_128_mag2(x: &[f32]) -> [f32; 65] {
    // N=128, return |X(k)|^2 for k=0..64 (Nyquist)
    // Naive O(NK) is fine here (128*65 ~ 8k mul-adds per frame).
    const N: usize = 128;
    let mut out = [0f32; 65];
    let n = x.len().min(N);
    let pi2 = std::f32::consts::PI * 2.0;
    for k in 0..=64 {
        let mut re = 0f32;
        let mut im = 0f32;
        let ang = -pi2 * (k as f32) / (N as f32);
        let mut t = 0f32;
        for i in 0..n {
            let c = t.cos();
            let s = t.sin();
            re += x[i] * c;
            im += x[i] * s;
            t += ang;
        }
        out[k] = re*re + im*im;
    }
    out
}

/// Build 8 coarse energy bands from a 65-bin (0..Nyq) spectrum.
fn bands8_from_mag2(mag2: &[f32; 65]) -> [f32; 8] {
    // geometric-ish partitions: edges at approx fractions of Nyquist
    // bins: 0..64. We'll ignore DC (0) in band calc and normalize later.
    let edges = [1, 3, 6, 10, 16, 24, 36, 50, 65];
    let mut b = [0f32; 8];
    for bi in 0..8 {
        let lo = edges[bi] as usize;
        let hi = edges[bi+1].min(65) as usize;
        let mut acc = 0f32;
        for k in lo..hi { acc += mag2[k]; }
        b[bi] = acc.max(0.0);
    }
    // normalize to sum 1 (if not zero)
    let sum: f32 = b.iter().sum();
    if sum > 1e-12 {
        for x in &mut b { *x /= sum; }
    }
    b
}

/// ---------- Video reader thread using ffmpeg -> rawvideo gray ----------
fn spawn_ffmpeg_video(
    src: &str, w: usize, h: usize, fps: usize
) -> std::io::Result<std::process::ChildStdout> {
    let args = [
        "-hide_banner", "-loglevel", "error",
        "-i", src,
        "-vf", &format!("scale={}:{}:flags=area,format=gray,fps={}", w, h, fps),
        "-f", "rawvideo",
        "-pix_fmt", "gray",
        "-"
    ];
    let mut child = Command::new("ffmpeg")
        .args(&args)
        .stdout(Stdio::piped())
        .spawn()?;
    Ok(child.stdout.take().unwrap())
}

/// ---------- Audio reader thread using ffmpeg -> f32le mono ----------
fn spawn_ffmpeg_audio(
    src: &str, ar: usize
) -> std::io::Result<std::process::ChildStdout> {
    let args = [
        "-hide_banner", "-loglevel", "error",
        "-i", src,
        "-vn", "-ac", "1",
        "-ar", &format!("{}", ar),
        "-f", "f32le",
        "-"
    ];
    let mut child = Command::new("ffmpeg")
        .args(&args)
        .stdout(Stdio::piped())
        .spawn()?;
    Ok(child.stdout.take().unwrap())
}

/// Compute video features from grayscale frame bytes.
fn video_features_from_frame(
    frame: &[u8], prev: &[u8], w: usize, h: usize, ts_ms: u128
) -> VideoFeat {
    let npix = (w*h) as usize;
    let mut sum = 0f32;
    let mut sum2 = 0f32;
    let mut diff = 0f32;

    // 4x4 grid accumulators
    let mut grid_acc = [0f32; 16];
    let gx = 4; let gy = 4;
    let cx = (w as f32) / gx as f32;
    let cy = (h as f32) / gy as f32;

    for y in 0..h {
        for x in 0..w {
            let i = y*w + x;
            let v = frame[i] as f32;
            sum += v;
            sum2 += v*v;
            let d = (v - prev[i] as f32).abs();
            diff += d;

            let gx_i = ((x as f32) / cx) as usize;
            let gy_i = ((y as f32) / cy) as usize;
            grid_acc[gy_i*gx + gx_i] += v;
        }
    }

    let mean = sum / (npix as f32) / 255.0;
    let var = (sum2 / (npix as f32) - (sum/(npix as f32)).powi(2)) / (255.0*255.0);
    let motion = diff / (255.0 * npix as f32);

    let mut grid16 = [0f32; 16];
    let block = (npix as f32) / 16.0;
    for i in 0..16 {
        grid16[i] = (grid_acc[i] / block) / 255.0;
    }

    VideoFeat { ts_ms, motion: clamp01(motion), mean: clamp01(mean), var: clamp01(var), grid16 }
}

/// Compute audio features on a short frame.
fn audio_features_from_frame(
    x: &[f32], sr: usize, ts_ms: u128
) -> AudioFeat {
    let n = x.len();
    // RMS
    let mut e = 0f32;
    let mut zc = 0u32;
    for i in 0..n {
        e += x[i]*x[i];
        if i+1 < n {
            if (x[i] >= 0.0 && x[i+1] < 0.0) || (x[i] < 0.0 && x[i+1] >= 0.0) {
                zc += 1;
            }
        }
    }
    let rms = (e / (n as f32)).sqrt();

    // DFT 128 (or downsample block if n != 128)
    const NDFT: usize = 128;
    let mut buf = [0f32; NDFT];
    if n >= NDFT {
        buf.copy_from_slice(&x[..NDFT]);
    } else {
        // zero-pad
        for i in 0..n { buf[i] = x[i]; }
        for i in n..NDFT { buf[i] = 0.0; }
    }
    // Hann window (cheap)
    for i in 0..NDFT {
        let w = 0.5 - 0.5 * (2.0*std::f32::consts::PI*(i as f32)/(NDFT as f32)).cos();
        buf[i] *= w as f32;
    }
    let mag2 = dft_128_mag2(&buf);
    let mut sum_mag = 0f32;
    let mut sum_k = 0f32;
    for k in 0..=64 {
        let m = mag2[k];
        sum_mag += m;
        sum_k += (k as f32) * m;
    }
    let centroid_bin = if sum_mag > 1e-12 { sum_k / sum_mag } else { 0.0 };
    let centroid = centroid_bin / 64.0; // 0..1 normalized to Nyquist

    let bands = bands8_from_mag2(&mag2);

    // Normalize RMS roughly: assume [-1,1] PCM from ffmpeg f32le
    // Map to 0..1 via soft knee
    let rms_n = clamp01(rms * 0.8);

    // Normalize ZCR to 0..1 relative to Nyquist crossings
    // Max zero-crossings per sample difference is ~1; per frame ~n/2 in white noise
    let zcr_n = clamp01((zc as f32) / ((n as f32) * 0.5));

    AudioFeat {
        ts_ms, rms: rms_n, zcr: zcr_n, centroid: clamp01(centroid), band_energy: bands
    }
}

/// ---------- Main ----------
fn main() {
    // Args:
    //   --video <path> or --media <path> (used for both)
    //   --audio <path> (optional; default: same as video/media)
    //   --w 160 --h 120 --fps 12 --stride 1
    //   --sr 16000 --aframe 512 --ahop 256
    //   --score-gate 0.15
    //   --tick-ms 80   (output cadence driven by video; audio is fused lazily)
    let args: Vec<String> = env::args().collect();
    if args.len() == 1 {
        eprintln!("Usage: {} (--video V|--media M) [--audio A] [--w 160 --h 120 --fps 12 --stride 1] [--sr 16000 --aframe 512 --ahop 256] [--score-gate 0.15] [--tick-ms 80]", args[0]);
        std::process::exit(1);
    }
    let mut video = None::<String>;
    let mut audio = None::<String>;
    let mut w = 160usize; let mut h = 120usize; let mut fps = 12usize; let mut stride = 1usize;
    let mut sr = 16000usize; let mut aframe = 512usize; let mut ahop = 256usize;
    let mut score_gate = 0.15f32;
    let mut tick_ms = 80u64;

    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--video" => { i+=1; video = Some(args[i].clone()); }
            "--media" => { i+=1; let m = args[i].clone(); video = Some(m.clone()); audio = Some(m); }
            "--audio" => { i+=1; audio = Some(args[i].clone()); }
            "--w" => { i+=1; w = parse_u(&args[i], w); }
            "--h" => { i+=1; h = parse_u(&args[i], h); }
            "--fps" => { i+=1; fps = parse_u(&args[i], fps); }
            "--stride" => { i+=1; stride = parse_u(&args[i], stride); }
            "--sr" => { i+=1; sr = parse_u(&args[i], sr); }
            "--aframe" => { i+=1; aframe = parse_u(&args[i], aframe); }
            "--ahop" => { i+=1; ahop = parse_u(&args[i], ahop); }
            "--score-gate" => { i+=1; score_gate = parse_u(&args[i], score_gate); }
            "--tick-ms" => { i+=1; tick_ms = parse_u(&args[i], tick_ms); }
            _ => {}
        }
        i += 1;
    }
    let vsrc = video.expect("need --video or --media");
    let asrc = audio.unwrap_or_else(|| vsrc.clone());

    // Spawn ffmpeg readers
    let vout = spawn_ffmpeg_video(&vsrc, w, h, fps).expect("spawn ffmpeg video");
    let aout = spawn_ffmpeg_audio(&asrc, sr).expect("spawn ffmpeg audio");

    // Channels
    let (tx_v, rx_v) = mpsc::sync_channel::<VideoFeat>(32);
    let (tx_a, rx_a) = mpsc::sync_channel::<AudioFeat>(64);

    // --- Video thread ---
    let vh = thread::spawn(move || {
        let frame_bytes = w * h;
        let mut rdr = std::io::BufReader::new(vout);
        let mut prev = vec![0u8; frame_bytes];
        let mut curr = vec![0u8; frame_bytes];
        let mut frame_idx: usize = 0;
        let t0 = Instant::now();

        // Initialize prev by reading one frame (if available)
        if rdr.read_exact(&mut prev).is_err() {
            // no frames
            return;
        }
        // Process loop
        loop {
            if rdr.read_exact(&mut curr).is_err() { break; }
            frame_idx += 1;
            if frame_idx % stride != 0 {
                std::mem::swap(&mut prev, &mut curr);
                continue;
            }
            let ts_ms = t0.elapsed().as_millis();

            let vf = video_features_from_frame(&curr, &prev, w, h, ts_ms);
            if tx_v.send(vf).is_err() { break; }
            std::mem::swap(&mut prev, &mut curr);
        }
    });

    // --- Audio thread ---
    let ah = thread::spawn(move || {
        let mut rdr = std::io::BufReader::new(aout);
        let mut buf = vec![0u8; 4]; // f32le
        let mut ring: Vec<f32> = vec![0.0; 8192];
        let mut head = 0usize;
        let mut filled = 0usize;
        let t0 = Instant::now();

        loop {
            // Read one sample f32
            if rdr.read_exact(&mut buf).is_err() { break; }
            let s = f32::from_le_bytes([buf[0],buf[1],buf[2],buf[3]]);
            ring[head] = s;
            head = (head + 1) % ring.len();
            if filled < ring.len() { filled += 1; }

            // When enough accumulated, compute hop
            if filled >= aframe && ((head + ring.len()) % ahop == 0) {
                // gather aframe samples ending at head
                let mut frame = vec![0f32; aframe];
                let start = (head + ring.len() - aframe) % ring.len();
                if start + aframe <= ring.len() {
                    frame.copy_from_slice(&ring[start..start+aframe]);
                } else {
                    let p = ring.len() - start;
                    frame[..p].copy_from_slice(&ring[start..]);
                    frame[p..].copy_from_slice(&ring[..aframe - p]);
                }
                let ts_ms = t0.elapsed().as_millis();
                let af = audio_features_from_frame(&frame, sr, ts_ms);
                if tx_a.send(af).is_err() { break; }
            }
        }
    });

    // --- Aggregator / gating ---
    let last_audio = Arc::new(Mutex::new(AudioFeat::default()));
    {
        let la = last_audio.clone();
        thread::spawn(move || {
            while let Ok(af) = rx_a.recv() {
                if let Ok(mut g) = la.lock() { *g = af; }
            }
        });
    }

    // Output JSON lines
    let mut out = BufWriter::new(stdout());
    let mut last_tick = Instant::now() - Duration::from_millis(tick_ms);
    while let Ok(vf) = rx_v.recv() {
        // limit cadence (avoid flooding when fps high)
        if last_tick.elapsed().as_millis() < tick_ms as u128 {
            continue;
        }
        last_tick = Instant::now();

        let af = { last_audio.lock().ok().cloned().unwrap_or_default() };
        let ts = vf.ts_ms.max(af.ts_ms);

        // Build score: motion + audio energy + novelty in spectrum
        let motion_s = vf.motion.min(1.0);
        let energy_s = af.rms.min(1.0);
        // simple novelty: center-of-mass distance from mid (0.5) and band entropy proxy
        let centroid_s = (af.centroid - 0.5).abs() * 2.0; // 0..1
        let mut ent = 0f32;
        for b in &af.band_energy {
            if *b > 1e-9 { ent -= *b * b.ln(); }
        }
        // normalize entropy roughly to 0..1
        let ent_s = clamp01((ent / 2.5) as f32);

        // Weighted mix; tuned for "interestingness"
        let mut score = 0.5*motion_s + 0.35*energy_s + 0.15*0.5*(centroid_s + ent_s);
        if af.zcr > 0.9 { score *= 0.9; } // very noisy boosts less
        score = clamp01(score);

        if score < score_gate { continue; } // gate to avoid fill saturation

        // Emit JSONL (compact)
        // v.grid16 flattened; a.band_energy flattened
        write!(out, "{{\"ts_ms\":{},\"score\":{:.3},\"video\":{{\"motion\":{:.3},\"mean\":{:.3},\"var\":{:.3},\"grid16\":[",
               ts, score, vf.motion, vf.mean, vf.var).unwrap();
        for i in 0..16 {
            if i>0 { out.write_all(b",").unwrap(); }
            write!(out, "{:.3}", vf.grid16[i]).unwrap();
        }
        out.write_all(b"]},\"audio\":{").unwrap();
        write!(out, "\"rms\":{:.3},\"zcr\":{:.3},\"centroid\":{:.3},\"bands\":[",
               af.rms, af.zcr, af.centroid).unwrap();
        for i in 0..8 {
            if i>0 { out.write_all(b",").unwrap(); }
            write!(out, "{:.3}", af.band_energy[i]).unwrap();
        }
        out.write_all(b"]}}\n").unwrap();
        out.flush().unwrap();
    }

    let _ = vh.join();
    let _ = ah.join();
}