import os
import tempfile
import threading
from flask import Flask, request, jsonify
import whisper

# محاولة توفير ffmpeg بدون Dockerfile
try:
    import imageio_ffmpeg
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    ffmpeg_dir = os.path.dirname(ffmpeg_exe)
    os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    os.environ["FFMPEG_BINARY"] = ffmpeg_exe
except Exception:
    pass

app = Flask(__name__)

_model = None
_model_lock = threading.Lock()

def get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                mmodel_name = os.getenv("WHISPER_MODEL", "base")
                _model = whisper.load_model(model_name)
    return _model

@app.get("/")
def health():
    return "ok", 200

@app.post("/transcribe")
def transcribe():
    if "file" not in request.files:
        return jsonify({"error": "no audio file (field name must be 'file')"}), 400

    uploaded = request.files["file"]

    _, ext = os.path.splitext(uploaded.filename or "")
    if not ext:
        ext = ".mp4"

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp_path = tmp.name
            uploaded.save(tmp_path)

        model = get_model()

        result = model.transcribe(
            tmp_path,
            task="transcribe",
            language="ar",
            fp16=False
        )

        return jsonify({
            "text": (result.get("text") or "").strip()
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except:
                pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
