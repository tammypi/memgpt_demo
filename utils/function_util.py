# coding: utf-8
import json
from itertools import islice

from memory.current_memory import CurrentMemory
from memory.long_memory import LongMemory
from utils.chat_util import ChatUtil
from utils.prompt_util import PromptUtil


class FunctionUtil(object):
    MAX_TOOL_ROUNDS = 6

    TOOL_SCHEMAS = [
        {
            "type": "function",
            "function": {
                "name": "current_memory_append",
                "description": "将用户明确提供的重要个人信息、口腔健康事实或预约信息写入当前记忆。内容必须语义完整、自足。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "包含人物、时间、状态等完整信息的记忆文本"},
                    },
                    "required": ["text"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "current_memory_replace",
                "description": "当用户纠正或更新当前记忆中的事实时，用完整的新事实替换旧事实。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "old": {"type": "string", "description": "需要被替换的原记忆内容"},
                        "new": {"type": "string", "description": "更新后的完整事实"},
                    },
                    "required": ["old", "new"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "long_memory_search",
                "description": "搜索 SQLite 长期记忆。当用户询问过去的事实，而当前记忆没有可靠答案，或用户质疑记忆时必须调用。不得猜测。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string", "description": "适合检索历史信息的核心关键词或短语"},
                    },
                    "required": ["keyword"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "long_memory_upload",
                "description": "将已经闭合的诊疗事件、预约结果或需要跨会话保留的重要事实归纳后写入长期记忆。不要重复写入。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "可独立理解、便于以后检索的完整事件摘要"},
                    },
                    "required": ["text"],
                    "additionalProperties": False,
                },
            },
        },
    ]

    def __init__(self, c_memory: CurrentMemory, l_memory: LongMemory, llm: ChatUtil):
        self.c_memory = c_memory
        self.l_memory = l_memory
        self.llm = llm
        self.tool_handlers = {
            "current_memory_append": self.current_memory_append,
            "current_memory_replace": self.current_memory_replace,
            "long_memory_search": self.long_memory_search,
            "long_memory_upload": self.long_memory_upload,
        }

    def current_memory_append(self, text: str) -> str:
        self.c_memory.working_context_append(text)
        return f"已写入当前记忆：{text}"

    def current_memory_replace(self, old: str, new: str) -> str:
        self.c_memory.working_context_replace(old, new)
        return f"已将当前记忆“{old}”更新为“{new}”"

    def memory_clear(self):
        queue_len = len(self.c_memory.fifo_queue)
        if queue_len == 0:
            return "当前会话队列为空，无需整理。"

        half_count = max(1, queue_len // 2)
        to_evict_msgs = list(islice(self.c_memory.fifo_queue, half_count))
        evict_text = "\n".join(to_evict_msgs)
        summary_current = self.llm.chat(
            "请简洁总结以下对话中仍对当前诊疗有用的事实，不要虚构：\n" + evict_text
        )
        self.c_memory.working_context_append(summary_current)
        self.l_memory.upload(evict_text)
        for _ in range(half_count):
            self.c_memory.fifo_queue.popleft()
        return f"已整理 {half_count} 条较早消息并归档重要事实。"

    def long_memory_search(self, keyword: str) -> str:
        results = self.l_memory.search(keyword)
        if not results:
            return f"没有搜索到与“{keyword}”相关的长期记忆。请如实告诉用户目前没有记录。"
        return "长期记忆搜索结果：\n" + "\n".join(f"- {result}" for result in results)

    def long_memory_upload(self, text: str) -> str:
        existing = self.l_memory.search(text, limit=5)
        if any(text in result for result in existing):
            return "长期记忆中已存在相同内容，本次未重复写入。"
        self.l_memory.upload(text)
        return f"已写入长期记忆：{text}"

    def execute_tool_call(self, tool_call):
        function = tool_call.get("function") or {}
        name = function.get("name", "")
        handler = self.tool_handlers.get(name)
        if not handler:
            return json.dumps({"ok": False, "error": f"未知工具：{name}"}, ensure_ascii=False)
        try:
            arguments = json.loads(function.get("arguments") or "{}")
            if not isinstance(arguments, dict):
                raise ValueError("工具参数必须是 JSON 对象")
            result = handler(**arguments)
            return json.dumps({"ok": True, "result": result}, ensure_ascii=False)
        except Exception as error:
            return json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False)

    @staticmethod
    def assistant_tool_message(message):
        return {
            "role": "assistant",
            "content": message.get("content"),
            "tool_calls": message.get("tool_calls", []),
        }

    def ope_llm_respond(self, user_input):
        self.c_memory.append_message(f"[User] {user_input}")
        messages = [
            {"role": "system", "content": PromptUtil.build_agent_prompt(self.c_memory)},
            {"role": "user", "content": user_input},
        ]

        answer = ""
        for _ in range(self.MAX_TOOL_ROUNDS):
            message = self.llm.complete(messages, tools=self.TOOL_SCHEMAS)
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                answer = (message.get("content") or "").strip()
                break

            messages.append(self.assistant_tool_message(message))
            for tool_call in tool_calls:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id"),
                    "name": (tool_call.get("function") or {}).get("name"),
                    "content": self.execute_tool_call(tool_call),
                })
        else:
            raise RuntimeError("模型连续调用工具次数过多，未能生成最终回答")

        if not answer:
            raise RuntimeError("模型没有生成最终回答")
        self.c_memory.append_message(f"[Dr.Li] {answer}")

        memory_rtn = None
        if self.c_memory.is_current_memory_too_long():
            memory_rtn = self.memory_clear()
        return answer, memory_rtn

    def ope_llm_respond_stream(self, user_input, on_delta):
        self.c_memory.append_message(f"[User] {user_input}")
        messages = [
            {"role": "system", "content": PromptUtil.build_agent_prompt(self.c_memory)},
            {"role": "user", "content": user_input},
        ]

        answer = ""
        for _ in range(self.MAX_TOOL_ROUNDS):
            round_parts = []
            message = self.llm.complete_stream(
                messages,
                tools=self.TOOL_SCHEMAS,
                on_content=lambda part: (round_parts.append(part), on_delta(part)),
            )
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                answer = "".join(round_parts).strip()
                break

            messages.append(self.assistant_tool_message(message))
            for tool_call in tool_calls:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id"),
                    "name": (tool_call.get("function") or {}).get("name"),
                    "content": self.execute_tool_call(tool_call),
                })
        else:
            raise RuntimeError("模型连续调用工具次数过多，未能生成最终回答")

        if not answer:
            raise RuntimeError("模型没有生成最终回答")
        self.c_memory.append_message(f"[Dr.Li] {answer}")
        memory_rtn = self.memory_clear() if self.c_memory.is_current_memory_too_long() else None
        return answer, memory_rtn
