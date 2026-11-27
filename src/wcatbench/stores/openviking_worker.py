"""Runs inside OpenViking's own virtualenv (openviking 0.4.17.1), never imported by wcatbench.

One JSON request on stdin, one JSON reply on stdout.

It talks to the OpenViking server the adapter started, through the SDK the package ships (`SyncHTTPClient`).
"""

import json
import sys
import time

from openviking import SyncHTTPClient


def main() -> None:
    request = json.loads(sys.stdin.read())
    client = SyncHTTPClient(url=request["url"])
    client.initialize()
    try:
        if request["op"] == "add":
            reply = client.add_resource(path=request["path"], to=request["to"], wait=True)
            client.wait_processed()
            print(json.dumps(reply, ensure_ascii=False, default=str))
        elif request["op"] == "find":
            reply = client.find(query=request["query"], target_uri=request["target"], limit=request["k"])
            print(json.dumps(reply, ensure_ascii=False, default=str))
        elif request["op"] == "read":
            print(json.dumps({"text": client.read(request["uri"])}, ensure_ascii=False))
        elif request["op"] == "dialogue":
            # One conversation: the user's turn and the agent's reply, committed so OpenViking extracts memories.
            client.create_session(session_id=request["session"])
            for message in request["messages"]:
                client.add_message(request["session"], message["role"], content=message["content"])
            reply = client.commit_session(request["session"])
            task_id = (reply.get("result") or reply).get("task_id") if isinstance(reply, dict) else None
            for _ in range(600):
                task = client.get_task(task_id) if task_id else None
                if not task or (task.get("result") or task).get("status") in ("completed", "failed", "cancelled"):
                    break
                time.sleep(2)
            client.wait_processed()
            print(json.dumps({"commit": reply, "task": task}, ensure_ascii=False, default=str))
        elif request["op"] == "ls":
            reply = client.ls(request["uri"], recursive=True)
            print(json.dumps(reply, ensure_ascii=False, default=str))
    finally:
        client.close()


if __name__ == "__main__":
    main()
