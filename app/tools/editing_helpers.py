"""
app/tools/editing_helpers.py

Building blocks for the Automated Video Editing Pipeline (auto-edit-video).

Design choice: most steps use ffmpeg directly (fast, stream-copy where
possible, no Python-side frame decoding) rather than MoviePy. MoviePy is
kept as the engine for the two things ffmpeg can't do cleanly on its own -
compositing multiple text overlays with per-element timing/animation, and
as a general fallback if an ffmpeg filter step fails. This mirrors the
ffmpeg-first/moviepy-fallback pattern already used elsewhere in tasks.py.

Public functions:
    load_template(name_or_path)                 -> dict
    detect_silences(audio_path, ...)             -> list[(start, end)] (seconds, SILENT ranges)
    trim_silence(video_path, out_path, ...)      -> (out_path, removed_seconds)
    concatenate_clips(clip_paths, out_path, ...) -> out_path
    apply_transitions(clip_paths, out_path, transition_type, duration) -> out_path
    overlay_text(video_path, out_path, text, style, start=0, duration=None) -> out_path
    duck_background_music(voice_audio_path, music_path, out_path, level) -> out_path
    burn_captions(video_path, srt_path, out_path, style=None)  -> out_path
    render_video(...) is just render via ffmpeg encode, folded into the
        functions above (each writes a real file, not an in-memory clip).
    export_multiple_formats(video_path, formats, out_dir)      -> {format: path}
"""
import json
import os
import subprocess

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

DEFAULT_TEMPLATE = {
    "name": "Default",
    "transition": {"type": "crossfade", "duration": 0.5},
    "text_style": {
        "font": "Arial", "size": 42, "color": "white",
        "position": "bottom", "outline_color": "black", "outline_width": 2,
    },
    "color_grade": {"contrast": 1.0, "saturation": 1.0, "brightness": 0.0},
    "audio_ducking_level": 0.25,
    "resolution": [1920, 1080],
    "aspect_ratio": "16:9",
}


def load_template(name_or_path):
    """
    Load a template by name (looked up in app/tools/templates/<name>.json)
    or by direct file path (for the "Custom" upload option). Falls back to
    DEFAULT_TEMPLATE for any keys the chosen template doesn't override.
    """
    path = name_or_path
    if not os.path.isfile(path):
        path = os.path.join(TEMPLATES_DIR, f"{name_or_path}.json")

    template = dict(DEFAULT_TEMPLATE)
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            user_template = json.load(f)
        template.update(user_template)
    return template


# ---------------------------------------------------------------------------
# Silence detection / trimming
# ---------------------------------------------------------------------------

