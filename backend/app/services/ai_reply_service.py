from __future__ import annotations

import asyncio
import logging
import re
from contextlib import suppress
from typing import Any

from app.services.ai_repository import AiRepository, ai_repository
from app.services.ai_secret import SecretDecryptionError, decrypt_secret
from app.services.bot_repository import bot_repository
from app.services.chat_repository import chat_repository
from app.services.chat_service import extract_message_content, extract_user_openid
from app.services.deepseek_client import DeepSeekClient, DeepSeekError, DeepSeekReply
from app.services.group_verification_service import extract_group_openid, extract_member_openid
from app.services.library_delivery_service import is_bot_mentioned
from app.services.qqbot_client import client_manager

logger = logging.getLogger(__name__)
PASSIVE_EXPIRED_CODES = {304103, 40034005, 40034024, 40034128}
MENTION_TAG_PATTERN = re.compile(r"<@!?[^>]+>")
LEADING_MENTION_PATTERN = re.compile(r"^\s*[@＠][^\s，,：:]+[\s，,：:]*")


def _clean_trigger_text(content: str) -> str:
    text = MENTION_TAG_PATTERN.sub(" ", str(content or ""))
    text = LEADING_MENTION_PATTERN.sub("", text, count=1)
    return " ".join(text.split()).strip()


def _error_code(result: dict[str, Any]) -> int:
    data = result.get("data")
    if not isinstance(data, dict):
        return 0
    value = data.get("code", data.get("error_code", 0))
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _error_detail(result: dict[str, Any]) -> str:
    data = result.get("data")
    if isinstance(data, dict):
        return str(data.get("message") or data.get("detail") or data)[:1200]
    return str(data or "QQ 消息发送失败")[:1200]


def _success(result: dict[str, Any]) -> bool:
    return 200 <= int(result.get("status_code") or 500) < 300


def _qq_message_id(result: dict[str, Any]) -> str:
    data = result.get("data")
    return str(data.get("id") or "") if isinstance(data, dict) else ""


