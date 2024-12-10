import os
import shutil
import json
from pathlib import Path
from typing import Optional, List, Dict
from fastapi import FastAPI, UploadFile, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pdf2zh.pdf2zh import extract_text
import tqdm
import uuid
from datetime import datetime
from dotenv import load_dotenv
from enum import Enum
import redis
from word import word  

# 加载环境变量
load_dotenv()

# API配置
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8080"))
BASE_URL = os.getenv("BASE_URL", f"http://{API_HOST}:{API_PORT}")

# Redis配置
REDIS_CONFIG = {
    "host": os.getenv("REDIS_CONFIG_HOST", "localhost"),
    "port": int(os.getenv("REDIS_CONFIG_PORT", 6379)),
    "db": int(os.getenv("REDIS_CONFIG_DB", 0)),
    "password": os.getenv("REDIS_CONFIG_PASSWORD", ""),
    "decode_responses": True
}

# Redis连接
redis_client = redis.Redis(**REDIS_CONFIG)

# Redis key前缀
REDIS_KEY_PREFIX = "pdf_translation:"
REDIS_EXPIRE_TIME = 60 * 60 * 24  # 24小时过期

app = FastAPI(
    title="PDF Translation API",
    description="PDF translation service with multiple translation providers",
    version="1.0.0"
)

# 存储翻译任务的状态
# translation_tasks = {}  # 移除内存字典

# 配置与gui.py相同的服务和语言映射
service_map = {
    "Google": ("google", None, None),
    "DeepL": ("deepl", "DEEPL_AUTH_KEY", None),
    "DeepLX": ("deeplx", "DEEPLX_AUTH_KEY", None),
    "Ollama": ("ollama", None, "gemma2"),
    "OpenAI": ("openai", "OPENAI_API_KEY", "gpt-4"),
    "Azure": ("azure", "AZURE_APIKEY", None),
    "Tencent": ("tencent", "TENCENT_SECRET_KEY", None),
}

lang_map = {
    "Chinese": "zh",
    "English": "en",
    "French": "fr",
    "German": "de",
    "Japanese": "ja",
    "Korean": "ko",
    "Russian": "ru",
    "Spanish": "es",
    "Italian": "it",
}

class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"     # 等待处理
    PROCESSING = "processing"  # 处理中
    COMPLETED = "completed"    # 已完成
    FAILED = "failed"      # 失败
    CANCELED = "canceled"     # 已取消

class DocumentType(str, Enum):
    """文档类型枚举"""
    PDF = "pdf"
    WORD = "word"

class PDFTranslationRequest(BaseModel):
    """PDF翻译请求参数"""
    task_id: str
    service: str = "OpenAI"
    apikey: Optional[str] = None
    model_id: Optional[str] = "gpt-4o-mini"
    lang_from: str = "English"
    lang_to: str = "Chinese"
    pages: Optional[List[int]] = None
    
    class Config:
        schema_extra = {
            "example": {
                "task_id": "your-task-id",
                "service": "OpenAI",
                "apikey": "your-api-key",
                "model_id": "gpt-4o-mini",
                "lang_from": "English",
                "lang_to": "Chinese",
                "pages": [1, 2, 3]
            }
        }

class WordTranslationRequest(BaseModel):
    """Word文档翻译请求参数"""
    task_id: str
    service: str = "OpenAI"
    apikey: Optional[str] = None
    model_id: Optional[str] = "gpt-4o-mini"
    lang_from: str = "English"
    lang_to: str = "Chinese"
    translation_type: str = "trans_text_only_inherit"  # 翻译类型，默认保留原文和格式
    
    class Config:
        schema_extra = {
            "example": {
                "task_id": "your-task-id",
                "service": "OpenAI",
                "apikey": "your-api-key",
                "model_id": "gpt-4o-mini",
                "lang_from": "English",
                "lang_to": "Chinese",
                "translation_type": "trans_text_only_inherit"
            }
        }

def save_task_status(task_id: str, status_data: dict):
    """保存任务状态到Redis"""
    redis_key = f"{REDIS_KEY_PREFIX}{task_id}"
    redis_client.set(redis_key, json.dumps(status_data), ex=REDIS_EXPIRE_TIME)

def get_task_status(task_id: str) -> Optional[dict]:
    """从Redis获取任务状态"""
    redis_key = f"{REDIS_KEY_PREFIX}{task_id}"
    data = redis_client.get(redis_key)
    return json.loads(data) if data else None

def update_task_progress(task_id: str):
    """更新任务进度的回调函数"""
    def callback(progress_data: dict):
        try:
            total_pages = progress_data.get("total", 0)
            current_page = progress_data.get("current", 0)
            
            if total_pages > 0:
                progress = round(current_page / total_pages, 2)
            else:
                progress = 0
                
            status_data = get_task_status(task_id)
            if status_data:
                status_data.update({
                    "progress": progress,
                    "message": f"Processing page {current_page} of {total_pages} ({progress * 100:.2f}%)",
                    "last_updated": datetime.now().isoformat()
                })
                save_task_status(task_id, status_data)
                
        except Exception as e:
            print(f"Error updating progress: {str(e)}")
    
    return callback

