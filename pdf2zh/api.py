import os
import shutil
import json
import hashlib
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

# 存储文件哈希映射
file_hash_mapping: Dict[str, str] = {}

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
    PENDING = "pending"      # 等待开始
    PROCESSING = "processing"  # 处理中
    COMPLETED = "completed"    # 已完成
    FAILED = "failed"         # 失败
    CANCELED = "canceled"     # 已取消

class TranslationRequest(BaseModel):
    service: str = "OpenAI"  # 默认使用OpenAI
    apikey: Optional[str] = None
    model_id: Optional[str] = "gpt-4o-mini"  # 默认使用最新的GPT-4模型
    lang_from: str = "English"  # 默认从英语翻译
    lang_to: str = "Chinese"    # 默认翻译到中文
    pages: Optional[List[int]] = None

    class Config:
        schema_extra = {
            "example": {
                "service": "OpenAI",
                "apikey": "your-api-key",
                "model_id": "gpt-4o-mini",
                "lang_from": "English",
                "lang_to": "Chinese",
                "pages": [1, 2, 3]
            }
        }

class TranslationStatus(BaseModel):
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
    status_data["last_updated"] = datetime.now().isoformat()
    translation_tasks[task_id] = status_data

def get_task_status(task_id: str) -> Optional[dict]:
    """从内存获取任务状态"""
    return translation_tasks.get(task_id)

def save_file_hash_mapping(file_hash: str, task_id: str):
    """保存文件哈希值与任务ID的映射关系到内存"""
    file_hash_mapping[file_hash] = task_id

def get_task_by_file_hash(file_hash: str) -> Optional[str]:
    """通过文件哈希值获取任务ID"""
    return file_hash_mapping.get(file_hash)

def update_task_progress(task_id: str, t: tqdm.tqdm):
    """更新任务进度的回调函数"""
    def progress_callback(progress_obj):
        t.update(1)  # 更新tqdm进度
        progress = t.n / t.total if t.total > 0 else 0
        status_data = {
            "task_id": task_id,
            "status": TaskStatus.PROCESSING,
            "progress": progress,
            "message": f"Processing... {t.n}/{t.total} pages"
        }
        save_task_status(task_id, status_data)
    return progress_callback

def calculate_md5(file_path: str) -> str:
    """计算文件的MD5值作为任务ID"""
    md5_hash = hashlib.md5()
    with open(file_path, "rb") as f:
        # 每次读取4KB数据
        for byte_block in iter(lambda: f.read(4096), b""):
            md5_hash.update(byte_block)
    return md5_hash.hexdigest()

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
    
    # 创建临时文件来计算MD5
    temp_file = Path("temp_upload.pdf")
    try:
        with temp_file.open("wb") as f:
            content = await file.read()
            f.write(content)
        
        # 使用MD5值作为任务ID
        task_id = calculate_md5(str(temp_file))
        print(f"File MD5/Task ID: {task_id}")
        
        # 检查是否存在相同文件的任务
        status = get_task_status(task_id)
        if status:
            print(f"Found existing task: {task_id}")
            if status["status"] == TaskStatus.COMPLETED:
                # 如果之前的任务已完成，直接返回结果
                return {
                    "task_id": task_id,
                    "status": "exists",
                    "message": "File was previously translated",
                    "result": status
                }
        
        # 创建任务目录
        task_dir = Path("pdf2zh_files") / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        
        # 移动文件到任务目录
        target_file = task_dir / file.filename
        shutil.move(str(temp_file), str(target_file))
        
        # 初始化任务状态
        initial_status = {
            "task_id": task_id,
            "status": TaskStatus.PENDING,
            "progress": 0,
            "message": "Translation task initialized",
            "error": None,
            "output_file": None,
            "output_file_dual": None
        }
        save_task_status(task_id, initial_status)
        
        return {
            "task_id": task_id,
            "status": "pending",
            "message": "File uploaded successfully"
        }
    except Exception as e:
        # 清理临时文件
        if temp_file.exists():
            temp_file.unlink()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # 确保临时文件被删除
        if temp_file.exists():
            temp_file.unlink()

