"""Runs inside Mem0 OSS's own virtualenv (mem0ai 2.2.1), never imported by wcatbench: one JSON request on stdin.

Mem0's dependencies would pin versions wcatbench also uses, so the library lives in a separate venv and this file
is its only entry point. The OpenAI key arrives in the environment of this process alone.
"""

import json
import os
import sys

import openai.resources.chat.completions as chat
import openai.resources.embeddings as embeddings
from mem0 import Memory

USAGE = {"chat_calls": 0, "input_tokens": 0, "output_tokens": 0, "embedding_calls": 0, "embedding_tokens": 0}


def counted(original, kind):
    def call(self, *args, **kwargs):
        reply = original(self, *args, **kwargs)
        usage = getattr(reply, "usage", None)
        if kind == "chat":
            USAGE["chat_calls"] += 1
            USAGE["input_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
            USAGE["output_tokens"] += getattr(usage, "completion_tokens", 0) or 0
        else:
            USAGE["embedding_calls"] += 1
            USAGE["embedding_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
        return reply

    return call


# Mem0 reports no spend; counting the SDK's own replies gives the tokens this store cost.
chat.Completions.create = counted(chat.Completions.create, "chat")
embeddings.Embeddings.create = counted(embeddings.Embeddings.create, "embedding")


def memory(root: str, llm: str, embedder: str) -> Memory:
    return Memory.from_config(
        {
            "llm": {"provider": "openai", "config": {"model": llm, "is_reasoning_model": True}},
            "embedder": {"provider": "openai", "config": {"model": embedder}},
            "vector_store": {
                "provider": "qdrant",
                "config": {"path": os.path.join(root, "qdrant"), "collection_name": "rules_trial", "on_disk": True},
            },
            "history_db_path": os.path.join(root, "history.db"),
        }
    )


def main() -> None:
    request = json.loads(sys.stdin.read())
    store = memory(request["root"], request["llm"], request["embedder"])
    user = request["user_id"]
    if request["op"] == "add":
        out = []
        for row in request["records"]:
            reply = store.add(row["text"], user_id=user, metadata={"key": row["key"]}, infer=True)
            out.append({"key": row["key"], "results": reply.get("results", [])})
        print(json.dumps(out, ensure_ascii=False))
    elif request["op"] == "search":
        reply = store.search(request["query"], top_k=request["k"], filters={"user_id": user})
        print(json.dumps(reply.get("results", []), ensure_ascii=False, default=str))
    elif request["op"] == "all":
        reply = store.get_all(filters={"user_id": user}, top_k=10000)
        print(json.dumps(reply.get("results", []), ensure_ascii=False, default=str))


if __name__ == "__main__":
    try:
        main()
    finally:
        with open(os.path.join(json.loads(os.environ["MEM0_REQUEST_ROOT_JSON"]), "usage.jsonl"), "a") as lines:
            lines.write(json.dumps(USAGE) + "\n")