def detect_silences(audio_or_video_path, silence_thresh_db=-35, min_silence_len=1.0):
    """
    Detect silent ranges using ffmpeg's silencedetect filter (no need to
    decode the whole file into memory the way pydub does).

    Returns a list of (start, end) tuples in seconds, each a SILENT range.
    """
    cmd = [
        "ffmpeg", "-i", audio_or_video_path,
        "-af", f"silencedetect=noise={silence_thresh_db}dB:d={min_silence_len}",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    stderr = result.stderr

    silences = []
    start = None
    for line in stderr.splitlines():
        line = line.strip()
        if "silence_start" in line:
            try:
                start = float(line.split("silence_start:")[1].strip().split(" ")[0])
            except (IndexError, ValueError):
                start = None
        elif "silence_end" in line and start is not None:
            try:
                end_part = line.split("silence_end:")[1].strip().split(" ")[0]
                end = float(end_part)
                silences.append((start, end))
            except (IndexError, ValueError):
                pass
            start = None

    return silences


def _get_duration(path):
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", path]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(json.loads(result.stdout).get("format", {}).get("duration") or 0)


def trim_silence(video_path, out_path, threshold=1.0, silence_thresh_db=-35, padding=0.15):
    """
    Remove silent stretches longer than `threshold` seconds from the video
    (dead air at the start/end and between sentences), keeping `padding`
    seconds of buffer around each cut so speech isn't clipped.

    Strategy: find silent ranges -> invert to get the "keep" ranges ->
    stream-copy-concat those ranges with ffmpeg's concat demuxer (fast,
    no re-encoding of the kept footage).
    """
    duration = _get_duration(video_path)
    silences = detect_silences(video_path, silence_thresh_db=silence_thresh_db, min_silence_len=threshold)

    if not silences:
        return video_path, 0.0  # nothing to trim - caller can use the original

    keep_ranges = []
    cursor = 0.0
    for s_start, s_end in silences:
        keep_start = cursor
        keep_end = max(keep_start, s_start + padding)
        if keep_end > keep_start:
            keep_ranges.append((keep_start, keep_end))
        cursor = max(cursor, s_end - padding)
    if cursor < duration:
        keep_ranges.append((cursor, duration))

    if not keep_ranges:
        return video_path, 0.0

    work_dir = os.path.dirname(out_path) or "."
    segment_paths = []
    for i, (seg_start, seg_end) in enumerate(keep_ranges):
        seg_path = os.path.join(work_dir, f"_keep_{i:03d}.mp4")
        # NOTE: -c copy here would only cut on keyframe boundaries, which
        # can silently produce segments far longer/shorter than requested
        # on footage with a wide GOP spacing. Silence trimming needs
        # frame-accurate cuts, so we re-encode each segment instead -
        # slower, but correct regardless of the source's keyframe interval.
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-ss", f"{seg_start:.3f}", "-to", f"{seg_end:.3f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac",
            "-avoid_negative_ts", "make_zero", seg_path,
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        segment_paths.append(seg_path)

    concatenate_clips(segment_paths, out_path, reencode=True)

    for p in segment_paths:
        if os.path.exists(p):
            os.remove(p)

    removed_seconds = duration - sum(e - s for s, e in keep_ranges)
    return out_path, max(0.0, removed_seconds)


# ---------------------------------------------------------------------------
# Concatenation / transitions
# ---------------------------------------------------------------------------

def concatenate_clips(clip_paths, out_path, reencode=False):
    """
    Join clips end-to-end, in order. Stream-copy by default (fast, no
    quality loss) - only safe when all clips share the same codec/resolution
    (true for segments cut from the same source, as in trim_silence).
    Set reencode=True when joining clips from different sources/resolutions.
    """
    if len(clip_paths) == 1:
        import shutil
        shutil.copy(clip_paths[0], out_path)
        return out_path

    work_dir = os.path.dirname(out_path) or "."
    list_path = os.path.join(work_dir, "_concat_list.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for p in clip_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")

    if not reencode:
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", out_path]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            os.remove(list_path)
            return out_path
        except subprocess.CalledProcessError:
            pass  # fall through to re-encoding concat below

    # Re-encoding concat (needed for mismatched clips, or as a fallback).
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", out_path]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    os.remove(list_path)
    return out_path


def apply_transitions(clip_paths, out_path, transition_type="crossfade", duration=0.5):
    """
    Join clips with a transition between each pair. "none" is a plain
    concat (re-encoded, since transitions require it anyway for anything
    else). "crossfade"/"slide"/"zoom" all use ffmpeg's xfade filter, which
    covers all three with a different `transition=` name.
    """
    if transition_type == "none" or len(clip_paths) == 1:
        return concatenate_clips(clip_paths, out_path, reencode=True)

    xfade_names = {
        "crossfade": "fade",
        "slide": "slideleft",
        "zoom": "zoomin",
    }
    xfade_name = xfade_names.get(transition_type, "fade")

    # Build a chained xfade filter graph: each clip after the first is
    # cross-faded into the running "accumulated" output.
    durations = [_get_duration(p) for p in clip_paths]

    inputs = []
    for p in clip_paths:
        inputs += ["-i", p]

    filter_parts = []
    running_label = "0:v"
    running_offset = durations[0] - duration
    for i in range(1, len(clip_paths)):
        out_label = f"v{i}"
        filter_parts.append(
            f"[{running_label}][{i}:v]xfade=transition={xfade_name}:duration={duration}:"
            f"offset={max(0, running_offset):.3f}[{out_label}]"
        )
        running_label = out_label
        running_offset += durations[i] - duration

    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", filter_complex,
        "-map", f"[{running_label}]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        out_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out_path


# ---------------------------------------------------------------------------
# Text overlays (drawtext - no ImageMagick dependency)
# ---------------------------------------------------------------------------

def _escape_drawtext(text):
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def overlay_text(video_path, out_path, text, style=None, start=0.0, duration=None):
    """
    Burn a single text overlay (title / lower-third / caption line) onto
    the video using ffmpeg's drawtext filter - no ImageMagick/MoviePy
    TextClip dependency required.

    style: {font, size, color, position ("top"|"center"|"bottom"),
            outline_color, outline_width}
    start/duration: seconds - if duration is None, the text stays for the
        rest of the video.
    """
    style = {**DEFAULT_TEMPLATE["text_style"], **(style or {})}
    text_escaped = _escape_drawtext(text)

    position_map = {
        "top": "x=(w-text_w)/2:y=h*0.08",
        "center": "x=(w-text_w)/2:y=(h-text_h)/2",
        "bottom": "x=(w-text_w)/2:y=h*0.85",
    }
    pos = position_map.get(style.get("position", "bottom"), position_map["bottom"])

    enable_expr = f":enable='between(t,{start},{start + duration})'" if duration else ""

    drawtext = (
        f"drawtext=text='{text_escaped}':fontsize={style['size']}:fontcolor={style['color']}:"
        f"bordercolor={style.get('outline_color', 'black')}:borderw={style.get('outline_width', 2)}:"
        f"{pos}{enable_expr}"
    )

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", drawtext,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "copy",
        out_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out_path


# ---------------------------------------------------------------------------
# Captions (burned-in subtitles from an .srt)
# ---------------------------------------------------------------------------

def burn_captions(video_path, srt_path, out_path, style=None):
    """
    Burn .srt captions into the video using ffmpeg's subtitles filter
    (libass under the hood). `style` keys map to ASS override tags:
    font, size, color (hex without '#', ASS uses &HBBGGRR&), outline_width.
    """
    style = {**DEFAULT_TEMPLATE["text_style"], **(style or {})}

    def _to_ass_color(css_color):
        # Minimal named-color -> ASS BGR hex map; extend as needed.
        named = {"white": "FFFFFF", "black": "000000", "yellow": "00FFFF"}
        hex_rgb = named.get(css_color, "FFFFFF")
        r, g, b = hex_rgb[0:2], hex_rgb[2:4], hex_rgb[4:6]
        return f"&H{b}{g}{r}&"

    force_style = (
        f"FontName={style.get('font', 'Arial')},"
        f"FontSize={style.get('size', 28)},"
        f"PrimaryColour={_to_ass_color(style.get('color', 'white'))},"
        f"OutlineColour=&H000000&,Outline={style.get('outline_width', 2)}"
    )

    # ffmpeg's subtitles filter needs a path with no unescaped colons on
    # Windows-style paths; on Linux this simple escaping is sufficient.
    srt_escaped = srt_path.replace(":", "\\:")

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"subtitles={srt_escaped}:force_style='{force_style}'",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "copy",
        out_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out_path


# ---------------------------------------------------------------------------
# Background music mixing / ducking
# ---------------------------------------------------------------------------

def duck_background_music(video_path, music_path, out_path, ducking_level=0.25):
    """
    Mix background music under the video's existing (speech) audio, ducking
    the music's volume automatically whenever speech is present, using
    ffmpeg's sidechaincompress filter (true auto-ducking, not just a flat
    volume reduction).

    ducking_level: target relative music volume during speech (0.0-1.0).
    Music is looped if shorter than the video, trimmed if longer.
    """
    video_duration = _get_duration(video_path)

    filter_complex = (
        f"[1:a]aloop=loop=-1:size=2e9,atrim=0:{video_duration}[music];"
        f"[music][0:a]sidechaincompress=threshold=0.05:ratio=8:attack=5:release=300:"
        f"makeup=1[ducked];"
        f"[ducked]volume={ducking_level}[ducked_lvl];"
        f"[0:a][ducked_lvl]amix=inputs=2:duration=first:dropout_transition=0[aout]"
    )

    cmd = [
        "ffmpeg", "-y", "-i", video_path, "-i", music_path,
        "-filter_complex", filter_complex,
        "-map", "0:v:0", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac",
        out_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out_path


# ---------------------------------------------------------------------------
# Color grading (simple contrast/saturation/brightness adjustment)
# ---------------------------------------------------------------------------

def apply_color_grade(video_path, out_path, color_grade):
    """
    Apply a basic contrast/saturation/brightness adjustment via ffmpeg's
    eq filter. `color_grade`: {"contrast": float, "saturation": float,
    "brightness": float} - values as used by ffmpeg's eq filter directly
    (contrast/saturation around 1.0 = no change, brightness around 0.0 =
    no change). A true LUT-based grade is a natural future upgrade here
    (ffmpeg's lut3d filter) but isn't needed for the template presets above.
    """
    contrast = color_grade.get("contrast", 1.0)
    saturation = color_grade.get("saturation", 1.0)
    brightness = color_grade.get("brightness", 0.0)

    if contrast == 1.0 and saturation == 1.0 and brightness == 0.0:
        return video_path  # nothing to do

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"eq=contrast={contrast}:saturation={saturation}:brightness={brightness}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "copy",
        out_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out_path


# ---------------------------------------------------------------------------
# Multi-format export
# ---------------------------------------------------------------------------

_FORMAT_SPECS = {
    "1080p": {"size": (1920, 1080), "pad": False},
    "4k": {"size": (3840, 2160), "pad": False},
    "vertical": {"size": (1080, 1920), "pad": True},   # TikTok/Reels
    "square": {"size": (1080, 1080), "pad": True},     # Instagram
}


def _scale_and_pad_filter(width, height, pad):
    if pad:
        # Fit inside the target box, then pad with black bars to fill it -
        # safest default for turning 16:9 footage into 9:16 or 1:1 without
        # distorting or cropping out content.
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    return f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"


def export_multiple_formats(video_path, output_formats, out_dir, progress_cb=None):
    """
    Transcode the finished video into each requested format
    ("1080p", "4k", "vertical", "square"). Returns {format: output_path}.
    """
    os.makedirs(out_dir, exist_ok=True)
    results = {}

    for i, fmt in enumerate(output_formats, start=1):
        spec = _FORMAT_SPECS.get(fmt)
        if not spec:
            continue
        width, height = spec["size"]
        vf = _scale_and_pad_filter(width, height, spec["pad"])
        out_file = os.path.join(out_dir, f"export_{fmt}.mp4")

        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", vf,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac",
            out_file,
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        results[fmt] = out_file

        if progress_cb:
            progress_cb(i, len(output_formats), fmt)

    return results


def zip_outputs(file_paths, zip_path):
    import zipfile
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in file_paths:
            zf.write(p, arcname=os.path.basename(p))
    return zip_path


# ---------------------------------------------------------------------------
# Highlight detection
# ---------------------------------------------------------------------------
# Combines two cheap, real signals rather than a black-box "AI picks the
# best parts" claim:
#   1. Visual scene changes (ffmpeg's own scene-detection filter) - used to
#      snap candidate window boundaries to natural cut points, so a
#      selected clip never starts or ends mid-shot.
#   2. Speech density (from Whisper segments, when available) - windows
#      with more actual talking score higher than long silent/b-roll
#      stretches. Falls back to a neutral score when no transcript is
#      available, so this still works on music-only or dialogue-free video.

def _detect_scene_changes(video_path, threshold=0.3):
    """Sorted list of timestamps (seconds) where ffmpeg detects a visual
    scene change/hard cut."""
    cmd = [
        "ffmpeg", "-i", video_path,
        "-filter:v", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    timestamps = []
    for line in result.stderr.splitlines():
        if "pts_time:" in line:
            try:
                timestamps.append(float(line.split("pts_time:")[1].split()[0]))
            except (IndexError, ValueError):
                continue
    return sorted(timestamps)


def _speech_density(segments, start, end):
    """Fraction of [start, end) covered by speech segments - 0.0 for a
    window with no speech at all, up to 1.0 for continuous talking."""
    if not segments:
        return 0.0
    window_len = max(0.001, end - start)
    covered = 0.0
    for seg in segments:
        seg_start = max(start, seg.get("start", 0))
        seg_end = min(end, seg.get("end", 0))
        if seg_end > seg_start:
            covered += seg_end - seg_start
    return min(1.0, covered / window_len)


def detect_highlights(video_path, target_duration=30.0, window_size=6.0,
                       whisper_segments=None, scene_threshold=0.3):
    """
    Pick the most "interesting" windows of a video for a highlight reel.
    Returns a chronologically-ordered list of (start, end) tuples whose
    total duration is close to target_duration - under-shoots rather than
    padding with low-value filler, over-shoots slightly rather than
    cutting a selected window awkwardly short.

    whisper_segments: the `segments` list from transcribe_with_whisper(),
        if you have one (e.g. already transcribed for captions earlier in
        the same auto-edit pipeline - reuse it rather than transcribing
        twice). None is fine; scoring then relies on window-size fit
        alone, still using real scene structure for boundaries.
    """
    total_duration = _get_duration(video_path)
    if total_duration <= target_duration:
        return [(0.0, total_duration)]  # already short enough - use it all

    scene_points = _detect_scene_changes(video_path, threshold=scene_threshold)
    boundaries = sorted(set([0.0] + scene_points + [total_duration]))

    # Candidate windows between consecutive boundaries, merging forward
    # over closely-spaced cuts so rapid-cut footage doesn't produce a
    # flood of sub-window-size slivers.
    candidates = []
    window_start = boundaries[0]
    for b in boundaries[1:]:
        if b - window_start >= window_size * 0.5:
            candidates.append((window_start, b))
            window_start = b
    if window_start < total_duration - 0.5:
        candidates.append((window_start, total_duration))

    # Fallback for footage with no usable scene structure (one continuous
    # static shot) - fixed-size windows instead of a single giant candidate.
    if len(candidates) <= 1:
        candidates = []
        t = 0.0
        while t < total_duration:
            candidates.append((t, min(t + window_size, total_duration)))
            t += window_size

    scored = []
    for start, end in candidates:
        duration = end - start
        density = _speech_density(whisper_segments, start, end) if whisper_segments else 0.5
        size_fit = 1.0 - min(1.0, abs(duration - window_size) / (window_size * 3))
        score = (density * 0.7) + (size_fit * 0.3)
        scored.append({"start": start, "end": end, "duration": duration, "score": score})

    scored.sort(key=lambda w: w["score"], reverse=True)

    selected = []
    accumulated = 0.0
    for window in scored:
        if accumulated >= target_duration:
            break
        selected.append(window)
        accumulated += window["duration"]

    # Chronological order for output - a reel that jumps backward in time
    # reads as broken even when each clip was individually a good pick.
    selected.sort(key=lambda w: w["start"])
    return [(w["start"], w["end"]) for w in selected]


def extract_highlight_reel(video_path, highlight_ranges, out_path, work_dir):
    """
    Cut video_path down to the given (start, end) ranges and concatenate
    them, in order, into out_path. Re-encodes each segment (rather than
    -c copy) for frame-accurate cuts - see trim_silence() for why -c copy
    is unsafe here: it only cuts on keyframe boundaries, which can produce
    segments far longer/shorter than requested depending on the source's
    GOP spacing, and highlight boundaries come from a scoring algorithm,
    not a human eyeballing a safe cut point.
    """
    os.makedirs(work_dir, exist_ok=True)
    segment_paths = []
    for i, (start, end) in enumerate(highlight_ranges):
        seg_path = os.path.join(work_dir, f"_highlight_{i:03d}.mp4")
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac",
            "-avoid_negative_ts", "make_zero", seg_path,
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        segment_paths.append(seg_path)

    if len(segment_paths) == 1:
        import shutil
        shutil.copy(segment_paths[0], out_path)
    else:
        concatenate_clips(segment_paths, out_path, reencode=True)

    for p in segment_paths:
        if os.path.exists(p):
            os.remove(p)

    return out_path