import Metal

@inline(__always)
public func dispatch1D(_ enc: MTLComputeCommandEncoder,
                       pso: MTLComputePipelineState,
                       count: Int,
                       threadsPerThreadgroup: Int = 0) {
    let tew = pso.threadExecutionWidth
    let tpt = max(threadsPerThreadgroup, tew)
    let tpT = MTLSize(width: tpt, height: 1, depth: 1)
    let thr = MTLSize(width: count, height: 1, depth: 1)
    enc.setComputePipelineState(pso)
    enc.dispatchThreads(thr, threadsPerThreadgroup: tpT)
}

@inline(__always)
public func dispatch2D(_ enc: MTLComputeCommandEncoder,
                       pso: MTLComputePipelineState,
                       width: Int, height: Int,
                       tptX: Int = 0, tptY: Int = 8) {
    let tew = pso.threadExecutionWidth
    let x = max(tptX, tew)
    let tpT = MTLSize(width: x, height: tptY, depth: 1)
    let thr = MTLSize(width: width, height: height, depth: 1)
    enc.setComputePipelineState(pso)
    enc.dispatchThreads(thr, threadsPerThreadgroup: tpT)
}

@inline(__always)
public func dispatch3D(_ enc: MTLComputeCommandEncoder,
                       pso: MTLComputePipelineState,
                       width: Int, height: Int, depth: Int,
                       tptX: Int = 0, tptY: Int = 4, tptZ: Int = 1) {
    let tew = pso.threadExecutionWidth
    let x = max(tptX, tew)
    let tpT = MTLSize(width: x, height: tptY, depth: tptZ)
    let thr = MTLSize(width: width, height: height, depth: depth)
    enc.setComputePipelineState(pso)
    enc.dispatchThreads(thr, threadsPerThreadgroup: tpT)
}
