# Dr.Li · 有记忆的 AI 口腔医生

这是一个支持长期记忆、文字与语音咨询的 AI 口腔医生演示。前台提供李医生真人形象、中文语音输入、等待状态动画，以及由阿里云百炼 TTS 和 VideoRetalk 生成的视频回答；后端保留原项目的当前记忆与 SQLite 长期记忆机制。整个数字人流程和全部视频素材只允许出现李医生，不使用患者或其他人物画面。

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

1. 复制配置并填写对话模型和百炼密钥：

   ```bash
   cp .env.example .env
   ```

2. 在 VS Code 中执行 `Dev Containers: Reopen in Container`。
3. 执行任务 `Dr.Li: 启动前后台`。
4. 打开 <http://localhost:5173>。首次使用语音时允许浏览器访问麦克风。

Dev Container 会把宿主机当前仓库显式绑定挂载到容器内的 `/workspace/memgpt_demo`。容器中的代码改动会立即同步到宿主机；`postCreateCommand` 会在该目录安装依赖，VS Code Task 也会以该目录作为 `${workspaceFolder}` 启动前后端。

推荐使用最新版 Chrome 或 Edge。浏览器原生语音识别通常需要联网；语音合成会优先选择操作系统提供的中文女声。

### 本地命令启动

```bash
python -m pip install -r requirements.txt
cp .env.example .env
# 编辑 .env，填写 LLM_API_KEY 和 DASHSCOPE_API_KEY
python -m uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

另开终端运行前端：

```bash
python -m http.server 5173 --directory frontend --bind 0.0.0.0
```

医生身份图位于 `frontend/assets/doctor-li.png`。未配置数字人服务或素材尚未生成时，页面自动使用浏览器中文语音和静态形象；配置完成后，页面会播放待机、聆听、思考状态视频，并在回答视频可播放时同步显示医生回复文字和播放视频。任何云端调用、视频生成或视频加载失败都会降级到浏览器语音和静态形象。

## 3.阿里云百炼数字人

本项目采用两类模型组合：

- `wan2.6-i2v-flash`：一次性生成待机、聆听和思考无声视频。
- `wan2.2-s2v`：一次性生成三段自然动作母版。
- `qwen3-tts-flash`：每次将医生回答转换为中文女声音频。
- `videoretalk`：每次把回答音频替换到随机母版中，保持身份和动作稳定。

全部模型均使用阿里云百炼华北 2（北京）地域。无需本地 GPU，也无需自行安装模型。
所有生成提示词都将“画面只能出现李医生一人”作为硬约束；状态视频和说话母版进入前端前仍须完成抽帧检查，包含患者、患者背影、手部或其他人物轮廓的素材不得使用。

### 3.1 配置

复制 `.env.example` 为 `.env`，然后填写对话模型和北京地域百炼密钥。当前完整配置如下：

```env
# 对话模型（OpenAI Chat Completions 兼容接口）
LLM_API_URL=https://api.moonshot.cn/v1/chat/completions
LLM_API_KEY=你的对话模型密钥
LLM_MODEL=moonshot-v1-auto

# 浏览器前端地址，多个地址使用英文逗号分隔
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

# 阿里云百炼（华北2/北京）TTS + VideoRetalk 数字人
DASHSCOPE_API_KEY=你的北京地域百炼APIKey
AVATAR_TTS_MODEL=qwen3-tts-flash
AVATAR_TTS_VOICE=Cherry
AVATAR_MASTER_VIDEOS=frontend/assets/doctor-speaking-long-01.mp4,frontend/assets/doctor-speaking-long-02.mp4,frontend/assets/doctor-speaking-long-03.mp4
AVATAR_REFERENCE_IMAGE=frontend/assets/doctor-li.png
AVATAR_TIMEOUT=300
AVATAR_POLL_INTERVAL=3

# 等待阶段使用的本地或远程循环视频
AVATAR_IDLE_VIDEO=assets/doctor-idle.mp4
AVATAR_LISTENING_VIDEO=assets/doctor-listening.mp4
AVATAR_THINKING_VIDEO=assets/doctor-thinking.mp4
```

密钥只写入已被 Git 忽略的 `.env`，不要写入代码、README 或 `.env.example`。

### 3.2 一次性生成素材

先预览任务，不会调用付费接口：

```bash
python scripts/generate_avatar_assets.py
```

确认费用后生成三段状态视频和三段短说话母版，并在本地合成三段长说话母版：

```bash
python scripts/generate_avatar_assets.py --confirm-paid-generation
```

也可以分开执行：

```bash
python scripts/generate_avatar_assets.py --states --confirm-paid-generation
python scripts/generate_avatar_assets.py --masters --confirm-paid-generation
python scripts/generate_avatar_assets.py --state listening --confirm-paid-generation
```

生成结果：

```text
frontend/assets/doctor-idle.mp4
frontend/assets/doctor-listening.mp4
frontend/assets/doctor-thinking.mp4
frontend/assets/doctor-speaking-01.mp4
frontend/assets/doctor-speaking-02.mp4
frontend/assets/doctor-speaking-03.mp4
frontend/assets/doctor-speaking-long-01.mp4
frontend/assets/doctor-speaking-long-02.mp4
frontend/assets/doctor-speaking-long-03.mp4
```

脚本会自动完成本地图片上传、异步任务轮询和 24 小时临时结果下载。状态视频固定使用 720P；说话母版默认使用更经济的 480P，可以通过 `--master-resolution 720P` 调高。S2V 的竖屏 480P 结果短边可能只有 512 像素，而 VideoRetalk 要求两条边均不小于 640 像素；脚本会在下载后通过 FFmpeg 等比放大到合规尺寸，再把三段同机位短母版按不同顺序无重叠拼接为约 23 秒的长母版，避免交叉淡化造成五官重影，并减少长回答触发倒放扩展的概率。已有短母版时可单独运行 `python scripts/generate_avatar_assets.py --compose-masters`，该操作完全在本地执行且不产生云端费用。

官方标价以 2026 年 8 月文档为准：三段 10 秒状态视频合计最多 9 元；三段说话母版按 TTS 实际时长计费，预计 12～18 元。新开通账号通常分别有 50 秒和 100 秒限时免费额度，是否抵扣以百炼控制台为准。

### 3.3 运行过程

1. 页面打开后循环播放待机视频。
2. 用户使用麦克风时切换到聆听视频。
3. 提交问题后立即循环播放思考视频。
4. 后端通过千问 TTS 生成音频 URL。
5. 后端自动把本地母版和参考图上传到百炼 48 小时临时存储，并提交 VideoRetalk。
6. 回答视频加载到可播放状态后，医生回复文字与视频同步出现。
7. 回答视频播放结束后回到待机视频。

VideoRetalk 是整段异步视频生成服务，不是实时流式数字人。生成期间页面会持续播放思考视频，实际等待时间可能达到几十秒或更长，费用随生成视频时长增加。百炼当前只允许一个 VideoRetalk 任务同时处理；前端会在回答视频可播放前锁定发送按钮，避免重复排队和额外计费。母版上传结果在进程内缓存 47 小时；生产高并发场景应迁移到长期 OSS。

应用接口：

- `GET /api/avatar/config`：返回启用状态、缺少配置和可用状态视频。
- `POST /api/avatar/render`：执行 TTS、VideoRetalk 提交和结果轮询。
- `GET /api/health`：`avatar_configured` 表示 Key 和母版素材是否齐全。
