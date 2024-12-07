"""Functions that can be used for the most common use-cases for pdf2zh.six"""

from typing import BinaryIO, List, Tuple
import numpy as np
import tqdm
from pymupdf import Document
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfinterp import PDFResourceManager
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfparser import PDFParser
from pdf2zh.converter import TranslateConverter
from pdf2zh.pdfinterp import PDFPageInterpreterEx
from pymupdf import Font


def _process_layout_box(d, h: int, w: int) -> Tuple[int, int, int, int]:
    """处理布局框的坐标"""
    x0, y0, x1, y1 = d.xyxy.squeeze()
    return (
        np.clip(int(x0 - 1), 0, w - 1),
        np.clip(int(h - y1 - 1), 0, h - 1),
        np.clip(int(x1 + 1), 0, w - 1),
        np.clip(int(h - y0 + 1), 0, h - 1),
    )


def _process_page_layout(page_layout, pix_height: int, pix_width: int) -> np.ndarray:
    """处理页面布局，返回布局矩阵"""
    box = np.ones((pix_height, pix_width))
    h, w = box.shape
    vcls = ["abandon", "figure", "table", "isolate_formula", "formula_caption"]
    
    # 处理非特殊区域
    for i, d in enumerate(page_layout.boxes):
        if not page_layout.names[int(d.cls)] in vcls:
            x0, y0, x1, y1 = _process_layout_box(d, h, w)
            box[y0:y1, x0:x1] = i + 2
    
    # 处理特殊区域
    for d in page_layout.boxes:
        if page_layout.names[int(d.cls)] in vcls:
            x0, y0, x1, y1 = _process_layout_box(d, h, w)
            box[y0:y1, x0:x1] = 0
            
    return box


def extract_text_to_fp(
    inf: BinaryIO,
    pages=None,
    password: str = "",
    debug: bool = False,
    page_count: int = 0,
    vfont: str = "",
    vchar: str = "",
    thread: int = 0,
    doc_en: Document = None,
    model=None,
    lang_in: str = "",
    lang_out: str = "",
    service: str = "",
    resfont: str = "",
    noto: Font = None,
    callback: object = None,
    **kwarg,
) -> dict:
    """Extract and process text from PDF file"""
    layout = {}  
    obj_patch = {}
    rsrcmgr = PDFResourceManager()
    device = TranslateConverter(
        rsrcmgr, vfont, vchar, thread, layout, lang_in, lang_out, service, resfont, noto
    )
    assert device is not None
    
    interpreter = PDFPageInterpreterEx(rsrcmgr, device, obj_patch)
    total_pages = len(pages) if pages else page_count
    
    parser = PDFParser(inf)
    doc = PDFDocument(parser, password=password)
    pages_iterator = enumerate(PDFPage.create_pages(doc))
    
    if not callback:
        pages_iterator = tqdm.tqdm(pages_iterator, total=total_pages)

    for pageno, page in pages_iterator:
        if pages and pageno not in pages:
            continue
            
        if callback:
            callback({"total": total_pages, "current": pageno + 1})
            
        # 处理页面
        page.pageno = pageno
        pix = doc_en[pageno].get_pixmap()
        image = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3)[:, :, ::-1]
        page_layout = model.predict(image, imgsz=int(pix.height / 32) * 32)[0]
        
        # 处理布局
        layout[pageno] = _process_page_layout(page_layout, pix.height, pix.width)
        
        # 更新页面内容
        page.page_xref = doc_en.get_new_xref()
        doc_en.update_object(page.page_xref, "<<>>")
        doc_en.update_stream(page.page_xref, b"")
        doc_en[pageno].set_contents(page.page_xref)
        interpreter.process_page(page)

    device.close()
    return obj_patch
