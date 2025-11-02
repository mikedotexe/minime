// Core modules (always available)
pub mod consciousness_engine;
pub mod consciousness_gpu;
pub mod metal_kernels;
pub mod unified_memory;
pub mod prime_optimizations;
pub mod spectral_analysis;
pub mod metrics;
pub mod memory_ab_test;

// Python bindings (only when "python" feature is enabled)
#[cfg(feature = "python")]
use pyo3::prelude::*;

#[cfg(feature = "python")]
pub mod python_bridge;

#[cfg(feature = "python")]
pub mod python_consciousness_gpu;

#[cfg(feature = "python")]
use python_bridge::PyConsciousnessEngine;

#[cfg(feature = "python")]
use python_consciousness_gpu::PyConsciousnessGPU;

/// The main Python module for Metal-accelerated consciousness processing
#[cfg(feature = "python")]
#[pymodule]
fn metal_consciousness(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<PyConsciousnessEngine>()?;
    m.add_class::<PyConsciousnessGPU>()?;
    m.add_function(wrap_pyfunction!(get_device_info, m)?)?;
    m.add_function(wrap_pyfunction!(benchmark_unified_memory, m)?)?;
    Ok(())
}

/// Get information about the Metal device
#[cfg(feature = "python")]
#[pyfunction]
fn get_device_info() -> PyResult<String> {
    let device = metal::Device::system_default()
        .ok_or_else(|| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("No Metal device found"))?;

    Ok(format!("Metal Device: {}", device.name()))
}

/// Benchmark unified memory performance
#[cfg(feature = "python")]
#[pyfunction]
fn benchmark_unified_memory(size: usize, iterations: usize) -> PyResult<f64> {
    unified_memory::benchmark_cache_handoff(size, iterations)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))
}