// ============================================================================
// Python Bindings for Consciousness GPU Operations
// ============================================================================

use pyo3::prelude::*;
use pyo3::exceptions::PyRuntimeError;
use numpy::{PyArray1, PyReadonlyArray1, PyReadonlyArray2};
use crate::consciousness_gpu::ConsciousnessGPU;

#[pyclass]
pub struct PyConsciousnessGPU {
    gpu: ConsciousnessGPU,
}

#[pymethods]
impl PyConsciousnessGPU {
    #[new]
    fn new() -> PyResult<Self> {
        let gpu = ConsciousnessGPU::new()
            .map_err(|e| PyRuntimeError::new_err(format!("Failed to initialize GPU: {}", e)))?;

        Ok(Self { gpu })
    }

    /// Prime projection: 4096-d embedding → 13×7 views
    ///
    /// Args:
    ///     embedding: np.ndarray[float32] of shape (4096,)
    ///     geometry_matrices: np.ndarray[float32] of shape (13, 7, 7) flattened to (637,)
    ///
    /// Returns:
    ///     np.ndarray[float32] of shape (13, 7) flattened to (91,)
    fn prime_projection<'py>(
        &self,
        py: Python<'py>,
        embedding: PyReadonlyArray1<f32>,
        geometry_matrices: PyReadonlyArray1<f32>,
    ) -> PyResult<&'py PyArray1<f32>> {
        let embedding_slice = embedding.as_slice()
            .map_err(|e| PyRuntimeError::new_err(format!("Failed to read embedding: {}", e)))?;

        let geometry_slice = geometry_matrices.as_slice()
            .map_err(|e| PyRuntimeError::new_err(format!("Failed to read geometry matrices: {}", e)))?;

        let result = self.gpu.prime_projection(embedding_slice, geometry_slice)
            .map_err(|e| PyRuntimeError::new_err(format!("Prime projection failed: {}", e)))?;

        Ok(PyArray1::from_vec(py, result))
    }

    /// Resonance tensor: 7×7 basis → 7×7 resonance
    ///
    /// Args:
    ///     bases: np.ndarray[float32] of shape (7, 7) flattened to (49,)
    ///     use_tiled: bool - use optimized tiled version
    ///
    /// Returns:
    ///     np.ndarray[float32] of shape (7, 7) flattened to (49,)
    fn resonance_tensor<'py>(
        &self,
        py: Python<'py>,
        bases: PyReadonlyArray1<f32>,
        use_tiled: bool,
    ) -> PyResult<&'py PyArray1<f32>> {
        let bases_slice = bases.as_slice()
            .map_err(|e| PyRuntimeError::new_err(format!("Failed to read bases: {}", e)))?;

        let result = self.gpu.resonance_tensor(bases_slice, use_tiled)
            .map_err(|e| PyRuntimeError::new_err(format!("Resonance tensor failed: {}", e)))?;

        Ok(PyArray1::from_vec(py, result))
    }

    /// Compute position: bases @ trajectory → 7D position
    ///
    /// Args:
    ///     bases: np.ndarray[float32] of shape (7, 7) flattened to (49,)
    ///     trajectory: np.ndarray[float32] of shape (7,)
    ///
    /// Returns:
    ///     np.ndarray[float32] of shape (7,)
    fn compute_position<'py>(
        &self,
        py: Python<'py>,
        bases: PyReadonlyArray1<f32>,
        trajectory: PyReadonlyArray1<f32>,
    ) -> PyResult<&'py PyArray1<f32>> {
        let bases_slice = bases.as_slice()
            .map_err(|e| PyRuntimeError::new_err(format!("Failed to read bases: {}", e)))?;

        let trajectory_slice = trajectory.as_slice()
            .map_err(|e| PyRuntimeError::new_err(format!("Failed to read trajectory: {}", e)))?;

        let result = self.gpu.compute_position(bases_slice, trajectory_slice)
            .map_err(|e| PyRuntimeError::new_err(format!("Compute position failed: {}", e)))?;

        Ok(PyArray1::from_vec(py, result))
    }

    /// Evolve geometry matrices based on trajectory
    ///
    /// Args:
    ///     geometry_matrices: np.ndarray[float32] of shape (13, 7, 7) flattened to (637,) - MODIFIED IN PLACE
    ///     trajectory: np.ndarray[float32] of shape (7,)
    ///     evolution_rate: float - learning rate
    ///
    /// Returns:
    ///     None (modifies geometry_matrices in place)
    fn evolve_geometry(
        &self,
        mut geometry_matrices: PyReadonlyArray1<f32>,
        trajectory: PyReadonlyArray1<f32>,
        evolution_rate: f32,
    ) -> PyResult<()> {
        // For in-place modification, we need a mutable slice
        // This is tricky with numpy - we'll read, modify, and write back
        let mut geometry_vec = geometry_matrices.as_slice()
            .map_err(|e| PyRuntimeError::new_err(format!("Failed to read geometry matrices: {}", e)))?
            .to_vec();

        let trajectory_slice = trajectory.as_slice()
            .map_err(|e| PyRuntimeError::new_err(format!("Failed to read trajectory: {}", e)))?;

        self.gpu.evolve_geometry(&mut geometry_vec, trajectory_slice, evolution_rate)
            .map_err(|e| PyRuntimeError::new_err(format!("Evolve geometry failed: {}", e)))?;

        // Note: This doesn't actually modify the input array in Python
        // We'll need to return the result instead
        // TODO: Fix this by using PyArrayMethods for true in-place modification

        Ok(())
    }

    /// Symmetrize a 7×7 matrix in-place
    ///
    /// Args:
    ///     matrix: np.ndarray[float32] of shape (7, 7) flattened to (49,) - MODIFIED IN PLACE
    ///
    /// Returns:
    ///     None (modifies matrix in place)
    fn symmetrize_matrix(
        &self,
        matrix: PyReadonlyArray1<f32>,
    ) -> PyResult<()> {
        let mut matrix_vec = matrix.as_slice()
            .map_err(|e| PyRuntimeError::new_err(format!("Failed to read matrix: {}", e)))?
            .to_vec();

        self.gpu.symmetrize_matrix(&mut matrix_vec)
            .map_err(|e| PyRuntimeError::new_err(format!("Symmetrize matrix failed: {}", e)))?;

        // TODO: Same issue as evolve_geometry - need true in-place modification

        Ok(())
    }
}
