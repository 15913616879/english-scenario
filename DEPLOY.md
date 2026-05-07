# English Scenario 部署指南

## 飞牛 fnOS 部署

### 1. 安装 Docker（如果尚未安装）

fnOS 基于 Debian/Ubuntu，可以使用以下命令安装 Docker：

```bash
# 安装必要组件
sudo apt update
sudo apt install -y ca-certificates curl gnupg lsb-release

# 添加 Docker GPG 密钥
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# 添加 Docker 仓库
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 安装 Docker
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 启动 Docker
sudo systemctl start docker
sudo systemctl enable docker

# 添加当前用户到 docker 组（免 sudo）
sudo usermod -aG docker $USER
# 重新登录后生效
```

### 2. 部署应用

#### 方式一：使用 docker-compose（推荐）

```bash
# 创建部署目录
mkdir -p ~/english-scenario
cd ~/english-scenario

# 创建必要的目录
mkdir -p data data/tts_cache

# 创建 docker-compose.yml（使用以下内容）
cat > docker-compose.yml << 'EOF'
services:
  english-scenario:
    image: english-scenario:latest
    container_name: english-scenario
    restart: unless-stopped
    ports:
      - "5000:5000"
    volumes:
      - ./data:/app/data
    environment:
      - SECRET_KEY=your-secret-key-here
      - PORT=5000
EOF

# 构建并启动
docker compose up -d
```

#### 方式二：使用 Dockerfile

```bash
# 构建镜像
docker build -t english-scenario:latest .

# 运行容器
docker run -d \
  --name english-scenario \
  --restart unless-stopped \
  -p 5000:5000 \
  -v $(pwd)/data:/app/data \
  -e SECRET_KEY=your-secret-key-here \
  english-scenario:latest
```

### 3. 访问应用

部署完成后，访问：
- Web界面: http://你的服务器IP:5000
- API文档: http://你的服务器IP:5000/api/stats

### 4. 常用命令

```bash
# 查看容器状态
docker compose ps

# 查看日志
docker compose logs -f

# 重启服务
docker compose restart

# 更新部署
git pull
docker compose up -d --build

# 停止服务
docker compose down
```

### 5. 数据持久化

所有数据（数据库、TTS缓存）存储在 `./data` 目录：

```
data/
├── english.db      # SQLite数据库（学习记录）
└── tts_cache/      # TTS音频缓存
```

### 6. 配置反向代理（Nginx）

如果需要通过域名访问：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 7. HTTPS 配置

使用 Let's Encrypt 免费证书：

```bash
# 安装 certbot
sudo apt install -y certbot python3-certbot-nginx

# 获取证书
sudo certbot --nginx -d your-domain.com

# 自动续期已配置
```

### 8. 预生成 TTS 音频

首次部署后，建议预生成所有音频：

```bash
# 进入容器
docker exec -it english-scenario bash

# 预生成音频
python app.py &
# 或者使用 API
curl -X POST http://localhost:5000/api/pregenerate
```

### 9. 备份

```bash
# 备份数据
tar -czvf english-scenario-backup.tar.gz data/

# 恢复数据
tar -xzvf english-scenario-backup.tar.gz
```

### 10. 防火墙配置

```bash
# 开放 5000 端口
sudo ufw allow 5000

# 或仅允许特定IP访问
sudo ufw allow from 192.168.1.0/24 to any port 5000
```

## 直接在服务器上运行（不使用Docker）

```bash
# 安装 Python 3.11
sudo apt install -y python3.11 python3.11-venv python3-pip

# 创建虚拟环境
python3.11 -m venv venv
source venv/bin/activate

# 安装依赖
pip install flask edge-tts

# 运行
python app.py
```