def get_date_directory() -> Path:
    """获取当前日期的目录路径"""
    current_time = datetime.now()
    year = current_time.strftime("%Y")
    month = current_time.strftime("%m")
    day = current_time.strftime("%d")
    return Path("pdf2zh_files") / year / month / day

@app.post("/upload/pdf", response_model=dict)
async def upload_pdf(file: UploadFile):
    """上传PDF文件"""
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(
            status_code=400,
            detail="仅支持PDF格式文件"
        )
    
    # 创建日期目录
    date_dir = get_date_directory()
    date_dir.mkdir(parents=True, exist_ok=True)
    
    # 生成唯一的任务ID
    task_id = str(uuid.uuid4())
    
    # 保存上传的文件
    file_path = date_dir / f"{task_id}.pdf"
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"文件保存失败: {str(e)}"
        )
    
    # 初始化任务状态
    status_data = {
        "task_id": task_id,
        "status": TaskStatus.PENDING,
        "progress": 0,
        "input_file": str(file_path),
        "last_updated": datetime.now().isoformat()
    }
    save_task_status(task_id, status_data)
    
    return {
        "task_id": task_id,
        "message": "PDF文件上传成功"
    }

@app.post("/upload/word", response_model=dict)
async def upload_word(file: UploadFile):
    """上传Word文档"""
    if not file.filename.lower().endswith(('.doc', '.docx')):
        raise HTTPException(
            status_code=400,
            detail="仅支持Word文档格式 (doc, docx)"
        )
    
    # 创建日期目录
    date_dir = get_date_directory()
    date_dir.mkdir(parents=True, exist_ok=True)
    
    # 生成唯一的任务ID
    task_id = str(uuid.uuid4())
    
    # 保存上传的文件
    file_ext = file.filename.split('.')[-1]
    file_path = date_dir / f"{task_id}.{file_ext}"
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"文件保存失败: {str(e)}"
        )
    
    # 初始化任务状态
    status_data = {
        "task_id": task_id,
        "status": TaskStatus.PENDING,
        "progress": 0,
        "input_file": str(file_path),
        "last_updated": datetime.now().isoformat()
    }
    save_task_status(task_id, status_data)
    
    return {
        "task_id": task_id,
        "message": "Word文档上传成功"
    }

