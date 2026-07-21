# 视频分析小应用

调用**火山引擎方舟（Ark）豆包视频理解模型**，对视频做内容分析（理解已有视频，不是生成视频）。Web 界面（Gradio），支持本地上传或公网 URL。

## 功能

- 🎬 上传本地视频，或填公网视频 URL
- 📦 URL 视频超 50MB 时自动下载到本地压缩（依赖本机 ffmpeg）
- 💬 自定义分析指令（整体分析，或针对性提问）
- 🎚️ 可调抽帧 `fps`、模型 ID
- 🧩 基于 Ark **Responses API**，模型 `doubao-seed-2-1-pro-260628`

## 快速开始

```bash
# 1. 安装依赖（建议用虚拟环境）
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env，填入 ARK_API_KEY（控制台 https://console.volcengine.com/ark 获取）

# 3. 启动
python app.py
# 浏览器打开 http://127.0.0.1:7860
```

## 项目结构

```
video-test/
├── app.py            # 应用主体：请求组装 analyze() / 响应解析 _extract_text() / Gradio 界面
├── requirements.txt  # gradio / requests / python-dotenv
├── .env.example      # 配置模板
├── .env              # 真实密钥（git 忽略，需自行创建）
├── CLAUDE.md         # 项目上下文快照
├── docs/
│   └── vibe_coding_log.md   # AI 辅助开发轨迹记录
└── README.md
```

## 配置项（`.env`）

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `ARK_API_KEY` | ✅ | — | 方舟 API Key（也可在界面「高级设置」临时填） |
| `ARK_BASE_URL` | | `https://ark.cn-beijing.volces.com/api/v3` | Ark 接口地址 |
| `ARK_MODEL` | | `doubao-seed-2-1-pro-260628` | 模型 ID，或推理接入点 `ep-xxxx` |

## 用法

- **上传视频**：选本地文件（上限 50MB，即 Ark 服务端对输入视频的硬性限制）。
- **视频 URL**：填一个公网可访问的视频链接。视频超过 50MB（Ark 上限）时会先自动下载到 `tmp/` 并用 ffmpeg 压缩再分析，无需手动处理；下载/压缩的中间文件留在 `tmp/` 可定期清理。
- **分析指令**：默认做整体内容分析，也可改成具体问题（如「视频里有几个人？在做什么？」）。
- **高级设置**：可改模型 ID、抽帧 fps、临时覆盖 API Key。

## 接口说明

走 Ark 的 **Responses API**（`POST /responses`）。视频通过 `input_video` 内容块传入，`video_url` 支持公网 URL 或 base64 data URL，`fps` 为可选同级字段。请求结构（已实测）：

```bash
curl https://ark.cn-beijing.volces.com/api/v3/responses \
  -H "Authorization: Bearer $ARK_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "doubao-seed-2-1-pro-260628",
    "input": [
      { "role": "user", "content": [
        { "type": "input_video", "video_url": "https://example.com/demo.mp4", "fps": 1 },
        { "type": "input_text",  "text": "请详细分析这个视频" }
      ]}
    ]
  }'
```

响应里助手文字位于 `output[]` 中 `type=="message"` 项的 `content[].output_text`（`type=="reasoning"` 的思考项会被跳过）。

## 排查

| 现象 | 可能原因 |
|---|---|
| `调用失败（HTTP 401）` | API Key 无效或填错 |
| `param: video_url ... 404` | 视频 URL 公网不可访问（Ark 服务端拉不到） |
| 模型不支持视频 / 参数报错 | `ARK_MODEL` 换成支持视频输入的模型 |
| 上传报「视频过大」 | 本地文件超 50MB（Ark 上限）；改用 URL 方式可自动压缩，或先自行压缩 |
| 「预处理失败：未安装 ffmpeg」 | URL 视频超 50MB 需压缩，本机没装 ffmpeg：`brew install ffmpeg` |
| 「压缩两轮后仍超 50MB」 | 视频太长，码率压到保底仍超限，请手动裁剪 |

界面会直接显示 Ark 返回的原始错误信息，便于定位。

> 注：Seedance 是字节的**视频生成**模型；视频**理解/分析**用的是豆包视觉（doubao-seed）系列，本应用用的是后者。
