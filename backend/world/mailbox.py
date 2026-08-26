"""居民之间的邮件系统：异步、有延迟、会积压。

视野是受限的——居民只看得见和自己同处一区的人。想知道别人在哪、想请人
帮忙、想约个时间，只能写信。这一层就是为了填上那个被刻意留出来的缺口。

## 为什么邮件是异步的

信送到收件箱之后，要等对方**下一次做决策**时才可能被看到，而两次决策之间
隔着一个完整的动作（15~180 游戏分钟）。所以最坏情况下一封信会躺三个小时。

这不是缺陷，是这套设计想要的：如果写信是即时的，将来的"打电话"就没有存在
意义，"该用哪个工具"这个判断也随之消失。**延迟正是让工具选择变得有意义的
那个东西。**

## 并发

收件箱是**跨 agent 的共享可变状态**——两个人同时给第三个人写信就是并发写，
而"读出未读 → 标记已读 → 落盘"更是一个必须原子完成的读-改-写序列。这里
的锁和 ``memory_system`` 那把是同一类：真正保护的是内存里那份共享字典，
文件的完整性另由"临时文件 + 原子替换"保证。
"""

import json
import threading
from pathlib import Path

from config import DATA_DIR

MAILBOX_FILE = DATA_DIR / "mailboxes.json"

# 正文长度上限。信是给模型读的，太长会挤占决策上下文；截断比拒收温和。
BODY_MAX_CHARS = 280
SUBJECT_MAX_CHARS = 60

# 每人收件箱保留的信件数上限，防止长期运行后无限增长。
# 超出时丢弃最旧的**已读**信件，未读的一律保留。
INBOX_LIMIT = 30


class Mailbox:
    def __init__(self, path=MAILBOX_FILE):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._boxes = self._load()

    # --- 对外接口 ---------------------------------------------------

    def send(self, sender, recipient, subject, body, life_day=None, time_text=None):
        """投递一封信，返回投递结果。

        收件人是否读得到、什么时候读到，发信人无从得知——这里只保证信
        进了对方的收件箱。"""
        subject = str(subject or "").strip()[:SUBJECT_MAX_CHARS]
        body = str(body or "").strip()[:BODY_MAX_CHARS]

        letter = {
            "from": sender,
            "subject": subject,
            "body": body,
            "life_day": life_day,
            "time_text": time_text,
            "read": False,
        }

        with self._lock:
            box = self._boxes.setdefault(recipient, [])
            letter["seq"] = self._next_seq(box)
            box.append(letter)
            self._boxes[recipient] = self._prune(box)
            self._save()
            return dict(letter)

    def take_unread(self, agent_name):
        """取出某人的全部未读信件，并**就地标记为已读**。

        命名刻意用 take 而不是 get：它有副作用。取信、标记、落盘必须在
        同一把锁里原子完成，否则同一封信可能被读两次，或者标记丢失。
        """
        with self._lock:
            box = self._boxes.get(agent_name) or []
            unread = [letter for letter in box if not letter.get("read")]
            if not unread:
                return []
            for letter in unread:
                letter["read"] = True
            self._save()
            return [dict(letter) for letter in unread]

    def unread_counts(self):
        """每个人各有多少封未读——用于构造世界快照。

        只读快照，所以调用方拿到的是一份拷贝；它会随世界快照一起进入
        决策上下文，让居民**免费**知道"有信该看了"，而信的内容仍然要
        花一步调工具去取。
        """
        with self._lock:
            return {
                name: sum(1 for letter in box if not letter.get("read"))
                for name, box in self._boxes.items()
            }

    def inbox(self, agent_name, limit=INBOX_LIMIT):
        """某人收件箱的只读视图，供调试与接口展示，不改变已读状态。"""
        with self._lock:
            box = self._boxes.get(agent_name) or []
            return [dict(letter) for letter in box[-limit:]]

    def reset(self):
        """清空所有收件箱——仅供测试与重新开局使用。"""
        with self._lock:
            self._boxes = {}
            self._save()

    # --- 内部实现 ---------------------------------------------------

    def _next_seq(self, box):
        return max((letter.get("seq", 0) for letter in box), default=0) + 1

    def _prune(self, box):
        """超出容量时，只丢弃最旧的已读信件；未读的一封都不能丢。"""
        if len(box) <= INBOX_LIMIT:
            return box
        unread = [letter for letter in box if not letter.get("read")]
        read = [letter for letter in box if letter.get("read")]
        keep_read = read[-(max(0, INBOX_LIMIT - len(unread))):] if read else []
        return sorted(unread + keep_read, key=lambda letter: letter.get("seq", 0))

    def _load(self):
        if not self.path.exists():
            return {}
        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self):
        """临时文件 + 原子替换：崩溃时要么是旧内容，不会是半个文件。
        调用方必须已持有 ``self._lock``。"""
        temp_path = self.path.with_name(f".{self.path.name}.{threading.get_ident()}.tmp")
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(self._boxes, file, ensure_ascii=False, indent=2)
        temp_path.replace(self.path)


# 全局单例，和 persona_store 的用法一致。
mailbox = Mailbox()
