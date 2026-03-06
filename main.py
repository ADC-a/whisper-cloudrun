import os
import time
import tempfile
import subprocess
import threading
from pathlib import Path

print("main.py import started")

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from faster_whisper import WhisperModel

print("faster-whisper imports loaded")

app = FastAPI()
print("FastAPI app created")

MODEL_NAME = os.getenv("WHISPER_MODEL", "base")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", "1"))
LANGUAGE = os.getenv("WHISPER_LANGUAGE", "ar")

print(f"MODEL_NAME={MODEL_NAME}, COMPUTE_TYPE={COMPUTE_TYPE}, BEAM_SIZE={BEAM_SIZE}, LANGUAGE={LANGUAGE}")

_model = None
_model_lock = threading.Lock()


def get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                print("Loading Whisper model...")
                _model = WhisperModel(
                    MODEL_NAME,
                    device="cpu",
                    compute_type=COMPUTE_TYPE,
                    cpu_threads=max(1, os.cpu_count() or 1),
                )
                print("Whisper model loaded successfully")
    return _model


def run_ffmpeg(cmd):
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg failed")


def preprocess_audio(input_path, workdir):
    converted_path = str(Path(workdir) / "converted.wav")
    trimmed_path = str(Path(workdir) / "trimmed.wav")

    print("Running ffmpeg convert...")
    run_ffmpeg([
        "ffmpeg",
        "-y",
        "-i", input_path,
        "-ac", "1",
        "-ar", "16000",
        "-vn",
        converted_path,
    ])

    try:
        print("Running ffmpeg silence remove...")
        run_ffmpeg([
            "ffmpeg",
            "-y",
            "-i", converted_path,
            "-af",
            "silenceremove=start_periods=1:start_silence=0.25:start_threshold=-35dB:"
            "stop_periods=1:stop_silence=0.25:stop_threshold=-35dB",
            trimmed_path,
        ])

        if os.path.exists(trimmed_path) and os.path.getsize(trimmed_path) > 1024:
            print("Using trimmed audio")
            return trimmed_path
    except Exception as e:
        print(f"Silence remove skipped: {e}")

    print("Using converted audio")
    return converted_path


@app.get("/")
def health():
    print("Health endpoint hit")
    return {"status": "ok", "model": MODEL_NAME, "compute_type": COMPUTE_TYPE}


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    start_time = time.time()
    print("Transcribe endpoint hit")

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    suffix = Path(file.filename).suffix.lower() or ".tmp"

    with tempfile.TemporaryDirectory() as temp_dir:
        input_path = str(Path(temp_dir) / f"input{suffix}")

        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Empty file")

        with open(input_path, "wb") as f:
            f.write(content)

        try:
            processed_path = preprocess_audio(input_path, temp_dir)

            model = get_model()
            print("Starting transcription...")
            segments, info = model.transcribe(
                processed_path,
                language=LANGUAGE,
                beam_size=BEAM_SIZE,
                vad_filter=True,
            )

            text = " ".join(segment.text.strip() for segment in segments).strip()
            print(f"Transcription done in {round(time.time() - start_time, 2)}s")

            return JSONResponse({
                "text": text,
                "language": getattr(info, "language", LANGUAGE),
                "duration": getattr(info, "duration", None),
                "processing_time": round(time.time() - start_time, 2),
                "model": MODEL_NAME,
            })

        except HTTPException:
            raise
        except Exception as e:
            print(f"Transcription error: {e}")
            return JSONResponse(
                status_code=500,
                content={
                    "error": str(e),
                    "processing_time": round(time.time() - start_time, 2),
                },
            )
