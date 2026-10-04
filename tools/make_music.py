"""릴스용 배경음악을 코드로 직접 작곡한다 (저작권 문제 없음).

python tools/make_music.py  →  music/*.mp3 (약 32초, 곡마다 템포·조·멜로디가 다름)
numpy 필요 (개발용 스크립트라 requirements.txt 에는 없음).
"""

from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import imageio_ffmpeg
import numpy as np

SR = 44100
OUT = Path(__file__).resolve().parent.parent / "music"

# (이름, 템포, 으뜸음 MIDI, 진행(반음 단위 근음), 스케일, 시드)
SONGS = [
    ("nyang_bounce", 116, 60, [0, 9, 5, 7], [0, 2, 4, 7, 9], 1),
    ("detective_walk", 104, 57, [0, 5, 7, 5], [0, 3, 5, 7, 10], 2),
    ("funny_trot", 124, 62, [0, 7, 9, 5], [0, 2, 4, 7, 9], 3),
    ("lazy_cat", 96, 55, [0, 9, 2, 7], [0, 2, 4, 7, 9], 4),
    ("news_flash", 128, 59, [0, 5, 0, 7], [0, 2, 5, 7, 9], 5),
]


def freq(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def env(n: int, attack: float, decay: float) -> np.ndarray:
    t = np.arange(n) / SR
    return np.minimum(t / attack, 1.0) * np.exp(-t / decay)


def pluck(f: float, dur: float) -> np.ndarray:
    n = int(SR * dur)
    t = np.arange(n) / SR
    wave_ = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * 2 * f * t) + 0.12 * np.sin(2 * np.pi * 3 * f * t)
    return wave_ * env(n, 0.004, 0.22)


def bass(f: float, dur: float) -> np.ndarray:
    n = int(SR * dur)
    t = np.arange(n) / SR
    return (np.sin(2 * np.pi * f * t) + 0.25 * np.sin(2 * np.pi * 2 * f * t)) * env(n, 0.01, dur * 0.8)


def pad(freqs: list[float], dur: float) -> np.ndarray:
    n = int(SR * dur)
    t = np.arange(n) / SR
    s = sum(np.sin(2 * np.pi * f * t) for f in freqs) / len(freqs)
    return s * np.minimum(t / 0.08, 1.0) * np.minimum((dur - t) / 0.12, 1.0)


def kick(rng) -> np.ndarray:
    n = int(SR * 0.22)
    t = np.arange(n) / SR
    return np.sin(2 * np.pi * (50 + 110 * np.exp(-t * 28)) * t) * np.exp(-t * 14)


def hat(rng) -> np.ndarray:
    n = int(SR * 0.05)
    return rng.standard_normal(n) * np.exp(-np.arange(n) / SR * 90) * 0.5


def snap(rng) -> np.ndarray:
    n = int(SR * 0.12)
    t = np.arange(n) / SR
    return (rng.standard_normal(n) * 0.6 + np.sin(2 * np.pi * 190 * t) * 0.4) * np.exp(-t * 28)


def mix(track: np.ndarray, clip: np.ndarray, start: int, gain: float) -> None:
    end = min(len(track), start + len(clip))
    if start < end:
        track[start:end] += clip[: end - start] * gain


def compose(name: str, bpm: int, root: int, chords: list[int], scale: list[int], seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    beat = 60 / bpm
    bars = 16  # 4/4 16마디
    total = int(SR * beat * 4 * bars) + SR
    track = np.zeros(total)
    for bar in range(bars):
        c = chords[bar % len(chords)]
        t0 = bar * 4 * beat
        triad = [freq(root + c + iv) for iv in (0, 4 if c in (0, 5, 7) else 3, 7)]
        mix(track, pad(triad, beat * 4), int(SR * t0), 0.16)
        for b in range(4):  # 베이스: 1·3박 근음, 2·4박 5도
            note = root - 12 + c + (0 if b % 2 == 0 else 7)
            mix(track, bass(freq(note), beat * 0.9), int(SR * (t0 + b * beat)), 0.5)
            mix(track, kick(rng), int(SR * (t0 + b * beat)), 0.7 if b % 2 == 0 else 0.0)
            if b % 2 == 1:
                mix(track, snap(rng), int(SR * (t0 + b * beat)), 0.35)
        for e in range(8):  # 8분음표 하이햇
            mix(track, hat(rng), int(SR * (t0 + e * beat / 2 + beat / 4)), 0.22)
        # 멜로디: 8마디 단위로 같은 프레이즈를 반복해 귀에 남게
        phrase_rng = np.random.default_rng(seed * 100 + bar % 4)
        pos = 0.0
        while pos < 4 * beat - 1e-6:
            length = phrase_rng.choice([0.5, 0.5, 1.0, 1.5]) * beat
            length = min(length, 4 * beat - pos)
            if phrase_rng.random() > 0.2 and bar >= 2:
                deg = int(phrase_rng.integers(0, len(scale) * 2))
                midi = root + 12 + c * 0 + scale[deg % len(scale)] + 12 * (deg // len(scale))
                mix(track, pluck(freq(midi), length + 0.15), int(SR * (t0 + pos)), 0.38)
            pos += length
    track = track[: int(SR * beat * 4 * bars)]
    fade = int(SR * 1.5)
    track[-fade:] *= np.linspace(1, 0, fade)
    track /= max(np.abs(track).max(), 1e-9) / 0.85
    return track


def main() -> None:
    OUT.mkdir(exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    for name, bpm, root, chords, scale, seed in SONGS:
        audio = compose(name, bpm, root, chords, scale, seed)
        wav_path = OUT / f"{name}.wav"
        with wave.open(str(wav_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes((audio * 32767).astype(np.int16).tobytes())
        mp3 = OUT / f"{name}.mp3"
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(wav_path), "-b:a", "96k", str(mp3)], check=True)
        wav_path.unlink()
        print(mp3, f"{len(audio) / SR:.1f}s", f"{mp3.stat().st_size // 1024}KB")


if __name__ == "__main__":
    main()
