#!/bin/sh
set -e

# ============================================
# Model resolution logic:
# 1. Check if MODEL_PATH exists → use it
# 2. If MODEL_URL set → download from URL
# 3. If MODEL_NAME set → download from HuggingFace
# ============================================

MODEL_DIR="/app/models"
HUGGINGFACE_BASE="https://huggingface.co/ggerganov/whisper.cpp/resolve/main"

# Ensure model directory exists
mkdir -p "$MODEL_DIR"

# Function to download model
download_model() {
    local url="$1"
    local dest="$2"
    
    echo "Downloading model from: $url"
    echo "Destination: $dest"
    
    if curl -L --progress-bar --fail -o "$dest" "$url"; then
        echo "Download complete!"
        return 0
    else
        echo "ERROR: Failed to download model"
        return 1
    fi
}

# Check if model exists at MODEL_PATH
if [ -f "$MODEL_PATH" ]; then
    echo "Found model at: $MODEL_PATH"
    
# If MODEL_URL is provided, download from custom URL
elif [ -n "$MODEL_URL" ]; then
    echo "Model not found, downloading from MODEL_URL..."
    download_model "$MODEL_URL" "$MODEL_PATH"
    
# If MODEL_NAME is provided, download from HuggingFace
elif [ -n "$MODEL_NAME" ]; then
    echo "Model not found, downloading '$MODEL_NAME' from HuggingFace..."
    MODEL_URL="${HUGGINGFACE_BASE}/ggml-${MODEL_NAME}.bin"
    download_model "$MODEL_URL" "$MODEL_PATH"
    
else
    echo "ERROR: No model found and no download source specified."
    echo ""
    echo "Options:"
    echo "  1. Mount model: -v /path/to/model.bin:/app/models/model.bin"
    echo "  2. Set MODEL_URL: -e MODEL_URL=https://example.com/model.bin"
    echo "  3. Set MODEL_NAME: -e MODEL_NAME=large-v3-turbo-q8_0"
    echo ""
    echo "Available MODEL_NAME values:"
    echo "  tiny, tiny.en, base, base.en, small, small.en"
    echo "  medium, medium.en, large-v1, large-v2, large-v3"
    echo "  large-v3-turbo, large-v3-turbo-q8_0, large-v3-turbo-q5_0"
    exit 1
fi

# Verify model exists before starting
if [ ! -f "$MODEL_PATH" ]; then
    echo "ERROR: Model file not found at $MODEL_PATH"
    exit 1
fi

echo "Starting whisper-server with model: $MODEL_PATH"
echo "============================================"

# Start the server
# --convert: uses ffmpeg to convert any audio format (mp3, ogg, flac, m4a, etc) to wav
exec whisper-server \
    -m "$MODEL_PATH" \
    --host 0.0.0.0 \
    --port 8080 \
    --convert \
    --inference-path /v1/audio/transcriptions
