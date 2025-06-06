#coding:utf-8
import os
import sqlite3
import time 
import datetime
import jieba
import jieba.analyse
import logging

jieba.setLogLevel(logging.WARNING)
root_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class LongMemory(object):
    def __init__(self, llm):
        self.llm = llm
        self.db_path = os.path.join(root_path, 'data', 'memgpt.db')

    def insert_into_history(self, text: str):
        """记录每一条历史消息"""
        conn = sqlite3.connect(self.db_path)
        insert_sql = "INSERT INTO history(message) VALUES(?)"
        cur = conn.cursor()
        cur.execute(insert_sql, (text,))
        conn.commit()
        conn.close()

    def date_to_timezone_date(self, date):
        t = time.strptime(date, "%Y-%m-%d %H:%M:%S")
        timestamp = int(time.mktime(t))
        dt = datetime.datetime.fromtimestamp(timestamp).replace(tzinfo=datetime.timezone.utc)
        dt8 = dt.astimezone(datetime.timezone(datetime.timedelta(hours=8)))
        date = dt8.strftime("%Y-%m-%d %H:%M:%S")

        return date 

    def retrive_history(self, limit=10):
        """程序启动时用，取出最近10条会话，放入上下文"""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        query_sql = "SELECT create_time,message FROM history ORDER BY create_time DESC LIMIT ?"
        cur.execute(query_sql, (limit,))
        results = [self.date_to_timezone_date(row[0]) + ": " + row[1] for row in cur.fetchall()]
        conn.close()
        return results  

    def upload(self, text: str):
        prompt = f"""
        请帮我对下面这段对话内容进行总结和提炼：
        \"\"\"{text}\"\"\"

        要求：
        1. 用简洁准确的语言总结这段对话中的重要信息和事实。
        2. 只针对重要的实体词（如人名、地点名、事件、专业术语、核心概念）进行关键词扩展，扩展5个以内的同义词或相关词。
        3. 不要扩展普通动词、连接词、描述性词汇（例如“提及”、“涉及”等这类词请忽略）。
        4. 输出格式：
        总结：……
        关键词扩展：关键词1，相关词1，相关词2；关键词2，相关词1，相关词2。
        示例：
        总结：用户张三预约了周一洗牙。
        关键词扩展：张三，姓名，用户；预约，预定，挂号；洗牙，洁牙，口腔清洁。
        请输出符合上述要求的总结和关键词扩展文本。
        """
        response = self.llm.chat(prompt)

        conn = sqlite3.connect(self.db_path)
        insert_sql = "INSERT INTO messages(message) VALUES(?)"
        cur = conn.cursor()
        cur.execute(insert_sql, (response,))
        conn.commit()
        conn.close()

    def extract_tokens(self, keyword, topk=3):
        return jieba.analyse.extract_tags(keyword, topk)

    def parse_expanded_keywords_flat(self, response):
        keywords = []
        lines = response.strip().split('\n')
        for line in lines:
            if '：' in line:
                try:
                    key, values = line.split('：', 1)
                    keywords.append(key.strip())
                    keywords += [w.strip() for w in values.split('，') if w.strip()]
                except Exception:
                    continue
        return list(set(keywords))

    def search(self, keyword, limit=10):
        # 使用 jieba 分词
        keyword = keyword.lower()
        tokens = self.extract_tokens(keyword)

        if len(tokens) == 0:
            return []

        prompt = (
            f"以下是用户输入的关键词：{', '.join(tokens)}。\n"
            f"请为每个关键词扩展出含义接近、适合用于中文语义搜索的3个相关词，"
            f"每个关键词请列出一行，格式为：\n关键词：相关词1，相关词2，相关词3，相关词4，相关词5。"
        )

        response = self.llm.chat(prompt)
        tokens = self.parse_expanded_keywords_flat(response)

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # 构造多个 LIKE 条件：message LIKE '%词1%' OR message LIKE '%词2%' ...
        like_clauses = " OR ".join(["message LIKE ?"] * len(tokens))
        query_sql = f"""
            SELECT create_time, message 
            FROM messages 
            WHERE {like_clauses}
            ORDER BY create_time DESC 
            LIMIT ?
        """
        # 构造参数：每个词都用模糊匹配 + LIMIT 参数
        params = [f"%{token}%" for token in tokens] + [limit]

        cur.execute(query_sql, params)
        results = [
            self.date_to_timezone_date(row[0]) + ": " + row[1]
            for row in cur.fetchall()
        ]

        conn.close()
        return results 