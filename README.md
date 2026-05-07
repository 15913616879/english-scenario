# English Scenario Practice — 项目文档

## 项目来源

基于 Obsidian 笔记「A英语学习场景练习计划」构建的个人英语学习工具。

- **数据源**：Obsidian vault `StarStar/英语学习/` 下的对话文档
- **现有内容**：10 大类 × 10 场景 = 100 个占位，其中 2 篇已写好（Setting the Alarm / Waking Up）
- **角色**：Star（你，27 岁男生）、Alex（室友/死党）、Emma（同事/朋友）
- **难度**：CEFR A2，最口语、最简单、最生活化的英语
- **对话规范**：每篇 8–10 句，角色色块区分，相邻场景双向关联

## 技术架构

```
浏览器（手机/平板/PC）
        │
        ▼
   Nginx 反向代理（用户自己的域名 + DDNS）
        │
        ▼
   Docker 容器（飞牛 NAS 上运行）
   ├── Python Flask（后端 API）
   ├── SQLite（浏览记录 activity 表）
   ├── edge-tts（微软免费 TTS，缓存到本地）
   └── 纯 HTML/CSS/JS（前端单页应用）
```

## 功能清单

### v2 当前功能

| 功能 | 说明 |
|------|------|
| 分类浏览 | 10 大类卡片，手机竖排 / 平板两列 / PC 三列 |
| 场景列表 | 点击分类进入场景列表，已浏览标注绿点 |
| 聊天气泡对话 | 微信风格气泡：Star 蓝色靠右，Alex 绿色靠左，Emma 粉色靠左 |
| 三种练习模式 | Read（全文阅读）/ Cover（遮盖 Star 台词）/ Fill（关键词填空） |
| TTS 逐句发音 | 点击气泡播放 edge-tts 美式女声，首次 1-2 秒，缓存后秒出 |
| 全文自动播放 | 点 Play All 按钮，顺序播放全部句子 |
| 复习模式 | 浏览历史 + 随机复习 |
| 响应式布局 | 手机（<640px）/ 平板（640-1024px）/ PC（>1024px 两栏） |
| 底部导航 | Learn / Review / About 三 tab |

### 已砍掉的功能

| 功能 | 原因 |
|------|------|
| PIN 登录 | 用户自己在 Nginx 层做访问控制 |
| 打卡进度系统 | 太复杂，简化成浏览记录追踪 |
| 进度条 | 跟打卡一起砍掉 |

## 项目文件

```
english-scenario/
├── app.py                 # Flask 后端（API + TTS + SQLite）
├── data/
│   ├── dialogues.json     # 对话数据（100 个场景）
│   ├── english.db         # SQLite 数据库（自动创建）
│   └── tts_cache/         # TTS 音频缓存（自动创建）
├── templates/
│   └── index.html         # 前端单页应用
├── requirements.txt       # Python 依赖
├── Dockerfile             # Docker 镜像打包
├── docker-compose.yml     # 一键部署配置
└── README.md              # 本文档
```

## API 清单

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 返回前端页面 |
| GET | `/api/categories` | 全部 10 大类 + 场景清单 + 浏览状态 |
| GET | `/api/scenario/<id>` | 单篇对话全文（含 TTS hash + 自动记录浏览） |
| GET | `/api/review` | 最近浏览历史（倒序，最多 50 条） |
| POST | `/api/tts` | `{"text": "..."}` → 返回 MP3 音频流 |

## TTS 实现

- **引擎**：edge-tts（微软 Edge 免费语音合成）
- **声音**：`en-US-JennyNeural`（美式女声）
- **缓存策略**：SHA256(text)[:12] → `data/tts_cache/<hash>.mp3`
- **性能**：首次生成 ~1.8 秒，缓存命中 ~0.02 秒
- **持久化**：Docker volume 挂载 `./data` 目录

## 部署步骤

### 本地开发

```bash
cd english-scenario
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
# 打开 http://127.0.0.1:5000
```

### Docker 本地测试

```bash
docker build -t english-scenario:latest .
docker run -d --name english-test -p 5099:5000 english-scenario:latest
# 打开 http://127.0.0.1:5099
```

### 部署到飞牛 NAS

```bash
# 1. 把 english-scenario/ 文件夹传到 NAS
# 2. 在飞牛 Docker 中导入 docker-compose.yml
# 3. 配置端口映射（默认 8888:5000）
# 4. 启动容器
# 5. 配 Nginx 反向代理 + DDNS 域名
```

### docker-compose.yml 关键配置

```yaml
services:
  english:
    image: english-scenario:latest
    ports:
      - "8888:5000"
    volumes:
      - ./data:/app/data          # 持久化数据库 + TTS 缓存
    environment:
      - SECRET_KEY=your-random-key
    restart: unless-stopped
```

## 如何添加新对话

1. 在 Obsidian 里写对话（遵循 A2 规范）
2. 编辑 `data/dialogues.json`，找到对应场景的 `id`
3. 把 `"status": "placeholder"` 改成 `"ready"`
4. 填写 `lines` 数组（每项 `{"speaker": "Star", "text": "..."}`）
5. 填写 `blanks` 数组（填空模式用，关键词用 `___` 替换）
6. 重启容器：`docker restart english-scenario`

## 决策记录

| 决策 | 选择 | 原因 |
|------|------|------|
| 后端语言 | Python Flask | 零基础看得懂，代码量最少 |
| 数据库 | SQLite | 单文件，不需安装，Docker volume 持久化 |
| 前端框架 | 无框架，纯 HTML/CSS/JS | 不增加学习成本，单页应用够用 |
| 部署方式 | Docker 单镜像 | 飞牛 NAS 一键部署，所有依赖打包 |
| TTS 引擎 | edge-tts | 免费、无需 API Key、质量好 |
| 外网访问 | 自有域名 + DDNS + Nginx | 已有域名，不用 Cloudflare Tunnel |
| UI 风格 | 微信聊天气泡 | 直觉式交互，角色色块区分 |
| 响应式 | CSS media queries 三断点 | PC/平板/手机自适应，不锁死宽度 |
| 认证 | 砍掉 PIN | 用户在 Nginx/防火墙层自行控制 |
| 打卡系统 | 砍掉 | 简化成浏览记录，不要进度压力 |

## 用户偏好

- 中文母语，偏好编号列表、表格等结构化表达
- 零编程基础，需要清晰的步骤和解释
- 输出风格：简洁直接，一个点一句话
- 决策前给 3 个方案选择，确认后干到底
- 部署环境：飞牛 NAS（支持 Docker），自有域名 + DDNS
