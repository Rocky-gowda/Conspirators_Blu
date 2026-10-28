"""Stage 5: render the SAME browser player frame by frame and mux with the voice into a 720p MP4.

Speed tricks (all keep audio and video perfectly in sync, because every frame is seeked, not recorded):
  1. Several browser tabs render different parts of the lesson in parallel.
  2. A frame is only captured when something on screen changed; still frames reuse the last image
     (most of a lesson is still between sentences, so this skips most captures).
  3. Fast JPEG capture through the Chrome DevTools protocol.
  4. The moving progress bar is drawn by FFmpeg, so it does not force a capture every frame.
"""
import asyncio
import base64
import json
import os
import subprocess
from pathlib import Path

from . import config

WORKERS = int(os.environ.get("BLU_EXPORT_WORKERS", str(max(1, min(4, (os.cpu_count() or 2) // 2)))))
BAR_COLOR = "0x2F6FED"


async def _render_chunk(browser, url, frames, fps, out, stats, on_frame):
    page = await browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=1)
    await page.goto(url)
    await page.wait_for_function("window.__ready === true", timeout=60000)
    cdp = await page.context.new_cdp_session(page)
    prev_sig, prev_img = None, None
    for i in frames:
        sig = await page.evaluate("t => window.renderSig(t)", i / fps)
        if sig != prev_sig or prev_img is None:
            r = await cdp.send("Page.captureScreenshot",
                               {"format": "jpeg", "quality": 85, "optimizeForSpeed": True})
            prev_img, prev_sig = base64.b64decode(r["data"]), sig
            stats["captured"] += 1
        out[i] = prev_img
        on_frame()
    await page.close()


async def _render_all(url, n_frames, fps, on_progress):
    from playwright.async_api import async_playwright
    out = [None] * n_frames
    stats = {"captured": 0, "done": 0}

    def on_frame():
        stats["done"] += 1
        if on_progress and stats["done"] % fps == 0:
            on_progress(stats["done"], n_frames)

    # contiguous chunks: each tab only re-captures when its own part of the lesson changes
    k = max(1, min(WORKERS, n_frames // (fps * 3) or 1))
    size = -(-n_frames // k)
    chunks = [range(s, min(n_frames, s + size)) for s in range(0, n_frames, size)]
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--disable-gpu"])
        await asyncio.gather(*[_render_chunk(browser, url, c, fps, out, stats, on_frame) for c in chunks])
        await browser.close()
    return out, stats["captured"]


def export(lesson_id: str, out_dir: Path, on_progress=None) -> Path:
    tl = json.loads((out_dir / "timeline.json").read_text(encoding="utf-8"))
    fps = config.EXPORT_FPS
    dur = tl["duration"]
    n_frames = int(dur * fps) + 1
    url = f"{config.SERVER_URL}/player.html?id={lesson_id}&export=1"

    frames, captured = asyncio.run(_render_all(url, n_frames, fps, on_progress))

    mp4 = out_dir / "lesson.mp4"
    tmp = out_dir / "lesson.tmp.mp4"
    # progress bar: a blue strip that slides in from the left as time passes
    vf = (f"[0:v]scale=1280:720,setsar=1[v];color=c={BAR_COLOR}:s=1280x10:r={fps}[bar];"
          f"[v][bar]overlay=x='-W+W*t/{dur:.3f}':y=H-10:shortest=1[out]")
    ff = subprocess.Popen([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-",
        "-i", str(out_dir / "audio.wav"),
        "-filter_complex", vf, "-map", "[out]", "-map", "1:a",
        # phone-friendly H.264: Main profile, level 3.1, capped bitrate, fast start
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-r", str(fps),
        "-profile:v", "main", "-level", "3.1", "-maxrate", "2500k", "-bufsize", "5000k",
        "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart",
        str(tmp)], stdin=subprocess.PIPE)
    try:
        for f in frames:
            ff.stdin.write(f)
        ff.stdin.close()
        if ff.wait() != 0:
            raise RuntimeError("ffmpeg failed")
    except Exception:
        ff.kill()
        raise
    tmp.replace(mp4)
    (out_dir / "export_stats.json").write_text(json.dumps(
        {"frames": n_frames, "captured": captured, "workers": WORKERS}), encoding="utf-8")
    return mp4


def verify(mp4: Path, expected_duration: float) -> dict:
    """Check the MP4 really is a complete 720p H.264 + AAC video of the right length."""
    if not mp4.exists() or mp4.stat().st_size < 10_000:
        raise RuntimeError(f"MP4 check failed: file missing or empty ({mp4.name})")
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height,profile",
                          "-show_entries", "format=duration", "-of", "json", str(mp4)],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError("MP4 check failed: ffprobe could not read the file")
    info = json.loads(out.stdout)
    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    dur = float(info.get("format", {}).get("duration", 0))
    problems = []
    if not v or v.get("codec_name") != "h264" or (v.get("width"), v.get("height")) != (1280, 720):
        problems.append("no 1280x720 H.264 video stream")
    if not a or a.get("codec_name") != "aac":
        problems.append("no AAC audio stream")
    if abs(dur - expected_duration) > 1.5:
        problems.append(f"duration {dur:.1f}s, expected {expected_duration:.1f}s")
    if problems:
        raise RuntimeError("MP4 check failed: " + "; ".join(problems))
    return {"ok": True, "size_mb": round(mp4.stat().st_size / 2**20, 2), "duration": round(dur, 2),
            "video": f"h264 {v.get('profile')} 1280x720", "audio": "aac"}
