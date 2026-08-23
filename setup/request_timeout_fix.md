# Request Timeout Fix

## Problem

While running the MultiUAV-Plat server and controller, normal session loading worked, but task-related actions failed with popups like:

```text
request timed out
```

This happened when trying to create tasks or run task-related checks from the controller UI.

## What Was Happening

The server has request logging middleware in:

```text
/Users/pearl/Documents/MultiUAV-Plat/server/api/server.py
```

The middleware tried to log the body of incoming requests:

```python
body_bytes = await request.body()
if body_bytes:
    request_body = json.loads(body_bytes)
```

This is fine for logging, but it caused a problem for `POST` requests.

In FastAPI/Starlette, the request body is like a stream. Once middleware reads it, the later endpoint handler may not be able to read it again unless the body is restored. Task creation and collision checks are `POST` requests, so their endpoints were waiting for request data that had already been consumed.

That made the controller wait until it showed a timeout.

## Why GET Requests Still Worked

Session list/detail requests mostly use `GET`.

`GET` requests usually do not need a JSON request body, so they were not affected in the same way. That is why session loading could work while task creation failed.

## Fix

The fix was to keep the logging behavior, but recreate the request body stream after reading it.

The old suspicious code was kept as a comment for reference:

```python
# if method in self.BODY_METHODS and path not in self.EXCLUDE_PATHS:
#     try:
#         body_bytes = await request.body()
#         if body_bytes:
#             request_body = json.loads(body_bytes)
#     except Exception as e:
#         request_body = {"error": f"Could not parse request body: {str(e)}"}
```

The fixed code reads the body, logs it, then makes the same body available again:

```python
if method in self.BODY_METHODS and path not in self.EXCLUDE_PATHS:
    try:
        body_bytes = await request.body()
        if body_bytes:
            request_body = json.loads(body_bytes)

        async def receive():
            return {
                "type": "http.request",
                "body": body_bytes,
                "more_body": False,
            }

        request = Request(request.scope, receive)
    except Exception as e:
        request_body = {"error": f"Could not parse request body: {str(e)}"}
```

Then the endpoint receives the repaired request:

```python
response = await call_next(request)
```

## Result

After this fix, the controller could create tasks successfully instead of timing out.

## Verification

Server tests were run after the change:

```bash
cd /Users/pearl/Documents/MultiUAV-Plat/server
/Users/pearl/miniforge3/envs/multiuav-server/bin/python -m unittest tests.test_session_request_history tests.test_check_endpoints
```

Result:

```text
51 tests passed
```