class AiReplyService:
    def __init__(self, repository: AiRepository = ai_repository) -> None:
        self.repository = repository
        self._worker: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._worker and not self._worker.done():
            return
        self._stop = asyncio.Event()
        self._worker = asyncio.create_task(self._run(), name="ai-reply-worker")

    async def stop(self) -> None:
        self._stop.set()
        if self._worker:
            self._worker.cancel()
            with suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None

    async def handle_event(self, bot_id: str, event_type: str, payload: dict[str, Any]) -> None:
        profile = self.repository.get_profile(bot_id)
        if not profile.get("enabled"):
            return
        owner_user_id = bot_repository.get_owner_user_id(bot_id)
        if not owner_user_id or not self.repository.credential_status(owner_user_id)["configured"]:
            return
        data = payload.get("d") if isinstance(payload.get("d"), dict) else {}
        message_id = str(data.get("id") or "").strip()
        if not message_id:
            return

        if event_type == "C2C_MESSAGE_CREATE":
            user_openid = extract_user_openid(data)
            if not user_openid:
                return
            self.repository.enqueue_job(
                bot_id=bot_id,
                owner_user_id=owner_user_id,
                user_openid=user_openid,
                trigger_message_id=message_id,
                trigger_content=_clean_trigger_text(extract_message_content(data)),
                channel="c2c",
            )
            return

        if event_type in {"GROUP_AT_MESSAGE_CREATE", "GROUP_MESSAGE_CREATE"}:
            if event_type == "GROUP_MESSAGE_CREATE" and not is_bot_mentioned(payload):
                return
            member_openid = extract_member_openid(payload)
            group_openid = extract_group_openid(payload)
            if not member_openid or not group_openid:
                return
            trigger_content = _clean_trigger_text(extract_message_content(data)) or "你好"
            self.repository.enqueue_job(
                bot_id=bot_id,
                owner_user_id=owner_user_id,
                user_openid=member_openid,
                trigger_message_id=message_id,
                trigger_content=trigger_content,
                channel="group",
                group_openid=group_openid,
            )

    async def _run(self) -> None:
        while not self._stop.is_set():
            job = self.repository.claim_next_job()
            if job is None:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=1.0)
                except TimeoutError:
                    pass
                continue
            try:
                await self._process(job)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("AI reply job crashed: %s", job.get("id"))
                attempts = int(job.get("attempts") or 1)
                self.repository.fail_job(
                    int(job["id"]),
                    "AI 回复任务发生未处理异常",
                    retry=attempts < 2,
                    delay_seconds=5 * attempts,
                )

    async def _process(self, job: dict[str, Any]) -> None:
        job_id = int(job["id"])
        attempts = int(job.get("attempts") or 1)
        profile = self.repository.get_profile(str(job["bot_id"]))
        if not profile.get("enabled"):
            self.repository.fail_job(job_id, "机器人 AI 自动回复已关闭", retry=False)
            return
        encrypted = self.repository.get_encrypted_credential(str(job["owner_user_id"]))
        if not encrypted:
            self.repository.fail_job(job_id, "用户尚未配置 DeepSeek API Key", retry=False)
            return
        try:
            api_key = decrypt_secret(encrypted)
            channel = str(job.get("channel") or "c2c")
            if channel == "group":
                # 群聊暂不复用好友会话上下文；触发内容直接作为本轮用户消息。
                trigger = str(job.get("trigger_content") or "").strip()
                history = [{"role": "user", "content": trigger}] if trigger else []
            else:
                history = chat_repository.list_ai_context(
                    str(job["bot_id"]),
                    str(job["user_openid"]),
                    turns=int(profile.get("context_turns") or 12),
                )
            reply = await DeepSeekClient(api_key).complete(
                profile=profile,
                history=history,
                bot_id=str(job["bot_id"]),
                user_openid=str(job["user_openid"]),
            )
            await self._deliver(job, profile, reply)
        except (DeepSeekError, SecretDecryptionError, ValueError) as exc:
            retry = attempts < 2 and not isinstance(exc, SecretDecryptionError)
            self.repository.fail_job(job_id, str(exc), retry=retry, delay_seconds=5 * attempts)
            if not retry:
                await self._send_failure_message(job, profile, str(exc))

    async def _deliver(self, job: dict[str, Any], profile: dict[str, Any], reply: DeepSeekReply) -> None:
        bot_id = str(job["bot_id"])
        user_openid = str(job["user_openid"])
        trigger_message_id = str(job["trigger_message_id"])
        channel = str(job.get("channel") or "c2c")
        group_openid = str(job.get("group_openid") or "")
        client = await client_manager.get(bot_id)
        quote_requested = str(profile.get("reply_mode") or "auto") in {"auto", "quote"}
        fallback_allowed = str(profile.get("reply_mode") or "auto") == "auto" or bool(profile.get("quote_fallback"))
        base_seq = (
            chat_repository.next_reply_seq(bot_id, trigger_message_id)
            if quote_requested and channel != "group"
            else 1
        )
        latest_qq_message_id = ""
        delivery_modes: list[str] = []
        partial_error = ""
        sent_any = False

        if reply.text:
            result, mode = await self._send_text(
                client=client,
                channel=channel,
                user_openid=user_openid,
                group_openid=group_openid,
                content=reply.text,
                trigger_message_id=trigger_message_id,
                msg_seq=base_seq,
                quote_requested=quote_requested,
                fallback_allowed=fallback_allowed,
            )
            status_code = int(result.get("status_code") or 500)
            success = _success(result)
            latest_qq_message_id = _qq_message_id(result)
            if channel != "group":
                chat_repository.record_outbound(
                    bot_id=bot_id,
                    user_openid=user_openid,
                    content=reply.text,
                    success=success,
                    qq_message_id=latest_qq_message_id,
                    reply_to_msg_id=trigger_message_id if mode == "quote" else "",
                    msg_seq=base_seq if mode == "quote" else None,
                    status_code=status_code,
                    detail="" if success else _error_detail(result),
                )
            if not success:
                raise DeepSeekError(f"QQ 文本回复失败：{_error_detail(result)}")
            sent_any = True
            delivery_modes.append(mode)
            if mode != "quote":
                quote_requested = False

        asset = self._resolve_asset(profile, reply.image_key)
        if asset is not None and channel == "group":
            partial_error = "群聊暂不支持 AI 图片回复"
            asset = None
        if asset is not None:
            upload = await client.upload_c2c_media(user_openid, str(asset["url"]), file_type=1)
            if not _success(upload):
                partial_error = f"图片上传失败：{_error_detail(upload)}"
                chat_repository.record_outbound(
                    bot_id=bot_id,
                    user_openid=user_openid,
                    content=f"[图片] {asset.get('label') or asset.get('key')}",
                    kind="image",
                    success=False,
                    status_code=int(upload.get("status_code") or 500),
                    detail=partial_error,
                )
            else:
                upload_data = upload.get("data") if isinstance(upload.get("data"), dict) else {}
                file_info = str(upload_data.get("file_info") or "")
                media_result, media_mode = await self._send_media(
                    client=client,
                    user_openid=user_openid,
                    file_info=file_info,
                    trigger_message_id=trigger_message_id,
                    msg_seq=base_seq + (1 if reply.text else 0),
                    quote_requested=quote_requested,
                    fallback_allowed=fallback_allowed,
                )
                media_success = _success(media_result)
                media_id = _qq_message_id(media_result)
                if media_id:
                    latest_qq_message_id = media_id
                chat_repository.record_outbound(
                    bot_id=bot_id,
                    user_openid=user_openid,
                    content=f"[图片] {asset.get('label') or asset.get('key')}",
                    kind="image",
                    success=media_success,
                    qq_message_id=media_id,
                    reply_to_msg_id=trigger_message_id if media_mode == "quote" else "",
                    msg_seq=base_seq + (1 if reply.text else 0) if media_mode == "quote" else None,
                    status_code=int(media_result.get("status_code") or 500),
                    detail="" if media_success else _error_detail(media_result),
                )
                if media_success:
                    sent_any = True
                    delivery_modes.append(media_mode)
                else:
                    partial_error = f"图片发送失败：{_error_detail(media_result)}"

        if not sent_any:
            raise DeepSeekError(partial_error or "模型没有生成可发送的消息")
        self.repository.complete_job(
            int(job["id"]),
            output_text=reply.text,
            output_image_key=reply.image_key,
            model=reply.model,
            prompt_tokens=reply.prompt_tokens,
            completion_tokens=reply.completion_tokens,
            total_tokens=reply.total_tokens,
            qq_message_id=latest_qq_message_id,
            delivery_mode="+".join(delivery_modes),
            error=partial_error,
        )

    async def _send_text(
        self,
        *,
        client: Any,
        channel: str = "c2c",
        user_openid: str,
        group_openid: str = "",
        content: str,
        trigger_message_id: str,
        msg_seq: int,
        quote_requested: bool,
        fallback_allowed: bool,
    ) -> tuple[dict[str, Any], str]:
        if channel == "group":
            if not group_openid:
                return {"ok": False, "status_code": 400, "detail": "缺少 group_openid"}, "group"
            # 群聊被动回复必须带 msg_id；过期后无法主动发群消息，故不做 normal 降级。
            result = await client.send_group_text(
                group_openid,
                content,
                msg_id=trigger_message_id or None,
                msg_seq=msg_seq,
                collapse_whitespace=False,
            )
            return result, "group_quote" if trigger_message_id else "group"

        if not quote_requested:
            return await client.send_c2c_text(user_openid, content), "normal"
        result = await client.send_c2c_text(
            user_openid,
            content,
            msg_id=trigger_message_id,
            msg_seq=msg_seq,
        )
        if _success(result):
            return result, "quote"
        if fallback_allowed and _error_code(result) in PASSIVE_EXPIRED_CODES:
            return await client.send_c2c_text(user_openid, content), "normal_fallback"
        return result, "quote"

    async def _send_media(
        self,
        *,
        client: Any,
        user_openid: str,
        file_info: str,
        trigger_message_id: str,
        msg_seq: int,
        quote_requested: bool,
        fallback_allowed: bool,
    ) -> tuple[dict[str, Any], str]:
        if not quote_requested:
            return await client.send_c2c_media(user_openid, file_info), "normal"
        result = await client.send_c2c_media(
            user_openid,
            file_info,
            msg_id=trigger_message_id,
            msg_seq=msg_seq,
        )
        if _success(result):
            return result, "quote"
        if fallback_allowed and _error_code(result) in PASSIVE_EXPIRED_CODES:
            return await client.send_c2c_media(user_openid, file_info), "normal_fallback"
        return result, "quote"

    async def _send_failure_message(self, job: dict[str, Any], profile: dict[str, Any], error: str) -> None:
        content = str(profile.get("failure_message") or "").strip()
        if not content:
            return
        try:
            client = await client_manager.get(str(job["bot_id"]))
            channel = str(job.get("channel") or "c2c")
            result, mode = await self._send_text(
                client=client,
                channel=channel,
                user_openid=str(job["user_openid"]),
                group_openid=str(job.get("group_openid") or ""),
                content=content,
                trigger_message_id=str(job["trigger_message_id"]),
                msg_seq=chat_repository.next_reply_seq(str(job["bot_id"]), str(job["trigger_message_id"])),
                quote_requested=True,
                fallback_allowed=True,
            )
            if channel != "group":
                chat_repository.record_outbound(
                    bot_id=str(job["bot_id"]),
                    user_openid=str(job["user_openid"]),
                    content=content,
                    success=_success(result),
                    qq_message_id=_qq_message_id(result),
                    reply_to_msg_id=str(job["trigger_message_id"]) if mode == "quote" else "",
                    status_code=int(result.get("status_code") or 500),
                    detail=f"AI 回复失败：{error}"[:1200],
                )
        except Exception:
            logger.exception("failed to send AI fallback message for job %s", job.get("id"))

    @staticmethod
    def _resolve_asset(profile: dict[str, Any], image_key: str) -> dict[str, Any] | None:
        if not profile.get("allow_images") or not image_key:
            return None
        assets = profile.get("image_assets")
        if not isinstance(assets, list):
            return None
        for item in assets:
            if isinstance(item, dict) and str(item.get("key") or "") == image_key:
                return item
        return None


ai_reply_service = AiReplyService()
