from __future__ import annotations

from typing import Any

# The webhook event list mirrors the current QQ management console list supplied
# for this project. Permission labels are guidance only; the official webhook
# subscription selection remains managed in the QQ console.
EVENT_GROUPS: tuple[dict[str, Any], ...] = (
    {
        "key": "c2c",
        "label": "单聊事件",
        "events": (
            {"code": "C2C_MESSAGE_CREATE", "label": "C2C消息事件", "description": "用户向机器人发送单聊消息", "permission": "special"},
            {"code": "FRIEND_ADD", "label": "C2C添加好友", "description": "用户添加机器人好友", "permission": "special"},
            {"code": "FRIEND_DEL", "label": "C2C删除好友", "description": "用户删除机器人好友", "permission": "special"},
            {"code": "C2C_MSG_REJECT", "label": "C2C关闭消息推送", "description": "用户关闭主动消息推送", "permission": "special"},
            {"code": "C2C_MSG_RECEIVE", "label": "C2C打开消息推送", "description": "用户打开主动消息推送", "permission": "special"},
        ),
    },
    {
        "key": "group",
        "label": "群事件",
        "events": (
            {"code": "GROUP_AT_MESSAGE_CREATE", "label": "群消息事件 AT 事件", "description": "群内用户 @ 机器人发送消息", "permission": "special"},
            {"code": "GROUP_MESSAGE_CREATE", "label": "群消息事件创建", "description": "群消息创建事件", "permission": "platform"},
            {"code": "GROUP_ADD_ROBOT", "label": "群添加机器人", "description": "机器人被添加到群聊", "permission": "special"},
            {"code": "GROUP_DEL_ROBOT", "label": "群移除机器人", "description": "机器人被移出群聊", "permission": "special"},
            {"code": "GROUP_MEMBER_ADD", "label": "群用户添加", "description": "用户加入群聊", "permission": "platform"},
            {"code": "GROUP_MEMBER_REMOVE", "label": "群用户移除", "description": "用户离开群聊", "permission": "platform"},
            {"code": "GROUP_JOIN_REQUEST", "label": "用户申请加群", "description": "用户提交入群申请或被自动审批", "permission": "special"},
            {"code": "GROUP_MSG_RECEIVE", "label": "群打开消息推送", "description": "群管理员打开消息推送", "permission": "special"},
            {"code": "GROUP_MSG_REJECT", "label": "群关闭消息推送", "description": "群管理员关闭消息推送", "permission": "special"},
            {"code": "SUBSCRIBE_MESSAGE_STATUS", "label": "订阅消息授权状态变更", "description": "订阅消息授权状态发生变化", "permission": "platform"},
        ),
    },
    {
        "key": "guild",
        "label": "频道事件",
        "events": (
            {"code": "AT_MESSAGE_CREATE", "label": "频道内@机器人的消息事件", "description": "频道内用户 @ 机器人发送消息", "permission": "basic"},
            {"code": "PUBLIC_MESSAGE_DELETE", "label": "撤回频道消息公域事件", "description": "公域频道消息被删除", "permission": "basic"},
            {"code": "DIRECT_MESSAGE_CREATE", "label": "私信创建事件", "description": "用户向机器人发送频道私信", "permission": "special"},
            {"code": "DIRECT_MESSAGE_DELETE", "label": "频道私信删除事件", "description": "频道私信被删除", "permission": "special"},
            {"code": "MESSAGE_REACTION_ADD", "label": "为消息添加表情表态", "description": "用户为频道消息添加表情表态", "permission": "special"},
            {"code": "MESSAGE_REACTION_REMOVE", "label": "为消息删除表情表态", "description": "用户移除频道消息表情表态", "permission": "special"},
            {"code": "MESSAGE_AUDIT_PASS", "label": "频道内消息审核通过", "description": "频道消息审核通过", "permission": "special"},
            {"code": "MESSAGE_AUDIT_REJECT", "label": "频道内消息审核不通过", "description": "频道消息审核不通过", "permission": "special"},
            {"code": "OPEN_FORUM_THREAD_CREATE", "label": "公域论坛事件：用户创建主题", "description": "用户创建论坛主题", "permission": "special"},
            {"code": "OPEN_FORUM_POST_CREATE", "label": "公域论坛事件：用户创建帖子", "description": "用户创建论坛帖子", "permission": "special"},
            {"code": "OPEN_FORUM_REPLY_CREATE", "label": "公域论坛事件：用户回复帖子", "description": "用户回复论坛帖子", "permission": "special"},
            {"code": "OPEN_FORUM_THREAD_UPDATE", "label": "公域论坛事件：用户更新主题", "description": "用户更新论坛主题", "permission": "special"},
            {"code": "OPEN_FORUM_POST_DELETE", "label": "公域论坛事件：用户删除帖子", "description": "用户删除论坛帖子", "permission": "special"},
            {"code": "OPEN_FORUM_REPLY_DELETE", "label": "公域论坛事件：用户回复被删除", "description": "论坛回复被删除", "permission": "special"},
            {"code": "OPEN_FORUM_THREAD_DELETE", "label": "公域论坛事件：用户删除主题", "description": "用户删除论坛主题", "permission": "special"},
            {"code": "GUILD_CREATE", "label": "频道创建事件", "description": "机器人被加入到某个频道", "permission": "basic"},
            {"code": "GUILD_UPDATE", "label": "频道信息变更事件", "description": "频道信息发生变化", "permission": "basic"},
            {"code": "GUILD_DELETE", "label": "频道删除事件", "description": "机器人被移出频道", "permission": "basic"},
            {"code": "CHANNEL_CREATE", "label": "子频道创建事件", "description": "子频道被创建", "permission": "basic"},
            {"code": "CHANNEL_UPDATE", "label": "子频道修改事件", "description": "子频道信息发生变化", "permission": "basic"},
            {"code": "CHANNEL_DELETE", "label": "子频道删除事件", "description": "子频道被删除", "permission": "basic"},
            {"code": "GUILD_MEMBER_ADD", "label": "新成员加入频道事件", "description": "成员加入频道", "permission": "basic"},
            {"code": "GUILD_MEMBER_REMOVE", "label": "频道成员离开频道事件", "description": "成员离开频道", "permission": "basic"},
            {"code": "GUILD_MEMBER_UPDATE", "label": "频道成员信息更新", "description": "频道成员信息发生变化", "permission": "basic"},
            {"code": "AUDIO_START", "label": "音频开始播放事件", "description": "频道音频开始播放", "permission": "special"},
            {"code": "AUDIO_FINISH", "label": "音频播放结束事件", "description": "频道音频播放结束", "permission": "special"},
            {"code": "AUDIO_ON_MIC", "label": "机器人上麦事件", "description": "机器人进入麦位", "permission": "special"},
            {"code": "AUDIO_OFF_MIC", "label": "机器人下麦事件", "description": "机器人离开麦位", "permission": "special"},
        ),
    },
    {
        "key": "interaction",
        "label": "互动事件",
        "events": (
            {"code": "INTERACTION_CREATE", "label": "创建互动事件", "description": "用户触发按钮等互动操作", "permission": "special"},
        ),
    },
)

EVENT_CODE_SET = frozenset(
    event["code"]
    for group in EVENT_GROUPS
    for event in group["events"]
)


def event_catalog_payload() -> list[dict[str, Any]]:
    return [
        {
            "key": group["key"],
            "label": group["label"],
            "events": [dict(event) for event in group["events"]],
        }
        for group in EVENT_GROUPS
    ]
