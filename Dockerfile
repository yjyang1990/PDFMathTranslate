# 使用Python 3.11作为基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV REDIS_CONFIG_HOST=redis
ENV REDIS_CONFIG_PORT=6379

# 安装系统依赖
RUN apt-get update && apt-get install -y \
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
    onnxruntime

# 复制项目文件
COPY . .

# 安装项目
RUN pip install --no-cache-dir -e .

# 创建数据目录
RUN mkdir -p pdf2zh_files && \
    chmod 777 pdf2zh_files

# 暴露API端口
EXPOSE 8080

# 启动命令
CMD ["uvicorn", "pdf2zh.api:app", "--host", "0.0.0.0", "--port", "8080"]