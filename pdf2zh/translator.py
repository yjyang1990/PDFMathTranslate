import os
from dotenv import load_dotenv
import html
import logging
import re
from json import dumps, loads
import time
from threading import Lock

import deepl
import ollama
import openai
import requests
from azure.ai.translation.text import TextTranslationClient
from azure.core.credentials import AzureKeyCredential

# 在文件开头加载.env配置
load_dotenv()

class BaseTranslator:
    def __init__(self, service, lang_out, lang_in, model):
        self.service = service
        self.lang_out = lang_out
        self.lang_in = lang_in
        self.model = model

    def translate(self, text) -> str:
        ...

    def __str__(self):
        pass

    def __str__(self):
        return f"{self.service} {self.lang_out} {self.lang_in}"


class GoogleTranslator(BaseTranslator):
    def __init__(self, service, lang_out, lang_in, model):
        lang_out = "zh-CN" if lang_out == "auto" else lang_out
        lang_in = "en" if lang_in == "auto" else lang_in
        super().__init__(service, lang_out, lang_in, model)
        self.session = requests.Session()
        self.base_link = "http://translate.google.com/m"
        self.headers = {
            "User-Agent": "Mozilla/4.0 (compatible;MSIE 6.0;Windows NT 5.1;SV1;.NET CLR 1.1.4322;.NET CLR 2.0.50727;.NET CLR 3.0.04506.30)"
        }

    def translate(self, text):
        text = text[:5000]  # google translate max length
        response = self.session.get(
            self.base_link,
            params={"tl": self.lang_out, "sl": self.lang_in, "q": text},
            headers=self.headers,
        )
        re_result = re.findall(
            r'(?s)class="(?:t0|result-container)">(.*?)<', response.text
        )
        if response.status_code == 400:
            result = 'IRREPARABLE TRANSLATION ERROR'
        elif len(re_result) == 0:
            raise ValueError("Empty translation result")
        else:
            result = html.unescape(re_result[0])
        return result


class DeepLXTranslator(BaseTranslator):
    def __init__(self, service, lang_out, lang_in, model):
        lang_out = "zh" if lang_out == "auto" else lang_out
        lang_in = "en" if lang_in == "auto" else lang_in
        super().__init__(service, lang_out, lang_in, model)
        try:
            auth_key = os.getenv("DEEPLX_AUTH_KEY")
            server_url = (
                "https://api.deeplx.org"
                if not os.getenv("DEEPLX_SERVER_URL")
                else os.getenv("DEEPLX_SERVER_URL")
            )
        except KeyError as e:
            missing_var = e.args[0]
            raise ValueError(
                f"The environment variable '{missing_var}' is required but not set."
            ) from e

        self.session = requests.Session()
        self.base_link = f"{server_url}/{auth_key}/translate"
        self.headers = {
            "User-Agent": "Mozilla/4.0 (compatible;MSIE 6.0;Windows NT 5.1;SV1;.NET CLR 1.1.4322;.NET CLR 2.0.50727;.NET CLR 3.0.04506.30)"
        }

    def translate(self, text):
        text = text[:5000]  # google translate max length
        response = self.session.post(
            self.base_link,
            dumps(
                {
                    "target_lang": self.lang_out,
                    "text": text,
                }
            ),
            headers=self.headers,
        )
        # 1. Status code test
        if response.status_code == 200:
            result = loads(response.text)
        else:
            raise ValueError("HTTP error: " + str(response.status_code))
        # 2. Result test
        try:
            result = result["data"]
            return result
        except KeyError:
            result = ""
            raise ValueError("No valid key in DeepLX's response")
        # 3. Result length check
        if len(result) == 0:
            raise ValueError("Empty translation result")
        return result


class DeepLTranslator(BaseTranslator):
    def __init__(self, service, lang_out, lang_in, model):
        lang_out='ZH' if lang_out=='auto' else lang_out
        lang_in='EN' if lang_in=='auto' else lang_in
        super().__init__(service, lang_out, lang_in, model)
        self.session = requests.Session()
        auth_key = os.getenv('DEEPL_AUTH_KEY')
        server_url = os.getenv('DEEPL_SERVER_URL')
        self.client = deepl.Translator(auth_key, server_url=server_url)

    def translate(self, text):
        response = self.client.translate_text(
            text,
            target_lang=self.lang_out,
            source_lang=self.lang_in
        )
        return response.text


