import threading
from docx import Document
from docx.shared import Pt
from docx.shared import Inches
from docx.oxml.ns import qn
import os
import sys
import time
import datetime
import zipfile
import string
from .word_style_utils import WordStyleCopier
from pdf2zh.translator import (
    OpenAITranslator,
    DeepLTranslator,
    GoogleTranslator,
    TencentTranslator,
    AzureTranslator,
    ZhipuTranslator,
    SiliconTranslator
)
import concurrent.futures

# 服务映射
SERVICE_MAP = {
    "OpenAI": (OpenAITranslator, None),
    "DeepL": (DeepLTranslator, None),
    "Google": (GoogleTranslator, None),
    "Tencent": (TencentTranslator, None),
    "Azure": (AzureTranslator, None),
    "Zhipu": (ZhipuTranslator, None),
    "Silicon": (SiliconTranslator, None)
}

# 语言映射
lang_map = {
    "Chinese": "zh",
    "English": "en",
    "Japanese": "ja",
    "Korean": "ko",
    "French": "fr",
    "German": "de",
    "Russian": "ru",
    "Spanish": "es",
    "Portuguese": "pt",
    "Italian": "it",
    "Dutch": "nl",
    "Polish": "pl",
    "Turkish": "tr",
    "Arabic": "ar",
    "Thai": "th",
    "Vietnamese": "vi",
    "Indonesian": "id",
    "Hindi": "hi",
}

def start(trans):
    """开始Word文档翻译"""
    # 允许的最大线程
    threads = trans.get('threads', 10)
    if threads is None or threads == "" or int(threads) < 0:
        max_threads = 10
    else:
        max_threads = int(threads)

    # 创建Document对象，加载Word文件
    try:
        document = Document(trans['file_path'])
    except Exception as e:
        print(f"[错误] 无法访问文档: {str(e)}")
        return False

    texts = []
    trans_type = trans.get('type', 'trans_text_both_inherit')

    # 根据翻译类型读取文本
    if trans_type in ["trans_text_only_inherit", "trans_all_only_inherit", "trans_all_both_inherit"]:
        read_rune_text(document, texts)
    else:
        read_paragraph_text(document, texts)

    print(f"[处理] 提取文本完成，共 {len(texts)} 个文本片段")

    # 初始化翻译器
    service = trans.get('service', 'OpenAI')
    apikey = trans.get('apikey')
    model_id = trans.get('model_id', 'gpt-4o-mini')
    lang_from = trans.get('lang_from', 'English')
    lang_to = trans.get('lang_to', 'Chinese')

    # 选择翻译服务
    translator_map = {
        'OpenAI': OpenAITranslator,
        'DeepL': DeepLTranslator,
        'Google': GoogleTranslator,
        'Tencent': TencentTranslator,
        'Azure': AzureTranslator,
        'Zhipu': ZhipuTranslator,
        'Silicon': SiliconTranslator
    }
    
    translator_class = translator_map.get(service, OpenAITranslator)
    translator = translator_class(
        service=service,
        lang_out=lang_to, 
        lang_in=lang_from, 
        model=model_id
    )

    # 并行翻译文本，同时保持原始顺序
    def translate_text(index, text_item):
        try:
            translated_text = translator.translate(text_item['text'])
            return index, {
                'text': translated_text, 
                'complete': True,
                'original': text_item
            }
        except Exception as e:
            print(f"[错误] 翻译失败: {str(e)}")
            return index, {
                'text': text_item['text'], 
                'complete': False,
                'original': text_item
            }

    # 使用线程池进行并行翻译，并保持原始顺序
    translated_texts = [None] * len(texts)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
        # 提交所有文本片段到线程池，同时传递原始索引
        futures = [
            executor.submit(translate_text, i, text_item) 
            for i, text_item in enumerate(texts)
        ]
        
        # 按原始顺序收集结果
        for future in concurrent.futures.as_completed(futures):
            try:
                index, result = future.result()
                translated_texts[index] = result
            except Exception as exc:
                print(f'[错误] 翻译任务生成异常: {exc}')

    # 替换原始文本列表为翻译后的文本
    texts = [item for item in translated_texts if item is not None]

    # 根据翻译类型写入文档
    text_count = 0
    write_type_map = {
        "trans_text_only_inherit": write_only_new,
        "trans_text_only_new": write_paragraph_text,
        "trans_text_both_new": write_both_new,
        "trans_text_both_inherit": write_rune_both,
        "trans_all_only_new": lambda doc, txts, cnt, only: write_paragraph_text(doc, txts, cnt, False),
        "trans_all_only_inherit": lambda doc, txts, cnt, only: write_only_new(doc, txts, cnt, False),
        "trans_all_both_new": lambda doc, txts, cnt, only: write_both_new(doc, txts, cnt, False),
        "trans_all_both_inherit": lambda doc, txts, cnt, only: write_rune_both(doc, txts, cnt, False)
    }

    write_func = write_type_map.get(trans_type)
    if write_func:
        write_func(document, texts, text_count, True)

    # 保存文档
    output_path = trans['file_path'].replace('.docx', '_translated.docx')
    document.save(output_path)
    print(f"[完成] 文档翻译完成，保存至 {output_path}")
    return True

