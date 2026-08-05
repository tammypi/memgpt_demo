# Dr.Li · 有记忆的 AI 口腔医生

这是一个支持长期记忆、文字与语音咨询的 AI 口腔医生演示。Kimi 负责文本生成；CosyVoice 2 和 MuseTalk 1.5 在本机分别完成中文语音与真人口型，不上传人脸或语音，也不产生按次数字人费用。后端保留原项目的当前记忆与 SQLite 长期记忆机制。

![Dr.Li AI 口腔诊室界面](./images/dr-li-interface.png)

## 1.原理

主要思路来自于论文《**MemGPT: Towards LLMs as Operating Systems**》

智能体定位：口腔医生，女性，姓李。温柔专业。

特点：具有记忆功能。

智能体记忆包含2个部分：

- 当前记忆（current_memory): 含有working_context和FIFO Queue
- 长期记忆（long_memory):持久化到sqlite

智能体可以调用的工具列表：

- current_memory_append(text)：将重要的对话内容/事实（仅记录用户信息、健康医疗相关内容）存入当前记忆。
- current_memory_replace(old, new)：替换当前记忆中与旧内容匹配的部分，适用于事实更新或修正。
- long_memory_search(keyword)：从长期记忆区中搜索包含指定关键字的记录。
- long_memory_upload(text)：对当前对话或重要事件进行归纳总结，并存入长期记忆区。

这些记忆能力使用 OpenAI Chat Completions 兼容的原生 `tools/tool_calls` 协议：后端向模型声明 JSON Schema，按模型返回的 `tool_calls` 执行工具，并以对应的 `tool_call_id` 回传 `role=tool` 结果，直到模型生成最终答复。项目不再解析模型文本中的自定义工具标签。

## 2.快速启动（推荐）

### Dev Container + VS Code Task

1. 复制配置并填写 Kimi 密钥：

   ```bash
   cp .env.example .env
   ```

2. 在 VS Code 中执行 `Dev Containers: Reopen in Container`。
3. 执行任务 `Dr.Li: 启动前后台`。
4. 打开 <http://localhost:5173>。首次使用语音时允许浏览器访问麦克风。

Dev Container 会把宿主机当前仓库显式绑定挂载到容器内的 `/workspace/memgpt_demo`。容器中的代码改动会立即同步到宿主机；`postCreateCommand` 会在该目录安装依赖，VS Code Task 也会以该目录作为 `${workspaceFolder}` 启动前后端。

推荐使用最新版 Chrome 或 Edge。浏览器原生语音识别通常需要联网；医生回答语音不使用浏览器 TTS。

### 本地命令启动

```bash
python -m pip install -r requirements.txt
cp .env.example .env
# 编辑 .env，填写 LLM_API_KEY
python -m uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

另开终端运行前端：

```bash
python -m http.server 5173 --directory frontend --bind 0.0.0.0
```

医生身份图位于 `frontend/assets/doctor-li.png`。本地模型尚未安装时，页面仍可文字咨询，但不会使用不自然的浏览器 TTS 或 CSS 假口型。

## 3.本地数字人

### 3.1 安装

Dev Container 重建完成后，在容器终端执行：

```bash
./scripts/install_local_avatar.sh
```

脚本从官方仓库安装 CosyVoice 2、MuseTalk 1.5 及其模型。模型保存在被 Git 忽略的 `models/`，不会进入镜像或仓库。完成后重启后端，用下面命令检查：

```bash
nvidia-smi
curl http://localhost:8000/api/avatar/config
```

返回的 `enabled` 为 `true` 即表示模型与母版路径齐全。

### 3.2 6GB 显存策略

- CosyVoice 2 0.5B 在 CPU 中惰性加载并常驻，避免占用显存。
- MuseTalk 1.5 使用 FP16 串行生成，子进程结束即释放显存。
- Kimi 回答按标点切为最多 70 字的片段；前端轮询任务，新片段生成后立即播放。
- 同一时间只运行一个数字人任务，避免并发导致 CUDA OOM。
- 输出位于 `data/avatar/`，仅通过本机 `/avatar-files` 路径提供给前端。

如需克隆指定音色，准备一段清晰的 16 kHz 单人语音，并同时设置：

```env
AVATAR_TTS_PROMPT_WAV=data/voice/doctor-li.wav
AVATAR_TTS_PROMPT_TEXT=参考音频中逐字对应的文本
```

`.env.example` 默认使用 CosyVoice 官方零样本参考音频。正式演示建议换成授权清晰女声；参考文本必须与音频逐字一致。其他路径与分段长度见 `.env.example`。

### 3.3 接口

- `WS /api/chat/ws`：发送 `{ "message": "..." }` 后，按 `delta`、`done` 或 `error` 消息实时接收回答；上游 LLM 使用 `stream: true`。
- `GET /api/avatar/config`：本地模型、母版及状态视频配置。
- `POST /api/avatar/render`：创建本地异步生成任务。
- `GET /api/avatar/jobs/{job_id}`：返回任务状态和已完成片段。
- `GET /api/health`：`avatar_configured` 表示本地模型是否齐全。
