# coding: utf-8
import json
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

    def complete_stream(self, messages, tools=None, tool_choice=None, on_content=None):
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.api_key,
        }
        data = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 0.2,
            "stream": True,
        }
        if tools:
            data["tools"] = tools
            data["tool_choice"] = tool_choice or "auto"

        content_parts = []
        tool_calls = {}
        with requests.post(self.api_url, json=data, headers=headers, timeout=120, stream=True) as response:
            response.raise_for_status()
            for raw_line in response.iter_lines(decode_unicode=False):
                if isinstance(raw_line, bytes):
                    raw_line = raw_line.decode("utf-8")
                if not raw_line or not raw_line.startswith("data:"):
                    continue
                payload = raw_line[5:].strip()
                if payload == "[DONE]":
                    break
                event = json.loads(payload)
                choices = event.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content = delta.get("content")
                if content:
                    content_parts.append(content)
                    if on_content:
                        on_content(content)
                for chunk in delta.get("tool_calls") or []:
                    index = chunk.get("index", 0)
                    call = tool_calls.setdefault(index, {
                        "id": "", "type": "function",
                        "function": {"name": "", "arguments": ""},
                    })
                    call["id"] += chunk.get("id") or ""
                    function = chunk.get("function") or {}
                    call["function"]["name"] += function.get("name") or ""
                    call["function"]["arguments"] += function.get("arguments") or ""
        return {"role": "assistant", "content": "".join(content_parts), "tool_calls": list(tool_calls.values())}

    def chat(self, prompt):
        message = self.complete([
            {"role": "system", "content": PromptUtil.load_system_prompt()},
            {"role": "user", "content": prompt},
        ])
        content = message.get("content")
        if not content:
            raise RuntimeError("模型未返回文本内容")
        return content.strip()
