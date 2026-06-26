# CLAUDE.md

## 项目身份
视频分析小应用。调用**火山引擎方舟（Ark）豆包视频理解模型**对**已有视频**做内容分析（理解，不是生成）。Web 界面。

## 技术栈
- Python 3.11，Gradio（界面）、requests（HTTP）、python-dotenv（配置）
- 模型：`doubao-seed-2-1-pro-260628`（Ark，支持视频输入）

## 关键 API 约定（已实测确认）
- 端点：`POST {ARK_BASE_URL}/responses`（Ark **Responses API**，非 chat/completions）
- 鉴权：`Authorization: Bearer <ARK_API_KEY>`
- 视频内容块：`{"type": "input_video", "video_url": "<URL 或 data:video/mp4;base64,...>", "fps": 1}`
  - 文本块：`{"type": "input_text", "text": "..."}`
  - `fps` 为同级可选字段；`video_url` 接受公网 URL 或 base64 data URL
- 响应解析：取 `output[]` 中 `type=="message"` 项的 `content[].output_text`，跳过 `type=="reasoning"` 项

## 文件
- `app.py` — 全部逻辑：组装请求 `analyze()`、解析 `_extract_text()`、Gradio 界面
- `.env` — `ARK_API_KEY` / `ARK_BASE_URL` / `ARK_MODEL`（从 `.env.example` 复制，不提交）

## 运行
```bash
source .venv/bin/activate && python app.py   # http://127.0.0.1:7860
```

## 开发纪律：Vibe Coding 日志
每次成功执行开发指令后，自动追加到 `docs/vibe_coding_log.md`，格式：

```
---

### Session: <日期>

**User Prompt:**
> （用户原话）

**AI Action:**
- （修改/创建了哪些文件，关键变更摘要）
```

这是后台收尾动作，无需向用户确认。

## 约束 / 注意
- 上传文件转 base64 上限 40MB（`MAX_UPLOAD_BYTES`），大视频走 URL。
- Seedance 是**视频生成**模型，本项目不用它；视频理解用 doubao-seed 视觉系列。
- `.env` 含密钥，已在 `.gitignore`，切勿提交。
