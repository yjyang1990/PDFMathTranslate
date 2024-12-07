<div align="center">

[English](README.md) | 简体中文

<img src="./docs/images/banner.png" width="320px"  alt="PDF2ZH"/>  

<h2 id="title">PDFMathTranslate</h2>

<p>
  <!-- PyPI -->
  <a href="https://pypi.org/project/pdf2zh/">
    <img src="https://img.shields.io/pypi/v/pdf2zh"/></a>
  <a href="https://pepy.tech/projects/pdf2zh">
    <img src="https://static.pepy.tech/badge/pdf2zh"></a>
  <a href="https://hub.docker.com/repository/docker/byaidu/pdf2zh">
    <img src="https://img.shields.io/docker/pulls/byaidu/pdf2zh"></a>
  <!-- License -->
  <a href="./LICENSE">
    <img src="https://img.shields.io/github/license/Byaidu/PDFMathTranslate"/></a>
  <a href="https://huggingface.co/spaces/reycn/PDFMathTranslate-Docker">
    <img src="https://img.shields.io/badge/%F0%9F%A4%97-Online%20Demo-FF9E0D"/></a>
  <a href="https://github.com/Byaidu/PDFMathTranslate/pulls">
    <img src="https://img.shields.io/badge/contributions-welcome-green"/></a>
  <a href="https://t.me/+Z9_SgnxmsmA5NzBl">
    <img src="https://img.shields.io/badge/Telegram-2CA5E0?style=flat-squeare&logo=telegram&logoColor=white"/></a>
</p>

</div>

科学 PDF 文档翻译及双语对照工具

