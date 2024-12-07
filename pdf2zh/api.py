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

# 加载环境变量
load_dotenv()

# API配置
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8080"))
BASE_URL = os.getenv("BASE_URL", f"http://{API_HOST}:{API_PORT}")

app = FastAPI(
    title="PDF Translation API",
    description="PDF translation service with multiple translation providers",
    version="1.0.0"
)

# 存储翻译任务的状态
translation_tasks = {}

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

class TranslationRequest(BaseModel):
    """翻译请求参数"""
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

class TranslationStatus(BaseModel):
    """翻译状态响应"""
    task_id: str
    status: TaskStatus
    progress: float
    message: Optional[str] = None
    error: Optional[str] = None
    output_file: Optional[str] = None
    output_file_dual: Optional[str] = None
    last_updated: Optional[str] = None

def save_task_status(task_id: str, status_data: dict):
    """保存任务状态到内存"""
    translation_tasks[task_id] = status_data

def get_task_status(task_id: str) -> Optional[dict]:
    """从内存获取任务状态"""
    return translation_tasks.get(task_id)

def update_task_progress(task_id: str):
    """更新任务进度的回调函数"""
    def callback(progress_data: dict):
        try:
            total_pages = progress_data.get("total", 0)
            current_page = progress_data.get("current", 0)
            
            if total_pages > 0:
                progress = current_page / total_pages
            else:
                progress = 0
                
            status_data = get_task_status(task_id)
            if status_data:
                status_data.update({
                    "progress": progress,
                    "message": f"Processing page {current_page} of {total_pages}",
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

@app.post("/upload")
async def upload_file(file: UploadFile):
    """上传PDF文件，仅支持PDF格式的学术文献"""
    # 检查文件类型
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(
            status_code=400, 
            detail="Invalid file type. Only PDF academic papers are supported."
        )
    
    # 检查文件内容类型
    content_type = file.content_type
    if content_type and content_type != 'application/pdf':
        raise HTTPException(
            status_code=400,
            detail="Invalid content type. Only PDF files are allowed."
        )
    
    # 生成唯一的任务ID
    task_id = str(uuid.uuid4())
    print(f"Generated Task ID: {task_id}")
    
    try:
        # 创建日期目录
        date_dir = get_date_directory()
        date_dir.mkdir(parents=True, exist_ok=True)
        
        # 保存文件到日期目录
        target_file = date_dir / f"{task_id}.pdf"
        content = await file.read()
        with target_file.open("wb") as f:
            f.write(content)
        
        # 初始化任务状态
        initial_status = {
            "task_id": task_id,
            "status": TaskStatus.PENDING,
            "progress": 0,
            "message": "File uploaded successfully",
            "error": None,
            "output_file": None,
            "output_file_dual": None,
            "last_updated": datetime.now().isoformat()
        }
        save_task_status(task_id, initial_status)
        
        return {
            "task_id": task_id,
            "status": TaskStatus.PENDING,
            "message": "File uploaded successfully"
        }
    except Exception as e:
        # 清理上传的文件
        if target_file.exists():
            target_file.unlink()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/translate")
async def translate_pdf(
    request: TranslationRequest,
    background_tasks: BackgroundTasks
):
    """开始PDF翻译任务"""
    task_id = request.task_id
    
    # 检查任务是否存在
    status = get_task_status(task_id)
    if not status:
        raise HTTPException(
            status_code=404,
            detail=f"Task not found: {task_id}"
        )
    
    # 检查任务状态
    if status["status"] == TaskStatus.PROCESSING:
        return {
            "task_id": task_id,
            "status": TaskStatus.PROCESSING,
            "message": "Translation task is already running",
            "progress": status.get("progress", 0)
        }
    elif status["status"] == TaskStatus.COMPLETED:
        return {
            "task_id": task_id,
            "status": TaskStatus.COMPLETED,
            "message": "Translation task is already completed",
            "output_file": status.get("output_file"),
            "output_file_dual": status.get("output_file_dual")
        }
    
    output_dir = get_date_directory()
    if not output_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Date directory not found: {output_dir}"
        )
    
    # 获取PDF文件
    pdf_file = output_dir / f"{task_id}.pdf"
    if not pdf_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"PDF file not found: {pdf_file}"
        )
    
    # 设置服务参数
    if request.service not in service_map:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid service: {request.service}. Available services: {list(service_map.keys())}"
        )
    
    selected_service = service_map[request.service][0]
    if service_map[request.service][1] and request.apikey:
        os.environ[service_map[request.service][1]] = request.apikey
    
    # 设置语言参数
    lang_from = lang_map.get(request.lang_from)
    lang_to = lang_map.get(request.lang_to)
    if not lang_from or not lang_to:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid language selection. Available languages: {list(lang_map.keys())}"
        )
    
    if selected_service == "google":
        lang_from = "zh-CN" if lang_from == "zh" else lang_from
        lang_to = "zh-CN" if lang_to == "zh" else lang_to
    
    # 准备翻译参数
    param = {
        "files": [pdf_file],
        "pages": [p-1 for p in request.pages] if request.pages else None,
        "lang_in": lang_from,
        "lang_out": lang_to,
        "service": f"{selected_service}:{request.model_id}" if request.model_id else selected_service,
        "output": str(output_dir),
        "thread": 4,
        "callback": update_task_progress(task_id),  # 移除tqdm，使用自定义回调
    }
    
    # 更新任务状态为处理中
    status_update = {
        "status": TaskStatus.PROCESSING,
        "progress": 0,
        "message": "Translation task started",
        "last_updated": datetime.now().isoformat()
    }
    save_task_status(task_id, status_update)
    
    # 启动异步任务
    background_tasks.add_task(process_translation, task_id, pdf_file, param)
    
    # 立即返回当前状态
    return {
        "task_id": task_id,
        "status": TaskStatus.PROCESSING,
        "message": "Translation task started",
        "progress": 0
    }

