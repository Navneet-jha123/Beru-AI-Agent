"""One-shot local voice turn using faster-whisper, sounddevice, and pyttsx3."""
from __future__ import annotations
import os


def voice_turn(seconds: int = 8, mode: str = "General") -> str:
    """Record one bounded microphone turn, transcribe locally, run BERU, speak reply."""
    seconds = max(2, min(int(seconds), 20))
    try:
        import numpy as np
        import sounddevice as sd
        import pyttsx3
        from faster_whisper import WhisperModel
        from agent import run_agent
    except ImportError as exc:
        return f"Voice dependencies are missing: {exc}. Install the optional dependencies listed in the upgrade guide."
    try:
        sample_rate = 16000
        print(f"Recording for up to {seconds} seconds. Speak now; press Ctrl+C to cancel.")
        audio = sd.rec(int(seconds * sample_rate), samplerate=sample_rate, channels=1,
                       dtype="float32", blocking=True)
        signal = np.asarray(audio[:, 0], dtype=np.float32)
        if signal.size == 0 or float(np.max(np.abs(signal))) < 0.003:
            return "No speech was detected."
        model_name = os.getenv("BERU_WHISPER_MODEL", "base")
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(signal, beam_size=3, vad_filter=True)
        transcript = " ".join(seg.text.strip() for seg in segments).strip()
        if not transcript:
            return "Speech could not be transcribed."
        print(f"You said: {transcript}")
        answer = run_agent(transcript, mode=mode)
        engine = pyttsx3.init()
        engine.say(answer[:3000])
        engine.runAndWait()
        return f"Transcript: {transcript}\n\nBERU: {answer}"
    except KeyboardInterrupt:
        return "Voice recording cancelled."
    except Exception as exc:
        return f"Voice turn failed: {type(exc).__name__}: {exc}"
