"""Audacity CLI - Audio utility functions.

Pure Python audio processing using only stdlib (wave, struct, math, array).
These functions handle raw PCM audio data as lists or arrays of samples.

All internal audio is represented as lists of float samples in [-1.0, 1.0].
Multi-channel audio is interleaved: [L0, R0, L1, R1, ...].
"""

import math
import struct
import wave
import array
import os
from typing import List, Tuple, Optional


def generate_sine_wave(
    frequency: float = 440.0,
    duration: float = 1.0,
    sample_rate: int = 44100,
    amplitude: float = 0.5,
    channels: int = 1,
) -> List[float]:
    """Generate a sine wave as a list of float samples [-1.0, 1.0]."""
    num_samples = int(duration * sample_rate)
    samples = []
    for i in range(num_samples):
        t = i / sample_rate
        val = amplitude * math.sin(2.0 * math.pi * frequency * t)
        for _ in range(channels):
            samples.append(val)
    return samples


def generate_silence(
    duration: float = 1.0,
    sample_rate: int = 44100,
    channels: int = 1,
) -> List[float]:
    """Generate silence as a list of zero-valued float samples."""
    num_samples = int(duration * sample_rate) * channels
    return [0.0] * num_samples


def mix_audio(
    tracks: List[List[float]],
    volumes: Optional[List[float]] = None,
    pans: Optional[List[float]] = None,
    channels: int = 2,
) -> List[float]:
    """Mix multiple audio tracks together.

    Args:
        tracks: List of track sample arrays (each interleaved if stereo).
        volumes: Volume multiplier per track (default 1.0 each).
        pans: Pan position per track (-1.0=left, 0.0=center, 1.0=right).
              Only applicable when channels=2.
        channels: Output channel count (1 or 2).

    Returns:
        Mixed audio as interleaved float samples.
    """
    if not tracks:
        return []

    if volumes is None:
        volumes = [1.0] * len(tracks)
    if pans is None:
        pans = [0.0] * len(tracks)

    # Find max length
    max_len = max(len(t) for t in tracks)
    # Ensure length is a multiple of channels
    if max_len % channels != 0:
        max_len += channels - (max_len % channels)

    mixed = [0.0] * max_len

    for track_idx, track in enumerate(tracks):
        vol = volumes[track_idx] if track_idx < len(volumes) else 1.0
        pan = pans[track_idx] if track_idx < len(pans) else 0.0

        # Pan law: equal power
        if channels == 2:
            pan_angle = (pan + 1.0) * math.pi / 4.0  # 0 to pi/2
            left_gain = math.cos(pan_angle) * vol
            right_gain = math.sin(pan_angle) * vol
        else:
            left_gain = vol
            right_gain = vol

        for i in range(0, min(len(track), max_len), channels):
            if channels == 2:
                # Source might be mono or stereo
                left_sample = track[i] if i < len(track) else 0.0
                right_sample = track[i + 1] if (i + 1) < len(track) else left_sample
                mixed[i] += left_sample * left_gain
                mixed[i + 1] += right_sample * right_gain
            else:
                mixed[i] += (track[i] if i < len(track) else 0.0) * vol

    return mixed


def apply_gain(samples: List[float], gain_db: float) -> List[float]:
    """Apply gain in decibels to audio samples."""
    factor = 10.0 ** (gain_db / 20.0)
    return [s * factor for s in samples]


def apply_fade_in(
    samples: List[float],
    duration: float,
    sample_rate: int = 44100,
    channels: int = 1,
) -> List[float]:
    """Apply a linear fade-in to audio samples."""
    fade_samples = int(duration * sample_rate)
    total_frames = len(samples) // channels
    result = list(samples)

    for frame in range(min(fade_samples, total_frames)):
        factor = frame / fade_samples
        for ch in range(channels):
            idx = frame * channels + ch
            if idx < len(result):
                result[idx] *= factor

    return result


def apply_fade_out(
    samples: List[float],
    duration: float,
    sample_rate: int = 44100,
    channels: int = 1,
) -> List[float]:
    """Apply a linear fade-out to audio samples."""
    fade_samples = int(duration * sample_rate)
    total_frames = len(samples) // channels
    result = list(samples)

    for frame in range(min(fade_samples, total_frames)):
        # Count from end
        frame_from_end = total_frames - 1 - frame
        factor = frame / fade_samples
        for ch in range(channels):
            idx = frame_from_end * channels + ch
            if 0 <= idx < len(result):
                result[idx] *= factor

    return result


