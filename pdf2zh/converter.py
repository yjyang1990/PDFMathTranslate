from pdfminer.pdfinterp import PDFGraphicState, PDFResourceManager
from pdfminer.pdffont import PDFFont, PDFCIDFont
from pdfminer.converter import PDFConverter
from pdfminer.pdffont import PDFUnicodeNotDefined
from pdfminer.utils import apply_matrix_pt, mult_matrix
from pdfminer.layout import (
    LTChar,
    LTFigure,
    LTLine,
    LTPage,
)
import logging
import re
import concurrent.futures
import numpy as np
import unicodedata
from tenacity import retry, wait_fixed
from pdf2zh import cache
from pdf2zh.translator import (
    BaseTranslator,
    GoogleTranslator,
    DeepLTranslator,
    DeepLXTranslator,
    OllamaTranslator,
    OpenAITranslator,
    AzureTranslator,
    TencentTranslator,
)
from pymupdf import Font

log = logging.getLogger(__name__)


class PDFConverterEx(PDFConverter):
    def __init__(
        self,
        rsrcmgr: PDFResourceManager,
    ) -> None:
        PDFConverter.__init__(self, rsrcmgr, None, "utf-8", 1, None)

    def begin_page(self, page, ctm) -> None:
        # 重载替换 cropbox
        (x0, y0, x1, y1) = page.cropbox
        (x0, y0) = apply_matrix_pt(ctm, (x0, y0))
        (x1, y1) = apply_matrix_pt(ctm, (x1, y1))
        mediabox = (0, 0, abs(x0 - x1), abs(y0 - y1))
        self.cur_item = LTPage(page.pageno, mediabox)

    def end_page(self, page):
        # 重载返回指令流
        return self.receive_layout(self.cur_item)

    def begin_figure(self, name, bbox, matrix) -> None:
        # 重载设置 pageid
        self._stack.append(self.cur_item)
        self.cur_item = LTFigure(name, bbox, mult_matrix(matrix, self.ctm))
        self.cur_item.pageid = self._stack[-1].pageid

    def end_figure(self, _: str) -> None:
        # 重载返回指令流
        fig = self.cur_item
        assert isinstance(self.cur_item, LTFigure), str(type(self.cur_item))
        self.cur_item = self._stack.pop()
        self.cur_item.add(fig)
        return self.receive_layout(fig)

    def render_char(
        self,
        matrix,
        font,
        fontsize: float,
        scaling: float,
        rise: float,
        cid: int,
        ncs,
        graphicstate: PDFGraphicState,
    ) -> float:
        # 重载设置 cid 和 font
        try:
            text = font.to_unichr(cid)
            assert isinstance(text, str), str(type(text))
        except PDFUnicodeNotDefined:
            text = self.handle_undefined_char(font, cid)
        textwidth = font.char_width(cid)
        textdisp = font.char_disp(cid)
        item = LTChar(
            matrix,
            font,
            fontsize,
            scaling,
            rise,
            text,
            textwidth,
            textdisp,
            ncs,
            graphicstate,
        )
        self.cur_item.add(item)
        item.cid = cid  # hack 插入原字符编码
        item.font = font  # hack 插入原字符字体
        return item.adv


class Paragraph:
    def __init__(self, y, x, x0, x1, size, font, brk):
        self.y: float = y  # 初始纵坐标
        self.x: float = x  # 初始横坐标
        self.x0: float = x0  # 左边界
        self.x1: float = x1  # 右边界
        self.size: float = size  # 字体大小
        self.font: PDFFont = font  # 字体
        self.brk: bool = brk  # 换行标记


