# src/agent/tools/attachment_save.py
"""
The save rules for email attachments, shared by every mailbox (spec: The save rules).

A save goes into one mailbox's subfolder of the agent folder (`gmail/`, `outlook/`):

  - the file is named with the attachment's own name, reduced to a bare name
  - the final path always resolves inside the mailbox's subfolder
  - identical bytes already saved in the same name family (`invoice.pdf`,
    `invoice (1).pdf`, ...) write nothing: "Already saved as <path>"
  - otherwise the first free name in the family is used; nothing is ever overwritten
  - files over 25 MB are refused

Two entry points: `save_bytes` for a mailbox that hands over the bytes (Gmail), and
`place_file` for one that has already downloaded into `temporary_path(...)` (Outlook's
server writes the file itself). Both return a plain string and never raise: success names
the full path and the size, every refusal or failure starts with "Error:".
"""

import filecmp
import itertools
import os
import re
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path

from agent.config import settings

MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
FALLBACK_NAME = "attachment"
_TEMPORARY_PREFIX = ".saving-"


def typeable_name(file_name: str) -> str:
    """
    The name in Unicode compatibility form (NFKC) with every whitespace run one plain space: a
    non-breaking space, which looks like a space in the Approval prompt, becomes a space.
    """
    return " ".join(unicodedata.normalize("NFKC", file_name).split())


def bare_name(file_name: str) -> str:
    """The attachment's typeable name with directory parts and path separators stripped."""
    name = typeable_name(file_name).replace("\x00", "").replace("\\", "/").split("/")[-1].strip()
    if not name.strip("."):
        return FALLBACK_NAME
    return name


def mailbox_folder(mailbox: str) -> Path:
    """The mailbox's subfolder of the agent folder, created (with the agent folder) when missing."""
    folder = Path(settings.agent_folder).expanduser() / mailbox
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def temporary_path(mailbox: str) -> Path:
    """A unique, not yet existing path inside the mailbox's subfolder to download into."""
    return mailbox_folder(mailbox) / f"{_TEMPORARY_PREFIX}{uuid.uuid4().hex}.part"


def check_listed_size(file_name: str, size: int | None) -> str | None:
    """The refusal for a size the mailbox lists before downloading, or None when it's within the cap."""
    if size is not None and size > MAX_ATTACHMENT_BYTES:
        return _too_large(file_name, size)
    return None


@dataclass(frozen=True)
class ListedAttachment:
    """An attachment as its mailbox lists it, for checking a save request before downloading."""

    name: str  # the attachment's real file name
    inline: bool
    size: int | None  # None when the mailbox doesn't list it
    not_a_file: str | None = None  # what it is instead (an attached email, a cloud link), if not a file


def check_request(
    attachment: ListedAttachment | None,
    attachment_id: str,
    file_name: str,
    include_inline: bool,
    listed_by: str,
) -> str | None:
    """
    The refusal for a save request, or None when it may go ahead: the attachment must exist
    (`None` when the message has none with that ID), `file_name` must be its real name, it must
    be a file, an inline one needs `include_inline`, and its listed size must be within the cap.
    `listed_by` names the tool that lists the attachments, for the name-mismatch refusal.
    """
    if attachment is None:
        return f"Error: the message has no attachment with ID {attachment_id}."
    real_name = attachment.name
    if typeable_name(file_name) != typeable_name(real_name):
        return (
            f"Error: file_name {file_name!r} does not match the attachment's real name {real_name!r}. "
            f"Use the exact name {listed_by} lists."
        )
    if attachment.not_a_file:
        return f"Error: {real_name!r} is {attachment.not_a_file}; only file attachments can be saved."
    if attachment.inline and not include_inline:
        return (
            f"Error: {real_name!r} is an inline image in the message body, not a file attachment. "
            "Pass include_inline=true only if the owner asked for the images in the email."
        )
    return check_listed_size(real_name, attachment.size)


def save_bytes(data: bytes, file_name: str, mailbox: str) -> str:
    """Save `data` under the attachment's name in the mailbox's subfolder."""
    refusal = check_listed_size(file_name, len(data))
    if refusal:
        return refusal
    try:
        temporary = temporary_path(mailbox)
        with open(temporary, "xb") as f:
            f.write(data)
    except OSError as e:
        return f"Error: could not save {file_name!r}: {e}"
    return place_file(temporary, file_name, mailbox)


def place_file(temporary: Path, file_name: str, mailbox: str) -> str:
    """
    Give an already-downloaded file in the mailbox's subfolder its final name.

    The temporary file is always removed: on an identical copy nothing new is kept, and on
    any failure no stray file is left behind.
    """
    temporary = Path(temporary)
    try:
        folder = mailbox_folder(mailbox)
        if temporary.resolve().parent != folder.resolve():
            return f"Error: {temporary} is not inside the {mailbox} folder."
        try:
            size = temporary.stat().st_size
            if size > MAX_ATTACHMENT_BYTES:
                return _too_large(file_name, size)
            name = bare_name(file_name)
            existing = _identical_in_family(temporary, folder, name)
            if existing is not None:
                return f"Already saved as {existing} ({size} bytes); nothing was written."
            for candidate in _family_names(name):
                target = folder / candidate
                if not target.resolve().is_relative_to(folder.resolve()):
                    return f"Error: {file_name!r} would be saved outside the {mailbox} folder."
                try:
                    os.link(temporary, target)  # fails on an existing name: never overwrites
                except FileExistsError:
                    continue
                return f"Saved {target} ({size} bytes)."
        finally:
            temporary.unlink(missing_ok=True)
    except OSError as e:
        return f"Error: could not save {file_name!r}: {e}"
    return f"Error: could not save {file_name!r}."  # unreachable: the name family never runs out


def _too_large(file_name: str, size: int) -> str:
    return (
        f"Error: {file_name!r} is too large to save ({size} bytes; "
        f"the limit is {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB)."
    )


def _family_names(name: str):
    """`invoice.pdf`, then `invoice (1).pdf`, `invoice (2).pdf`, ..."""
    stem, suffix = _split(name)
    yield name
    for n in itertools.count(1):
        yield f"{stem} ({n}){suffix}"


def _identical_in_family(temporary: Path, folder: Path, name: str) -> Path | None:
    """The first file in the name family with exactly the temporary file's bytes, if any."""
    stem, suffix = _split(name)
    family = re.compile(rf"{re.escape(stem)}( \(\d+\))?{re.escape(suffix)}")
    size = temporary.stat().st_size
    for path in sorted(folder.iterdir(), key=lambda p: (len(p.name), p.name)):
        if (
            family.fullmatch(path.name)
            and path.is_file()
            and path.stat().st_size == size
            and filecmp.cmp(path, temporary, shallow=False)
        ):
            return path
    return None


def _split(name: str) -> tuple[str, str]:
    path = Path(name)
    return path.stem, path.suffix