class OllamaTranslator(BaseTranslator):
    def __init__(self, service, lang_out, lang_in, model):
        lang_out='zh-CN' if lang_out=='auto' else lang_out
        lang_in='en' if lang_in=='auto' else lang_in
        super().__init__(service, lang_out, lang_in, model)
        self.options = {"temperature": 0}  # 随机采样可能会打断公式标记
        # OLLAMA_HOST
        self.client = ollama.Client()

    def translate(self, text):
        response = self.client.chat(
            model=self.model,
            options=self.options,
            messages=[
                {
                    "role": "system",
                    "content": "You are a professional,authentic machine translation engine.",
                },
                {
                    "role": "user",
                    "content": f"Translate the following markdown source text to {self.lang_out}. Keep the formula notation $v*$ unchanged. Output translation directly without any additional text.\nSource Text: {text}\nTranslated Text:",
                },
            ],
        )
        return response["message"]["content"].strip()

class RateLimiter:
    def __init__(self, tokens_per_second):
        self.tokens_per_second = tokens_per_second
        self.tokens = tokens_per_second
        self.last_update = time.time()
        self.lock = Lock()

    def acquire(self):
        with self.lock:
            now = time.time()
            time_passed = now - self.last_update
            self.tokens = min(
                self.tokens_per_second,
                self.tokens + time_passed * self.tokens_per_second
            )
            
            if self.tokens < 1:
                sleep_time = (1 - self.tokens) / self.tokens_per_second
                time.sleep(sleep_time)
                self.tokens = 0
                self.last_update = time.time()
            else:
                self.tokens -= 1
                self.last_update = now

class OpenAITranslator(BaseTranslator):
    def __init__(self, service, lang_out, lang_in, model):
        lang_out = 'zh-CN' if lang_out == 'auto' else lang_out
        lang_in = 'en' if lang_in == 'auto' else lang_in
        super().__init__(service, lang_out, lang_in, model)
        self.options = {
            "temperature": 0,  # 随机采样可能会打断公式标记
            "stream": False  # 禁用流式响应
        }
        
        # 从环境变量获取配置
        openai.api_key = os.getenv('OPENAI_API_KEY')
        openai.base_url = os.getenv('OPENAI_BASE_URL')
        self.client = openai.OpenAI()
        
        # 创建速率限制器，每分钟最多60个请求（每秒1个请求）
        self.rate_limiter = RateLimiter(1.0)

    def translate(self, text) -> str:
        if not text.strip():  # 如果文本为空，直接返回
            return text
            
        try:
            # 在发送请求前等待令牌
            self.rate_limiter.acquire()
            
            # 打印请求参数
            request_params = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a professional,authentic machine translation engine.",
                    },
                    {
                        "role": "user",
                        "content": f"Translate the following markdown source text to {self.lang_out}. Keep the formula notation $v*$ unchanged. Output translation directly without any additional text.\nSource Text: {text}\nTranslated Text:",
                    },
                ]
            }
            
            try:
                response = self.client.chat.completions.create(**request_params)
                if hasattr(response, 'choices') and response.choices:
                    result = response.choices[0].message.content.strip()
                    logging.info(f"Translation: {text} -> {result}")
                    return result
                else:
                    logging.error("No choices in response")
                    return text
                    
            except Exception as api_error:
                logging.error(f"OpenAI API Error: {str(api_error)}")
                return text
                
        except Exception as e:
            logging.error(f"Translation error for text '{text[:100]}...': {str(e)}")
            return text  # 如果翻译失败，返回原文