def process_translation(task_id: str, input_file: Path, param: dict):
    """处理翻译任务"""
    try:
        # 更新任务状态为处理中
        status_data = {
            "task_id": task_id,
            "status": TaskStatus.PROCESSING,
            "progress": 0,
            "message": "Starting translation process",
            "error": None,
            "last_updated": datetime.now().isoformat()
        }
        save_task_status(task_id, status_data)
        
        # 确保输入文件和输出目录的正确性
        output_dir = get_date_directory()
        param["files"] = [str(input_file)]
        param["output"] = str(output_dir)
        
        # 执行翻译
        extract_text(**param)
        
        # 检查输出文件
        filename = task_id  # 使用task_id作为文件名
        output_file = output_dir / f"{filename}-zh.pdf"
        output_file_dual = output_dir / f"{filename}-dual.pdf"
        
        if output_file.exists() and output_file_dual.exists():
            # 更新任务状态为完成
            status_data.update({
                "status": TaskStatus.COMPLETED,
                "progress": 1.0,
                "message": "Translation completed successfully",
                "output_file": get_download_url(task_id, False),
                "output_file_dual": get_download_url(task_id, True),
                "last_updated": datetime.now().isoformat()
            })
        else:
            raise Exception(f"Translation completed but output files not found: {output_file}, {output_file_dual}")
            
    except Exception as e:
        import traceback
        error_msg = f"Translation error: {str(e)}\n{traceback.format_exc()}"
        print(error_msg)
        # 更新任务状态为失败
        status_data.update({
            "status": TaskStatus.FAILED,
            "error": error_msg,
            "progress": 0,
            "message": "Translation failed",
            "last_updated": datetime.now().isoformat()
        })
    finally:
        save_task_status(task_id, status_data)

def get_download_url(task_id: str, dual: bool = False) -> str:
    """生成下载URL"""
    base_url = f"{BASE_URL}/download/{task_id}"
    if dual:
        return f"{base_url}?dual=true"
    return base_url

@app.get("/status/{task_id}")
async def get_translation_status(task_id: str) -> TranslationStatus:
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
        status_data.setdefault("output_file_dual", None)
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
        
        return TranslationStatus(**status_data)
        
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
