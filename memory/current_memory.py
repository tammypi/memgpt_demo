#coding:utf-8
from collections import deque

class CurrentMemory(object):
    def __init__(self, l_memory, llm, max_tokens=2048, warning_threshold=0.7):
        self.working_context = []
        self.fifo_queue = deque()
        self.max_tokens = max_tokens
        self.warning_tokens = int(warning_threshold * self.max_tokens)
        self.l_memory = l_memory
        self.llm = llm
        #如果持久记忆有数据，加载最近的N条
        history = self.l_memory.retrive_history()
        for item in history:
            self.fifo_queue.append(item)

    def append_message(self, message: str):
        self.fifo_queue.append(message)
        self.l_memory.insert_into_history(message)

    def is_current_memory_too_long(self):
        if self.token_count() > self.warning_tokens:
            return True
            
    def token_count(self) -> int:
        #token长度评估，一个token大概等于4个字母
        total = sum(len(m) for m in self.working_context)
        total += sum(len(m) for m in self.fifo_queue)
        return total // 4

    def working_context_append(self, text: str):
        #文本写入working context
        self.working_context.append(text)

    def working_context_replace(self, old: str, new: str):
        #利用新知识，替换掉掉working context里的旧知识
        self.working_context = [s.replace(old, new) for s in self.working_context]

    def show_context(self) -> str:
        return "\n".join([
            "[Working Context]",
            *self.working_context,
            "[FIFO Queue]",
            *self.fifo_queue
        ]) 
    