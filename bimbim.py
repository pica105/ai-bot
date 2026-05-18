import httpx
import os
import uuid
import json
from datetime import datetime
from typing import Optional
from threading import RLock
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT_PATH = "system_prompt.md"

system_prompt = open(SYSTEM_PROMPT_PATH, encoding="utf-8").read()
src_path = "src/"
logo_text = open(f"{src_path}logo_text.md", encoding="utf-8").read()


def get_system_prompt() -> str:
    """Прочитать текущий системный промпт с диска."""
    with open(SYSTEM_PROMPT_PATH, encoding="utf-8") as f:
        return f.read()


def update_system_prompt(text: str) -> None:
    """Сохранить новый системный промпт на диск и обновить глобальную переменную."""
    global system_prompt
    with open(SYSTEM_PROMPT_PATH, "w", encoding="utf-8") as f:
        f.write(text)
    system_prompt = text


# ─────────────────────────────────────────────────────────
# BimBimSession — один диалог с нейронкой
# ─────────────────────────────────────────────────────────
class BimBimSession:
    def __init__(self, session_id: str | None = None,
                 messages: list | None = None,
                 model: str | None = None,
                 api_key: str | None = None,
                 name: str | None = None):
        self.session_id = session_id or str(uuid.uuid4())
        self.messages = messages or [{"role": "system", "content": system_prompt}]
        self.model = model or os.getenv("AI_MODEL", "deepseek/deepseek-v4-flash")
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.name = name or self.session_id[:8]
        self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()

    async def ask(self, client: httpx.AsyncClient, user_text: str) -> Optional[dict]:
        """Отправить сообщение, получить ответ, сохранить в историю."""
        if not user_text.strip():
            return None

        self.messages.append({"role": "user", "content": user_text})
        self.updated_at = datetime.now().isoformat()

        ai_basic_url = os.getenv("AI_BASIC_URL",
                                 "https://openrouter.ai/api/v1/chat/completions")

        payload = {
            "model": self.model,
            "messages": self.messages,
            "session_id": self.session_id,
            "provider": {
                "order": ["Azure"],
                "allow_fallbacks": True,
            },
        }

        try:
            response = await client.post(
                url=ai_basic_url,
                headers={
                    "Authorization": f"Bearer {self.api_key.strip()}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": os.getenv("APP_URL", ""),
                    "X-OpenRouter-Title": os.getenv("APP_TITLE", "BimBim"),
                },
                json=payload,
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()
            reply = data["choices"][0]["message"]["content"]
            self.messages.append({"role": "assistant", "content": reply})
            return data

        except Exception as e:
            self.messages.pop()  # убираем user-сообщение, т.к. ответа нет
            raise e

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "name": self.name,
            "model": self.model,
            "api_key": self.api_key,
            "messages": self.messages,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BimBimSession":
        session = cls.__new__(cls)
        session.session_id = data["session_id"]
        session.name = data.get("name", session.session_id[:8])
        session.model = data.get("model", os.getenv("AI_MODEL", "deepseek/deepseek-v4-flash"))
        session.api_key = data.get("api_key", os.getenv("OPENROUTER_API_KEY", ""))
        session.messages = data["messages"]
        session.created_at = data.get("created_at", datetime.now().isoformat())
        session.updated_at = data.get("updated_at", datetime.now().isoformat())
        return session


# ─────────────────────────────────────────────────────────
# SessionManager — сохраняет/загружает сессии в JSON
# ─────────────────────────────────────────────────────────
class SessionManager:
    def __init__(self, filepath: str = "sessions.json"):
        self.filepath = filepath
        self.current_session_id: str = ""
        self.sessions: dict[str, BimBimSession] = {}
        self._lock = RLock()
        self.load()

    def load(self):
        if not os.path.exists(self.filepath):
            self._ensure_default()
            return
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self.current_session_id = raw.get("current_session", "")
            self.sessions = {}
            for sid, sdata in raw.get("sessions", {}).items():
                self.sessions[sid] = BimBimSession.from_dict(sdata)
            if not self.sessions:
                self._ensure_default()
        except Exception:
            self._ensure_default()

    def _ensure_default(self):
        session = BimBimSession()
        self.sessions[session.session_id] = session
        self.current_session_id = session.session_id
        self.save()

    def save(self):
        with self._lock:
            raw = {
                "current_session": self.current_session_id,
                "sessions": {sid: s.to_dict() for sid, s in self.sessions.items()},
            }
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2)

    @property
    def current(self) -> BimBimSession:
        return self.sessions[self.current_session_id]

    def create(self) -> BimBimSession:
        with self._lock:
            session = BimBimSession()
            self.sessions[session.session_id] = session
            self.current_session_id = session.session_id
            self.save()
        return session

    def switch(self, session_id: str) -> bool:
        if session_id not in self.sessions:
            return False
        with self._lock:
            self.current_session_id = session_id
            self.save()
        return True

    def rename(self, session_id: str, new_name: str) -> bool:
        if session_id not in self.sessions:
            return False
        with self._lock:
            self.sessions[session_id].name = new_name
            self.save()
        return True

    def delete(self, session_id: str) -> bool:
        if session_id not in self.sessions:
            return False
        with self._lock:
            if len(self.sessions) <= 1:
                return False  # нельзя удалить единственную сессию
            del self.sessions[session_id]
            if self.current_session_id == session_id:
                self.current_session_id = next(iter(self.sessions))
            self.save()
        return True

    def list_sessions(self) -> list[tuple[str, str, str, str]]:
        """(полный id, короткий id, имя, created_at)"""
        result = []
        for sid, s in self.sessions.items():
            result.append((sid, sid[:8], s.name, s.created_at))
        return result


# ─────────────────────────────────────────────────────────
# CLI (режим консоли)
# ─────────────────────────────────────────────────────────
async def cli_main():
    sm = SessionManager()

    print(logo_text)
    print(f"  session: {sm.current.session_id[:8]}...  (/new – новый сеанс, /exit – выход)\n")

    async with httpx.AsyncClient() as client:
        while True:
            try:
                user_input = input("\n> ")
            except (EOFError, KeyboardInterrupt):
                print()
                break

            cmd = user_input.strip().lower()

            if cmd == "/exit":
                break

            if cmd == "/new":
                s = sm.create()
                print(f"  ✦ Новая сессия: {s.session_id[:8]}...")
                continue

            if not user_input.strip():
                continue

            try:
                data = await sm.current.ask(client, user_input)
                sm.save()
            except Exception as e:
                print(f"[error] {e}")
                continue

            if data is None:
                continue

            result = data["choices"][0]["message"]["content"]
            print(f"bimbim: {result}")
            print(f"\n  len: {len(result)}")
            print(f"  tokens: {data['usage']['total_tokens']}")
            print(f"  provider: {data.get('provider', '?')}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(cli_main())
