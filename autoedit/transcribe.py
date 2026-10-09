"""faster-whisper로 단어 단위 타임스탬프가 있는 한국어 대본을 만든다."""
import json
import subprocess
from pathlib import Path


def transcribe(video: Path, out_json: Path, model_name: str = "large-v3-turbo") -> list[dict]:
    """단어 목록 [{"w": 단어, "s": 시작초, "e": 끝초}] 을 out_json에 저장하고 반환한다.

    이미 out_json이 있으면 다시 인식하지 않고 읽어서 돌려준다.
    """
    if out_json.exists():
        return json.loads(out_json.read_text(encoding="utf-8"))

    import numpy as np
    from faster_whisper import WhisperModel

    # PyAV 버전 차이를 피하려고 오디오는 ffmpeg로 직접 16kHz 모노 PCM으로 뽑는다.
    pcm = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
         "-f", "s16le", "-"],
        check=True, capture_output=True,
    ).stdout
    audio = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(
        audio,
        language="ko",
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300},
        condition_on_previous_text=False,
    )
    words = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append({"w": text, "s": round(w.start, 3), "e": round(w.end, 3)})
        print(f"  인식 {seg.end:7.1f}s  {seg.text.strip()[:40]}", flush=True)

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(words, ensure_ascii=False, indent=0), encoding="utf-8")
    return words
