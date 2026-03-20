# Clawamorphosis (CAM) — Multi-stage Docker build
# Produces a lean runtime image with the cam CLI ready to use.
#
# Build:   docker build -t cam .
# Run:     docker run --rm -v $(pwd)/data:/app/data -e OPENROUTER_API_KEY cam evaluate /app/target-repo

# ---- builder stage ----
FROM python:3.12-slim AS builder

WORKDIR /build

# System deps for building native extensions (sqlite-vec, numpy)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml claw.toml ./
COPY src/ src/
COPY prompts/ prompts/

# Install CAM and dev deps for validation
RUN pip install --no-cache-dir -e ".[dev]"

# Run tests in builder to catch issues early
COPY tests/ tests/
RUN pytest tests/ -q --tb=short

# ---- runtime stage ----
FROM python:3.12-slim AS runtime

WORKDIR /app

# Runtime-only: no gcc needed
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/cam /usr/local/bin/cam

COPY pyproject.toml claw.toml ./
COPY src/ src/
COPY prompts/ prompts/
COPY scripts/ scripts/
COPY README.md SKILL.md ./

# Re-install in editable mode so the cam entrypoint resolves
RUN pip install --no-cache-dir -e .

# Ensure data dir exists for volume mount
RUN mkdir -p data

# Default: show help
ENTRYPOINT ["cam"]
CMD ["--help"]
