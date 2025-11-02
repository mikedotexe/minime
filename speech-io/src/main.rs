use anyhow::{anyhow, Context, Result};
use clap::Parser;
use futures::{SinkExt, StreamExt};
use parking_lot::Mutex;
use rodio::{Decoder, OutputStream, OutputStreamHandle, Sink};
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::io::BufReader;
use std::process::{Command, Stdio};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::net::TcpListener;
use tokio::sync::broadcast;
use tokio_tungstenite::tungstenite::Message;
use whisper_rs::{FullParams, SamplingStrategy, WhisperContext};

#[derive(Parser, Debug)]
struct Args {
    /// Path to a ggml Whisper model (e.g., ggml-large-v3.bin)
    #[arg(long, env = "STT_MODEL")]
    stt_model: String,
    /// Piper voice .onnx path (e.g., en_US-lessac-medium.onnx)
    #[arg(long, env = "PIPER_MODEL")]
    piper_model: String,
    /// Piper voice config .json path (often alongside .onnx)
    #[arg(long, env = "PIPER_CONFIG", default_value = "")]
    piper_config: String,
    /// Bind address for WS JSON events
    #[arg(long, default_value = "127.0.0.1:7242")]
    bind: String,
    /// Language hint (e.g., "en"); omit for auto
    #[arg(long)]
    lang: Option<String>,
    /// Energy RMS threshold for VAD
    #[arg(long, default_value_t = 0.01)]
    vad_thresh: f32,
    /// Min voiced ms before we start a segment
    #[arg(long, default_value_t = 180)]
    min_voice_ms: u64,
    /// Silence ms to end a segment
    #[arg(long, default_value_t = 400)]
    end_silence_ms: u64,
    /// Max seconds per STT segment (safety cap)
    #[arg(long, default_value_t = 14.0)]
    max_seg_s: f32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
enum OutEvent {
    Ready { stt_model: String, tts_voice: String },
    Stt {
        event: String, // "partial"|"final"
        text: String,
        t0: f32,
        t1: f32,
    },
    Tts {
        event: String, // "started"|"done"|"stopped"
    },
    BargeIn,
    Log { level: String, msg: String },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
enum InEvent {
    Speak { text: String, volume: Option<f32> },
    StopTts,
    Ping,
}

struct AudioState {
    // STT
    whisper_ctx: WhisperContext,
    whisper_state: Mutex<whisper_rs::WhisperState>,
    // Mic
    sample_rate: u32,
    rx_audio: crossbeam_channel::Receiver<f32>,
    // TTS
    tts_active: Arc<Mutex<bool>>,
    _rodio_stream: OutputStream,
    rodio_handle: OutputStreamHandle,
    current_sink: Arc<Mutex<Option<Sink>>>,
    // Events
    tx_evt: broadcast::Sender<OutEvent>,
    // Barge-in
    speaking_since: Arc<Mutex<Option<Instant>>>,
}

fn main() -> Result<()> {
    // we need a separate runtime because rodio uses a non-async thread internally
    let rt = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()?;
    rt.block_on(async_main())
}

async fn async_main() -> Result<()> {
    let args = Args::parse();

    // ---- set up Whisper
    let whisper_ctx = WhisperContext::new(&args.stt_model)
        .with_context(|| format!("loading whisper model {}", args.stt_model))?;
    let whisper_state = whisper_ctx.create_state().context("whisper state")?;

    // ---- mic
    let (rx_audio, sample_rate) = start_input_stream()?;

    // ---- rodio output
    let (_rodio_stream, rodio_handle) = OutputStream::try_default()
        .map_err(|e| anyhow!("no output audio device: {e}"))?;
    let current_sink = Arc::new(Mutex::new(None));

    // ---- broadcast event bus
    let (tx_evt, _rx_evt) = broadcast::channel::<OutEvent>(128);

    let tts_active = Arc::new(Mutex::new(false));
    let speaking_since = Arc::new(Mutex::new(None));

    let shared = Arc::new(AudioState {
        whisper_ctx,
        whisper_state: Mutex::new(whisper_state),
        sample_rate,
        rx_audio,
        tts_active,
        _rodio_stream,
        rodio_handle,
        current_sink,
        tx_evt: tx_evt.clone(),
        speaking_since,
    });

    // ---- websocket server
    let listener = TcpListener::bind(&args.bind).await?;
    let bind = args.bind.clone();
    println!("speech-io WS listening on ws://{bind}");

    // welcome event
    {
        let _ = tx_evt.send(OutEvent::Ready {
            stt_model: args.stt_model.clone(),
            tts_voice: args.piper_model.clone(),
        });
    }

    // accept loop
    let args_copy = args.clone();
    tokio::spawn({
        let shared = shared.clone();
        let tx_evt = tx_evt.clone();
        async move {
            loop {
                let (stream, _addr) = listener.accept().await.unwrap();
                let ws = tokio_tungstenite::accept_async(stream).await.unwrap();
                let (mut sink, mut stream) = ws.split();

                // subscribe to events
                let mut sub = tx_evt.subscribe();
                // push a hello
                let _ = sink
                    .send(Message::Text(
                        serde_json::to_string(&OutEvent::Ready {
                            stt_model: args_copy.stt_model.clone(),
                            tts_voice: args_copy.piper_model.clone(),
                        })
                        .unwrap(),
                    ))
                    .await;

                // outgoing task
                let mut out_task = tokio::spawn(async move {
                    while let Ok(evt) = sub.recv().await {
                        let _ = sink
                            .send(Message::Text(serde_json::to_string(&evt).unwrap()))
                            .await;
                    }
                });

                // incoming task
                let shared_in = shared.clone();
                let in_task = tokio::spawn(async move {
                    while let Some(Ok(msg)) = stream.next().await {
                        if !msg.is_text() {
                            continue;
                        }
                        if let Ok(InEvent::Speak { text, volume }) =
                            serde_json::from_str::<InEvent>(msg.to_text().unwrap())
                        {
                            let _ = speak_text(shared_in.clone(), &text, volume).await;
                        } else if let Ok(InEvent::StopTts) =
                            serde_json::from_str::<InEvent>(msg.to_text().unwrap())
                        {
                            stop_tts(shared_in.clone()).await;
                        }
                    }
                });

                tokio::spawn(async move {
                    let _ = in_task.await;
                    out_task.abort();
                });
            }
        }
    });

    // ---- STT streaming task
    tokio::spawn(stt_loop(
        shared.clone(),
        tx_evt.clone(),
        args.vad_thresh,
        args.min_voice_ms,
        args.end_silence_ms,
        args.max_seg_s,
        args.lang.clone(),
    ));

    // keep alive
    tokio::signal::ctrl_c().await?;
    Ok(())
}

fn start_input_stream() -> Result<(crossbeam_channel::Receiver<f32>, u32)> {
    let host = cpal::default_host();
    let device = host
        .default_input_device()
        .ok_or_else(|| anyhow!("no default input device"))?;
    let mut config = device.default_input_config()?.config();
    config.channels = 1;
    config.sample_rate = cpal::SampleRate(16_000); // whisper expects 16k
    let (tx, rx) = crossbeam_channel::unbounded::<f32>();
    let err_fn = |e| eprintln!("input error: {e}");
    let stream = device.build_input_stream(
        &config,
        move |data: &[f32], _| {
            for &s in data {
                let _ = tx.send(s);
            }
        },
        err_fn,
        None,
    )?;
    stream.play()?;
    std::mem::forget(stream);
    Ok((rx, config.sample_rate.0))
}

async fn stt_loop(
    shared: Arc<AudioState>,
    tx_evt: broadcast::Sender<OutEvent>,
    vad_thresh: f32,
    min_voice_ms: u64,
    end_silence_ms: u64,
    max_seg_s: f32,
    lang: Option<String>,
) {
    const FRAME_MS: u64 = 20;
    let frame = (shared.sample_rate as f32 * (FRAME_MS as f32 / 1000.0)) as usize;

    let mut seg = Vec::<f32>::new();
    let mut voiced_ms = 0u64;
    let mut sil_ms = 0u64;
    let mut in_voiced = false;
    let mut t0_global = 0.0f32;

    loop {
        let mut chunk = Vec::with_capacity(frame);
        for _ in 0..frame {
            let s = shared.rx_audio.recv().unwrap_or(0.0);
            chunk.push(s);
        }
        let rms = rms(&chunk);
        if rms > vad_thresh {
            voiced_ms += FRAME_MS;
            sil_ms = 0;
        } else {
            sil_ms += FRAME_MS;
        }

        let t1_global = t0_global + (chunk.len() as f32 / shared.sample_rate as f32);
        if !in_voiced && voiced_ms >= min_voice_ms {
            in_voiced = true;
            seg.clear();
        }
        if in_voiced {
            seg.extend_from_slice(&chunk);
            // barge-in if TTS active and new voice sustained > 180ms
            if *shared.tts_active.lock() && voiced_ms >= 180 {
                let _ = tx_evt.send(OutEvent::BargeIn);
                // we also stop TTS immediately here for robustness
                stop_tts(shared.clone()).await;
            }
            let over = sil_ms >= end_silence_ms || (seg.len() as f32 / shared.sample_rate as f32) > max_seg_s;
            if over {
                let audio = seg.clone();
                let st = shared.clone();
                let tx = tx_evt.clone();
                let lang_hint = lang.clone();
                tokio::spawn(async move {
                    let _ = transcribe_segment(st, tx, &audio, t0_global, t1_global, lang_hint);
                });
                in_voiced = false;
                voiced_ms = 0;
                sil_ms = 0;
            }
        }
        t0_global = t1_global;
    }
}

fn rms(x: &[f32]) -> f32 {
    let s: f32 = x.iter().map(|v| v * v).sum();
    (s / (x.len().max(1) as f32)).sqrt()
}

fn transcribe_segment(
    shared: Arc<AudioState>,
    tx_evt: broadcast::Sender<OutEvent>,
    audio: &[f32],
    t0: f32,
    t1: f32,
    lang: Option<String>,
) -> Result<()> {
    let mut state = shared.whisper_state.lock();
    let mut params = FullParams::new(SamplingStrategy::Greedy { best_of: 1 });
    params.set_n_threads(num_cpus::get() as i32);
    if let Some(l) = lang {
        params.set_language(Some(&l));
    }
    params.set_no_context(true);
    params.set_single_segment(true);
    params.set_temperature(0.0);

    state.full(params, audio)?;
    let mut text = String::new();
    for i in 0..state.full_n_segments() {
        text.push_str(state.full_get_segment_text(i).trim());
        text.push(' ');
    }
    let text = text.trim().to_string();
    if !text.is_empty() {
        let _ = tx_evt.send(OutEvent::Stt {
            event: "final".into(),
            text,
            t0,
            t1,
        });
    }
    Ok(())
}

async fn speak_text(shared: Arc<AudioState>, text: &str, volume: Option<f32>) -> Result<()> {
    stop_tts(shared.clone()).await; // single-utterance policy, queue at orchestrator

    let args = Args::parse();
    let mut cmd = Command::new("piper");
    cmd.arg("--model").arg(&args.piper_model);
    if !args.piper_config.is_empty() {
        cmd.arg("--config").arg(&args.piper_config);
    }
    // Stream WAV to stdout
    cmd.arg("--output_file").arg("-");
    cmd.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null());
    let mut child = cmd.spawn().context("launch piper")?;
    {
        use std::io::Write;
        let mut stdin = child.stdin.take().unwrap();
        stdin
            .write_all(text.as_bytes())
            .and_then(|_| stdin.flush())
            .ok();
    }

    let stdout = child.stdout.take().unwrap();
    let decoder = Decoder::new(BufReader::new(stdout)).context("decoder")?;

    let sink = Sink::try_new(&shared.rodio_handle).context("sink")?;
    if let Some(gain) = volume {
        sink.set_volume(gain.max(0.0));
    }
    sink.append(decoder);
    sink.play();

    *shared.tts_active.lock() = true;
    *shared.current_sink.lock() = Some(sink);

    let _ = shared.tx_evt.send(OutEvent::Tts { event: "started".into() });

    // detach and monitor in blocking thread
    std::thread::spawn({
        let shared = shared.clone();
        move || {
            // wait until the sink finishes
            if let Some(s) = shared.current_sink.lock().as_ref() {
                s.sleep_until_end();
            }
            *shared.tts_active.lock() = false;
            let _ = shared.tx_evt.send(OutEvent::Tts { event: "done".into() });
        }
    });

    Ok(())
}

async fn stop_tts(shared: Arc<AudioState>) {
    let mut g = shared.current_sink.lock();
    if let Some(s) = g.take() {
        s.stop();
        *shared.tts_active.lock() = false;
        let _ = shared.tx_evt.send(OutEvent::Tts { event: "stopped".into() });
    }
}