@app.post("/translate/{task_id}")
async def translate_pdf(
    task_id: str,
    request: TranslationRequest,
    background_tasks: BackgroundTasks
):
    """开始PDF翻译任务"""
    # 检查任务是否已存在且正在进行中
    # current_status = get_task_status(task_id)
    # if current_status:
    #     if current_status["status"] == TaskStatus.PROCESSING:
    #         return {
    #             "task_id": task_id,
    #             "status": TaskStatus.PROCESSING,
    #             "message": "Translation task is already running"
    #         }
    #     elif current_status["status"] == TaskStatus.COMPLETED:
    #         return {
    #             "task_id": task_id,
    #             "status": TaskStatus.COMPLETED,
    #             "message": "Translation task is already completed",
    #             "output_file": current_status.get("output_file"),
    #             "output_file_dual": current_status.get("output_file_dual")
    #         }
    
    output_dir = Path("pdf2zh_files") / task_id
    if not output_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Task directory not found: {output_dir}"
        )
    
    # 获取PDF文件
    pdf_files = list(output_dir.glob("*.pdf"))
    if not pdf_files:
        raise HTTPException(
            status_code=404,
            detail=f"No PDF files found in directory: {output_dir}"
        )
    
    input_file = pdf_files[0]
    print(f"Found input file: {input_file}")
    
    # 初始化任务状态
    initial_status = {
        "task_id": task_id,
        "status": TaskStatus.PENDING,
        "progress": 0,
        "message": "Translation task initialized",
        "error": None,
        "output_file": None,
        "output_file_dual": None
    }
    save_task_status(task_id, initial_status)
    
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
    
    print(f"Translation config: service={selected_service}, from={lang_from}, to={lang_to}")
    
    # 准备翻译参数
    param = {
        "files": [input_file],
        "pages": [p-1 for p in request.pages] if request.pages else None,  # 转换页码从1开始到从0开始
        "lang_in": lang_from,
        "lang_out": lang_to,
        "service": f"{selected_service}:{request.model_id}" if request.model_id else selected_service,
        "output": output_dir,
        "thread": 4,
        "callback": update_task_progress(task_id, tqdm.tqdm(total=100)),  # 使用回调函数更新进度
    }
    
    # 启动异步任务
    background_tasks.add_task(process_translation, task_id, input_file, param)
    
    # 立即返回当前状态
    return {
        "task_id": task_id,
        "status": TaskStatus.PENDING,
        "message": "Translation task started"
    }

