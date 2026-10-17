"""faster-whisper 음성 인식 (단어 단위 타임스탬프)."""
import logging

log = logging.getLogger(__name__)

_models: dict = {}


def transcribe(path: str, model_name: str = "small", language: str | None = "ko") -> list[dict]:
    """[{start, end, text, words:[{start,end,text}]}] 반환. 실패하면 빈 리스트."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        log.warning("faster-whisper 미설치: 자막 없이 진행합니다.")
        return []
    try:
        model = _models.get(model_name)
        if model is None:
            model = _models[model_name] = WhisperModel(model_name, device="auto", compute_type="int8")
        # PyAV 버전 차이 문제를 피하려고 ffmpeg로 직접 디코딩해서 넘김
        from .media import load_audio
        segments, _ = model.transcribe(load_audio(path), language=language, word_timestamps=True,
                                       vad_filter=True, beam_size=5)
        result = []
        for s in segments:
            words = [{"start": round(float(w.start), 2), "end": round(float(w.end), 2), "text": w.word.strip()}
                     for w in (s.words or []) if w.word.strip()]
            result.append({"start": round(float(s.start), 2), "end": round(float(s.end), 2),
                           "text": s.text.strip(), "words": words})
        return result
    except Exception:  # 음성 인식 실패해도 편집은 계속
        log.exception("음성 인식 실패")
        return []
