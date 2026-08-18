#!/usr/bin/env python3
"""
CRO Slack Agent — FastAPI entry point.
Receives questions from Zapier (Slack trigger),
dispatches to handlers, sends answer to Zapier (Slack reply).

Zapier Zap 1 (in):
  Trigger: New message in #revops-intel channel
  Action: POST https://<railway-url>/slack/question
  Body: {text, user_id, channel_id, thread_ts, ts}

Zapier Zap 2 (out):
  Trigger: Catch Hook at https://<railway-url>/zap/reply-url
  Action: Slack "Send Channel Message" → reply in thread
  (channel_id + thread_ts from the incoming payload)
"""

import os
import json
import asyncio
import logging
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse
import httpx

logger = logging.getLogger(__name__)

app = FastAPI(title="CRO Agent")

ZAP_REPLY_URL = os.environ.get("ZAP_REPLY_URL", "")
# The Zapier catch hook URL for Zap 2 — stored as Railway
# env var, never in code.

@app.post("/slack/question")
async def receive_question(request: Request,
                           background: BackgroundTasks):
    """
    Zapier Zap 1 posts here. Responds within 3 seconds
    with an ack so Zapier doesn't time out. The real
    answer is sent asynchronously via ZAP_REPLY_URL.
    """
    payload = await request.json()
    text      = (payload.get("text") or "").strip()
    user_id   = payload.get("user_id", "")
    channel   = payload.get("channel_id", "")
    thread_ts = payload.get("thread_ts") or payload.get("ts", "")

    # Guard: warn if both thread_ts and ts are empty
    if not thread_ts:
        logger.warning("[THREAD] empty thread_ts AND empty ts "
                      "— entity context and cache will not be "
                      "retrievable on follow-ups")

    if not text or text.startswith("bot:"):
        # Ignore empty messages and bot's own replies
        return JSONResponse({"ok": True})

    background.add_task(
        process_and_reply, text, user_id, channel, thread_ts
    )
    return JSONResponse({"ok": True, "ack": "received"})

async def send_to_zap(channel: str, thread_ts: str,
                      text: str):
    """POST answer to Zapier catch hook → Slack reply."""
    if not ZAP_REPLY_URL:
        print(f"⚠️  ZAP_REPLY_URL not set — would reply: {text[:100]}")
        return
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(ZAP_REPLY_URL, json={
            "channel_id": channel,
            "thread_ts":  thread_ts,
            "text":       text,
        })

async def process_and_reply(text: str, user_id: str,
                             channel: str, thread_ts: str):
    """
    Full question processing pipeline:
    1. Load conversation history (thread context)
    2. Classify intent → handler
    3. Check if slow → send ack first
    4. Execute handler
    5. Verify answer numbers against tool results
    6. Send reply via Zap 2
    7. Update conversation history
    8. Log unanswerable questions
    """
    from api.router import route_question
    from api.db import get_supabase, load_thread, save_thread

    sb = get_supabase()
    history = load_thread(sb, thread_ts)

    result = await route_question(
        question=text,
        user_id=user_id,
        history=history,
        sb=sb,
        thread_ts=thread_ts,
    )

    if result.get("needs_ack"):
        await send_to_zap(channel, thread_ts,
            "On it — this one needs a moment, I'll reply here.")

    answer = result.get("answer", "")
    await send_to_zap(channel, thread_ts, answer)
    tool_results = result.get("tool_results", {})
    handler_name = result.get("handler_name", "unknown")
    save_thread(sb, thread_ts, channel,
                history, text, answer, tool_results, handler_name)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/admin/refresh-schema")
async def refresh_schema(request: Request):
    """Refresh the schema context cache. Call after
    running discover_properties.py with new properties."""
    from api.schema_context import invalidate_cache
    payload = await request.json()
    # Require a shared secret to prevent abuse
    if payload.get("secret") != os.environ.get("ADMIN_SECRET"):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    invalidate_cache()
    return JSONResponse({"ok": True,
                          "message": "Schema cache cleared"})