class AzureTranslator(BaseTranslator):
    def __init__(self, service, lang_out, lang_in, model):
        lang_out='zh-Hans' if lang_out=='auto' else lang_out
        lang_in='en' if lang_in=='auto' else lang_in
        super().__init__(service, lang_out, lang_in, model)

        try:
            api_key = os.environ["AZURE_APIKEY"]
            endpoint = os.environ["AZURE_ENDPOINT"]
            region = os.environ["AZURE_REGION"]
        except KeyError as e:
            missing_var = e.args[0]
            raise ValueError(f"The environment variable '{missing_var}' is required but not set.") from e

        credential = AzureKeyCredential(api_key)
        self.client = TextTranslationClient(
            endpoint=endpoint, credential=credential, region=region
        )

        # https://github.com/Azure/azure-sdk-for-python/issues/9422
        logger = logging.getLogger("azure.core.pipeline.policies.http_logging_policy")
        logger.setLevel(logging.WARNING)

    def translate(self, text) -> str:
        response = self.client.translate(
            body=[text],
            from_language=self.lang_in,
            to_language=[self.lang_out],
        )

        translated_text = response[0].translations[0].text
        return translated_text

def test_openai_translator():
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s',
        handlers=[logging.StreamHandler()]
    )

    # 测试文本
    test_texts = [
        "This is a simple test.",
        "The value of $v1$ is proportional to the square of $v2$.",
        """In this paper, we propose a novel approach to machine learning.
        The equation $E = mc^2$ represents the relationship between energy and mass."""
    ]

    # 创建翻译器实例
    translator = OpenAITranslator(
        service="openai",
        lang_out="zh-CN",
        lang_in="en",
        model="gpt-4o-mini"  # 使用配置的模型
    )

    print("\n=== OpenAI Translator Test ===")
    print(f"Base URL: {openai.base_url}")
    print(f"Model: {translator.model}\n")

    # 测试每个文本
    for i, text in enumerate(test_texts, 1):
        print(f"\nTest {i}:")
        print(f"Input:  {text}")
        result = translator.translate(text)
        print(f"Output: {result}")
        print("-" * 50)

def test_concurrent_translation():
    import concurrent.futures
    import time
    from datetime import datetime
    
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(message)s',
        datefmt='%H:%M:%S'
    )

    # 生成大量测试文本
    test_texts = [
        f"Test {i}: This is a sample text with formula $E_{i} = mc^2$ and number {i}."
        for i in range(20)  # 生成20个测试文本
    ]
    test_texts.extend([
        "Complex formula: The integral $\int_{0}^{\infty} e^{-x^2} dx = \frac{\sqrt{\pi}}{2}$",
        "Matrix notation: Let $A = \begin{pmatrix} a & b \\ c & d \end{pmatrix}$ be a matrix",
        "Long text with multiple formulas: Consider $f(x) = ax^2 + bx + c$ where $a \neq 0$",
    ])

    # 创建翻译器实例
    translator = OpenAITranslator(
        service="openai",
        lang_out="zh-CN",
        lang_in="en",
        model="gpt-4o-mini"
    )

    def translate_with_time(text):
        start_time = time.time()
        result = translator.translate(text)
        end_time = time.time()
        return {
            'input': text,
            'output': result,
            'time': end_time - start_time
        }

    print("\n=== Concurrent OpenAI Translator Test ===")
    print(f"Base URL: {openai.base_url}")
    print(f"Model: {translator.model}")
    print(f"Total tasks: {len(test_texts)}")
    print("Starting concurrent translation...\n")

    start_total = time.time()
    results = []
    
    # 使用线程池并发执行翻译
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_text = {executor.submit(translate_with_time, text): text for text in test_texts}
        
        # 收集结果
        for future in concurrent.futures.as_completed(future_to_text):
            try:
                result = future.result()
                results.append(result)
                print(f"\nTask completed ({len(results)}/{len(test_texts)}):")
                print(f"Input:  {result['input'][:50]}...")
                print(f"Output: {result['output'][:50]}...")
                print(f"Time:   {result['time']:.2f}s")
            except Exception as e:
                print(f"Task failed: {str(e)}")

    end_total = time.time()
    total_time = end_total - start_total

    # 打印统计信息
    print("\n=== Translation Statistics ===")
    print(f"Total tasks completed: {len(results)}")
    print(f"Total time: {total_time:.2f}s")
    print(f"Average time per task: {total_time/len(results):.2f}s")
    print(f"Success rate: {len(results)/len(test_texts)*100:.1f}%")

def test_single():
    test_openai_translator()

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--concurrent":
        test_concurrent_translation()
    else:
        test_single()
