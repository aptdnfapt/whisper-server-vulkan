# ============================================
# STAGE 1: Builder - compile whisper-server
# ============================================
FROM ubuntu:24.04 AS builder

WORKDIR /app
ENV DEBIAN_FRONTEND=noninteractive

# Layer 1: Install build dependencies (cached unless base image changes)
RUN apt-get update && \
    apt-get install -y \
    build-essential \
    cmake \
    git \
    glslc \
    libvulkan-dev \
    pkg-config \
    curl \
    libcurl4-openssl-dev && \
    rm -rf /var/lib/apt/lists/*

# Layer 2: Clone whisper.cpp (cached unless repo changes)
ARG WHISPER_VERSION=master
RUN git clone --depth 1 --branch ${WHISPER_VERSION} https://github.com/ggml-org/whisper.cpp.git

# Layer 3: Configure cmake (cached unless source or flags change)
RUN cmake whisper.cpp \
    -B whisper.cpp/build \
    -DGGML_VULKAN=ON \
    -DBUILD_SHARED_LIBS=OFF \
    -DCMAKE_C_FLAGS="-march=sandybridge -mtune=generic -mno-avx -mno-avx2 -mno-bmi -mno-bmi2" \
    -DCMAKE_CXX_FLAGS="-march=sandybridge -mtune=generic -mno-avx -mno-avx2 -mno-bmi -mno-bmi2"

# Layer 4: Build server binary
RUN cmake --build whisper.cpp/build --target whisper-server -j"$(nproc)"

# ============================================
# STAGE 2: Runtime - minimal image
# ============================================
FROM ubuntu:24.04

WORKDIR /app
ENV DEBIAN_FRONTEND=noninteractive

# Runtime deps only (small layer, cached)
# ffmpeg: converts any audio format (mp3, ogg, flac, etc) to wav
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libgomp1 \
    libvulkan1 \
    mesa-vulkan-drivers \
    curl \
    ca-certificates \
    ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Copy compiled binary from builder
COPY --from=builder /app/whisper.cpp/build/bin/whisper-server /usr/local/bin/whisper-server

# Copy entrypoint script
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# ============================================
# Runtime configuration via environment vars
# ============================================
# MODEL_PATH: path to model file (default: /app/models/model.bin)
# MODEL_URL:  URL to download if model not found (optional)
# MODEL_NAME: shorthand like "large-v3-turbo-q8_0" for auto-download
ENV MODEL_PATH=/app/models/model.bin
ENV MODEL_NAME=large-v3-turbo-q8_0
ENV MODEL_URL=""

# Create models directory for volume mount
RUN mkdir -p /app/models

EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
