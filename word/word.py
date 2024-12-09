import os
import json
import time
import hashlib
import threading
from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.table import _Cell, Table
from docx.text.paragraph import Paragraph
from docx.shared import Pt
from docx.shared import Inches
from docx.oxml.ns import qn
import concurrent.futures
import sys
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
from pdf2zh.cache import load_paragraph, write_paragraph, create_cache, deterministic_hash
from copy import deepcopy
from lxml import etree

# 并行翻译文本，同时保持原始顺序
def translate_text(index, text_item, translator, lang_from, lang_to, service):
    try:


        # 如果文本无效，直接返回原文
        if not check_text(text_item['text']):
            print(f"[翻译跳过] 无效文本: '{text_item['text']}'")
            return {
                'index': index, 
                'text': text_item['text']
            }
        
        # 生成文本的哈希值
        text_hash = deterministic_hash(text_item['text'])
        
        # 尝试从缓存加载翻译
        cached_translation = load_paragraph(text_hash, f"{lang_from}_{lang_to}_{service}")

        if cached_translation:
            translated_text = cached_translation
        else:
            # 如果缓存未命中，进行翻译
            translated_text = translator.translate(text_item['text'])
            
            # 创建缓存目录
            create_cache(text_hash)
            
            # 保存翻译到缓存
            write_paragraph(text_hash, f"{lang_from}_{lang_to}_{service}", translated_text)
        
        return {
            'index': index, 
            'text': translated_text
        }
    except Exception as e:
        print(f"[错误] 翻译文本时出错: {e}")
        return {
            'index': index, 
            'text': text_item['text']  # 返回原文本
        }