def read_paragraph_text(document, texts):
    """按段落读取文本"""
    for paragraph in document.paragraphs:
        append_text(paragraph.text, texts)

    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                read_cell_text(cell, texts)

def read_rune_text(document, texts):
    """按run读取文本"""
    for paragraph in document.paragraphs:
        read_run(paragraph.runs, texts)
        
        # 处理超链接
        if paragraph.hyperlinks:
            for hyperlink in paragraph.hyperlinks:
                read_run(hyperlink.runs, texts)

    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                read_cell_text(cell, texts)

def read_cell_text(cell, texts):
    """读取单元格文本"""
    for paragraph in cell.paragraphs:
        append_text(paragraph.text, texts)

def read_run(runs, texts):
    """读取run文本"""
    for run in runs:
        append_text(run.text, texts)

def append_text(text, texts):
    """追加文本"""
    if check_text(text):
        texts.append({"text": text, "complete": False})

def check_text(text):
    """检查文本是否有效"""
    return text is not None and len(text) > 0 and not all(char in string.punctuation for char in text.strip())

def write_paragraph_text(document, texts, text_count, onlyText):
    """按段落写入文本"""
    for paragraph in document.paragraphs:
        replace_paragraph_text(paragraph, texts, text_count, onlyText, False)

    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                write_paragraph_text(cell, texts, text_count, onlyText)

def write_both_new(document, texts, text_count, onlyText):
    """保留原文并重新排版"""
    for paragraph in document.paragraphs:
        replace_paragraph_text(paragraph, texts, text_count, onlyText, True)

    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                write_both_new(cell, texts, text_count, onlyText)

def write_only_new(document, texts, text_count, onlyText):
    """仅写入新文本"""
    for paragraph in document.paragraphs:
        text_count += write_run(paragraph.runs, texts)

        if paragraph.hyperlinks:
            for hyperlink in paragraph.hyperlinks:
                text_count += write_run(hyperlink.runs, texts)

        if onlyText:
            clear_image(paragraph)

    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                write_cell_text(cell, texts)

def write_rune_both(document, texts, text_count, onlyText):
    """保留原文并继承版面"""
    for paragraph in document.paragraphs:
        if paragraph.runs:
            paragraph.runs[-1].add_break()
            add_paragraph_run(paragraph, paragraph.runs, texts, text_count)

        if paragraph.hyperlinks:
            for hyperlink in paragraph.hyperlinks:
                hyperlink.runs[-1].add_break()
                add_paragraph_run(paragraph, hyperlink.runs, texts, text_count)

        if onlyText:
            clear_image(paragraph)

    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    replace_paragraph_text(paragraph, texts, text_count, onlyText, True)

                    if paragraph.hyperlinks:
                        for hyperlink in paragraph.hyperlinks:
                            replace_paragraph_text(hyperlink, texts, text_count, onlyText, True)

