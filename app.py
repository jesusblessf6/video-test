"""
视频分析小应用 —— 调用火山引擎方舟（Ark）豆包视频理解模型分析视频。

- 走 Ark 的 Responses API（/responses）。视频通过 content 里的 input_video 传入，
  字段 video_url 接受公网 URL 或 base64 data URL，可选 fps（每秒抽帧数）。
- 运行: python app.py  然后浏览器打开 http://127.0.0.1:7860
"""

import base64
import mimetypes
import os

import gradio as gr
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
DEFAULT_MODEL = os.getenv("ARK_MODEL", "doubao-seed-2-1-pro-260628")

DEFAULT_PROMPT = "请详细分析这个视频：概述主要内容、关键画面/场景、出现的人物或物体，以及整体在表达什么。"

# 上传文件转 base64 的体积上限（base64 比原文件大 ~33%，过大易超时/超限）。
# 大视频建议用「视频 URL」方式，公网可访问的链接直接交给模型拉取。
MAX_UPLOAD_BYTES = 40 * 1024 * 1024  # 40 MB


def _api_key(override: str) -> str:
    key = (override or "").strip() or os.getenv("ARK_API_KEY", "").strip()
    if not key:
        raise gr.Error("未配置 API Key：请在下方填入，或在 .env 里设置 ARK_API_KEY")
    return key


def _file_to_data_url(path: str) -> str:
    size = os.path.getsize(path)
    if size > MAX_UPLOAD_BYTES:
        raise gr.Error(
            f"视频过大（{size / 1024 / 1024:.1f} MB，上限 {MAX_UPLOAD_BYTES // 1024 // 1024} MB）。"
            "请改用「视频 URL」方式，填入一个公网可访问的视频链接。"
        )
    mime = mimetypes.guess_type(path)[0] or "video/mp4"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{b64}"


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


def analyze(video_file, video_url, prompt, model, fps, api_key):
    """组装请求并调用 Ark Responses API，返回模型文字分析。"""
    url = (video_url or "").strip()
    if not url and video_file:
        url = _file_to_data_url(video_file)
    if not url:
        raise gr.Error("请上传视频文件，或填入一个视频 URL")

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
        r = requests.post(
            f"{BASE_URL}/responses",
            headers={
                "Authorization": f"Bearer {_api_key(api_key)}",
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
            run_btn = gr.Button("开始分析", variant="primary")
        with gr.Column(scale=1):
            output = gr.Markdown(label="分析结果")

    run_btn.click(
        analyze,
        inputs=[video_in, url_in, prompt_in, model_in, fps_in, key_in],
        outputs=output,
    )


if __name__ == "__main__":
    demo.launch()