async def process_translation(task_id: str, input_file: Path, param: dict):
    """处理翻译任务"""
    try:
        print(f"Starting translation with parameters: {param}")
        status_data = get_task_status(task_id)
        status_data["status"] = TaskStatus.PROCESSING
        save_task_status(task_id, status_data)
        
        # 确保使用原始文件
        original_filename = input_file.name
        if original_filename.endswith('-zh.pdf') or original_filename.endswith('-en.pdf'):
            # 在同一目录下查找原始文件
            base_filename = original_filename[:-7]  # 移除 '-zh.pdf' 或 '-en.pdf'
            original_file = input_file.parent / f"{base_filename}.pdf"
            if original_file.exists():
                input_file = original_file
                print(f"Using original file: {input_file}")
        
        # 确保文件路径是字符串类型
        param["files"] = [str(input_file)]  # 转换为字符串
        
        # 设置输出目录为任务目录
        task_dir = Path("pdf2zh_files") / task_id
        param["output"] = str(task_dir)  # 确保输出路径也是字符串
        
        print(f"Processing translation with files: {param['files']}")
        print(f"Output directory: {param['output']}")
        
        # 执行翻译
        extract_text(**param)
        
        # 更新输出文件路径
        filename = input_file.stem
        # 移除可能存在的 -zh 或 -en 后缀
        if filename.endswith('-zh') or filename.endswith('-en'):
            filename = filename[:-3]
        output_file = task_dir / f"{filename}-zh.pdf"
        output_file_dual = task_dir / f"{filename}-dual.pdf"
        
        print(f"Checking output files: {output_file}, {output_file_dual}")
        
        if output_file.exists() and output_file_dual.exists():
            status_data = get_task_status(task_id)
            status_data.update({
                "status": TaskStatus.COMPLETED,
                "progress": 1.0,
                "message": "Translation completed successfully",
                "output_file": get_download_url(task_id, False),
                "output_file_dual": get_download_url(task_id, True)
            })
            save_task_status(task_id, status_data)
        else:
            raise Exception(f"Translation completed but output files not found. Expected: {output_file}, {output_file_dual}")
            
    except Exception as e:
        import traceback
        error_msg = f"Translation error: {str(e)}\n{traceback.format_exc()}"
        print(error_msg)
        status_data = get_task_status(task_id)
        status_data.update({
            "status": TaskStatus.FAILED,
            "error": error_msg,
            "progress": 0,
            "message": "Translation failed"
        })
        save_task_status(task_id, status_data)

def get_download_url(task_id: str, dual: bool = False) -> str:
    """生成下载URL"""
    base_url = f"{BASE_URL}/download/{task_id}"
    if dual:
        return f"{base_url}?dual=true"
    return base_url

@app.get("/status/{task_id}", response_model=TranslationStatus)
async def get_translation_status(task_id: str):
    """获取翻译任务的状态，立即返回当前状态"""
    try:
        status_data = get_task_status(task_id)
        if not status_data:
            raise HTTPException(
                status_code=404,
                detail=f"Task not found: {task_id}"
            )
        
        # 确保所有必需的字段都存在
        status_data.setdefault("status", TaskStatus.PENDING)
        status_data.setdefault("progress", 0.0)
        status_data.setdefault("error", None)
        status_data.setdefault("output_file", None)
        status_data.setdefault("output_file_dual", None)
        status_data.setdefault("last_updated", datetime.now().isoformat())
        
        return TranslationStatus(**status_data)
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
        task_dir = Path("pdf2zh_files") / task_id
        print(f"Looking in task directory: {task_dir}")
        print(f"Task directory exists: {task_dir.exists()}")
        
        if not task_dir.exists():
            raise HTTPException(status_code=404, detail="Task directory not found")
        
        # 获取原始PDF文件名（不带-zh或-dual后缀的文件）
        original_files = [f for f in task_dir.glob("*.pdf") 
                        if not (f.stem.endswith('-zh') or f.stem.endswith('-dual'))]
        print(f"Found original PDF files: {original_files}")
        
        if not original_files:
            raise HTTPException(status_code=404, detail="Original PDF not found")
        
        # 获取不带后缀的第一个PDF文件名
        original_name = original_files[0].stem
        print(f"Original filename stem: {original_name}")
        
        # 直接查找目标文件
        if dual:
            target_file = f"{original_name}-dual.pdf"
        else:
            target_file = f"{original_name}-zh.pdf"
        
        file_path = task_dir / target_file
        print(f"Attempting to access file: {file_path}")
        print(f"File exists: {file_path.exists()}")
        
        if not file_path.exists():
            # 列出目录中的所有文件
            all_files = list(task_dir.glob("*"))
            print(f"All files in directory: {all_files}")
            raise HTTPException(status_code=404, detail=f"Translated file not found: {file_path}")
        
        print(f"Returning file: {file_path}")
        response = FileResponse(
            path=str(file_path),
            filename=file_path.name,
            media_type="application/pdf"
        )
        # 添加禁止缓存的响应头
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
        
    except Exception as e:
        print(f"Error in download_file: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
