#coding:utf-8
import os
import sys 

root_path = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, root_path)

from utils.chat_util import ChatUtil
from utils.function_util import FunctionUtil
from memory.long_memory import LongMemory
from memory.current_memory import CurrentMemory

class MemGpt(object):
    def __init__(self, api_url, api_key, model_name):
        self.llm = ChatUtil(api_url, api_key, model_name) 
        self.long_memory = LongMemory(self.llm)
        self.current_memory = CurrentMemory(self.long_memory, self.llm)
        self.functions = FunctionUtil(self.current_memory, self.long_memory, self.llm)

    def print_separator(self):
        print("=" * 50)

    def respond(self, user_input):
        return self.functions.ope_llm_respond(user_input)

    def run(self):
        print("欢迎来到 🦷 Dr.Li 的 AI 口腔诊所！我可以记住你说过的事，也能帮你回忆过去 🤖")
        print("请输入内容（输入 'exit' 退出）：")
        self.print_separator()

        while True:
            user_input = input("🧑 你：").strip()
            print()
            if user_input.lower() in {"exit", "quit"}:
                break
            
            answer, memory_rtn = self.respond(user_input)
            print(answer)
            if memory_rtn:
                print(memory_rtn)
            print()

if __name__ == '__main__':
    api_url = os.getenv("LLM_API_URL", "https://api.moonshot.cn/v1/chat/completions")
    api_key = os.getenv("LLM_API_KEY", "")
    model_name = os.getenv("LLM_MODEL", "moonshot-v1-auto")

    if not api_key:
        raise SystemExit("请先设置环境变量 LLM_API_KEY")

    memgpt = MemGpt(api_url, api_key, model_name)
    memgpt.run()
