"""Runs inside OpenViking's own virtualenv (openviking 0.4.17.1), never imported by wcatbench.

One JSON request on stdin, one JSON reply on stdout.

It talks to the OpenViking server the adapter started, through the SDK the package ships (`SyncHTTPClient`).
"""

import json
import sys
import time

from openviking import SyncHTTPClient
from openviking_sdk._utils import run_async as run_on_sdk_loop

DONE = ("completed", "failed", "cancelled")


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
            # In 0.4.17.1 the client's commit runs on openviking_cli's event loop while its other calls run on
            # openviking_sdk's, and fails ("bound to a different event loop"). Run it on the SDK's loop.
            reply = run_on_sdk_loop(client._async_client.commit_session(request["session"]))
            task_id = (reply.get("result") or reply).get("task_id") if isinstance(reply, dict) else None
            for _ in range(600):
                task = client.get_task(task_id) if task_id else None
                # The task record carries its own status; a reply wrapped as {"result": task} carries it inside.
                inner = task.get("result") if task and isinstance(task.get("result"), dict) else {}
                status = (task or {}).get("status") if (task or {}).get("status") in DONE else inner.get("status")
                if not task or status in DONE:
                    break
                time.sleep(2)
            client.wait_processed()
            print(json.dumps({"commit": reply, "task": task}, ensure_ascii=False, default=str))
        elif request["op"] == "rm":
            client.rm(request["uri"], recursive=True, wait=True)
            client.wait_processed()
            print(json.dumps({"removed": request["uri"]}))
        elif request["op"] == "ls":
            reply = client.ls(request["uri"], recursive=True)
            print(json.dumps(reply, ensure_ascii=False, default=str))
    finally:
        client.close()


if __name__ == "__main__":
    main()
