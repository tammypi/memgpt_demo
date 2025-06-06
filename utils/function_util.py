#coding:utf-8
import re
from memory.current_memory import CurrentMemory 
from memory.long_memory import LongMemory
from utils.chat_util import ChatUtil
from utils.prompt_util import PromptUtil
from itertools import islice

class FunctionUtil(object):
    def __init__(self, c_memory: CurrentMemory, l_memory: LongMemory, llm:ChatUtil):
        self.c_memory = c_memory
        self.l_memory = l_memory
        self.llm = llm

    def current_memory_append(self, text: str) -> str:
        self.c_memory.working_context_append(text)
        return f"[当前记忆上下文追加]: '{text}' 被追加到当前记忆"

    def current_memory_replace(self, old: str, new: str) -> str:
        self.c_memory.working_context_replace(old, new)
        return f"[当前记忆上下文替换]: 对于当前记忆内容，使用 '{new}'替换原'{old}'"

    def memory_clear(self):
        '''
        1.将current_memory fifo队列的前50%，交给大模型总结，总结内容放入working_context
        2.将current_memory fifo队列的前50%，交给大模型总结需要存入长期记忆部分，总结内容放入long_memory messages
        3.移除memory fifo队列的前50%内容
        '''
        queue_len = len(self.c_memory.fifo_queue)
        if queue_len == 0:
            return "[memory_clear]: 当前fifo队列为空，无需驱逐。"

        half_count = queue_len // 2

        # 取前半部分消息，使用islice转换成list
        to_evict_msgs = list(islice(self.c_memory.fifo_queue, half_count))

        # 拼接文本，用于总结
        evict_text = "\n".join(to_evict_msgs)

        # 1. 总结放入当前记忆（working_context）
        prompt_current = (
            "请对下面这段对话内容进行简洁总结，"
            "总结内容适合放入当前对话上下文中，便于短期调用：\n"
            f"{evict_text}"
        )
        summary_current = self.llm.chat(prompt_current)
        self.c_memory.working_context_append(summary_current)

        # 2. 总结需要存入长期记忆的内容
        prompt_long = (
            "请对下面这段对话内容进行提炼和归纳，提取关键信息，"
            "以便写入长期记忆库，方便后续检索：\n"
            f"{evict_text}"
        )
        summary_long = self.llm.chat(prompt_long)
        self.l_memory.upload(summary_long)

        # 3. 从fifo队列移除已驱逐消息，逐条弹出前半部分
        for _ in range(half_count):
            self.c_memory.fifo_queue.popleft()

        return (
            f"[memory_clear]: 已总结前{half_count}条消息。\n"
            f"短期记忆追加内容: {summary_current}\n"
            f"长期记忆写入内容: {summary_long}\n"
            f"剩余fifo队列长度: {len(self.c_memory.fifo_queue)}"
        )

    def long_memory_search(self, keyword: str) -> str:
        results = self.l_memory.search(keyword)
        if not results:
            return f"[长期记忆区搜索结果]: 如下关键字无搜索结果： '{keyword}'"
        return f"[长期记忆区搜索结果] \n" + "\n".join(f" - {r}" for r in results)

    def long_memory_upload(self, keyword: str) -> str:
        self.l_memory.upload(keyword)
        return f"[长期记忆区写入]: 写入： ({len(keyword)} 字符)"

    def current_memory_remove(self, keyword: str) -> str:
        before = len(self.c_memory.working_context)
        self.c_memory.working_context = [s for s in self.c_memory.working_context if keyword not in s]
        after = len(self.c_memory.working_context)
        return f"[当前记忆清理]: 已移除 {before - after} 条包含 '{keyword}' 的记忆"

    def fifo_queue_remove(self, keyword: str) -> str:
        before = len(self.c_memory.fifo_queue)
        self.c_memory.fifo_queue = deque([s for s in self.c_memory.fifo_queue if keyword not in s])
        after = len(self.c_memory.fifo_queue)
        return f"[FIFO 队列清理]: 已移除 {before - after} 条包含 '{keyword}' 的消息"
        
    def parse_and_execute(self, llm_output: str) -> str:
        # 匹配函数名
        func_match = re.search(r'\[tool_name\](.*?)\[/tool_name\]', llm_output, re.DOTALL)
        if not func_match:
            return "错误: 没有[tool_name]"

        func_name = func_match.group(1).strip()

        # 匹配参数列表
        args = re.findall(r'\[tool_param\](.*?)\[/tool_param\]', llm_output, re.DOTALL)
        args = [arg.strip() for arg in args]

        # 获取对应函数
        func = getattr(self, func_name, None)
        if not func:
            return f"错误: 不存在此名称工具： '{func_name}'"

        try:
            result = func(*args)
            self.c_memory.append_message(f"[Dr.Li] 工具调用结果： {result}")
            return result
        except Exception as e:
            return f"工具执行错误： '{func_name}': {e}"

    def parse_anwser(self, llm_output: str) -> str:
        answer_match = re.search(r"\[answer\](.*?)\[/answer\]", llm_output, re.DOTALL)
        answer_text = answer_match.group(1).strip() if answer_match else "[警告] 未包含 [answer] 回复"
        self.c_memory.append_message(f"[Dr.Li] {answer_text}")
        return answer_text

    def ope_llm_respond(self, user_input):
        self.c_memory.append_message(f"[User] {user_input}")
        
        question = PromptUtil.build_question_prompt(user_input, self.c_memory)
        llm_output = self.llm.chat(question)
        answer_rtn = ""
        
        if llm_output.find("[tool_name]") != -1 and llm_output.find("[answer]") != -1 \
        and "long_memory_search" not in llm_output:
            answer = self.parse_anwser(llm_output)
            tool_rtn = self.parse_and_execute(llm_output)
            while "错误" in tool_rtn:
                tool_error_promt = PromptUtil.build_tool_error_prompt(tool_rtn, self.c_memory)
                re_llm_output = self.llm.chat(tool_error_promt)
                tool_rtn = self.parse_and_execute(re_llm_output)
                #print("工具调用出现问题，正在重试...", re_llm_output, tool_rtn)
            answer_rtn =  f"🦷 Dr.Li： {answer} \n🛠️ {tool_rtn}"
        elif llm_output.find("[tool_name]") != -1:
            tool_rtn = self.parse_and_execute(llm_output)
            while "错误" in tool_rtn:
                tool_error_promt = PromptUtil.build_tool_error_prompt(tool_rtn, self.c_memory)
                re_llm_output = self.llm.chat(tool_error_promt)
                tool_rtn = self.parse_and_execute(re_llm_output)
                #print("工具调用出现问题，正在重试...", re_llm_output, tool_rtn)
            tool_rtn_prompt = PromptUtil.build_tool_rtn_prompt(tool_rtn, self.c_memory)
            tool_rtn_answer = self.llm.chat(tool_rtn_prompt)
            self.c_memory.append_message(f"[Dr.Li] {tool_rtn_answer}")
            answer_rtn =  f"🦷 Dr.Li： {tool_rtn_answer} \n🛠️ {tool_rtn}"
        elif llm_output.find("[answer]") != -1:
            answer = self.parse_anwser(llm_output)
            answer_rtn =  f"🦷 Dr.Li： {answer}"
        #判定当前是否有内存压力，如果有，则进行记忆驱逐
        memory_rtn = None
        if self.c_memory.is_current_memory_too_long():
            memory_clear_rtn = self.memory_clear()
            memory_rtn = f"🧠 记忆压力，进行记忆驱逐： {memory_clear_rtn}"
        return answer_rtn, memory_rtn