def write_cell_text(cell, texts):
    """写入单元格文本"""
    for paragraph in cell.paragraphs:
        if check_text(paragraph.text) and texts:
            item = texts.pop(0)
            for index, run in enumerate(paragraph.runs):
                if index == 0:
                    run.text = item.get('text', "")
                else:
                    run.clear()

def write_run(runs, texts):
    """写入run文本"""
    text_count = 0
    if not runs:
        return text_count

    for run in runs:
        text = run.text
        if check_text(text) and texts:
            item = texts.pop(0)
            text_count += item.get('count', 0)
            run.text = item.get('text', "")

    return text_count

def add_paragraph_run(paragraph, runs, texts, text_count):
    """添加段落run"""
    for run in runs:
        if check_text(run.text) and texts:
            item = texts.pop(0)
            text_count += item.get('count', 0)
            new_run = paragraph.add_run(item.get('text', ""), run.style)
            set_run_style(new_run, run)
    
    set_paragraph_linespace(paragraph)

def set_run_style(new_run, copy_run):
    """设置run样式"""
    new_run.font.italic = copy_run.font.italic
    new_run.font.strike = copy_run.font.strike
    new_run.font.bold = copy_run.font.bold
    new_run.font.size = copy_run.font.size
    new_run.font.color.rgb = copy_run.font.color.rgb
    new_run.underline = copy_run.underline
    new_run.style = copy_run.style

    # 字体名称设置
    new_run.font.name = '微软雅黑'
    r = new_run._element.rPr.rFonts
    r.set(qn('w:eastAsia'), '微软雅黑')

def set_paragraph_linespace(paragraph):
    """设置段落行间距"""
    if hasattr(paragraph, "paragraph_format"):
        space_before = paragraph.paragraph_format.space_before
        space_after = paragraph.paragraph_format.space_after
        line_spacing = paragraph.paragraph_format.line_spacing
        line_spacing_rule = paragraph.paragraph_format.line_spacing_rule

        if space_before is not None:
            paragraph.paragraph_format.space_before = space_before
        if space_after is not None:
            paragraph.paragraph_format.space_after = space_after
        if line_spacing is not None:
            paragraph.paragraph_format.line_spacing = line_spacing
        if line_spacing_rule is not None:
            paragraph.paragraph_format.line_spacing_rule = line_spacing_rule

def check_image(run):
    """检查是否为图片"""
    return run.element.find('.//w:drawing', namespaces=run.element.nsmap) is not None

def clear_image(paragraph):
    """清除图片"""
    for run in paragraph.runs:
        if check_image(run):
            run.clear()

def replace_paragraph_text(paragraph, texts, text_count, onlyText, appendTo):
    """替换段落文本"""
    text = paragraph.text
    if check_text(text) and texts:
        item = texts.pop(0)
        trans_text = item.get('text', "")

        if appendTo:
            if paragraph.runs:
                paragraph.runs[-1].add_break()
                paragraph.runs[-1].add_text(trans_text)
            elif paragraph.hyperlinks:
                paragraph.hyperlinks[-1].runs[-1].add_break()
                paragraph.hyperlinks[-1].runs[-1].add_text(trans_text)
        else:
            replaced = False
            if paragraph.runs:
                for run in paragraph.runs:
                    if not check_image(run):
                        if not replaced:
                            run.text = trans_text
                            replaced = True
                        else:
                            run.clear()
            elif paragraph.hyperlinks:
                for hyperlink in paragraph.hyperlinks:
                    for run in hyperlink.runs:
                        if not check_image(run):
                            if not replaced:
                                run.text = trans_text
                                replaced = True
                            else:
                                run.clear()

        text_count += item.get('count', 0)
        set_paragraph_linespace(paragraph)

    if onlyText:
        clear_image(paragraph)

    return text_count
