from docx.shared import Pt, RGBColor, Inches, Cm, Twips
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

class WordStyleCopier:
    @staticmethod
    def copy_run_style(new_run, source_run):
        """完整复制run级别的样式"""
        if source_run.font is not None:
            if new_run.font is None:
                return
            
            # 基础字体属性
            new_run.font.name = source_run.font.name
            new_run.font.size = source_run.font.size
            new_run.font.bold = source_run.font.bold
            new_run.font.italic = source_run.font.italic
            new_run.font.underline = source_run.font.underline
            new_run.font.strike = source_run.font.strike
            new_run.font.subscript = source_run.font.subscript
            new_run.font.superscript = source_run.font.superscript
            new_run.font.shadow = source_run.font.shadow
            new_run.font.outline = source_run.font.outline
            new_run.font.rtl = source_run.font.rtl
            new_run.font.small_caps = source_run.font.small_caps
            new_run.font.all_caps = source_run.font.all_caps
            new_run.font.double_strike = source_run.font.double_strike
            new_run.font.emboss = source_run.font.emboss
            new_run.font.imprint = source_run.font.imprint
            
            # 颜色属性
            if source_run.font.color.rgb is not None:
                new_run.font.color.rgb = source_run.font.color.rgb
            
            # 突出显示颜色
            if hasattr(source_run.font, 'highlight_color'):
                new_run.font.highlight_color = source_run.font.highlight_color

    @staticmethod
    def copy_paragraph_style(new_paragraph, source_paragraph):
        """完整复制段落级别的样式"""
        if source_paragraph.style is not None:
            new_paragraph.style = source_paragraph.style
        
        # 段落格式
        pf = new_paragraph.paragraph_format
        source_pf = source_paragraph.paragraph_format
        
        if source_pf.alignment is not None:
            pf.alignment = source_pf.alignment
        if source_pf.line_spacing is not None:
            pf.line_spacing = source_pf.line_spacing
        if source_pf.line_spacing_rule is not None:
            pf.line_spacing_rule = source_pf.line_spacing_rule
        if source_pf.space_before is not None:
            pf.space_before = source_pf.space_before
        if source_pf.space_after is not None:
            pf.space_after = source_pf.space_after
        if source_pf.first_line_indent is not None:
            pf.first_line_indent = source_pf.first_line_indent
        if source_pf.left_indent is not None:
            pf.left_indent = source_pf.left_indent
        if source_pf.right_indent is not None:
            pf.right_indent = source_pf.right_indent
        
        # 边框和底纹
        WordStyleCopier._copy_paragraph_borders(new_paragraph, source_paragraph)

    @staticmethod
    def copy_table_style(new_table, source_table):
        """完整复制表格样式"""
        # 表格整体样式
        new_table.style = source_table.style
        new_table.alignment = source_table.alignment
        
        # 复制每个单元格的样式
        for i, row in enumerate(source_table.rows):
            for j, cell in enumerate(row.cells):
                if i < len(new_table.rows) and j < len(new_table.rows[i].cells):
                    new_cell = new_table.rows[i].cells[j]
                    WordStyleCopier.copy_cell_style(new_cell, cell)

    @staticmethod
    def copy_cell_style(new_cell, source_cell):
        """复制单元格样式"""
        # 垂直对齐
        new_cell.vertical_alignment = source_cell.vertical_alignment
        
        # 边框和底纹
        WordStyleCopier._copy_cell_borders(new_cell, source_cell)
        
        # 单元格宽度
        new_cell.width = source_cell.width
        
        # 单元格边距
        new_cell._tc.tcPr.tcMar = source_cell._tc.tcPr.tcMar

    @staticmethod
    def copy_image(new_paragraph, image_run):
        """复制图片，保持原有属性"""
        if hasattr(image_run, '_inline_image'):
            image = image_run._inline_image
            if image is not None:
                # 保存图片属性
                width = image.width
                height = image.height
                
                # 创建新的图片run
                new_run = new_paragraph.add_run()
                new_run.add_picture(
                    image.blob,
                    width=width,
                    height=height
                )
                
                # 复制图片的位置和环绕方式
                if hasattr(image_run, '_r'):
                    new_run._r.drawing = image_run._r.drawing

    @staticmethod
    def _copy_paragraph_borders(new_paragraph, source_paragraph):
        """复制段落边框和底纹"""
        try:
            pPr = new_paragraph._p.get_or_add_pPr()
            source_pPr = source_paragraph._p.pPr
            if source_pPr is not None:
                # 复制边框
                if source_pPr.pBdr is not None:
                    pPr.pBdr = source_pPr.pBdr
                # 复制底纹
                if source_pPr.shd is not None:
                    pPr.shd = source_pPr.shd
        except Exception:
            pass

    @staticmethod
    def _copy_cell_borders(new_cell, source_cell):
        """复制单元格边框和底纹"""
        try:
            # 获取源单元格和目标单元格的属性
            source_tcPr = source_cell._tc.get_or_add_tcPr()
            new_tcPr = new_cell._tc.get_or_add_tcPr()
            
            # 复制边框
            if source_tcPr.tcBorders is not None:
                new_tcPr.tcBorders = source_tcPr.tcBorders
            
            # 复制底纹
            if source_tcPr.shd is not None:
                new_tcPr.shd = source_tcPr.shd
        except Exception:
            pass

    @staticmethod
    def copy_section_properties(new_section, source_section):
        """复制节属性"""
        # 页面设置
        new_section.page_height = source_section.page_height
        new_section.page_width = source_section.page_width
        new_section.left_margin = source_section.left_margin
        new_section.right_margin = source_section.right_margin
        new_section.top_margin = source_section.top_margin
        new_section.bottom_margin = source_section.bottom_margin
        new_section.header_distance = source_section.header_distance
        new_section.footer_distance = source_section.footer_distance
        new_section.orientation = source_section.orientation
        new_section.page_number_restart = source_section.page_number_restart
