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
            
            response = self.client.chat.completions.create(
                model=self.model,
                **self.options,
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
            
            # 输出原始响应内容
            logging.info(f"OpenAI API Response: {response}")
            
            # 处理不同的响应格式
            if isinstance(response, str):
                logging.info("Response is string type")
                try:
                    import json
                    response_data = json.loads(response)
                    result = response_data.get('choices', [{}])[0].get('message', {}).get('content', '').strip()
                    logging.info(f"Parsed JSON result: {result}")
                    return result
                except (json.JSONDecodeError, KeyError, IndexError) as e:
                    logging.error(f"JSON parsing error: {str(e)}")
                    return response.strip() if response else text
            else:
                logging.info(f"Response type: {type(response)}")
                try:
                    result = response.choices[0].message.content.strip()
                    logging.info(f"Object result: {result}")
                    return result
                except (AttributeError, IndexError) as e:
                    logging.error(f"Object parsing error: {str(e)}")
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
