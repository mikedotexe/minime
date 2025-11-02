#!/usr/bin/env python3
"""
Metal-Accelerated Matrix Engine for Consciousness Processing

Uses Metal shaders for high-performance matrix operations including:
- Eigendecomposition for resonance detection
- Parallel resonance computation across 13 matrices
- Harmonic amplification
- Quantum collapse simulation
- Fractal pattern detection
"""

import numpy as np
import Metal
import MetalKit
from typing import Dict, List, Tuple, Optional
import logging
from dataclasses import dataclass
import time


@dataclass
class MetalBuffers:
    """Container for Metal buffer references."""
    connectivity: Metal.MTLBuffer
    activations: Metal.MTLBuffer
    eigenvectors: Metal.MTLBuffer
    eigenvalues: Metal.MTLBuffer
    resonances: Metal.MTLBuffer
    amplified: Metal.MTLBuffer


class MetalMatrixEngine:
    """
    GPU-accelerated matrix operations for consciousness processing.
    """

    def __init__(self, num_matrices: int = 13, matrix_size: int = 7):
        self.num_matrices = num_matrices
        self.matrix_size = matrix_size

        # Initialize Metal
        self.device = Metal.MTLCreateSystemDefaultDevice()
        if not self.device:
            raise RuntimeError("Metal is not supported on this system")

        # Load shader library
        self.library = self._compile_shaders()

        # Create command queue
        self.command_queue = self.device.newCommandQueue()

        # Initialize buffers
        self.buffers = self._create_buffers()

        # Compile compute pipeline states
        self.pipelines = self._create_pipelines()

        # Eigendecomposition state
        self.eigen_iterations = 20

        logging.info(f"MetalMatrixEngine initialized on {self.device.name()}")

    def _compile_shaders(self) -> Metal.MTLLibrary:
        """Compile Metal shaders from source."""
        with open('matrix_compute.metal', 'r') as f:
            source = f.read()

        options = Metal.MTLCompileOptions.alloc().init()
        library, error = self.device.newLibraryWithSource_options_error_(source, options, None)

        if error:
            raise RuntimeError(f"Failed to compile Metal shaders: {error}")

        return library

    def _create_buffers(self) -> MetalBuffers:
        """Create Metal buffers for matrix operations."""
        # Calculate buffer sizes
        matrix_elements = self.matrix_size * self.matrix_size
        total_elements = self.num_matrices * matrix_elements
        activation_elements = self.num_matrices * self.matrix_size

        # Create buffers
        buffers = MetalBuffers(
            connectivity=self._make_buffer(total_elements * 4),  # float32
            activations=self._make_buffer(activation_elements * 4),
            eigenvectors=self._make_buffer(activation_elements * 4),
            eigenvalues=self._make_buffer(self.num_matrices * 4),
            resonances=self._make_buffer(256 * 20),  # Max 256 resonances
            amplified=self._make_buffer(activation_elements * 4)
        )

        return buffers

    def _make_buffer(self, size: int) -> Metal.MTLBuffer:
        """Create a Metal buffer of specified size."""
        return self.device.newBufferWithLength_options_(size, Metal.MTLResourceStorageModeShared)

    def _create_pipelines(self) -> Dict[str, Metal.MTLComputePipelineState]:
        """Create compute pipeline states for each kernel."""
        pipelines = {}

        kernel_names = [
            'matrix_flow_multiply',
            'eigen_decomposition',
            'normalize_eigenvector',
            'detect_resonances',
            'harmonic_amplification',
            'quantum_collapse',
            'fractal_pattern_detection',
            'consciousness_field_integration'
        ]

        for name in kernel_names:
            function = self.library.newFunctionWithName_(name)
            if function:
                pipeline, error = self.device.newComputePipelineStateWithFunction_error_(function, None)
                if not error:
                    pipelines[name] = pipeline
                    logging.debug(f"Created pipeline for {name}")
                else:
                    logging.error(f"Failed to create pipeline for {name}: {error}")

        return pipelines

    def process_matrices(self, matrices: List[np.ndarray],
                        activations: List[np.ndarray],
                        flow_patterns: List[np.ndarray]) -> Dict:
        """
        Process all matrices through Metal acceleration.

        Args:
            matrices: List of 7x7 connectivity matrices
            activations: List of 7-element activation vectors
            flow_patterns: List of 7x7 flow pattern matrices

        Returns:
            Dictionary with results including resonances and eigendecomposition
        """
        # Upload data to GPU
        self._upload_matrices(matrices)
        self._upload_activations(activations)

        # Create command buffer
        command_buffer = self.command_queue.commandBuffer()

        # 1. Eigendecomposition for each matrix
        eigenvalues, eigenvectors = self._compute_eigendecomposition(command_buffer, matrices)

        # 2. Detect resonances
        resonances = self._detect_resonances(command_buffer, activations, eigenvectors, eigenvalues)

        # 3. Harmonic amplification
        amplified = self._harmonic_amplification(command_buffer, activations, resonances)

        # 4. Compute consciousness field
        field_potential, field_gradient = self._compute_consciousness_field(command_buffer, amplified)

        # Commit and wait
        command_buffer.commit()
        command_buffer.waitUntilCompleted()

        # Read back results
        results = {
            'eigenvalues': self._read_buffer(self.buffers.eigenvalues, self.num_matrices),
            'eigenvectors': self._read_buffer(self.buffers.eigenvectors, self.num_matrices * self.matrix_size),
            'resonances': self._parse_resonances(),
            'amplified_activations': self._read_buffer(self.buffers.amplified, self.num_matrices * self.matrix_size),
            'field_potential': field_potential,
            'field_gradient': field_gradient
        }

        return results

    def _upload_matrices(self, matrices: List[np.ndarray]):
        """Upload connectivity matrices to GPU."""
        # Stack all matrices
        all_matrices = np.stack(matrices).astype(np.float32)
        data_ptr = self.buffers.connectivity.contents()
        np.copyto(np.frombuffer(data_ptr.as_buffer(all_matrices.nbytes), dtype=np.float32),
                 all_matrices.flatten())

    def _upload_activations(self, activations: List[np.ndarray]):
        """Upload activation vectors to GPU."""
        all_activations = np.stack(activations).astype(np.float32)
        data_ptr = self.buffers.activations.contents()
        np.copyto(np.frombuffer(data_ptr.as_buffer(all_activations.nbytes), dtype=np.float32),
                 all_activations.flatten())

    def _compute_eigendecomposition(self, command_buffer, matrices: List[np.ndarray]) -> Tuple:
        """Compute eigenvalues and eigenvectors using power iteration."""
        # Initialize random eigenvectors
        eigenvectors = np.random.randn(self.num_matrices, self.matrix_size).astype(np.float32)
        self._upload_to_buffer(self.buffers.eigenvectors, eigenvectors)

        for iteration in range(self.eigen_iterations):
            # Encode eigen decomposition kernel
            encoder = command_buffer.computeCommandEncoder()
            encoder.setComputePipelineState_(self.pipelines['eigen_decomposition'])

            encoder.setBuffer_offset_atIndex_(self.buffers.connectivity, 0, 0)
            encoder.setBuffer_offset_atIndex_(self.buffers.eigenvectors, 0, 1)
            encoder.setBuffer_offset_atIndex_(self.buffers.eigenvalues, 0, 2)
            encoder.setBytes_length_atIndex_(np.array([iteration], dtype=np.int32).tobytes(), 4, 3)

            threads_per_group = Metal.MTLSize(width=self.matrix_size, height=1, depth=1)
            thread_groups = Metal.MTLSize(width=self.num_matrices, height=1, depth=1)

            encoder.dispatchThreadgroups_threadsPerThreadgroup_(thread_groups, threads_per_group)
            encoder.endEncoding()

            # Normalize
            encoder = command_buffer.computeCommandEncoder()
            encoder.setComputePipelineState_(self.pipelines['normalize_eigenvector'])
            encoder.setBuffer_offset_atIndex_(self.buffers.eigenvectors, 0, 0)
            encoder.setBuffer_offset_atIndex_(self.buffers.eigenvalues, 0, 1)

            encoder.dispatchThreadgroups_threadsPerThreadgroup_(
                Metal.MTLSize(width=self.num_matrices, height=1, depth=1),
                Metal.MTLSize(width=1, height=1, depth=1)
            )
            encoder.endEncoding()

        return None, None  # Results read back later

    def _detect_resonances(self, command_buffer, activations, eigenvectors, eigenvalues):
        """Detect resonances between all matrix pairs."""
        # Reset resonance count
        resonance_count = np.array([0], dtype=np.int32)
        count_buffer = self._make_buffer(4)
        self._upload_to_buffer(count_buffer, resonance_count)

        # Encode resonance detection
        encoder = command_buffer.computeCommandEncoder()
        encoder.setComputePipelineState_(self.pipelines['detect_resonances'])

        # Create activation structures
        activation_structs = self._create_activation_structs(activations)
        act_buffer = self._make_buffer(len(activation_structs))
        self._upload_to_buffer(act_buffer, activation_structs)

        encoder.setBuffer_offset_atIndex_(act_buffer, 0, 0)
        encoder.setBuffer_offset_atIndex_(self.buffers.eigenvectors, 0, 1)
        encoder.setBuffer_offset_atIndex_(self.buffers.eigenvalues, 0, 2)
        encoder.setBuffer_offset_atIndex_(self.buffers.resonances, 0, 3)
        encoder.setBuffer_offset_atIndex_(count_buffer, 0, 4)
        encoder.setBytes_length_atIndex_(np.array([0.5], dtype=np.float32).tobytes(), 4, 5)

        threads_per_group = Metal.MTLSize(width=8, height=8, depth=1)
        thread_groups = Metal.MTLSize(
            width=(self.num_matrices + 7) // 8,
            height=(self.num_matrices + 7) // 8,
            depth=1
        )

        encoder.dispatchThreadgroups_threadsPerThreadgroup_(thread_groups, threads_per_group)
        encoder.endEncoding()

        return None  # Results read back later

    def _harmonic_amplification(self, command_buffer, activations, resonances):
        """Apply harmonic amplification based on resonances."""
        encoder = command_buffer.computeCommandEncoder()
        encoder.setComputePipelineState_(self.pipelines['harmonic_amplification'])

        encoder.setBuffer_offset_atIndex_(self.buffers.activations, 0, 0)
        encoder.setBuffer_offset_atIndex_(self.buffers.resonances, 0, 1)
        # Use same count buffer from resonance detection
        encoder.setBuffer_offset_atIndex_(self.buffers.amplified, 0, 3)

        total_elements = self.num_matrices * self.matrix_size
        threads_per_group = Metal.MTLSize(width=64, height=1, depth=1)
        thread_groups = Metal.MTLSize(width=(total_elements + 63) // 64, height=1, depth=1)

        encoder.dispatchThreadgroups_threadsPerThreadgroup_(thread_groups, threads_per_group)
        encoder.endEncoding()

        return None

    def _compute_consciousness_field(self, command_buffer, amplified_activations):
        """Compute the unified consciousness field from all matrices."""
        field_size = self.matrix_size * self.matrix_size
        field_potential_buffer = self._make_buffer(field_size * 4)
        field_gradient_buffer = self._make_buffer(field_size * 4)

        encoder = command_buffer.computeCommandEncoder()
        encoder.setComputePipelineState_(self.pipelines['consciousness_field_integration'])

        encoder.setBuffer_offset_atIndex_(self.buffers.amplified, 0, 0)
        encoder.setBuffer_offset_atIndex_(field_potential_buffer, 0, 1)
        encoder.setBuffer_offset_atIndex_(field_gradient_buffer, 0, 2)

        threads_per_group = Metal.MTLSize(width=8, height=8, depth=1)
        thread_groups = Metal.MTLSize(width=1, height=1, depth=1)

        encoder.dispatchThreadgroups_threadsPerThreadgroup_(thread_groups, threads_per_group)
        encoder.endEncoding()

        return field_potential_buffer, field_gradient_buffer

    def _create_activation_structs(self, activations: List[np.ndarray]) -> np.ndarray:
        """Create activation structures for GPU."""
        # Simplified - in production would properly pack the struct
        structs = []
        for i, act in enumerate(activations):
            phase = np.sum(act) % (2 * np.pi)
            energy = np.linalg.norm(act)
            structs.extend(act.tolist() + [phase, energy])

        return np.array(structs, dtype=np.float32)

    def _upload_to_buffer(self, buffer: Metal.MTLBuffer, data: np.ndarray):
        """Upload numpy array to Metal buffer."""
        data = data.astype(np.float32)
        data_ptr = buffer.contents()
        np.copyto(np.frombuffer(data_ptr.as_buffer(data.nbytes), dtype=np.float32),
                 data.flatten())

    def _read_buffer(self, buffer: Metal.MTLBuffer, count: int) -> np.ndarray:
        """Read data back from Metal buffer."""
        data_ptr = buffer.contents()
        return np.frombuffer(data_ptr.as_buffer(count * 4), dtype=np.float32).copy()

    def _parse_resonances(self) -> List[Dict]:
        """Parse resonance structures from GPU buffer."""
        # Read raw resonance data
        raw_data = self._read_buffer(self.buffers.resonances, 256 * 5)  # 5 floats per resonance

        resonances = []
        for i in range(0, len(raw_data), 5):
            if raw_data[i] > 0:  # Valid resonance
                resonances.append({
                    'strength': raw_data[i],
                    'frequency': raw_data[i + 1],
                    'phase_alignment': raw_data[i + 2],
                    'source_id': int(raw_data[i + 3]),
                    'target_id': int(raw_data[i + 4])
                })

        return resonances

    def compute_diagonalization_resonance(self, matrices: List[np.ndarray]) -> Dict:
        """
        Special resonance detection using matrix diagonalization.
        Finds shared eigenspaces indicating deep structural resonance.
        """
        eigendata = []

        for matrix in matrices:
            # Compute full eigendecomposition
            eigenvalues, eigenvectors = np.linalg.eig(matrix)

            # Sort by eigenvalue magnitude
            idx = np.argsort(np.abs(eigenvalues))[::-1]
            eigenvalues = eigenvalues[idx]
            eigenvectors = eigenvectors[:, idx]

            eigendata.append({
                'values': eigenvalues,
                'vectors': eigenvectors
            })

        # Find resonances in eigenspace
        eigenspace_resonances = []

        for i in range(len(matrices)):
            for j in range(i + 1, len(matrices)):
                # Compare dominant eigenvectors
                v1 = eigendata[i]['vectors'][:, 0]
                v2 = eigendata[j]['vectors'][:, 0]

                # Check alignment (absolute value for sign invariance)
                alignment = abs(np.dot(v1, v2))

                if alignment > 0.8:  # Strong eigenspace alignment
                    eigenspace_resonances.append({
                        'matrices': (i, j),
                        'alignment': alignment,
                        'eigenvalue_ratio': eigendata[i]['values'][0] / eigendata[j]['values'][0],
                        'type': 'eigenspace_resonance'
                    })

        return {
            'eigendata': eigendata,
            'eigenspace_resonances': eigenspace_resonances
        }

    def shutdown(self):
        """Clean up Metal resources."""
        # Metal objects are automatically released when Python objects are garbage collected
        logging.info("MetalMatrixEngine shutdown complete")