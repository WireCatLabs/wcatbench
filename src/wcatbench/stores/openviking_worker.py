"""Runs inside OpenViking's own virtualenv (openviking 0.4.17.1), never imported by wcatbench.

One JSON request on stdin, one JSON reply on stdout.

It talks to the OpenViking server the adapter started, through the SDK the package ships (`SyncHTTPClient`).
"""

import json
import sys

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
        elif request["op"] == "ls":
            reply = client.ls(request["uri"], recursive=True)
            print(json.dumps(reply, ensure_ascii=False, default=str))
    finally:
        client.close()


if __name__ == "__main__":
    main()