def start(trans):
    """开始Word文档翻译"""
    print("[DEBUG] 开始文档翻译流程")
    
    # 允许的最大线程
    threads = trans.get('threads', 10)
    if threads is None or threads == "" or int(threads) < 0:
        max_threads = 10
    else:
        max_threads = int(threads)

    # 创建Document对象，加载Word文件
    try:
        file_path = trans.get('file_path', '')
        print(f"[DEBUG] 源文件路径: {file_path}")
        document = Document(file_path)
    except Exception as e:
        print(f"[错误] 无法访问文档: {str(e)}")
        return False

    # 创建新文档并复制原始文档样式
    translated_document = Document()
    
    # 复制文档样式
    def deep_copy_document_styles(source_doc, target_doc):
        """深度复制文档样式，确保格式完全一致"""
        print("[DEBUG] 开始复制文档样式")
        for style in source_doc.styles:
            try:
                if style.name not in target_doc.styles:
                    target_doc.styles.add_style(style.name, style.type)
            except Exception as e:
                print(f"[警告] 复制样式 {style.name} 时出错: {e}")

    deep_copy_document_styles(document, translated_document)

    texts = []
    trans_type = trans.get('type', 'trans_text_only_inherit')
    print(f"[DEBUG] 翻译类型: {trans_type}")

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
    lang_from = trans.get('lang_from', 'Chinese')
    lang_to = trans.get('lang_to', 'English')

    print(f"[DEBUG] 翻译服务: {service}, 模型: {model_id}")
    print(f"[DEBUG] 源语言: {lang_from}, 目标语言: {lang_to}")

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

    # 使用线程池进行并行翻译，并保持原始顺序
    translated_texts = [None] * len(texts)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
        # 提交所有文本片段到线程池，同时传递原始索引
        futures = [
            executor.submit(
                translate_text, 
                i, 
                text_item, 
                translator, 
                lang_from, 
                lang_to, 
                service
            ) 
            for i, text_item in enumerate(texts)
        ]
        
        # 按原始顺序收集结果
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
                translated_texts[result['index']] = result
            except Exception as exc:
                print(f'[错误] 翻译任务生成异常: {exc}')

    # 替换原始文本列表为翻译后的文本
    texts = [item for item in translated_texts if item is not None]
    print(f"[DEBUG] 翻译完成，共 {len(texts)} 个文本片段")

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
        # 修改传入的文本格式
        translated_texts_for_write = [{'text': t['text']} for t in texts]
        print(f"[调试] 准备写入的文本: {translated_texts_for_write}")
        
        # 初始化文本计数器
        text_count = 0
        
        # 调用写入函数，并传递文本计数器
        print("[DEBUG] 开始写入文档")
        text_count = write_func(translated_document, translated_texts_for_write, text_count, True)
        
        print(f"[调试] 最终处理的文本数量: {text_count}")
        
        # 如果没有文本被写入，尝试强制写入
        if text_count == 0 and len(translated_texts_for_write) > 0:
            print("[警告] 未写入任何文本，尝试强制写入")
            for paragraph in translated_document.paragraphs:
                paragraph.clear()
            
            for text in translated_texts_for_write:
                translated_document.add_paragraph(text['text'])

    # 复制媒体元素
    def copy_media_elements(source_doc, translated_document, trans):
        """
        复制媒体元素，保留翻译后的内容并添加图片和表格
        """
        print("[DEBUG] 开始复制媒体元素")
        
        # 保留已翻译的段落数量
        translated_paragraph_count = len(translated_document.paragraphs)
        
        # 复制图片
        for paragraph in source_doc.paragraphs:
            # 检查段落是否有图片
            has_image = any(
                run.element.find('.//pic:pic', namespaces={'pic': 'http://schemas.openxmlformats.org/drawingml/2006/picture'}) is not None 
                for run in paragraph.runs
            )
            
            if has_image:
                # 找到对应的翻译段落（如果存在）
                matching_translated_paragraph = None
                paragraph_text = paragraph.text.strip()
                
                for trans_para in translated_document.paragraphs:
                    trans_para_text = trans_para.text.strip()
                    if trans_para_text and (trans_para_text in paragraph_text or paragraph_text in trans_para_text):
                        matching_translated_paragraph = trans_para
                        break
                
                # 如果找到匹配的段落，复制图片到该段落
                target_paragraph = matching_translated_paragraph or translated_document.paragraphs[-1]
                
                # 复制图片
                for run in paragraph.runs:
                    pic_element = run.element.find('.//pic:pic', namespaces={'pic': 'http://schemas.openxmlformats.org/drawingml/2006/picture'})
                    if pic_element is not None:
                        WordStyleCopier.copy_image(target_paragraph, run)
        
        # 复制表格
        for source_table in source_doc.tables:
            # 使用精确复制方法，但不覆盖已翻译的内容
            copy_table_with_position(source_table, translated_document, trans)
        
        print(f"[DEBUG] 媒体元素复制完成。原始段落数: {len(source_doc.paragraphs)}, 翻译后段落数: {len(translated_document.paragraphs)}")
        
        return translated_document

    def copy_table_with_position(source_table, translated_document, trans):
        """
        精确复制表格，包括其在文档中的位置和格式，并插入翻译后的文本
        """
        print("[DEBUG] 开始复制表格")
        # 创建新表格
        new_table = translated_document.add_table(rows=len(source_table.rows), 
                                                  cols=len(source_table.rows[0].cells) if source_table.rows else 1)
        
        # 复制表格样式
        WordStyleCopier.copy_table_style(new_table, source_table)
        
        # 创建一个更高效的翻译映射
        translation_map = {}
        for text_item in trans:
            original = text_item.get('original', '').strip()
            translated = text_item.get('text', '').strip()
            if original:
                translation_map[original] = translated
        
        # 复制单元格内容和样式
        for i, source_row in enumerate(source_table.rows):
            for j, source_cell in enumerate(source_row.cells):
                if i < len(new_table.rows) and j < len(new_table.rows[i].cells):
                    new_cell = new_table.cell(i, j)
                    
                    # 清除新单元格的默认内容
                    for para in new_cell.paragraphs:
                        para._element.clear()
                    
                    # 处理源单元格的每个段落
                    for source_para in source_cell.paragraphs:
                        # 创建新段落
                        new_para = new_cell.add_paragraph()
                        
                        # 复制段落样式
                        WordStyleCopier.copy_paragraph_style(new_para, source_para)
                        
                        # 处理每个run
                        for source_run in source_para.runs:
                            # 创建新run
                            new_run = new_para.add_run()
                            
                            # 复制run样式
                            WordStyleCopier.copy_run_style(new_run, source_run)
                            
                            # 获取原始文本
                            original_text = source_run.text.strip()
                            
                            # 查找翻译
                            translated_text = translation_map.get(original_text, original_text)
                            
                            # 设置文本
                            new_run.text = translated_text
    
        return new_table

    # 复制媒体元素
    copy_media_elements(document, translated_document, texts)

    # 保存文档
    output_path = trans['file_path'].replace('.docx', '_translated.docx')
    translated_document.save(output_path)
    print(f"[调试] 文档已保存至: {output_path}")
    
    # 验证文档内容
    def verify_document_content(document_path, translated_texts):
        """验证生成文档的内容是否正确"""
        from docx import Document
        
        try:
            doc = Document(document_path)
            
            # 收集所有段落文本
            paragraph_texts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            
            print("[调试] 文档段落内容验证:")
            print("预期翻译文本:")
            for text in translated_texts:
                print(f"- {text['text']}")
            
            print("\n实际文档段落:")
            for text in paragraph_texts:
                print(f"- {text}")
            
            # 检查是否所有翻译文本都在文档中
            missing_texts = [
                text['text'] for text in translated_texts 
                if not any(text['text'] in doc_text for doc_text in paragraph_texts)
            ]
            
            if missing_texts:
                print("[警告] 以下翻译文本未在文档中找到:")
                for missing in missing_texts:
                    print(f"- {missing}")
                return False
            
            print("[成功] 文档内容验证通过")
            return True
        
        except Exception as e:
            print(f"[错误] 文档内容验证失败: {e}")
            return False
    
    # 执行文档内容验证
    verify_result = verify_document_content(output_path, texts)
    if not verify_result:
        print("[警告] 文档内容可能存在问题，请检查翻译过程")
    
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
    """检查文本是否有效，包括处理空白和特殊字符"""
    if not text:
        return False
    
    # 去除所有空白字符
    stripped_text = text.strip()
    
    # 定义需要排除的特殊字符和文本
    special_chars = set('　_：:')
    exclude_texts = set()
    
    # 检查是否为空、仅包含特殊字符，或在排除列表中
    return (
        len(stripped_text) > 0 and 
        not all(char in special_chars for char in stripped_text) and
        stripped_text not in exclude_texts
    )

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

