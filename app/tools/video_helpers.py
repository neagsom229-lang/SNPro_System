"""
app/tools/video_helpers.py

Small, focused ffmpeg-first / moviepy-fallback helpers for pulling audio out
of a video and muxing a new audio track back in. Used by the Video Speech
Translator tool, but generic enough to reuse elsewhere.

Mirrors the ffmpeg-first-then-moviepy-fallback pattern already used in
app/tools/tasks.py (see _ffmpeg_remove_or_replace_audio / task_remove_audio).
"""

import os
import subprocess


def probe_duration(path):
    """Return media duration in seconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", path,
    ]
    import json
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    return float(data.get("format", {}).get("duration") or 0)


# ---------------------------------------------------------------------------
# Extract audio from video
# ---------------------------------------------------------------------------

def _ffmpeg_extract_audio(video_path, output_audio_path):
    ext = os.path.splitext(output_audio_path)[1].lower()
    cmd = ["ffmpeg", "-y", "-i", video_path, "-vn"]
    if ext == ".wav":
        cmd += ["-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1"]
    elif ext == ".mp3":
        cmd += ["-q:a", "2"]
    subprocess.run(cmd + [output_audio_path], check=True, capture_output=True, text=True)
    return output_audio_path


def _moviepy_extract_audio(video_path, output_audio_path):
    import moviepy.editor as mp
    clip = mp.VideoFileClip(video_path)
    if clip.audio is None:
        raise RuntimeError("This video has no audio track.")
    clip.audio.write_audiofile(output_audio_path, logger=None)
    clip.close()
    return output_audio_path


def extract_audio_from_video(video_path, output_audio_path):
    """
    Pull the audio track out of a video file. Tries ffmpeg first (fast,
    no re-encoding of the video); falls back to moviepy if ffmpeg is
    unavailable or the call fails.
    """
    try:
        _ffmpeg_extract_audio(video_path, output_audio_path)
        if not os.path.exists(output_audio_path) or os.path.getsize(output_audio_path) == 0:
            raise RuntimeError("ffmpeg produced an empty audio file.")
        return output_audio_path
    except Exception:
        return _moviepy_extract_audio(video_path, output_audio_path)


# ---------------------------------------------------------------------------
# Replace audio in video
# ---------------------------------------------------------------------------

def _ffmpeg_replace_audio(video_path, new_audio_path, output_video_path):
    """
    Mux `new_audio_path` onto `video_path`'s picture track, keeping the
    video stream untouched (stream copy - no quality loss, fast).

    The new audio is padded with silence if it's shorter than the video
    (`apad`) and the whole output is capped at the video's own length
    (`-shortest`), so dubbed speech that runs long doesn't cut the video
    short and speech that runs short doesn't leave the video without an
    audio track partway through.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", new_audio_path,
        "-filter_complex", "[1:a]apad[a]",
        "-map", "0:v:0", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-shortest",
        output_video_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return output_video_path


def _moviepy_replace_audio(video_path, new_audio_path, output_video_path):
    import moviepy.editor as mp

    video = mp.VideoFileClip(video_path)
    new_audio = mp.AudioFileClip(new_audio_path)

    if new_audio.duration > video.duration:
        new_audio = new_audio.subclip(0, video.duration)
    # NOTE: unlike the ffmpeg path above, this fallback does not pad short
    # audio with silence - if the dubbed speech is shorter than the video,
    # the video will simply play silently for the remainder. Good enough
    # for a fallback path; the primary ffmpeg path handles this properly.

    final = video.set_audio(new_audio)
    final.write_videofile(output_video_path, codec="libx264", audio_codec="aac", logger=None)
    video.close()
    new_audio.close()
    return output_video_path


def replace_audio_in_video(video_path, new_audio_path, output_video_path):
    """
    Replace a video's audio track with `new_audio_path`. Tries ffmpeg first
    (stream-copies the video, so no re-encoding/quality loss); falls back
    to moviepy (slower, re-encodes video) if ffmpeg is unavailable or fails.
    """
    try:
        _ffmpeg_replace_audio(video_path, new_audio_path, output_video_path)
        if not os.path.exists(output_video_path) or os.path.getsize(output_video_path) == 0:
            raise RuntimeError("ffmpeg produced an empty video file.")
        return output_video_path
    except Exception:
        return _moviepy_replace_audio(video_path, new_audio_path, output_video_path)