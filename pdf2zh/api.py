from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import FileResponse
import tempfile
import os
import shutil
import logging
from typing import Optional
from pdf2zh.pdf2zh import extract_text
import asyncio
from concurrent.futures import ThreadPoolExecutor

# 配置日志
logging.basicConfig(level=logging.WARNING)  # 修改默认日志级别为WARNING
logger = logging.getLogger(__name__)

app = FastAPI(
    title="PDF Math Translate API",
    description="API service for translating PDF documents with mathematical formulas",
    version="1.0.0"
)

@app.post("/translate/", tags=["Translation"])
async def translate_pdf(
    file: UploadFile = File(...),
    lang_in: str = Form("en"),
    lang_out: str = Form("zh-CN"),
    service: str = Form("openai:gpt-4o-mini")
):
    """
    翻译上传的PDF文件
    
    Parameters:
    - file: PDF文件
    - lang_in: 输入语言 (默认: en)
    - lang_out: 输出语言 (默认: zh-CN)
    - service: 翻译服务 (可选: google, deepl, deeplx, ollama:model, openai:model, azure)
    
    Returns:
    - 翻译后的PDF文件
    """
    try:
        # 创建临时目录
        with tempfile.TemporaryDirectory() as temp_dir:
            # 保存上传的文件
            temp_pdf = os.path.join(temp_dir, file.filename)
            logger.info(f"Saving uploaded file to {temp_pdf}")
            
            with open(temp_pdf, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            
            # 获取文件名（不含扩展名）
            filename = os.path.splitext(file.filename)[0]
            
            # 执行翻译
            logger.info(f"Starting translation with service: {service}")
            logger.info(f"Input file: {temp_pdf}")
            
            # 保存当前工作目录
            original_cwd = os.getcwd()
            
            try:
                # 切换到临时目录
                os.chdir(temp_dir)
                logger.info(f"Changed working directory to: {os.getcwd()}")
                
                # 使用线程池执行翻译，设置超时
                with ThreadPoolExecutor(max_workers=4) as executor:
                    future = executor.submit(
                        extract_text,
                        files=[temp_pdf],
                        lang_in=lang_in,
                        lang_out=lang_out,
                        service=service,
                        thread=4
                    )
                    
                    try:
                        # 等待翻译完成，设置超时时间（例如300秒）
                        future.result(timeout=300)
                    except TimeoutError:
                        logger.error("Translation timed out")
                        raise HTTPException(status_code=504, detail="Translation timed out")
                    except Exception as e:
                        logger.error(f"Translation failed: {str(e)}")
                        raise HTTPException(status_code=500, detail=f"Translation failed: {str(e)}")
                
            except Exception as e:
                logger.error(f"Extract text failed: {str(e)}")
                raise
            finally:
                # 恢复工作目录
                os.chdir(original_cwd)
                logger.info(f"Restored working directory to: {os.getcwd()}")
            
            # 获取生成的文件路径
            zh_pdf = os.path.join(temp_dir, f"{filename}-zh.pdf")
            dual_pdf = os.path.join(temp_dir, f"{filename}-dual.pdf")
            
            logger.info(f"Checking output files...")
            logger.info(f"Temp directory contents: {os.listdir(temp_dir)}")
            
            if not os.path.exists(zh_pdf):
                raise HTTPException(status_code=500, detail="Translation failed: Output file not generated")
            
            # 将文件移动到新的临时位置
            output_dir = tempfile.mkdtemp()
            final_zh_pdf = os.path.join(output_dir, f"{filename}-zh.pdf")
            final_dual_pdf = os.path.join(output_dir, f"{filename}-dual.pdf")
            
            shutil.copy2(zh_pdf, final_zh_pdf)
            if os.path.exists(dual_pdf):
                shutil.copy2(dual_pdf, final_dual_pdf)
            
            logger.info(f"Translation completed successfully")
            
            # 返回中文版PDF
            return FileResponse(
                final_zh_pdf,
                media_type="application/pdf",
                filename=f"{filename}-zh.pdf"
            )
            
    except Exception as e:
        logger.error(f"Error during translation: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/services/", tags=["Information"])
async def list_services():
    """
    获取支持的翻译服务列表
    """
    return {
        "services": [
            {
                "name": "google",
                "description": "Google Translate (免费，无需配置)",
                "config_needed": False
            },
            {
                "name": "deepl",
                "description": "DeepL API (需要 API Key)",
                "config_needed": True,
                "env_vars": ["DEEPL_AUTH_KEY", "DEEPL_SERVER_URL"]
            },
            {
                "name": "deeplx",
                "description": "DeepLX API (需要 API Key)",
                "config_needed": True,
                "env_vars": ["DEEPLX_AUTH_KEY", "DEEPLX_SERVER_URL"]
            },
            {
                "name": "ollama:model_name",
                "description": "Ollama 本地模型 (需要安装 Ollama)",
                "config_needed": True,
                "example": "ollama:llama2"
            },
            {
                "name": "openai:model_name",
                "description": "OpenAI API (需要 API Key)",
                "config_needed": True,
                "env_vars": ["OPENAI_API_KEY", "OPENAI_BASE_URL"],
                "example": "openai:gpt-3.5-turbo"
            },
            {
                "name": "azure",
                "description": "Azure Translator (需要 Azure 配置)",
                "config_needed": True,
                "env_vars": ["AZURE_APIKEY", "AZURE_ENDPOINT", "AZURE_REGION"]
            }
        ]
    }

def main():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main()