def write_only_new(document, texts, text_count, onlyText=True):
    """仅写入新文本，更加健壮的实现"""
    print(f"[调试] 进入 write_only_new 函数，文本数量: {len(texts)}, 当前文本计数: {text_count}")
    
    # 处理文档对象
    if isinstance(document, (DocxDocument, Document)):
        # 遍历文档段落
        for paragraph in document.paragraphs:
            # 清空段落
            paragraph.clear()
        
        # 重新填充段落
        for text_item in texts:
            current_text = text_item['text']
            print(f"[调试] 写入文本: {current_text}")
            document.add_paragraph(current_text)
        
        print(f"[调试] write_only_new 完成，写入 {len(texts)} 个文本")
        return len(texts)
    
    # 处理表格中的文本
    elif isinstance(document, (_Cell, Table)):
        for paragraph in document.paragraphs:
            paragraph.clear()
        
        for text_item in texts:
            current_text = text_item['text']
            print(f"[调试] 写入单元格文本: {current_text}")
            document.add_paragraph(current_text)
        
        return len(texts)
    
    print("[调试] write_only_new 未处理任何文本")
    return text_count

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

        # 复制段落样式
        WordStyleCopier.copy_paragraph_style(paragraph, paragraph)

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
    # 使用WordStyleCopier完整复制run样式
    WordStyleCopier.copy_run_style(new_run, copy_run)
    
    # 确保使用中文字体
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
