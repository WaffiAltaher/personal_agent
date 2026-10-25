# src/agent/tools/ms365_attachments.py
"""
ms365_save_attachment: save one Outlook attachment into the agent folder's outlook/ subfolder (ADR-015).

An agent-side wrapper over the MS365 server's own tools, so the Outlook login stays inside the
server (ADR-005):
  1. `list-mail-attachments` finds the attachment and its real name, inline flag, kind and size;
  2. `download-bytes-to-file` writes its `$value` bytes to a unique temporary name in outlook/
     (the server never overwrites a file, so it can't compare first);
  3. the shared save rules (attachment_save.place_file) give it its final name, or drop it as a
     copy of a file already saved.

The model never sees `download-bytes-to-file` or any path: the loader binds this tool in its
place (ToolWrapper). Every refusal or failure is a string starting with "Error:", and no
failure leaves a temporary file behind.
"""

import json
import uuid
from collections.abc import Mapping

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from agent.tools import attachment_save
from agent.tools.mcp_loader import ToolWrapper

OUTLOOK_FOLDER = "outlook"  # this mailbox's subfolder of the agent folder
LIST_TOOL = "list-mail-attachments"
DOWNLOAD_TOOL = "download-bytes-to-file"
FILE_ATTACHMENT = "#microsoft.graph.fileAttachment"


class SaveOutlookAttachmentInput(BaseModel):
    message_id: str = Field(description="The ID of the Outlook message.")
    attachment_id: str = Field(description="The attachment's ID exactly as list-mail-attachments lists it.")
    file_name: str = Field(
        description=(
            "The attachment's file name (`name`), exactly as list-mail-attachments lists it. "
            "The save is refused if it doesn't match."
        )
    )
    include_inline: bool = Field(
        default=False,
        description="Allow saving an inline image (isInline). Only when the owner asked for the images in the email.",
    )


DESCRIPTION = """
Save one attachment of an Outlook message into the agent folder's outlook/
subfolder (~/Downloads/personal_agent/outlook by default), under the
attachment's own name. The tool chooses the path: it never overwrites a
file, writes `name (1).ext` on a clash, and saves nothing if the same
file is already there. Files over 25 MB, attached emails and cloud links
are refused.

This tool requires human approval before execution (it is a Write action).

On success returns the full path of the saved file and its size.
On failure returns a string beginning with "Error:".
""".strip()


def _text(message: ToolMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(block.get("text", "") if isinstance(block, dict) else str(block) for block in content)


async def _call(tool: BaseTool, args: dict) -> tuple[bool, str]:
    """Call a server tool; (succeeded, its text)."""
    message = await tool.ainvoke({
        "type": "tool_call",
        "id": f"call-{uuid.uuid4().hex}",
        "name": tool.name,
        "args": args,
    })
    return message.status != "error", _text(message)


def _is_file_attachment(attachment: dict) -> bool:
    """A file attachment, not an attached email (itemAttachment) or a cloud link (referenceAttachment).

    The pinned server strips `@odata.type` from its responses, so without it a file attachment
    is the kind that carries `contentBytes`.
    """
    if "@odata.type" in attachment:
        return attachment["@odata.type"] == FILE_ATTACHMENT
    return "contentBytes" in attachment


async def _save(
    tools: Mapping[str, BaseTool],
    message_id: str,
    attachment_id: str,
    file_name: str,
    include_inline: bool,
) -> str:
    listed_ok, listed = await _call(tools[LIST_TOOL], {"messageId": message_id})
    if not listed_ok:
        return f"Error: could not list the attachments of message {message_id}: {listed}"
    matches = [a for a in json.loads(listed).get("value", []) if a.get("id") == attachment_id]
    attachment = matches[0] if matches else {}
    real_name = attachment.get("name") or ""
    found = attachment_save.ListedAttachment(
        name=real_name,
        inline=bool(attachment.get("isInline")),
        size=attachment.get("size"),
        not_a_file=None if _is_file_attachment(attachment) else "an attached email or a cloud link, not a file",
    ) if matches else None
    refusal = attachment_save.check_request(found, attachment_id, file_name, include_inline, LIST_TOOL)
    if refusal:
        return refusal
    temporary = attachment_save.temporary_path(OUTLOOK_FOLDER)
    try:
        downloaded, text = await _call(tools[DOWNLOAD_TOOL], {
            "target": f"/me/messages/{message_id}/attachments/{attachment_id}/$value",
            "outputPath": str(temporary),
        })
        if not downloaded:
            return f"Error: could not download {real_name!r}: {text}"
        return attachment_save.place_file(temporary, real_name, OUTLOOK_FOLDER)
    finally:
        temporary.unlink(missing_ok=True)  # place_file removes it too; this covers every other way out


def build_save_attachment(name: str, tools: Mapping[str, BaseTool]) -> BaseTool:
    """The model-facing save tool, over the server's list-mail-attachments and download-bytes-to-file."""

    async def save_attachment(
        message_id: str, attachment_id: str, file_name: str, include_inline: bool = False
    ) -> str:
        try:
            return await _save(tools, message_id, attachment_id, file_name, include_inline)
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"

    return StructuredTool.from_function(
        coroutine=save_attachment,
        name=name,
        description=DESCRIPTION,
        args_schema=SaveOutlookAttachmentInput,
    )


SAVE_ATTACHMENT = ToolWrapper(name="save_attachment", replaces=DOWNLOAD_TOOL, build=build_save_attachment)
