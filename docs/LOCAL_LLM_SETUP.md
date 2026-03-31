# Local LLM Setup Guide

**Audience**: CAM operators who want to run inference locally (zero cloud cost, zero API keys for LLM).

---

## Why Local

- Zero API cost for mining/enhancement tasks
- Data stays on your machine
- KV cache prefix caching for repeated queries
- Works offline

---

## Supported Backends

| Backend | Install | Port | KV Cache | Speed (M4) | Notes |
|---------|---------|------|----------|-------------|-------|
| Ollama 0.19+ | `brew install ollama` | 11434 | q8_0 (2x) | ~44 tok/s | Easiest setup, MLX engine |
| TurboQuant (turboq) | Build from source | 11435 | turbo3 (4.9x) | ~19 tok/s | Best memory efficiency |
| MLX-LM | `pip install mlx-lm` | 8080 | f16 only | varies | Native Apple Silicon |
| llama.cpp | Build from source | 8080 | q4_0-q8_0 | varies | Cross-platform |
| Atomic Chat | App bundle | 1337 | turbo3 via plugin | varies | GUI + API |

---

## Quick Start: Ollama (Recommended for Beginners)

### Step 1: Install Ollama

```bash
brew install ollama
ollama serve  # Start the server (runs on port 11434)
```

- Use this when: you want the fastest path from zero to running local inference.

### Step 2: Pull a Model

```bash
ollama pull qwen2.5:7b      # 4.4GB, good balance of quality/speed
```

- Use this when: you need a general-purpose model for mining and enhancement tasks.

```bash
ollama pull qwen3.5:9b      # 6.1GB, latest Qwen, better quality
```

- Use this when: you want the best output quality and are running Ollama (not TurboQuant).

### Step 3: Configure CAM

Add the following to your `claw.toml`:

```toml
[agents.local]
enabled = true
mode = "local"
model = "qwen2.5:7b"
local_base_url = "http://localhost:11434/v1"
timeout = 300
max_tokens = 16384

[local_llm]
provider = "ollama"
base_url = "http://localhost:11434/v1"
model = "qwen2.5:7b"
kv_cache_quantization = "q8_0"
keep_alive = -1               # Never unload model (recommended)
ctx_size = 32768
```

### Step 4: Verify

```bash
.venv/bin/cam doctor environment
```

- Use this when: you have finished configuration and want to confirm the local agent is healthy and Ollama is connected.
- Expected output: `local agent = healthy`, `Ollama = connected`.

---

## TurboQuant Setup (Advanced -- Best Memory Efficiency)

### When to Use TurboQuant

- You need 64K+ context windows
- You are running 13B+ models on limited memory
- You want 4.9x KV cache compression (vs 2x with Ollama)

### Step 1: Build the Binary

```bash
git clone https://github.com/TheTom/llama-cpp-turboquant.git
cd llama-cpp-turboquant
git checkout feature/turboquant-kv-cache
mkdir -p build && cd build
cmake .. -DGGML_METAL=ON -DGGML_METAL_EMBED_LIBRARY=ON \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64 \
  -DLLAMA_BUILD_SERVER=ON -DLLAMA_BUILD_CLI=ON
cmake --build . --config Release -j$(sysctl -n hw.logicalcpu)
```

- Use this when: you are on Apple Silicon and want Metal GPU acceleration.

### Step 2: Install

```bash
cp bin/llama-server ~/.local/bin/llama-server-turboq
cp bin/llama-cli ~/.local/bin/llama-cli-turboq
```

- Use this when: you want the TurboQuant binaries available system-wide without polluting your PATH with the full build tree.

### Step 3: Configure CAM

Add the following to your `claw.toml`:

```toml
[local_llm]
provider = "turboq"
kv_cache_quantization = "turbo3"
turboq_binary = "/Users/yourname/.local/bin/llama-server-turboq"
keep_alive = -1
ctx_size = 32768
```

### Known Limitations

- TheTom fork (build 8670) does NOT support qwen3.5 (qwen35 arch) -- use qwen2.5 (qwen2 arch) instead.
- Speed is ~2.3x slower than Ollama MLX (19 vs 44 tok/s) -- this is the engine difference, not a compression penalty.
- TurboQuant's value is MEMORY savings, not speed.

---

## KV Compression Comparison

| Type | Compression | KV Memory (32K ctx, 7B) | KV Memory (64K ctx, 7B) | Quality Loss |
|------|-------------|-------------------------|-------------------------|--------------|
| f16 | 1.0x | 1,792 MiB | 3,584 MiB | None |
| q8_0 | 2.0x | 896 MiB | 1,792 MiB | Negligible |
| q4_0 | 4.0x | 448 MiB | 896 MiB | Small |
| turbo3 | 4.9x | 350 MiB | 731 MiB | Near-zero |
| turbo4 | 6.0x | 299 MiB | 597 MiB | Near-zero |

---

## Enabling CAG with Local LLM

Both `[cag]` and `[agents.local]` must be enabled in `claw.toml`. See `CAG_GUIDE.md` for full configuration details.

---

## Model Recommendations

| Model | Size | Use Case | Context |
|-------|------|----------|---------|
| qwen2.5:0.5b | 397MB | Testing, quick checks | 32K |
| qwen2.5:7b | 4.4GB | General mining, good quality | 32K |
| qwen3.5:9b | 6.1GB | Best quality (Ollama only) | 32K |

---

## Full Config Reference

All `[local_llm]` fields:

```toml
[local_llm]
provider = "ollama"                    # ollama | turboq | mlx-server | atomic-chat | llama-cpp
base_url = "http://localhost:11434/v1" # OpenAI-compatible endpoint
model = "qwen2.5:7b"                  # Model name (Ollama model tag or GGUF path)
timeout = 300                          # Request timeout in seconds
ctx_size = 32768                       # Context window size
kv_cache_type = "f16"                  # Legacy field, prefer kv_cache_quantization
keep_alive = -1                        # -1 = never unload, 0 = unload immediately, N = seconds
kv_cache_quantization = "q8_0"        # f16 | q8_0 | q4_0 | turbo3 | turbo4
turboq_binary = "llama-server-turboq"  # Path to TurboQuant binary (only for provider=turboq)
```

All `[agents.local]` fields:

```toml
[agents.local]
enabled = false                        # Set true to enable local inference
mode = "local"                         # Must be "local"
model = "qwen2.5:7b"                  # Model name
local_base_url = "http://localhost:11434/v1"
timeout = 300
max_tokens = 16384                     # Max tokens per response
```

---

## Troubleshooting

### "Connection refused on 11434"

Run `ollama serve` first. The Ollama daemon must be running before CAM can connect.

### "Model not found"

Run `ollama pull <model>` to download the model. CAM does not auto-pull models.

### "turboq: rope.dimension_sections mismatch"

The model architecture is incompatible with the TheTom fork. Use qwen2.5 (qwen2 arch) instead of qwen3.5 (qwen35 arch).

### "Slow first request"

Normal behavior. The KV cache is cold on the first request. The second request will be faster due to prefix cache hits.

### "Out of memory"

Reduce `ctx_size` in your `claw.toml`, or switch to turbo3/turbo4 KV cache compression for better memory efficiency. See the KV Compression Comparison table above.