# fmt: off
class TranslateConverter(PDFConverterEx):
    def __init__(
        self,
        rsrcmgr,
        vfont: str = None,
        vchar: str = None,
        thread: int = 0,
        layout={},
        lang_in: str = "",
        lang_out: str = "",
        service: str = "",
        resfont: str = "",
        noto: Font = None,
    ) -> None:
        super().__init__(rsrcmgr)
        self.vfont = vfont
        self.vchar = vchar
        self.thread = thread
        self.layout = layout
        self.resfont = resfont
        self.noto = noto
        self.translator: BaseTranslator = None
        param = service.split(":", 1)
        if param[0] == "google":
            self.translator = GoogleTranslator(service, lang_out, lang_in, None)
        elif param[0] == "deepl":
            self.translator = DeepLTranslator(service, lang_out, lang_in, None)
        elif param[0] == "deeplx":
            self.translator = DeepLXTranslator(service, lang_out, lang_in, None)
        elif param[0] == "ollama":
            self.translator = OllamaTranslator(service, lang_out, lang_in, param[1])
        elif param[0] == "openai":
            self.translator = OpenAITranslator(service, lang_out, lang_in, param[1])
        elif param[0] == "azure":
            self.translator = AzureTranslator(service, lang_out, lang_in, None)
        elif param[0] == "tencent":
            self.translator = TencentTranslator(service, lang_out, lang_in, None)
        else:
            raise ValueError("Unsupported translation service")

    def receive_layout(self, ltpage: LTPage):
        # 段落
        sstk: list[str] = []            # 段落文字栈
        pstk: list[Paragraph] = []      # 段落属性栈
        vbkt: int = 0                   # 段落公式括号计数
        # 公式组
        vstk: list[LTChar] = []         # 公式符号组
        vlstk: list[LTLine] = []        # 公式线条组
        vfix: float = 0                 # 公式纵向偏移
        # 公式组栈
        var: list[list[LTChar]] = []    # 公式符号组栈
        varl: list[list[LTLine]] = []   # 公式线条组栈
        varf: list[float] = []          # 公式纵向偏移栈
        vlen: list[float] = []          # 公式宽度栈
        # 全局
        lstk: list[LTLine] = []         # 全局线条栈
        xt: LTChar = None               # 上一个字符
        xt_cls: int = -1                # 上一个字符所属段落
        vmax: float = ltpage.width / 4  # 行内公式最大宽度
        ops: str = ""                   # 渲染结果

        def decode_font_name(font_name):    # 解码字体名称
            if isinstance(font_name, bytes):
                return font_name.decode('utf-8', errors='ignore')
            return font_name

        def vflag(font: str, char: str):    # 匹配公式（和角标）字体
            font = decode_font_name(font)
            if isinstance(char, bytes):
                char = char.decode('utf-8', errors='ignore')
            font = font.split("+")[-1]      # 字体名截断
            if re.match(r"\(cid:", char):
                return True
            # 基于字体名规则的判定
            if self.vfont:
                if re.match(self.vfont, font):
                    return True
            else:
                # 只匹配明确的数学和符号字体，不包括普通斜体和拉丁文
                if re.match(
                    r"(CM[^R]|(MS|XY|MT|BL|RM|EU|RS)[A-Z]|LINE|TeX-|rsfs|txsy|wasy|stmary|.*Math|.*Sym)",
                    font,
                ):
                    return True
            # 基于字符集规则的判定
            if self.vchar:
                if re.match(self.vchar, char):
                    return True
            else:
                if (
                    char
                    and char != " "                                     # 非空格
                    and (
                        unicodedata.category(char[0])
                        in ["Mn", "Sm"]                                 # 只匹配数学符号和修饰符
                        or ord(char[0]) in range(0x370, 0x400)          # 希腊字母
                    )
                ):
                    return True
            return False

        ############################################################
        # A. 原文档解析
        for child in ltpage:
            if isinstance(child, LTChar):
                cur_v = False
                layout = self.layout[ltpage.pageid]
                # ltpage.height 可能是 fig 里面的高度，这里统一用 layout.shape
                h, w = layout.shape
                # 读取当前字符在 layout 中的类别
                cx, cy = np.clip(int(child.x0), 0, w - 1), np.clip(int(child.y0), 0, h - 1)
                cls = layout[cy, cx]
                if (                                                                                        # 判定当前字符是否属于公式
                    cls == 0                                                                                # 1. 类别为保留区域
                    or (cls == xt_cls and len(sstk[-1].strip()) > 1 and child.size < pstk[-1].size * 0.79)  # 2. 角标字体
                    or (child.matrix[0] == 0 and child.matrix[3] == 0)                                      # 3. 垂直字体
                ):
                    cur_v = True
                else:
                    # 打印调试信息
                    text = child.get_text()
                    
                    # 检查是否是需要翻译的拉丁文
                    is_latin_quote = False
                    if sstk:
                        current_text = sstk[-1]
                        # 检查是否在引号内
                        quote_count = current_text.count('"')
                        in_quotes = quote_count % 2 == 1
                        # 检查是否包含拉丁字母
                        has_latin = any(c.isalpha() and ord(c) < 128 for c in text)
                        is_latin_quote = in_quotes and has_latin
                    
                    if is_latin_quote or not vflag(child.fontname, text):
                        cur_v = False
                    else:
                        cur_v = True
                # 判定括号组是否属于公式
                if not cur_v:
                    if vstk and child.get_text() == "(":
                        cur_v = True
                        vbkt += 1
                    if vbkt and child.get_text() == ")":
                        cur_v = True
                        vbkt -= 1
                if (                                                        # 判定当前公式是否结束
                    not cur_v                                               # 1. 当前字符不属于公式
                    or cls != xt_cls                                        # 2. 当前字符与前一个字符不属于同一段落
                    or (abs(child.x0 - xt.x0) > vmax and cls != 0)          # 3. 段落内换行，可能是一长串斜体的段落，也可能是段内分式换行，这里设个阈值进行区分
                ):
                    if vstk:
                        if (                                                # 根据公式右侧的文字修正公式的纵向偏移
                            not cur_v                                       # 1. 当前字符不属于公式
                            and cls == xt_cls                               # 2. 当前字符与前一个字符属于同一段落
                            and child.x0 > max([vch.x0 for vch in vstk])    # 3. 当前字符在公式右侧
                        ):
                            vfix = vstk[0].y0 - child.y0
                        sstk[-1] += f"$v{len(var)}$"
                        var.append(vstk)
                        varl.append(vlstk)
                        varf.append(vfix)
                        vstk = []
                        vlstk = []
                        vfix = 0
                # 当前字符不属于公式或当前字符是公式的第一个字符
                if not vstk:
                    if cls == xt_cls:               # 当前字符与前一个字符属于同一段落
                        if child.x0 > xt.x1 + 1:    # 添加行内空格
                            sstk[-1] += " "
                        elif child.x1 < xt.x0:      # 添加换行空格并标记原文段落存在换行
                            sstk[-1] += " "
                            pstk[-1].brk = True
                    else:                           # 根据当前字符构建一个新的段落
                        sstk.append("")
                        pstk.append(Paragraph(child.y0, child.x0, child.x0, child.x0, child.size, child.font, False))
                if not cur_v:                                               # 文字入栈
                    if (                                                    # 根据当前字符修正段落属性
                        child.size > pstk[-1].size / 0.79                   # 1. 当前字符显著比段落字体大
                        or len(sstk[-1].strip()) == 1                       # 2. 当前字符为段落第二个文字（考虑首字母放大的情况）
                        or vflag(pstk[-1].font.fontname, "")                # 3. 段落字体为公式字体
                        or re.match(                                        # 4. 段落字体为粗体
                            r"(.*Medi|.*Bold)",
                            decode_font_name(pstk[-1].font.fontname),
                            re.IGNORECASE,
                        )
                    ):
                        pstk[-1].y -= child.size - pstk[-1].size             # hack 这个段落纵向位置的修正有问题，不过先凑合用吧
                        pstk[-1].size = child.size
                        pstk[-1].font = child.font
                    sstk[-1] += child.get_text()
                else:                                                       # 公式入栈
                    if (                                                    # 根据公式左侧的文字修正公式的纵向偏移
                        not vstk                                            # 1. 当前字符是公式的第一个字符
                        and cls == xt_cls                                   # 2. 当前字符与前一个字符属于同一段落
                        and child.x0 > xt.x0                                # 3. 前一个字符在公式左侧
                    ):
                        vfix = child.y0 - xt.y0
                    vstk.append(child)
                # 更新段落边界，因为段落内换行之后可能是公式开头，所以要在外边处理
                pstk[-1].x0 = min(pstk[-1].x0, child.x0)
                pstk[-1].x1 = max(pstk[-1].x1, child.x1)
                # 更新上一个字符
                xt = child
                xt_cls = cls
            elif isinstance(child, LTFigure):   # 图表
                pass
            elif isinstance(child, LTLine):     # 线条
                layout = self.layout[ltpage.pageid]
                # ltpage.height 可能是 fig 里面的高度，这里统一用 layout.shape
                h, w = layout.shape
                # 读取当前线条在 layout 中的类别
                cx, cy = np.clip(int(child.x0), 0, w - 1), np.clip(int(child.y0), 0, h - 1)
                cls = layout[cy, cx]
                if vstk and cls == xt_cls:      # 公式线条
                    vlstk.append(child)
                else:                           # 全局线条
                    lstk.append(child)
            else:
                pass
        # 处理结尾
        if vstk:    # 公式出栈
            sstk[-1] += f"$v{len(var)}$"
            var.append(vstk)
            varl.append(vlstk)
            varf.append(vfix)
        log.debug("\n==========[VSTACK]==========\n")
        for id, v in enumerate(var):  # 计算公式宽度
            l = max([vch.x1 for vch in v]) - v[0].x0
            log.debug(f'< {l:.1f} {v[0].x0:.1f} {v[0].y0:.1f} {v[0].cid} {v[0].fontname} {len(varl[id])} > $v{id}$ = {"".join([ch.get_text() for ch in v])}')
            vlen.append(l)

        ############################################################
        # B. 段落翻译
        log.debug("\n==========[SSTACK]==========\n")
        hash_key = cache.deterministic_hash("PDFMathTranslate")
        cache.create_cache(hash_key)

        @retry(wait=wait_fixed(1))
        def worker(s: str):  # 多线程翻译
            try:
                hash_key_paragraph = cache.deterministic_hash(
                    (s, str(self.translator))
                )
                new = cache.load_paragraph(hash_key, hash_key_paragraph)  # 查询缓存
                if new is None:
                    new = self.translator.translate(s)
                    cache.write_paragraph(hash_key, hash_key_paragraph, new)
                return new
            except BaseException as e:
                if log.isEnabledFor(logging.DEBUG):
                    log.exception(e)
                else:
                    log.exception(e, exc_info=False)
                raise e
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.thread
        ) as executor:
            news = list(executor.map(worker, sstk))

        ############################################################
        # C. 新文档排版
        def raw_string(fcur: str, cstk: str):  # 编码字符串
            if fcur == 'noto':
                return "".join(["%04x" % self.noto.has_glyph(ord(c)) for c in cstk])
            elif isinstance(self.fontmap[fcur], PDFCIDFont):  # 判断编码长度
                return "".join(["%04x" % ord(c) for c in cstk])
            else:
                return "".join(["%02x" % ord(c) for c in cstk])

        _x, _y = 0, 0
        for id, new in enumerate(news):
            x: float = pstk[id].x           # 段落初始横坐标
            y: float = pstk[id].y           # 段落上边界
            x0: float = pstk[id].x0         # 段落左边界
            x1: float = pstk[id].x1         # 段落右边界
            size: float = pstk[id].size     # 段落字体大小
            font: PDFFont = pstk[id].font   # 段落字体
            brk: bool = pstk[id].brk        # 段落属性
            cstk: str = ""                  # 当前文字栈
            fcur: str = None                # 当前字体ID
            tx = x
            fcur_ = fcur
            ptr = 0
            log.debug(f"< {y} {x} {x0} {x1} {size} {font.fontname} {brk} > {sstk[id]} | {new}")
            while ptr < len(new):
                vy_regex = re.match(
                    r"\$?\s*v([\d\s]+)\$", new[ptr:], re.IGNORECASE
                )  # 匹配 $vn$ 公式标记，前面的 $ 有的时候会被丢掉
                mod = 0  # 文字修饰符
                if vy_regex:  # 加载公式
                    ptr += len(vy_regex.group(0))
                    try:
                        vid = int(vy_regex.group(1).replace(" ", ""))
                        adv = vlen[vid]
                    except Exception:
                        continue  # 翻译器可能会自动补个越界的公式标记
                    if var[vid][-1].get_text() and unicodedata.category(var[vid][-1].get_text()[0]) in ["Lm", "Mn", "Sk"]:  # 文字修饰符
                        mod = var[vid][-1].width
                else:  # 加载文字
                    ch = new[ptr]
                    fcur_ = None
                    # 原字体编码容易出问题，这里直接放弃掉
                    # try:
                    #     if font.widths.get(ord(ch)) and font.to_unichr(ord(ch))==ch:
                    #         fcur_=self.fontid[font] # 原字体
                    # except:
                    #     pass
                    try:
                        if fcur_ is None and self.fontmap["tiro"].to_unichr(ord(ch)) == ch:
                            fcur_ = "tiro"  # 默认拉丁字体
                    except Exception:
                        pass
                    if fcur_ is None:
                        fcur_ = self.resfont  # 默认非拉丁字体
                    # print(self.fontid[font],fcur_,ch,font.char_width(ord(ch)))
                    if fcur_ == 'noto':
                        adv = self.noto.char_lengths(ch, size)[0]
                    else:
                        adv = self.fontmap[fcur_].char_width(ord(ch)) * size
                    ptr += 1
                if (                                # 输出文字缓冲区
                    fcur_ != fcur                   # 1. 字体更新
                    or vy_regex                     # 2. 插入公式
                    or x + adv > x1 + 0.1 * size    # 3. 到达右边界（可能一整行都被符号化，这里需要考虑浮点误差）
                ):
                    if cstk:
                        ops += f"/{fcur} {size:f} Tf 1 0 0 1 {tx:f} {y:f} Tm [<{raw_string(fcur, cstk)}>] TJ "
                        cstk = ""
                if brk and x + adv > x1 + 0.1 * size:  # 到达右边界且原文段落存在换行
                    x = x0
                    lang_space = {"zh-CN": 1.4, "zh-TW": 1.4, "ja": 1.1, "ko": 1.2, "en": 1.2, "ar": 1.0, "ru": 0.8, "uk": 0.8, "ta": 0.8}
                    y -= size * lang_space.get(self.translator.lang_out, 1.1)  # 小语种大多适配 1.1
                if vy_regex:  # 插入公式
                    fix = 0
                    if fcur is not None:  # 段落内公式修正纵向偏移
                        fix = varf[vid]
                    for vch in var[vid]:  # 排版公式字符
                        vc = chr(vch.cid)
                        ops += f"/{self.fontid[vch.font]} {vch.size:f} Tf 1 0 0 1 {x + vch.x0 - var[vid][0].x0:f} {fix + y + vch.y0 - var[vid][0].y0:f} Tm [<{raw_string(self.fontid[vch.font], vc)}>] TJ "
                        if log.isEnabledFor(logging.DEBUG):
                            lstk.append(LTLine(0.1, (_x, _y), (x + vch.x0 - var[vid][0].x0, fix + y + vch.y0 - var[vid][0].y0)))
                            _x, _y = x + vch.x0 - var[vid][0].x0, fix + y + vch.y0 - var[vid][0].y0
                    for l in varl[vid]:  # 排版公式线条
                        if l.linewidth < 5:  # hack 有的文档会用粗线条当图片背景
                            ops += f"ET q 1 0 0 1 {l.pts[0][0] + x - var[vid][0].x0:f} {l.pts[0][1] + fix + y - var[vid][0].y0:f} cm [] 0 d 0 J {l.linewidth:f} w 0 0 m {l.pts[1][0] - l.pts[0][0]:f} {l.pts[1][1] - l.pts[0][1]:f} l S Q BT "
                else:  # 插入文字缓冲区
                    if not cstk:  # 单行开头
                        tx = x
                        if x == x0 and ch == " ":  # 消除段落换行空格
                            adv = 0
                        else:
                            cstk += ch
                    else:
                        cstk += ch
                adv -= mod # 文字修饰符
                fcur = fcur_
                x += adv
                if log.isEnabledFor(logging.DEBUG):
                    lstk.append(LTLine(0.1, (_x, _y), (x, y)))
                    _x, _y = x, y
            # 处理结尾
            if cstk:
                ops += f"/{fcur} {size:f} Tf 1 0 0 1 {tx:f} {y:f} Tm [<{raw_string(fcur, cstk)}>] TJ "
        for l in lstk:  # 排版全局线条
            if l.linewidth < 5:  # hack 有的文档会用粗线条当图片背景
                ops += f"ET q 1 0 0 1 {l.pts[0][0]:f} {l.pts[0][1]:f} cm [] 0 d 0 J {l.linewidth:f} w 0 0 m {l.pts[1][0] - l.pts[0][0]:f} {l.pts[1][1] - l.pts[0][1]:f} l S Q BT "
        ops = f"BT {ops}ET "
        return ops
