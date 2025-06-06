#coding:utf-8
import requests
import urllib3
from utils.prompt_util import PromptUtil

urllib3.disable_warnings()

class ChatUtil(object):
    def __init__(self, api_url, api_key, model_name):
        self.api_url = api_url
        self.api_key = api_key
        self.model_name = model_name

    def chat(self, prompt):
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.api_key
        }
        data = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": PromptUtil.load_system_prompt()},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
        }

        try:
            response = requests.post(self.api_url, json=data, headers=headers, timeout=15, verify=False)
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content'].strip()
        except Exception as e:
            return f"[LLM Error]: {e}"
