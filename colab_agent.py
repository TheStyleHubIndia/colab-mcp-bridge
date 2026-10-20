# Run this in a Google Colab cell. It polls the Render bridge and asks before running every task.
import contextlib
import getpass
import io
import json
import time
import urllib.error
import urllib.request

BRIDGE_URL = "https://colab-mcp-bridge-3jkv.onrender.com"
BRIDGE_TOKEN = getpass.getpass("Render COLAB_BRIDGE_TOKEN: ")

def bridge_request(path, method="GET", payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BRIDGE_URL + path,
        data=data,
        method=method,
        headers={
            "Authorization": "Bearer " + BRIDGE_TOKEN,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))

print("Colab agent connected. Stop this cell with the stop button whenever you want.")
print("Every task's code will be displayed and requires your approval before execution.")

while True:
    try:
        response = bridge_request("/colab/next")
        task = response.get("task")
        if not task:
            time.sleep(5)
            continue

        print("\n" + "=" * 72)
        print("Task:", task.get("description", "Python task"))
        print("Task ID:", task["task_id"])
        print("\nReview this code carefully before approving:\n")
        print(task["code"])
        approval = input("\nType RUN to execute this exact code, or anything else to reject: ").strip()

        if approval != "RUN":
            bridge_request("/colab/result", "POST", {
                "task_id": task["task_id"],
                "status": "rejected",
                "output": "User rejected this task in Colab.",
            })
            print("Task rejected.")
            continue

        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                exec(compile(task["code"], "<mcp-colab-task>", "exec"), globals())
            status = "completed"
        except Exception:
            import traceback
            output.write(traceback.format_exc())
            status = "failed"

        result_text = output.getvalue()[:20000]
        bridge_request("/colab/result", "POST", {
            "task_id": task["task_id"],
            "status": status,
            "output": result_text or "(No text output)",
        })
        print("Task", status + ". Result sent to bridge.")
        print(result_text[:4000])

    except KeyboardInterrupt:
        print("Colab agent stopped.")
        break
    except urllib.error.HTTPError as exc:
        print("HTTP error:", exc.code, exc.read().decode("utf-8", errors="replace")[:1000])
        time.sleep(5)
    except Exception as exc:
        print("Bridge connection error:", repr(exc))
        time.sleep(5)
