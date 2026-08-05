# coding: utf-8
import requests

from utils.prompt_util import PromptUtil


class ChatUtil(object):
    def __init__(self, api_url, api_key, model_name):
        self.api_url = api_url
        self.api_key = api_key
        self.model_name = model_name

    def complete(self, messages, tools=None, tool_choice=None):
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.api_key,
        }
        data = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 0.2,
        }
        if tools:
            data["tools"] = tools
            data["tool_choice"] = tool_choice or "auto"

        response = requests.post(
            self.api_url,
            json=data,
            headers=headers,
            timeout=60,
        )
        response.raise_for_status()
        result = response.json()
        choices = result.get("choices") or []
        if not choices or not choices[0].get("message"):
            raise RuntimeError("模型响应中缺少 choices[0].message")
        return choices[0]["message"]

    def chat(self, prompt):
        message = self.complete([
            {"role": "system", "content": PromptUtil.load_system_prompt()},
            {"role": "user", "content": prompt},
        ])
        content = message.get("content")
        if not content:
            raise RuntimeError("模型未返回文本内容")
        return content.strip()
