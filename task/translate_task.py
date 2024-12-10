import os
import time
from .db import get_db_conn, close_db_conn
from pdf2zh.pdf2zh import extract_text

def get_pending_tasks(limit=10):
    conn = get_db_conn()
    cur = conn.cursor()
    sql = """
        SELECT 
            id, 
            origin_filepath, 
            target_filepath, 
            origin_lang, 
            target_lang, 
            model, 
            status
        FROM translate 
        WHERE status='start' 
        LIMIT %s
    """
    cur.execute(sql, (limit,))
    tasks = [
        {
            'id': task[0],
            'origin_filepath': task[1],
            'target_filepath': task[2], 
            'origin_lang': task[3],
            'target_lang': task[4],
            'model': task[5],
            'status': task[6]
        }
        for task in cur.fetchall()
    ]
    close_db_conn(conn)
    return tasks 

def update_task_status(task_id, status):
    conn = get_db_conn()
    cur = conn.cursor()
    sql = "UPDATE translate SET status=%s WHERE id=%s"
    cur.execute(sql, (status, task_id))
    conn.commit()
    close_db_conn(conn) 

def update_task_progress(task_id, progress):
    conn = get_db_conn()
    cur = conn.cursor()
    sql = "UPDATE translate SET process=%s WHERE id=%s"
    cur.execute(sql, (progress, task_id))
    conn.commit()
    close_db_conn(conn)

def update_task_callback(task_id: str):
    """更新任务进度的回调函数"""
    def callback(progress_data: dict):
        try:
            total_pages = progress_data.get("total", 0)
            current_page = progress_data.get("current", 0)
            
            if total_pages > 0:
                progress = round(current_page / total_pages, 2)
            else:
                progress = 0
                
            update_task_progress(task_id, progress * 100)
            
            if progress == 1:
                update_task_status(task_id, 'done')
            print(f"Task {task_id} processed successfully")
                
        except Exception as e:
            print(f"Error updating progress: {str(e)}")
    
    return callback

def process_tasks(keep_running=False):
    """
    处理翻译任务
    
    Args:
        keep_running (bool): 是否持续运行任务处理。默认为True,表示持续运行;False表示只处理一次。
    """
    while True:
        print("Checking for pending tasks...")
        tasks = get_pending_tasks()
        if not tasks:
            print("No pending tasks, wait for 60 seconds...")
            if keep_running:
                time.sleep(60)
            else:
                break
            continue
            
        for task in tasks:
            if task['status'] == 'done' or task['status'] == 'process':
                continue
            
            task_id = task['id']
            print(f"Start processing task: {task_id}")
            update_task_status(task_id, 'process')
            
            # 确保输出目录存在
            output_dir = "./pdf2zh_files"
            os.makedirs(output_dir, exist_ok=True)
            
            # 准备翻译参数
            param = {
                "files": [task['origin_filepath']],
                "pages": None,
                "lang_in": task['origin_lang'],
                "lang_out": task['target_lang'],
                "service": task['model'] or "google",  # 如果model为None,使用google作为默认值
                "output": output_dir,
                "thread": 10,
                "callback": update_task_callback(task_id),  # 移除tqdm，使用自定义回调
            }
    
            extract_text(**param)
        
        if not keep_running:
            break

def stop_tasks():
    global keep_running
    keep_running = False
    
if __name__ == '__main__':
    try:
        process_tasks()
    except KeyboardInterrupt:
        stop_tasks() 