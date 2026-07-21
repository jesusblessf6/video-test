"""
视频分析小应用 —— 调用火山引擎方舟（Ark）豆包视频理解模型分析视频。

- 走 Ark 的 Responses API（/responses）。视频通过 content 里的 input_video 传入，
  字段 video_url 接受公网 URL 或 base64 data URL，可选 fps（每秒抽帧数）。
- 运行: python app.py  然后浏览器打开 http://127.0.0.1:7860
"""

import base64
import datetime
import mimetypes
import os
import shutil
import subprocess
from pathlib import Path

import gradio as gr
import requests
from dotenv import load_dotenv

load_dotenv()

# 分析结果自动归档目录
RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# 超限 URL 视频的下载/压缩暂存目录（已 gitignore，可定期手动清理）
TMP_DIR = Path(__file__).parent / "tmp"
TMP_DIR.mkdir(exist_ok=True)

BASE_URL = os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
DEFAULT_MODEL = os.getenv("ARK_MODEL", "doubao-seed-2-1-pro-260628")

# Ark 是国内端点，走本机系统代理（如 Clash 127.0.0.1:7897）会间歇性 RemoteDisconnected。
# trust_env=False 让请求忽略环境变量与 macOS 系统代理，直连。需要代理时设 ARK_USE_PROXY=1。
_session = requests.Session()
_session.trust_env = os.getenv("ARK_USE_PROXY", "").strip() == "1"

DEFAULT_PROMPT = (
    "我当前是一个短剧素材投流的投手，上面这个视频是一个表现很好的投流素材，"
    "我想学习它的剪辑方式，并把结论沉淀为可复用的 agent skill。\n\n"
    "【输入说明】视频按抽帧（fps 可调）加音轨输入。画面或台词看不清、听不准的地方，"
    "直接标注「不确定」，严禁编造。\n\n"
    "【输出要求】用 Markdown 严格按以下结构输出，每节都必须有，某节确实没有内容就写「无」：\n"
    "1. 素材概览：题材、时长、目标人群、核心矛盾/卖点（一段话）。\n"
    "2. 分镜拆解：Markdown 表格，按时间顺序列关键镜头：时间区间 | 画面内容 | 台词/字幕 | 剪辑手法 | 作用。\n"
    "3. 剪辑手法清单：逐条拆解节奏、转场、字幕花字、BGM/音效、钩子设计，"
    "每条 = 具体做法 + 出现时间点 + 为什么有效。\n"
    "4. 可复用 SOP：把手法抽象成硬标准，每条 = 操作标准（尽量量化：秒数、字数、镜头数）"
    "+ 可直接照抄的示例 + 适用题材。\n"
    "5. 投产 Checklist：把 SOP 转成「如果…就…」的规则清单，方便直接写成 agent skill。\n\n"
    "【质量红线】只要能量化的就必须量化；禁止「注意节奏」「画面要有张力」这类无法执行的虚话；"
    "标注「不确定」不影响其余部分照常输出。"
)

# Ark 服务端对输入视频的硬性上限是 50 MiB（实测：148 MiB 视频返回 HTTP 400）。
# 该限制与传入方式无关：base64 上传和公网 URL（Ark 服务端拉取）都受限。
# 超限视频只能先压缩/裁剪（如 ffmpeg）再分析。
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MiB，与 Ark 上限对齐


def _api_key(override: str) -> str:
    key = (override or "").strip() or os.getenv("ARK_API_KEY", "").strip()
    if not key:
        raise gr.Error("未配置 API Key：请在下方填入，或在 .env 里设置 ARK_API_KEY")
    return key


def _file_to_data_url(path: str) -> str:
    size = os.path.getsize(path)
    if size > MAX_UPLOAD_BYTES:
        raise gr.Error(
            f"视频过大（{size / 1024 / 1024:.1f} MB，Ark 上限 {MAX_UPLOAD_BYTES // 1024 // 1024} MB，"
            "URL 方式同样受限）。请先压缩/裁剪再分析，例如：\n"
            "ffmpeg -i 原视频.mp4 -vf scale=-2:720 -crf 28 压缩后.mp4"
        )
    mime = mimetypes.guess_type(path)[0] or "video/mp4"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{b64}"


# 下载体积安全上限，防止异常 URL 把磁盘打满
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB


def _remote_size(url: str):
    """HEAD 探测远程视频体积（字节），失败或无 Content-Length 返回 None。"""
    try:
        r = _session.head(url, timeout=10, allow_redirects=True)
        n = r.headers.get("content-length", "")
        return int(n) if n.isdigit() else None
    except requests.RequestException:
        return None


