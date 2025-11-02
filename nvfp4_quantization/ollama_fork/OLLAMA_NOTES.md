# Ollama NVFP4 Integration Notes

## Build Information
- Date: $(date)
- Go Version: $(go version)
- Platform: $(uname -a)

## Key Integration Points

### 1. Quantization Types
Look for quantization type definitions in:
- `llm/ggml.go` - GGML type mappings
- `llm/llama.cpp/*` - C++ quantization implementation

### 2. Model Loading
Model loading logic is in:
- `server/routes.go` - HTTP endpoints
- `llm/server.cpp` - C++ server implementation

### 3. Adding NVFP4 Support

To add NVFP4 quantization:

1. **Define the type** in GGML:
   ```go
   // In llm/ggml.go
   const (
       GGML_TYPE_Q4_NV2D = 16 // or next available number
   )
   ```

2. **Implement dequantization** in C++:
   ```cpp
   // In llm/llama.cpp/ggml.c
   void dequantize_row_q4_nv2d(...)
   ```

3. **Register the type**:
   - Update type_traits
   - Add to quantization map
   - Implement conversion functions

4. **Metal kernel** (for Apple Silicon):
   ```metal
   // In llm/llama.cpp/ggml-metal.metal
   kernel void kernel_get_rows_q4_nv2d(...)
   ```

## Next Steps

1. Study existing Q4_K_M implementation as reference
2. Add NVFP4 type definitions
3. Implement CPU dequantization
4. Add Metal acceleration
5. Test with small models first

## Testing

```bash
# Test the built binary
./ollama serve

# In another terminal
./ollama pull tinyllama
./ollama run tinyllama "Hello world"
```
