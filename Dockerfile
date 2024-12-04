# 使用Python 3.11作为基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 安装Python依赖
RUN pip install --no-cache-dir \
    python-dotenv \
    redis \
    doclayout-yolo \
    torch \
    onnx \
    onnxruntime \
    opencv-python-headless

# 复制项目文件
COPY . .

# 创建默认的.env文件
RUN echo "API_HOST=0.0.0.0\n\
API_PORT=8081\n\
BASE_URL=http://103.73.163.68:8081\n\
REDIS_CONFIG_HOST=127.0.0.1\n\
REDIS_CONFIG_PORT=6379\n\
REDIS_CONFIG_DB=0\n\
REDIS_CONFIG_PASSWORD=lianggehuangli\n\
OPENAI_API_KEY=sk-LRDDbSj4PyI7VeW83401Bd89170041F59aCa417fD7424a46\n\
OPENAI_BASE_URL=https://api.bltcy.ai/v1\n\
" > .env

# 安装项目
RUN pip install --no-cache-dir -e .

# 创建数据目录
RUN mkdir -p pdf2zh_files && \
    chmod 777 pdf2zh_files

# 暴露API端口
EXPOSE 8081

# 启动命令
CMD ["uvicorn", "pdf2zh.api:app", "--host", "0.0.0.0", "--port", "8081"]