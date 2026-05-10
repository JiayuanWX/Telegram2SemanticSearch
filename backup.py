import argparse
import asyncio
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.types import Message, MessageMediaDocument, MessageMediaPhoto, MessageMediaWebPage


@dataclass
class SenderInfo:
    id: Optional[int]
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]


def parse_sender(message: Message) -> SenderInfo:
    sender = getattr(message, "sender", None)
    if sender is not None:
        return SenderInfo(
            id=getattr(sender, "id", None),
            username=getattr(sender, "username", None),
            first_name=getattr(sender, "first_name", None),
            last_name=getattr(sender, "last_name", None),
        )

    from_id = getattr(message, "from_id", None)
    if from_id is not None:
        if hasattr(from_id, "user_id"):
            return SenderInfo(id=from_id.user_id, username=None, first_name=None, last_name=None)
        return SenderInfo(id=from_id, username=None, first_name=None, last_name=None)

    return SenderInfo(id=None, username=None, first_name=None, last_name=None)


def parse_reactions(message: Message) -> Optional[Dict[str, Any]]:
    reactions = getattr(message, "reactions", None)
    if not reactions:
        return None

    def serialize_reaction_value(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        if hasattr(value, "emoticon"):
            return getattr(value, "emoticon")
        if hasattr(value, "text"):
            return getattr(value, "text")
        return str(value)

    result_counts = getattr(reactions, "results", []) or []
    total = getattr(reactions, "count", getattr(reactions, "total", None))
    if total is None:
        total = sum(getattr(item, "count", 0) for item in result_counts)

    return {
        "total": total,
        "items": [
            {
                "emoji": serialize_reaction_value(getattr(item, "reaction", None)),
                "count": getattr(item, "count", None),
                "is_chosen": getattr(item, "chosen_order", None) is not None,
            }
            for item in result_counts
        ],
    }


def parse_media(message: Message) -> Optional[Dict[str, Any]]:
    media = getattr(message, "media", None)
    if media is None:
        return None

    media_info: Dict[str, Any] = {"type": type(media).__name__}

    if isinstance(media, MessageMediaPhoto):
        photo = getattr(media, "photo", None)
        if photo is not None:
            media_info.update(
                {
                    "photo_id": getattr(photo, "id", None),
                    "sizes": [
                        {
                            "type": getattr(size, "type", None),
                            "width": getattr(size, "w", None),
                            "height": getattr(size, "h", None),
                            "file_size": getattr(size, "size", None),
                        }
                        for size in getattr(photo, "sizes", [])
                    ],
                }
            )

    elif isinstance(media, MessageMediaDocument):
        document = getattr(media, "document", None)
        if document is not None:
            media_info.update(
                {
                    "document_id": getattr(document, "id", None),
                    "mime_type": getattr(document, "mime_type", None),
                    "file_name": getattr(document, "attributes", None),
                    "size": getattr(document, "size", None),
                }
            )
            if getattr(document, "attributes", None):
                media_info["attributes"] = [
                    {"type": type(attr).__name__, **{"file_name": getattr(attr, "file_name", None)}}
                    for attr in getattr(document, "attributes", [])
                ]

    elif isinstance(media, MessageMediaWebPage):
        webpage = getattr(media, "webpage", None)
        if webpage is not None:
            media_info.update(
                {
                    "url": getattr(webpage, "url", None),
                    "display_url": getattr(webpage, "display_url", None),
                    "type_name": getattr(webpage, "type", None),
                    "title": getattr(webpage, "title", None),
                    "description": getattr(webpage, "description", None),
                }
            )

    return media_info


def message_to_dict(message: Message, topic_ids: set) -> Dict[str, Any]:
    sender = parse_sender(message)
    
    # Extraer topic_id
    reply_to = getattr(message, "reply_to", None)
    topic_id = None
    reply_to_msg_id = None
    
    if reply_to:
        # En grupos con temas, reply_to_top_id suele ser el ID del tema
        top_id = getattr(reply_to, "reply_to_top_id", None)
        # Si tiene un top_id y está en nuestra lista de tópicos, es el topic_id
        if top_id in topic_ids:
            topic_id = top_id
            # El reply_to_msg_id sería el mensaje específico al que responde dentro del tema
            reply_to_msg_id = getattr(reply_to, "reply_to_msg_id", None)
            # Si el reply_to_msg_id es el mismo que el topic_id, es el mensaje inicial del tema
            if reply_to_msg_id == topic_id:
                reply_to_msg_id = None
        else:
            # Si no hay top_id o no está en la lista de tópicos, tratamos el reply_to_msg_id como respuesta normal
            reply_to_msg_id = getattr(reply_to, "reply_to_msg_id", None)
            # Algunos mensajes pueden tener reply_to_msg_id que resulta ser un topic_id
            if reply_to_msg_id in topic_ids:
                topic_id = reply_to_msg_id
                reply_to_msg_id = None

    result: Dict[str, Any] = {
        "id": message.id,
        "date": message.date.isoformat() if getattr(message, "date", None) else None,
        "sender": asdict(sender),
        "text": message.message,
        "reply_to": reply_to_msg_id,
        "topic_id": topic_id,
        "reactions": parse_reactions(message),
        "media": parse_media(message),
        "entities": [
            {"type": type(entity).__name__, "offset": entity.offset, "length": entity.length}
            for entity in (getattr(message, "entities", []) or [])
        ],
    }

    if getattr(message, "forward", None):
        result["forwarded_from_user_id"] = getattr(message.forward, "from_id", None)

    return result


async def backup_group_messages(
    api_id: int,
    api_hash: str,
    phone: str,
    group: str,
    output_file: str,
    target_topic_id: Optional[int] = None,
) -> None:
    client = TelegramClient("tg_backup_session", api_id, api_hash)
    await client.start(phone=phone)

    entity = await client.get_entity(group)
    print(f"Connected. Fetching messages from: {getattr(entity, 'title', getattr(entity, 'username', str(entity)))}")

    # Obtener IDs de tópicos (mensajes de servicio que crean tópicos)
    topic_ids = set()
    async for msg in client.iter_messages(entity):
        if msg.action and hasattr(msg.action, "title"):
            topic_ids.add(msg.id)
    
    messages: List[Dict[str, Any]] = []
    async for message in client.iter_messages(entity, reverse=True):
        if not isinstance(message, Message):
            continue
            
        msg_dict = message_to_dict(message, topic_ids)
        
        # Filtrar por tópico si se especifica
        if target_topic_id is not None:
            if msg_dict["topic_id"] != target_topic_id and msg_dict["id"] != target_topic_id:
                continue
                
        messages.append(msg_dict)

    print(f"Fetched {len(messages)} messages. Writing to {output_file}.")

    with open(output_file, "w", encoding="utf-8") as fp:
        json.dump(messages, fp, ensure_ascii=False, indent=2)

    print("Backup complete.")


def load_config() -> Dict[str, Any]:
    load_dotenv()
    group_val = os.environ["GROUP"]
    try:
        # Intenta convertir a int si empieza con '-' o es puramente numérico
        if group_val.startswith("-") or group_val.isdigit():
            group = int(group_val)
        else:
            group = group_val
    except ValueError:
        group = group_val

    return {
        "api_id": int(os.environ["API_ID"]),
        "api_hash": os.environ["API_HASH"],
        "phone": os.environ["PHONE"],
        "group": group,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Backup Telegram group messages to JSON.")
    parser.add_argument(
        "--output",
        default="backup.json",
        help="Path to the output JSON file (default: backup.json)",
    )
    parser.add_argument(
        "--topic",
        type=int,
        help="ID of the topic to backup",
    )
    args = parser.parse_args()

    config = load_config()
    output_file = args.output

    try:
        asyncio.run(backup_group_messages(
            config["api_id"], 
            config["api_hash"], 
            config["phone"], 
            config["group"], 
            output_file,
            target_topic_id=args.topic
        ))
    except KeyboardInterrupt:
        print("Backup interrupted.")
        raise


if __name__ == "__main__":
    main()
