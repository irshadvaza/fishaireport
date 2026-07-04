"""
audio_utils.py
--------------
Small helpers to:
- persist an uploaded/recorded audio blob to a temp wav/mp3 file
- extract the audio track from an uploaded video file (mp4/mov/etc.) using moviepy/ffmpeg
"""

import os
import tempfile


def save_uploaded_bytes(uploaded_bytes: bytes, suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(uploaded_bytes)
    return path


def extract_audio_from_video(video_path: str) -> str:
    """Returns path to a temp .wav file containing the extracted audio track."""
    from moviepy.editor import VideoFileClip

    audio_path = tempfile.mktemp(suffix=".wav")
    clip = VideoFileClip(video_path)
    if clip.audio is None:
        clip.close()
        raise ValueError("This video file has no audio track to transcribe.")
    clip.audio.write_audiofile(audio_path, logger=None)
    clip.close()
    return audio_path