def apply_reverse(samples: List[float], channels: int = 1) -> List[float]:
    """Reverse audio samples (frame-by-frame)."""
    if channels == 1:
        return list(reversed(samples))

    # Reverse by frames
    total_frames = len(samples) // channels
    result = []
    for frame in range(total_frames - 1, -1, -1):
        start = frame * channels
        for ch in range(channels):
            if start + ch < len(samples):
                result.append(samples[start + ch])
    return result


def apply_echo(
    samples: List[float],
    delay_ms: float = 500.0,
    decay: float = 0.5,
    sample_rate: int = 44100,
    channels: int = 1,
) -> List[float]:
    """Apply an echo effect to audio samples."""
    delay_frames = int((delay_ms / 1000.0) * sample_rate)
    delay_samples = delay_frames * channels

    # Extend output to fit echo tail
    result = list(samples) + [0.0] * delay_samples

    for i in range(len(samples)):
        target = i + delay_samples
        if target < len(result):
            result[target] += samples[i] * decay

    return result


def apply_low_pass(
    samples: List[float],
    cutoff: float = 1000.0,
    sample_rate: int = 44100,
    channels: int = 1,
) -> List[float]:
    """Apply a simple single-pole low-pass filter."""
    rc = 1.0 / (2.0 * math.pi * cutoff)
    dt = 1.0 / sample_rate
    alpha = dt / (rc + dt)

    result = list(samples)
    for ch in range(channels):
        prev = 0.0
        for frame in range(len(samples) // channels):
            idx = frame * channels + ch
            if idx < len(result):
                result[idx] = prev + alpha * (samples[idx] - prev)
                prev = result[idx]

    return result


def apply_high_pass(
    samples: List[float],
    cutoff: float = 100.0,
    sample_rate: int = 44100,
    channels: int = 1,
) -> List[float]:
    """Apply a simple single-pole high-pass filter."""
    rc = 1.0 / (2.0 * math.pi * cutoff)
    dt = 1.0 / sample_rate
    alpha = rc / (rc + dt)

    result = list(samples)
    for ch in range(channels):
        prev_in = 0.0
        prev_out = 0.0
        for frame in range(len(samples) // channels):
            idx = frame * channels + ch
            if idx < len(result):
                result[idx] = alpha * (prev_out + samples[idx] - prev_in)
                prev_in = samples[idx]
                prev_out = result[idx]

    return result


def apply_normalize(
    samples: List[float],
    target_db: float = -1.0,
) -> List[float]:
    """Normalize audio to a target peak level in dB."""
    if not samples:
        return samples

    peak = max(abs(s) for s in samples)
    if peak == 0:
        return list(samples)

    target_linear = 10.0 ** (target_db / 20.0)
    factor = target_linear / peak
    return [s * factor for s in samples]


def apply_change_speed(
    samples: List[float],
    factor: float = 1.0,
    channels: int = 1,
) -> List[float]:
    """Change speed by resampling (linear interpolation)."""
    if factor <= 0:
        raise ValueError("Speed factor must be > 0")

    total_frames = len(samples) // channels
    new_frame_count = int(total_frames / factor)
    result = []

    for new_frame in range(new_frame_count):
        src_frame = new_frame * factor
        src_frame_int = int(src_frame)
        frac = src_frame - src_frame_int

        for ch in range(channels):
            idx1 = src_frame_int * channels + ch
            idx2 = (src_frame_int + 1) * channels + ch

            s1 = samples[idx1] if idx1 < len(samples) else 0.0
            s2 = samples[idx2] if idx2 < len(samples) else 0.0

            result.append(s1 + frac * (s2 - s1))

    return result


def apply_limit(
    samples: List[float],
    threshold_db: float = -1.0,
) -> List[float]:
    """Apply hard limiter at the given threshold."""
    threshold = 10.0 ** (threshold_db / 20.0)
    result = []
    for s in samples:
        if s > threshold:
            result.append(threshold)
        elif s < -threshold:
            result.append(-threshold)
        else:
            result.append(s)
    return result


def clamp_samples(samples: List[float]) -> List[float]:
    """Clamp samples to [-1.0, 1.0] range."""
    return [max(-1.0, min(1.0, s)) for s in samples]


def samples_to_wav_bytes(
    samples: List[float],
    sample_rate: int = 44100,
    channels: int = 1,
    bit_depth: int = 16,
) -> bytes:
    """Convert float samples to WAV file bytes."""
    import io

    clamped = clamp_samples(samples)

    if bit_depth == 16:
        max_val = 32767
        fmt = "<h"
        sample_width = 2
    elif bit_depth == 8:
        max_val = 127
        fmt = "<b"
        sample_width = 1
    elif bit_depth == 24:
        max_val = 8388607
        sample_width = 3
        fmt = None  # Special handling for 24-bit
    elif bit_depth == 32:
        max_val = 2147483647
        fmt = "<i"
        sample_width = 4
    else:
        raise ValueError(f"Unsupported bit depth: {bit_depth}")

    raw = bytearray()
    for s in clamped:
        int_val = int(s * max_val)
        int_val = max(-max_val - 1, min(max_val, int_val))
        if bit_depth == 24:
            # Pack 24-bit as 3 bytes little-endian
            raw.extend(struct.pack("<i", int_val)[:3])
        else:
            raw.extend(struct.pack(fmt, int_val))

    buf = io.BytesIO()
    with wave.open(buf, "w") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(raw))

    return buf.getvalue()


def write_wav(
    path: str,
    samples: List[float],
    sample_rate: int = 44100,
    channels: int = 1,
    bit_depth: int = 16,
) -> str:
    """Write float samples to a WAV file."""
    clamped = clamp_samples(samples)

    if bit_depth == 16:
        max_val = 32767
        fmt = "<h"
        sample_width = 2
    elif bit_depth == 8:
        max_val = 127
        fmt = "<b"
        sample_width = 1
    elif bit_depth == 24:
        max_val = 8388607
        sample_width = 3
        fmt = None
    elif bit_depth == 32:
        max_val = 2147483647
        fmt = "<i"
        sample_width = 4
    else:
        raise ValueError(f"Unsupported bit depth: {bit_depth}")

    raw = bytearray()
    for s in clamped:
        int_val = int(s * max_val)
        int_val = max(-max_val - 1, min(max_val, int_val))
        if bit_depth == 24:
            raw.extend(struct.pack("<i", int_val)[:3])
        else:
            raw.extend(struct.pack(fmt, int_val))

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with wave.open(path, "w") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(raw))

    return os.path.abspath(path)


