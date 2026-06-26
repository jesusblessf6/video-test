# 视频分析小应用

调用**火山引擎方舟（Ark）豆包视频理解模型**，对视频做内容分析（理解已有视频，不是生成视频）。Web 界面（Gradio），支持本地上传或公网 URL。

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

## 用法

- **上传视频**：直接选本地文件（默认上限 40MB，过大请用 URL 方式）。
- **视频 URL**：填一个公网可访问的视频链接，大文件优先用这个。
- **分析指令**：默认会做整体内容分析，也可改成具体问题（如「视频里有几个人？在做什么？」）。
- **高级设置**：可改模型 ID、抽帧 fps、临时覆盖 API Key。

## 说明

- 接口是 Ark 的 **Responses API**（`/responses`），视频通过 `input_video` 内容块传入，`video_url` 支持公网 URL 或 base64 data URL，可选 `fps` 抽帧参数。
- 模型默认 `doubao-seed-2-1-pro-260628`（支持视频输入）。若你在控制台创建了推理接入点，把 `ARK_MODEL` 改成 `ep-xxxx` 即可。
- 若报错，界面会直接显示 Ark 返回的原始错误信息，便于排查（key 无效 / 模型不支持视频 / 视频格式等）。

> 注：Seedance 是字节的**视频生成**模型；视频**理解/分析**用的是豆包视觉（doubao-seed）系列，本应用用的是后者。
