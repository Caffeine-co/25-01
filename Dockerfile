# 使用 Python 3.11 轻量级基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 优先拷贝 requirements.txt 以利用 Docker 缓存层加速依赖安装
COPY requirements.txt .

# 安装项目依赖
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝项目的所有文件到工作目录
COPY . .

# 提供非敏感配置的默认运行文件。
# 用户仍可以通过 volume 覆盖这些文件。
RUN cp active_model.example.json active_model.json \
    && cp default_status.example.json default_status.json \
    && cp location.example.json location.json \
    && cp image_metadata.example.json image_metadata.json

# 暴露 NoneBot 默认端口（根据 configs.json 配置，这里是 2501）
EXPOSE 2501

# 设置容器启动时执行的命令
CMD ["python", "bot.py"]