- 📊 保留公式、图表、目录和注释 *([预览效果](#preview))*
- 🌐 支持 [多种语言](#language) 和 [诸多翻译服务](#services)
- 🤖 提供 [命令行工具](#usage)，[图形交互界面](#gui)，以及 [容器化部署](#docker)

欢迎在 [GitHub Issues](https://github.com/Byaidu/PDFMathTranslate/issues)、[Telegram 用户群](https://t.me/+Z9_SgnxmsmA5NzBl) 或 [QQ 用户群](https://qm.qq.com/q/DixZCxQej0) 中提供反馈

<h2 id="updates">近期更新</h2>

- [Nov. 26 2024] CLI 现在已支持（多个）在线 PDF 文件 *(by [@reycn](https://github.com/reycn))*  
- [Nov. 24 2024] 为降低依赖大小，提供 [ONNX](https://github.com/onnx/onnx) 支持 *(by [@Wybxc](https://github.com/Wybxc))*  
- [Nov. 23 2024] 🌟 [免费公共服务](#demo) 上线! *(by [@Byaidu](https://github.com/Byaidu))*  
- [Nov. 23 2024] 防止网页爬虫的防火墙 *(by [@Byaidu](https://github.com/Byaidu))*  
- [Nov. 22 2024] 图形用户界面现已支持意大利语，并获得了一些更新 *(by [@Byaidu](https://github.com/Byaidu), [@reycn](https://github.com/reycn))*  
- [Nov. 22 2024] 现在你可以将自己部署的服务分享给朋友了 *(by [@Zxis233](https://github.com/Zxis233))*  
- [Nov. 22 2024] 支持腾讯翻译 *(by [@hellofinch](https://github.com/hellofinch))*  
- [Nov. 21 2024] 图形用户界面现在支持下载双语文档 *(by [@reycn](https://github.com/reycn))*  
- [Nov. 20 2024] 🌟 提供了 [在线演示](#demo)！ *(by [@reycn](https://github.com/reycn))*  

<h2 id="preview">效果预览</h2>

<div align="center">
<img src="./docs/images/preview.gif" width="80%"/>
</div>

<h2 id="demo">在线演示 🌟</h2>

### 免费服务 (<https://pdf2zh.com/>)

你可以立即尝试 [免费公共服务](https://pdf2zh.com/) 而无需安装

### Hugging Face 在线演示

你可以立即尝试 [在 HuggingFace 上的在线演示](https://huggingface.co/spaces/reycn/PDFMathTranslate-Docker) 而无需安装
请注意，演示的计算资源有限，因此请避免滥用

<h2 id="install">安装和使用</h2>

### 本地安装

1. 确保安装了版本大于 3.8 且小于 3.12 的 Python

2. 安装依赖：
```bash
pip install python-dotenv
pip install redis
pip install doclayout-yolo torch onnx onnxruntime
pip install pdf2zh
```

3. 运行服务：
```bash
uvicorn pdf2zh.api:app --reload --port 8080
```

4. 打开浏览器访问：
```
http://127.0.0.1:8080
```

<h3 id="gui">方法三、图形交互界面</h3>

1. 确保安装了版本大于 3.8 且小于 3.12 的 Python
2. 安装此程序：

      ```bash
      pip install pdf2zh
      ```

3. 开始在浏览器中使用：

      ```bash
      pdf2zh -i
      ```

4. 如果您的浏览器没有自动启动并跳转，请用浏览器打开：

    ```bash
    http://localhost:7860/
    ```

    <img src="./docs/images/gui.gif" width="500"/>

查看 [documentation for GUI](./docs/README_GUI.md) 获取细节说明

<h3 id="docker">方法四、容器化部署</h3>

1. 安装 Docker：
   - 对于 Windows/Mac 用户，安装 [Docker Desktop](https://www.docker.com/products/docker-desktop/)
   - 对于 Linux 用户，按照 [Docker 安装指南](https://docs.docker.com/engine/install/) 进行安装

2. 确保远程 Redis 服务器已启动（103.73.163.68:6379）

3. 拉取并运行 PDF 翻译服务：
```bash
docker pull byaidu/pdf2zh
docker run -d -p 8080:8080 byaidu/pdf2zh
```

4. 打开浏览器访问：
```
http://localhost:8080
```

注意事项：
- 确保能够连接到远程 Redis 服务器（103.73.163.68:6379）
- 如果需要修改端口，请相应地更改 `-p 8080:8080` 中的第一个 8080
- 如果需要自定义配置，可以通过挂载自定义的 .env 文件：
  ```bash
  docker run -d -p 8080:8080 -v /path/to/your/.env:/app/.env byaidu/pdf2zh
  ```
- 如果遇到权限问题，可能需要在命令前添加 `sudo`

用于在云服务上部署容器镜像：

<div>
<a href="https://www.heroku.com/deploy?template=https://github.com/Byaidu/PDFMathTranslate">
  <img src="https://www.herokucdn.com/deploy/button.svg" alt="Deploy" height="26"></a>
<a href="https://render.com/deploy">
  <img src="https://render.com/images/deploy-to-render-button.svg" alt="Deploy to Koyeb" height="26"></a>
<a href="https://zeabur.com/templates/5FQIGX?referralCode=reycn">
  <img src="https://zeabur.com/button.svg" alt="Deploy on Zeabur" height="26"></a>
<a href="https://app.koyeb.com/deploy?type=git&builder=buildpack&repository=github.com/Byaidu/PDFMathTranslate&branch=main&name=pdf-math-translate">
  <img src="https://www.koyeb.com/static/images/deploy/button.svg" alt="Deploy to Koyeb" height="26"></a>
</div>

<h2 id="usage">高级选项</h2>

在命令行中执行翻译命令，在当前工作目录下生成译文文档 `example-zh.pdf` 和双语对照文档 `example-dual.pdf`，默认使用 Google 翻译服务

<img src="./docs/images/cmd.explained.png" width="580px"  alt="cmd"/>  

我们在下表中列出了所有高级选项，以供参考：

| Option    | Function | Example |
| -------- | ------- |------- |
| files | 本地文件 |  `pdf2zh ~/local.pdf` |
| links | 在线文件 |  `pdf2zh http://arxiv.org/paper.pdf` |
| `-i`  | [进入图形界面](#gui) |  `pdf2zh -i` |
| `-p`  | [仅翻译部分文档](#partial) |  `pdf2zh example.pdf -p 1` |
| `-li` | [源语言](#languages) |  `pdf2zh example.pdf -li en` |
| `-lo` | [目标语言](#languages) |  `pdf2zh example.pdf -lo zh` |
| `-s`  | [指定翻译服务](#services) |  `pdf2zh example.pdf -s deepl` |
| `-t`  | [多线程](#threads) | `pdf2zh example.pdf -t 1` |
| `-o`  | 输出目录 | `pdf2zh example.pdf -o output` |
| `-f`, `-c` | [例外规则](#exceptions) | `pdf2zh example.pdf -f "(MS.*)"` |

<h3 id="partial">全文或部分文档翻译</h3>

- **全文翻译**

```bash
pdf2zh example.pdf
```

- **部分翻译**

```bash
pdf2zh example.pdf -p 1-3,5
```

<h3 id="language">指定源语言和目标语言</h3>

参考 [Google Languages Codes](https://developers.google.com/admin-sdk/directory/v1/languages), [DeepL Languages Codes](https://developers.deepl.com/docs/resources/supported-languages)

```bash
pdf2zh example.pdf -li en -lo ja
```

<h3 id="services">使用不同的翻译服务</h3>

下表列出了每个翻译服务所需的 [环境变量](https://chatgpt.com/share/6734a83d-9d48-800e-8a46-f57ca6e8bcb4)，在使用相应服务之前，请确保已设置这些变量

|**Translator**|**Service**|**Environment Variables**|**Default Values**|**Notes**|
|-|-|-|-|-|
|**Google (Default)**|`google`|None|N/A|None|
|**Bing**|`bing`|None|N/A|None|
|**DeepL**|`deepl`|`DEEPL_SERVER_URL`,`DEEPL_AUTH_KEY`|`https://api.deepl.com`, `[Your Key]`|See [DeepL](https://support.deepl.com/hc/en-us/articles/360020695820-API-Key-for-DeepL-s-API)|
|**DeepLX**|`deeplx`|`DEEPLX_ENDPOINT`|`https://api.deepl.com/translate`|See [DeepLX](https://github.com/OwO-Network/DeepLX)|
|**Ollama**|`ollama`|`OLLAMA_HOST`, `OLLAMA_MODEL`|`http://127.0.0.1:11434`, `gemma2`|See [Ollama](https://github.com/ollama/ollama)|
|**OpenAI**|`openai`|`OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`|`https://api.openai.com/v1`, `[Your Key]`, `gpt-4o-mini`|See [OpenAI](https://platform.openai.com/docs/overview)|
|**Zhipu**|`zhipu`|`ZHIPU_API_KEY`, `ZHIPU_MODEL`|`[Your Key]`, `glm-4-flash`|See [Zhipu](https://open.bigmodel.cn/dev/api/thirdparty-frame/openai-sdk)|
|**Silicon**|`silicon`|`SILICON_API_KEY`, `SILICON_MODEL`|`[Your Key]`, `Qwen/Qwen2.5-7B-Instruct`|See [SiliconCloud](https://docs.siliconflow.cn/quickstart)|
|**Azure**|`azure`|`AZURE_ENDPOINT`, `AZURE_API_KEY`|`https://api.translator.azure.cn`, `[Your Key]`|See [Azure](https://docs.azure.cn/en-us/ai-services/translator/text-translation-overview)|
|**Tencent**|`tencent`|`TENCENTCLOUD_SECRET_ID`, `TENCENTCLOUD_SECRET_KEY`|`[Your ID]`, `[Your Key]`|See [Tencent](https://www.tencentcloud.com/products/tmt?from_qcintl=122110104)|

使用 `-s service` 或 `-s service:model` 指定翻译服务:

```bash
pdf2zh example.pdf -s openai:gpt-4o-mini
```

或者使用环境变量指定模型：

```bash
set OPENAI_MODEL=gpt-4o-mini
pdf2zh example.pdf -s openai
```

<h3 id="exceptions">指定例外规则</h3>

使用正则表达式指定需保留的公式字体与字符：

```bash
pdf2zh example.pdf -f "(CM[^RT].*|MS.*|.*Ital)" -c "(\(|\||\)|\+|=|\d|[\u0080-\ufaff])"
```

<h3 id="threads">指定线程数量</h3>

使用 `-t` 指定翻译时使用的线程数量：

```bash
pdf2zh example.pdf -t 1
```

<h2 id="acknowledgement">致谢</h2>

- 文档合并：[PyMuPDF](https://github.com/pymupdf/PyMuPDF)

- 文档解析：[Pdfminer.six](https://github.com/pdfminer/pdfminer.six)

- 文档提取：[MinerU](https://github.com/opendatalab/MinerU)

- 多线程翻译：[MathTranslate](https://github.com/SUSYUSTC/MathTranslate)

- 布局解析：[DocLayout-YOLO](https://github.com/opendatalab/DocLayout-YOLO)

- 文档标准：[PDF Explained](https://zxyle.github.io/PDF-Explained/), [PDF Cheat Sheets](https://pdfa.org/resource/pdf-cheat-sheets/)

- 多语言字体：[Go Noto Universal](https://github.com/satbyy/go-noto-universal)

<h2 id="contrib">贡献者</h2>

<a href="https://github.com/Byaidu/PDFMathTranslate/graphs/contributors">
  <img src="https://opencollective.com/PDFMathTranslate/contributors.svg?width=890&button=false" />
</a>

![Alt](https://repobeats.axiom.co/api/embed/dfa7583da5332a11468d686fbd29b92320a6a869.svg "Repobeats analytics image")

<h2 id="star_hist">星标历史</h2>

<a href="https://star-history.com/#Byaidu/PDFMathTranslate&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=Byaidu/PDFMathTranslate&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=Byaidu/PDFMathTranslate&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=Byaidu/PDFMathTranslate&type=Date"/>
 </picture>
</a>