def _download_video(url: str) -> str:
    """把远程视频流式下载到 tmp/，返回本地路径。"""
    dst = TMP_DIR / f"下载_{datetime.datetime.now():%Y%m%d_%H%M%S}.mp4"
    try:
        with _session.get(url, stream=True, timeout=(10, 60)) as r:
            if r.status_code != 200:
                raise gr.Error(f"视频下载失败（HTTP {r.status_code}）")
            downloaded = 0
            with open(dst, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    downloaded += len(chunk)
                    if downloaded > MAX_DOWNLOAD_BYTES:
                        raise gr.Error("视频超过 2GB，超出本 demo 的处理能力，请自行裁剪")
                    f.write(chunk)
    except requests.RequestException as e:
        raise gr.Error(f"视频下载失败：{e}")
    return str(dst)


def _probe_duration(path: str):
    """ffprobe 取视频时长（秒），失败返回 None。"""
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=60,
        )
        return float(out.stdout.strip())
    except (subprocess.SubprocessError, ValueError):
        return None


def _compress_video(src: str) -> str:
    """把本地视频压到 50 MiB 以内（按时长反推码率，720p→480p 两轮保底），返回输出路径。"""
    if not shutil.which("ffmpeg"):
        raise gr.Error("视频超过 50MB 需要压缩，但本机未安装 ffmpeg（brew install ffmpeg）")
    dst = TMP_DIR / f"压缩_{datetime.datetime.now():%Y%m%d_%H%M%S}.mp4"
    duration = _probe_duration(src)
    for height, margin, crf in ((720, 0.9, 30), (480, 0.55, 36)):
        cmd = ["ffmpeg", "-y", "-i", src, "-vf", f"scale=-2:'min({height},ih)'"]
        if duration:
            # 目标码率 = 目标体积（留 margin 余量）/ 时长；音频 96k，其余给视频，150k 保底
            v_kbps = max(int(MAX_UPLOAD_BYTES * margin * 8 / duration / 1000) - 96, 150)
            cmd += ["-b:v", f"{v_kbps}k", "-maxrate", f"{v_kbps}k",
                    "-bufsize", f"{v_kbps * 2}k"]
        else:  # 拿不到时长就按固定 crf 压
            cmd += ["-crf", str(crf)]
        cmd += ["-b:a", "96k", "-movflags", "+faststart", str(dst)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if proc.returncode != 0:
            raise gr.Error(f"ffmpeg 压缩失败：{proc.stderr[-300:]}")
        if dst.stat().st_size <= MAX_UPLOAD_BYTES:
            return str(dst)
    raise gr.Error(
        f"压缩两轮后仍超 50MB（{dst.stat().st_size / 1048576:.0f}MB），"
        "视频可能太长，请手动裁剪/压缩后再试"
    )


def _extract_text(resp: dict) -> str:
    """从 Responses API 的 output 里取出助手文字（跳过 reasoning 项）。"""
    parts = []
    for item in resp.get("output", []):
        if item.get("type") != "message":
            continue
        for c in item.get("content", []):
            if c.get("type") == "output_text" and c.get("text"):
                parts.append(c["text"])
    return "\n".join(parts).strip() or "（模型未返回文字内容）"


def _call(url, prompt, model, fps, api_key):
    """组装请求并调用 Ark Responses API，返回模型文字分析。"""
    video_part = {"type": "input_video", "video_url": url}
    if fps and float(fps) > 0:
        video_part["fps"] = float(fps)

    payload = {
        "model": (model or "").strip() or DEFAULT_MODEL,
        "input": [
            {
                "role": "user",
                "content": [
                    video_part,
                    {"type": "input_text", "text": (prompt or "").strip() or DEFAULT_PROMPT},
                ],
            }
        ],
    }

    try:
        r = _session.post(
            f"{BASE_URL}/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=300,
        )
    except requests.RequestException as e:
        raise gr.Error(f"网络请求失败：{e}")

    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code != 200 or "error" in data:
        err = data.get("error", {})
        msg = err.get("message") or r.text[:500]
        raise gr.Error(f"调用失败（HTTP {r.status_code}）：{msg}")

    return _extract_text(data)


# 按钮的「就绪」「分析中」两种外观，供生成器切换。
BTN_READY = gr.update(value="🚀 开始分析", interactive=True)
BTN_BUSY = gr.update(value="⏳ 分析中…", interactive=False)


def _save_result(text, source, model, fps, prompt):
    """把一次分析结果连同元信息存为 Markdown，返回文件路径。"""
    now = datetime.datetime.now()
    stamp = now.strftime("%Y%m%d_%H%M%S")
    doc = (
        f"# 视频分析结果\n\n"
        f"- 时间：{now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"- 视频来源：{source}\n"
        f"- 模型：{(model or '').strip() or DEFAULT_MODEL}\n"
        f"- 抽帧 fps：{fps}\n"
        f"- 分析指令：{(prompt or '').strip() or DEFAULT_PROMPT}\n\n"
        f"---\n\n{text}\n"
    )
    path = RESULTS_DIR / f"分析_{stamp}.md"
    path.write_text(doc, encoding="utf-8")
    return path


def analyze(video_file, video_url, prompt, model, fps, api_key):
    """界面入口：先校验，再以加载态调用，最后吐结果并自动归档。

    yield 四元组 (结果 Markdown, 状态行, 按钮状态, 下载文件)，让前端有明确反馈。
    """
    # —— 即时校验（出错弹 toast，按钮维持就绪态）——
    url = (video_url or "").strip()
    source = url  # 归档时记录的视频来源
    if not url and video_file:
        source = f"上传文件 {os.path.basename(video_file)}"
        url = _file_to_data_url(video_file)
    if not url:
        raise gr.Error("请上传视频文件，或填入一个视频 URL")
    key = _api_key(api_key)

    # —— 进入加载态：清空旧结果、显示进度提示、禁用按钮、隐藏旧下载 ——
    yield "", "⏳ 正在分析视频，请稍候…（通常 10–30 秒，长视频更久）", BTN_BUSY, gr.update(visible=False)

    # —— URL 视频预检：超过 50 MiB 先下载到本地压缩，再改走 base64 ——
    if url.startswith(("http://", "https://")):
        size = _remote_size(url)
        if size and size > MAX_UPLOAD_BYTES:
            yield (
                "",
                f"⏳ 视频约 {size / 1048576:.0f}MB，超过 50MB 上限，"
                "正在下载并压缩（可能需几分钟）…",
                BTN_BUSY,
                gr.update(visible=False),
            )
            try:
                packed = _compress_video(_download_video(url))
            except gr.Error as e:
                yield f"### ❌ 预处理失败\n\n{e.message}", "失败", BTN_READY, gr.update(visible=False)
                return
            packed_mb = os.path.getsize(packed) / 1048576
            source = f"{url}（原约 {size / 1048576:.0f}MB，已自动压缩至 {packed_mb:.1f}MB）"
            url = _file_to_data_url(packed)  # 压缩结果必然 ≤50 MiB，这里同时完成 base64 封装
            yield "", "⏳ 压缩完成，正在分析视频…", BTN_BUSY, gr.update(visible=False)

    try:
        text = _call(url, prompt, model, fps, key)
    except gr.Error as e:
        yield f"### ❌ 调用失败\n\n{e.message}", "失败", BTN_READY, gr.update(visible=False)
        return
    except Exception as e:  # 兜底，避免界面卡在加载态
        yield f"### ❌ 出错\n\n```\n{e}\n```", "失败", BTN_READY, gr.update(visible=False)
        return

    path = _save_result(text, source, model, fps, prompt)
    yield (
        text,
        f"✅ 分析完成 · 已自动保存到 `results/{path.name}`",
        BTN_READY,
        gr.update(value=str(path), visible=True),
    )


with gr.Blocks(title="视频分析 · 豆包视频理解") as demo:
    gr.Markdown(
        "# 🎬 视频分析\n"
        "调用火山引擎方舟（Ark）豆包视频理解模型，对视频做内容分析。"
        "上传本地视频，或填入一个公网视频 URL。"
    )

    with gr.Row():
        with gr.Column(scale=1):
            video_in = gr.Video(label="上传视频", sources=["upload"])
            url_in = gr.Textbox(
                label="或：视频 URL（公网可访问，大文件推荐用这个）",
                placeholder="https://example.com/demo.mp4",
            )
            prompt_in = gr.Textbox(
                label="分析指令 / 你想问什么", value=DEFAULT_PROMPT, lines=3
            )
            with gr.Accordion("高级设置", open=False):
                model_in = gr.Textbox(label="模型 ID", value=DEFAULT_MODEL)
                fps_in = gr.Slider(
                    label="抽帧 fps（每秒抽几帧给模型；越大越细但越贵/越慢）",
                    minimum=0, maximum=5, step=0.5, value=1,
                )
                key_in = gr.Textbox(
                    label="API Key（留空则用 .env 里的 ARK_API_KEY）",
                    type="password",
                )
            with gr.Row():
                run_btn = gr.Button("🚀 开始分析", variant="primary", scale=3)
                clear_btn = gr.Button("清空", scale=1)
        with gr.Column(scale=1):
            status = gr.Markdown("", elem_id="status")
            output = gr.Markdown(
                value="*结果会显示在这里。上传视频或填 URL，点「开始分析」。*",
                label="分析结果",
            )
            download_btn = gr.DownloadButton(
                "⬇️ 下载结果 (.md)", visible=False
            )

    run_btn.click(
        analyze,
        inputs=[video_in, url_in, prompt_in, model_in, fps_in, key_in],
        outputs=[output, status, run_btn, download_btn],
        show_progress="minimal",
    )

    clear_btn.click(
        lambda: (None, "", "", "*结果会显示在这里。*", gr.update(visible=False)),
        outputs=[video_in, url_in, status, output, download_btn],
    )


if __name__ == "__main__":
    demo.queue().launch()
