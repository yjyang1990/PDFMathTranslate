import logging
from fastapi import FastAPI
from pdf2zh.api import app as pdf_app

# 配置日志
logging.basicConfig(
    level=logging.WARNING,  # 默认只显示警告及以上级别
    format='%(message)s',   # 简化日志格式
    handlers=[
        logging.StreamHandler()  # 只输出到控制台
    ]
)

# 只允许特定模块的INFO日志
logging.getLogger("pdf2zh.translator").setLevel(logging.INFO)

app = FastAPI(
    title="PDF Math Translate API",
    description="PDF Math Document Translation Service",
    version="0.1.0"
)

# 挂载 PDF 翻译 API
app.mount("/", pdf_app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