def read_wav(path: str) -> Tuple[List[float], int, int, int]:
    """Read a WAV file and return (samples, sample_rate, channels, bit_depth).

    Returns float samples in [-1.0, 1.0].
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"WAV file not found: {path}")

    with wave.open(path, "r") as wf:
        sample_rate = wf.getframerate()
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        bit_depth = sample_width * 8
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    samples = []
    if bit_depth == 16:
        max_val = 32767.0
        fmt = "<h"
        step = 2
    elif bit_depth == 8:
        # 8-bit WAV is unsigned
        max_val = 128.0
        fmt = None  # Special handling
        step = 1
    elif bit_depth == 24:
        max_val = 8388607.0
        fmt = None
        step = 3
    elif bit_depth == 32:
        max_val = 2147483647.0
        fmt = "<i"
        step = 4
    else:
        raise ValueError(f"Unsupported bit depth: {bit_depth}")

    total_samples = n_frames * channels
    for i in range(total_samples):
        offset = i * step
        if offset + step > len(raw):
            break

        if bit_depth == 8:
            # Unsigned 8-bit
            val = raw[offset]
            samples.append((val - 128) / max_val)
        elif bit_depth == 24:
            # 24-bit little-endian signed
            b = raw[offset:offset + 3]
            int_val = struct.unpack("<i", b + (b"\xff" if b[2] & 0x80 else b"\x00"))[0]
            samples.append(int_val / max_val)
        else:
            int_val = struct.unpack(fmt, raw[offset:offset + step])[0]
            samples.append(int_val / max_val)

    return samples, sample_rate, channels, bit_depth


def get_rms(samples: List[float]) -> float:
    """Calculate RMS (Root Mean Square) level of audio samples."""
    if not samples:
        return 0.0
    sum_sq = sum(s * s for s in samples)
    return math.sqrt(sum_sq / len(samples))


def get_peak(samples: List[float]) -> float:
    """Get peak absolute sample value."""
    if not samples:
        return 0.0
    return max(abs(s) for s in samples)


def db_from_linear(linear: float) -> float:
    """Convert linear amplitude to decibels."""
    if linear <= 0:
        return -math.inf
    return 20.0 * math.log10(linear)


def goertzel_magnitude(samples: List[float], sample_rate: int, freq: float) -> float:
    """Calculate magnitude at a specific frequency using Goertzel algorithm.

    More efficient than FFT for single frequency detection.
    Matches verifier implementation in audacity.py:382-396.

    Args:
        samples: List of float samples in [-1.0, 1.0]
        sample_rate: Sample rate in Hz
        freq: Target frequency in Hz

    Returns:
        Normalized magnitude (0.0 to 1.0)
    """
    n = len(samples)
    if n == 0 or sample_rate <= 0:
        return 0.0

    omega = 2.0 * math.pi * freq / sample_rate
    coeff = 2.0 * math.cos(omega)
    s_prev = 0.0
    s_prev2 = 0.0

    for x in samples:
        s = x + coeff * s_prev - s_prev2
        s_prev2 = s_prev
        s_prev = s

    power = s_prev2 * s_prev2 + s_prev * s_prev - coeff * s_prev * s_prev2
    magnitude = math.sqrt(max(0.0, power)) / max(1, n)

    return magnitude


def dominant_frequency(
    samples: List[float],
    sample_rate: int,
    fmin: float = 50.0,
    fmax: Optional[float] = None,
    step_hz: float = 5.0
) -> float:
    """Find the dominant frequency in audio samples.

    Uses Goertzel algorithm to scan frequency range.
    Matches verifier implementation in audacity.py:399-427.

    Args:
        samples: List of float samples in [-1.0, 1.0]
        sample_rate: Sample rate in Hz
        fmin: Minimum frequency to scan (Hz)
        fmax: Maximum frequency to scan (Hz). Defaults to Nyquist - 100
        step_hz: Frequency step for coarse scan (Hz)

    Returns:
        Dominant frequency in Hz, or 0.0 if no samples
    """
    if not samples:
        return 0.0

    if fmax is None:
        fmax = sample_rate / 2.0 - 100.0

    best_f = 0.0
    best_mag = -1.0

    # Coarse scan
    f = fmin
    while f <= fmax:
        m = goertzel_magnitude(samples, sample_rate, f)
        if m > best_mag:
            best_mag = m
            best_f = f
        f += step_hz

    # Refine around best frequency
    refine_lo = max(fmin, best_f - step_hz)
    refine_hi = min(fmax, best_f + step_hz)
    f = refine_lo
    while f <= refine_hi:
        m = goertzel_magnitude(samples, sample_rate, f)
        if m > best_mag:
            best_mag = m
            best_f = f
        f += 0.5

    return best_f


def band_energy_ratio(samples: List[float], sample_rate: int, cutoff_hz: float) -> float:
    """Calculate ratio of energy above cutoff to total energy.

    Uses one-pole high-pass filter.
    Matches verifier implementation in audacity.py:430-452.

    Args:
        samples: List of float samples in [-1.0, 1.0]
        sample_rate: Sample rate in Hz
        cutoff_hz: Cutoff frequency for high-pass filter (Hz)

    Returns:
        Ratio of energy above cutoff (0.0 to 1.0)
    """
    if not samples:
        return 0.0

    total_e = sum(s * s for s in samples)
    if total_e <= 0.0:
        return 0.0

    # One-pole high-pass filter
    # alpha = RC/(RC+dt); fc = 1/(2*pi*RC)
    dt = 1.0 / sample_rate
    rc = 1.0 / (2.0 * math.pi * cutoff_hz)
    alpha = rc / (rc + dt)

    y_prev = 0.0
    x_prev = 0.0
    hp_e = 0.0

    for x in samples:
        y = alpha * (y_prev + x - x_prev)
        hp_e += y * y
        y_prev = y
        x_prev = x

    return hp_e / total_e


def peak_db(samples: List[float]) -> float:
    """Calculate peak level in dBFS.

    Args:
        samples: List of float samples in [-1.0, 1.0]

    Returns:
        Peak level in dBFS (negative values, -inf for silence)
    """
    if not samples:
        return -math.inf

    peak = max(abs(s) for s in samples)
    if peak <= 0.0:
        return -math.inf

    return 20.0 * math.log10(peak)


def rms_db(samples: List[float]) -> float:
    """Calculate RMS level in dBFS.

    Args:
        samples: List of float samples in [-1.0, 1.0]

    Returns:
        RMS level in dBFS (negative values, -inf for silence)
    """
    if not samples:
        return -math.inf

    rms = get_rms(samples)
    if rms <= 0.0:
        return -math.inf

    return 20.0 * math.log10(rms)
