#!/usr/bin/env python3

import os
import signal
import subprocess
import sys
import time
from datetime import datetime

# --- Configuration ---
WHISPER_URL = os.getenv("WHISPER_URL", "http://127.0.0.1:8002")
ENDPOINT = "/v1/audio/transcriptions"
AUDIO_FILE_TMP = "/tmp/whisper_recording.wav"
PID_FILE = "/tmp/whisper_tray.pid"

# Audio recording settings
ARECORD_RATE = "16000"
ARECORD_CHANNELS = "1"
ARECORD_FORMAT = "s16le"

# YAD Notification Configuration
ICON_NAME_IDLE = "audio-input-microphone"
ICON_NAME_RECORDING = "media-record"
ICON_NAME_PROCESSING = "system-search"
TOOLTIP_IDLE = "Whisper: Idle (Press Ctrl+Alt+V to record)"
TOOLTIP_RECORDING = "Whisper: Recording... (Press Ctrl+Alt+V to stop)"
TOOLTIP_PROCESSING = "Whisper: Processing..."

# --- Global State ---
is_recording = False
is_processing = False
arecord_process = None
yad_process = None

def log_message(message):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)

def check_command(command_name):
    try:
        subprocess.run(['which', command_name], check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError:
        return False

def send_yad_command(command_str):
    global yad_process
    if yad_process and yad_process.poll() is None:
        try:
            if yad_process.stdin:
                yad_process.stdin.write(f"{command_str.strip()}\n".encode('utf-8'))
                yad_process.stdin.flush()
        except (BrokenPipeError, AttributeError):
            log_message("ERROR: Broken pipe to yad")
            yad_process = None
        except Exception as e:
            log_message(f"ERROR: Could not send yad command: {e}")

def update_tray_icon_state():
    global is_recording, is_processing, yad_process
    if not yad_process:
        return

    if is_processing:
        send_yad_command(f"icon:{ICON_NAME_PROCESSING}")
        send_yad_command(f"tooltip:{TOOLTIP_PROCESSING}")
    elif is_recording:
        send_yad_command(f"icon:{ICON_NAME_RECORDING}")
        send_yad_command(f"tooltip:{TOOLTIP_RECORDING}")
    else:
        send_yad_command(f"icon:{ICON_NAME_IDLE}")
        send_yad_command(f"tooltip:{TOOLTIP_IDLE}")

def cleanup_resources():
    global arecord_process, yad_process
    log_message("Cleaning up...")

    if arecord_process and arecord_process.poll() is None:
        arecord_process.terminate()
        try:
            arecord_process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            arecord_process.kill()
            arecord_process.wait()

    if yad_process and yad_process.poll() is None:
        send_yad_command("quit")
        try:
            if yad_process.stdin:
                yad_process.stdin.close()
            yad_process.wait(timeout=2)
        except Exception:
            pass
        yad_process = None

    if os.path.exists(PID_FILE):
        try:
            os.remove(PID_FILE)
        except OSError as e:
            log_message(f"Error removing PID: {e}")

    if os.path.exists(AUDIO_FILE_TMP):
        try:
            os.remove(AUDIO_FILE_TMP)
        except OSError:
            pass

    exit(0)

def handle_exit_signal(signum, frame):
    log_message(f"Exit signal: {signum}")
    cleanup_resources()

def copy_to_clipboard(text):
    if not text:
        return False
    try:
        subprocess.run(['xsel', '-b', '-i'],
                     input=text.encode('utf-8'),
                     check=True, capture_output=True, timeout=2)
        log_message("Copied to clipboard")
        return True
    except subprocess.TimeoutExpired:
        log_message("ERROR: Clipboard timeout")
        return False
    except FileNotFoundError:
        log_message("ERROR: xsel not found, install it")
        return False
    except Exception as e:
        log_message(f"Clipboard error: {e}")
        return False

def create_wav_header(sample_rate, channels, bits_per_sample, data_size):
    header = bytearray()

    # RIFF header
    header.extend(b'RIFF')
    header.extend((36 + data_size).to_bytes(4, 'little'))
    header.extend(b'WAVE')

    # fmt chunk
    header.extend(b'fmt ')
    header.extend((16).to_bytes(4, 'little'))
    header.extend((1).to_bytes(2, 'little'))
    header.extend(channels.to_bytes(2, 'little'))
    header.extend(sample_rate.to_bytes(4, 'little'))
    header.extend((sample_rate * channels * bits_per_sample // 8).to_bytes(4, 'little'))
    header.extend((channels * bits_per_sample // 8).to_bytes(2, 'little'))
    header.extend(bits_per_sample.to_bytes(2, 'little'))

    # data chunk
    header.extend(b'data')
    header.extend(data_size.to_bytes(4, 'little'))

    return bytes(header)

def transcribe_audio():
    """Transcribe audio - BLOCKING, no threading"""
    global is_processing

    log_message("Starting transcription...")
    is_processing = True
    update_tray_icon_state()

    try:
        # Call Whisper server
        result = subprocess.run([
            'curl', '-s', '-X', 'POST',
            f"{WHISPER_URL}{ENDPOINT}",
            '-F', f'file=@{AUDIO_FILE_TMP}',
            '-F', 'model=whisper-1'
        ], capture_output=True, text=True, timeout=60)

        # Parse JSON
        import json
        try:
            response = json.loads(result.stdout)
            text = response.get('text', '').strip()
            text = text.replace('\\n', '\n').replace('\\"', '"')
        except json.JSONDecodeError:
            log_message(f"JSON error: {result.stdout}")
            text = None

        if text:
            log_message(f"Transcription: '{text}'")
            copy_to_clipboard(text)
        else:
            log_message("ERROR: No text in response")

    except subprocess.TimeoutExpired:
        log_message("ERROR: Timeout")
    except Exception as e:
        log_message(f"ERROR: {e}")

    finally:
        log_message("Cleaning up audio file and resetting state...")
        if os.path.exists(AUDIO_FILE_TMP):
            try:
                os.remove(AUDIO_FILE_TMP)
                log_message(f"Removed: {AUDIO_FILE_TMP}")
            except OSError:
                pass

        is_processing = False
        log_message(f"is_processing now: {is_processing}")
        update_tray_icon_state()
        log_message("Transcription complete - icon should be IDLE")

def toggle_recording_handler(signum, frame):
    """Toggle recording - BLOCKING, no threading"""
    global is_recording, is_processing, arecord_process

    if is_recording:
        log_message("STOPPING recording...")

        if arecord_process and arecord_process.poll() is None:
            arecord_process.terminate()
            try:
                arecord_process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                arecord_process.kill()
                arecord_process.wait()

        is_recording = False
        update_tray_icon_state()

        # BLOCKING transcription call
        transcribe_audio()

    else:
        if is_processing:
            log_message("Ignored - still processing")
            return

        log_message("STARTING recording...")

        arecord_cmd = [
            "ffmpeg",
            "-f", "pulse",
            "-i", "default",
            "-ac", ARECORD_CHANNELS,
            "-ar", ARECORD_RATE,
            "-f", "wav",
            "-acodec", "pcm_s16le",
            "-loglevel", "quiet",
            AUDIO_FILE_TMP
        ]

        try:
            arecord_process = subprocess.Popen(arecord_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(0.1)
            if arecord_process.poll() is not None:
                err = arecord_process.stderr.read().decode(errors='ignore').strip() if arecord_process.stderr else "Unknown"
                log_message(f"ERROR: {err}")
            else:
                is_recording = True
                update_tray_icon_state()
        except Exception as e:
            log_message(f"ERROR: {e}")

def start_yad_notification():
    global yad_process
    if not check_command("yad"):
        return None

    yad_cmd = [
        "yad", "--notification",
        f"--image={ICON_NAME_IDLE}",
        f"--text={TOOLTIP_IDLE}",
        "--listen"
    ]

    try:
        log_message("Starting YAD...")
        yad_process = subprocess.Popen(
            yad_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE
        )
        time.sleep(0.2)
        if yad_process.poll() is not None:
            err = yad_process.stderr.read().decode(errors='ignore').strip()
            log_message(f"ERROR: {err}")
            return None
        log_message("YAD started")
        return yad_process
    except Exception as e:
        log_message(f"ERROR: {e}")
        return None

def main():
    global yad_process

    if not check_command("xsel"):
        log_message("ERROR: xsel not found")
        sys.exit(1)
    if not check_command("ffmpeg"):
        log_message("ERROR: ffmpeg not found")
        sys.exit(1)

    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            log_message(f"Already running: {pid}")
            sys.exit(1)
        except (OSError, ValueError):
            try:
                os.remove(PID_FILE)
            except OSError:
                pass

    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

    signal.signal(signal.SIGTERM, handle_exit_signal)
    signal.signal(signal.SIGINT, handle_exit_signal)
    signal.signal(signal.SIGUSR1, toggle_recording_handler)

    yad_process = start_yad_notification()

    if yad_process:
        log_message("Tray active")
    else:
        log_message("WARNING: Tray inactive")

    log_message(f"Started PID {os.getpid()}. Ctrl+Alt+V to toggle.")

    try:
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        handle_exit_signal(signal.SIGINT, None)

if __name__ == "__main__":
    main()