@app.post("/translate/pdf")
async def translate_pdf(
    request: PDFTranslationRequest,
    background_tasks: BackgroundTasks
):
    """开始PDF翻译任务"""
    try:
        # 获取任务状态
        status = get_task_status(request.task_id)
        if not status:
            raise HTTPException(status_code=404, detail="任务不存在")
        
        input_file = Path(status.get("input_file", ""))
        if not input_file.exists():
            raise HTTPException(status_code=404, detail="源文件不存在")
        
        # 准备翻译参数
        param = request.dict()
        param["task_id"] = request.task_id
        
        # 添加后台任务
        background_tasks.add_task(
            process_pdf_translation,
            request.task_id,
            input_file,
            param
        )
        
        return {
            "task_id": request.task_id,
            "message": "PDF翻译任务已开始",
            "status": TaskStatus.PROCESSING
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/translate/word")
async def translate_word(
    request: WordTranslationRequest,
    background_tasks: BackgroundTasks
):
    """开始Word文档翻译任务"""
    try:
        # 获取任务状态
        status = get_task_status(request.task_id)
        if not status:
            raise HTTPException(status_code=404, detail="任务不存在")
        
        input_file = Path(status.get("input_file", ""))
        if not input_file.exists():
            raise HTTPException(status_code=404, detail="源文件不存在")
        
        # 准备翻译参数
        trans = {
            'id': request.task_id,
            'file_path': str(input_file),
            'service': request.service,
            'apikey': request.apikey,
            'model_id': request.model_id,
            'lang_from': request.lang_from,
            'lang_to': request.lang_to,
            'type': request.translation_type
        }
        
        # 添加后台任务
        background_tasks.add_task(
            process_word_translation,
            request.task_id,
            input_file,
            trans
        )
        
        return {
            "task_id": request.task_id,
            "message": "Word文档翻译任务已开始",
            "status": TaskStatus.PROCESSING
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def process_pdf_translation(task_id: str, input_file: Path, param: dict):
    """处理PDF翻译任务"""
    try:
        # 更新任务状态为处理中
        status_data = {
            "status": TaskStatus.PROCESSING,
            "progress": 0,
            "last_updated": datetime.now().isoformat()
        }
        save_task_status(task_id, status_data)
        
        # 执行PDF翻译
        extract_text(
            str(input_file),
            task_id=task_id,
            service=param.get('service', 'OpenAI'),
            apikey=param.get('apikey'),
            model_id=param.get('model_id', 'gpt-4o-mini'),
            lang_from=param.get('lang_from', 'English'),
            lang_to=param.get('lang_to', 'Chinese'),
            pages=param.get('pages'),
            progress_callback=update_task_progress
        )
        
        # 更新任务状态为完成
        output_file = str(input_file).replace('.pdf', '_translated.pdf')
        status_data = {
            "status": TaskStatus.COMPLETED,
            "progress": 100,
            "output_file": output_file,
            "last_updated": datetime.now().isoformat()
        }
        save_task_status(task_id, status_data)
        
    except Exception as e:
        # 更新任务状态为失败
        status_data = {
            "status": TaskStatus.FAILED,
            "error": str(e),
            "last_updated": datetime.now().isoformat()
        }
        save_task_status(task_id, status_data)
        raise

async def process_word_translation(task_id: str, input_file: Path, trans: dict):
    """处理Word文档翻译任务"""
    try:
        # 更新任务状态为处理中
        status_data = {
            "status": TaskStatus.PROCESSING,
            "progress": 0,
            "last_updated": datetime.now().isoformat()
        }
        save_task_status(task_id, status_data)
        
        # 执行Word文档翻译
        word.start(trans)
        
        # 更新任务状态为完成
        file_ext = input_file.suffix
        output_file = str(input_file).replace(file_ext, f"_translated{file_ext}")
        status_data = {
            "status": TaskStatus.COMPLETED,
            "progress": 100,
            "output_file": output_file,
            "last_updated": datetime.now().isoformat()
        }
        save_task_status(task_id, status_data)
        
    except Exception as e:
        # 更新任务状态为失败
        status_data = {
            "status": TaskStatus.FAILED,
            "error": str(e),
            "last_updated": datetime.now().isoformat()
        }
        save_task_status(task_id, status_data)
        raise

@app.get("/status/{task_id}")
async def get_translation_status(task_id: str) -> dict:
    """获取翻译任务的状态，立即返回当前状态"""
    try:
        status_data = get_task_status(task_id)
        if not status_data:
            raise HTTPException(
                status_code=404,
                detail=f"Task not found: {task_id}"
            )
        
        # 确保所有必要的字段都存在
        status_data.setdefault("task_id", task_id)
        status_data.setdefault("status", TaskStatus.PENDING)
        status_data.setdefault("progress", 0.0)
        status_data.setdefault("message", "Task status unknown")
        status_data.setdefault("error", None)
        status_data.setdefault("output_file", None)
        status_data.setdefault("last_updated", datetime.now().isoformat())
        
        # 检查任务目录是否存在
        output_dir = get_date_directory()
        if not output_dir.exists():
            status_data.update({
                "status": TaskStatus.FAILED,
                "message": "Date directory not found",
                "error": "Date directory missing"
            })
        
        # 如果任务已完成，检查输出文件
        if status_data["status"] == TaskStatus.COMPLETED:
            output_file = output_dir / f"{task_id}-zh.pdf"
            output_file_dual = output_dir / f"{task_id}-dual.pdf"
            
            if not (output_file.exists() and output_file_dual.exists()):
                status_data.update({
                    "status": TaskStatus.FAILED,
                    "message": "Output files missing",
                    "error": "Translation completed but output files are missing"
                })
        
        return status_data
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error getting task status: {str(e)}"
        )

@app.get("/download/{task_id}")
async def download_file(task_id: str, dual: bool = False):
    """下载翻译后的PDF文件"""
    try:
        print(f"Download request for task {task_id}, dual={dual}")
        
        # 检查任务状态
        status = get_task_status(task_id)
        if not status:
            print(f"Task {task_id} not found in status")
            raise HTTPException(status_code=404, detail="Task not found")
        
        print(f"Task status: {status}")
        
        if status["status"] != TaskStatus.COMPLETED:
            print(f"Task not completed, current status: {status['status']}")
            raise HTTPException(status_code=400, detail="Translation not completed")
        
        # 构建文件路径
        output_dir = get_date_directory()
        print(f"Looking in date directory: {output_dir}")
        print(f"Date directory exists: {output_dir.exists()}")
        
        if not output_dir.exists():
            raise HTTPException(status_code=404, detail="Date directory not found")
        
        # 根据dual参数选择文件
        filename = f"{task_id}-dual.pdf" if dual else f"{task_id}-zh.pdf"
        file_path = output_dir / filename
        
        if not file_path.exists():
            raise HTTPException(status_code=404, detail=f"File not found: {filename}")
        
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type="application/pdf"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error downloading file: {str(e)}"
        )

def get_download_url(task_id: str, dual: bool = False) -> str:
    """生成下载URL"""
    base_url = f"{BASE_URL}/download/{task_id}"
    if dual:
        return f"{base_url}?dual=true"
    return base_url
