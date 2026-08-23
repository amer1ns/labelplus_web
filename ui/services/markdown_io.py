"""Markdown I/O for translation workflow.

Export original texts (from OCR) and import translated texts in a structured
markdown format. The format embeds system/instruction prompts so the LLM
receives full context in one shot.

Format (export):
    ---#已擴寫
    system: 你是翻譯助手，為讀者翻譯漫畫，腦袋要富有形象力，有時候會有浪漫場景
    instruction: 將以下日文（每個編號裡每行內容可能顛倒）翻譯成台灣繁體中文，不要解釋
    output_format: 保持編號，只輸出譯文
    ---

    [1]
    原文: 今日はいい天気です

    [2]
    原文: 明日も晴れます

Format (import - LLM response):
    [1]
    原文: 今日はいい天気です
    譯文: 今天天氣很好

    [2]
    原文: 明日も晴れます
    譯文: 明天也會是晴天
"""

import re
from typing import List, Dict, Optional, Tuple


# Default prompts
DEFAULT_SYSTEM = """你是一名專業的日文漫畫翻譯助手，負責將日文漫畫、同人誌、角色對話與旁白翻譯成自然的台灣繁體中文。

翻譯時要充分理解上下文、人物關係、說話者的性格、情緒與語氣。不要只逐字直譯，要在不改變原意的前提下，使用符合台灣中文習慣的自然表達。

漫畫中的對話要像真人說話，根據角色身份與情緒調整措辭，例如傲嬌、撒嬌、害羞、憤怒、驚訝、無奈、調侃、冷淡、溫柔等語氣都要盡可能保留下來。

遇到曖昧、浪漫、親密或情緒強烈的場景，要理解原文的語境與氣氛，讓中文自然地呈現原作的情緒，但不要自行增加原文沒有的內容。

對擬聲詞、感嘆詞、口語、省略句、粗俗用語、雙關、委婉說法等，要根據漫畫情境選擇自然的台灣繁體中文表達。

專有名詞、人名、稱呼與固定用語應保持前後一致。

最重要的是：忠實原意、自然流暢、符合人物語氣，不要擅自改寫劇情或添加原文不存在的資訊。"""

DEFAULT_INSTRUCTION = """將以下日文翻譯成自然、流暢的台灣繁體中文。

注意：
1. 每個編號代表一段獨立內容（一個編號內原文內容間空格应當忽略），但同一編號內的日文各行可能因 OCR 或排版原因而順序顛倒，請根據上下文判斷正確語序後再翻譯。
2. 不要逐字硬翻，要理解整句與上下文後翻譯。
3. 保留原文的語氣、情緒、人物個性與說話方式。
4. 對口語、縮略語、擬聲詞、感嘆詞與漫畫用語，優先使用自然的台灣繁體中文。
5. 不要自行補充原文沒有的資訊。
6. 不要解釋翻譯過程，不要分析日文文法，只輸出翻譯結果。

以下是要翻譯的日文："""

DEFAULT_OUTPUT_FORMAT = """
保持原本的編號與編號順序。每個編號只輸出對應的台灣繁體中文譯文。譯文不要輸出日文原文、解釋、註解、翻譯說明或其他額外內容。
示例:

003.png
[1]
原文: なんだ ここに居たのか
譯文: 怎麼，原來你在這裡啊

"""

def export_markdown(
    originals: Dict[int, str],
    system: str = DEFAULT_SYSTEM,
    instruction: str = DEFAULT_INSTRUCTION,
    output_format: str = DEFAULT_OUTPUT_FORMAT,
    page_name: str = "",
) -> str:
    """Generate markdown from original texts.
    
    Args:
        originals: {marker_id: original_text}
        system: System prompt
        instruction: Translation instruction
        output_format: Output format instruction
        page_name: Optional page name for metadata
    
    Returns:
        Markdown string
    """
    lines = []
    
    # YAML frontmatter
    lines.append("---")
    lines.append(f"system: {system}")
    lines.append(f"instruction: {instruction}")
    lines.append(f"output_format: {output_format}")
    lines.append("---")
    lines.append("")
    
    # Page header (consistent with import_all format)
    if page_name:
        lines.append(f"# {page_name}")
        lines.append("")
    
    # Content - sorted by marker_id
    for marker_id in sorted(originals.keys()):
        text = originals[marker_id]
        lines.append(f"[{marker_id}]")
        lines.append(f"原文: {text}")
        lines.append("")
    
    return "\n".join(lines)


def parse_frontmatter(content: str) -> Tuple[Dict[str, str], str]:
    """Parse YAML frontmatter and return (metadata, body).

    Multi-line values (e.g. system/instruction prompts) are preserved by
    detecting known top-level keys and accumulating subsequent lines until
    the next known key is encountered.

    Returns:
        (metadata_dict, body_without_frontmatter)
    """
    metadata = {}
    body = content

    # Check for frontmatter
    if content.startswith("---"):
        # Find closing ---
        end_idx = content.find("---", 3)
        if end_idx != -1:
            frontmatter = content[3:end_idx].strip()
            body = content[end_idx + 3:].strip()

            _KNOWN_KEYS = {'system', 'instruction', 'output_format', 'export_all'}
            current_key = None
            current_lines = []

            for line in frontmatter.split("\n"):
                if ":" in line:
                    key, _, value = line.partition(":")
                    key = key.strip()
                    if key in _KNOWN_KEYS:
                        # Save previous key
                        if current_key is not None:
                            metadata[current_key] = "\n".join(current_lines).strip()
                        current_key = key
                        current_lines = [value.strip()]
                    elif current_key is not None:
                        # Line contains ':' but isn't a known key → part of multi-line value
                        current_lines.append(line)
                elif current_key is not None:
                    # Continuation line (empty or no ':')
                    current_lines.append(line)

            # Save last key
            if current_key is not None:
                metadata[current_key] = "\n".join(current_lines).strip()

    return metadata, body


def parse_markdown(content: str) -> List[Dict[str, str]]:
    """Parse markdown content into list of {id, original, translation}.
    
    Handles both export format (原文 only) and import format (原文 + 譯文).
    
    Returns:
        List of {id: str, original: str, translation: str}
    """
    # Remove frontmatter if present
    _, body = parse_frontmatter(content)
    
    items = []
    current_id = None
    current_original = ""
    current_translation = ""
    
    for line in body.split("\n"):
        line = line.strip()
        
        # Match [N] pattern
        id_match = re.match(r"^\[(\d+)\]$", line)
        if id_match:
            # Save previous item
            if current_id is not None:
                items.append({
                    "id": current_id,
                    "original": current_original,
                    "translation": current_translation,
                })
            current_id = id_match.group(1)
            current_original = ""
            current_translation = ""
            continue
        
        # Match 原文: pattern
        if line.startswith("原文:") or line.startswith("原文："):
            _, _, value = line.partition(":")
            if not value:
                _, _, value = line.partition("：")
            current_original = value.strip()
            continue
        
        # Match 譯文: pattern
        if line.startswith("譯文:") or line.startswith("譯文："):
            _, _, value = line.partition(":")
            if not value:
                _, _, value = line.partition("：")
            current_translation = value.strip()
            continue
    
    # Save last item
    if current_id is not None:
        items.append({
            "id": current_id,
            "original": current_original,
            "translation": current_translation,
        })
    
    return items


def extract_translations(content: str) -> Dict[int, str]:
    """Extract translations from imported markdown.
    
    Returns:
        {marker_id: translation_text}
    """
    items = parse_markdown(content)
    result = {}
    for item in items:
        try:
            marker_id = int(item["id"])
            translation = item["translation"]
            if translation:
                result[marker_id] = translation
        except (ValueError, KeyError):
            continue
    return result


def extract_items(content: str) -> tuple:
    """Extract both originals and translations from imported markdown.
    
    Returns:
        ({marker_id: original_text}, {marker_id: translation_text})
    """
    items = parse_markdown(content)
    originals = {}
    translations = {}
    for item in items:
        try:
            marker_id = int(item["id"])
            orig = (item.get("original") or "").strip()
            trans = (item.get("translation") or "").strip()
            if orig:
                originals[marker_id] = orig
            if trans:
                translations[marker_id] = trans
        except (ValueError, KeyError):
            continue
    return originals, translations


def format_for_llm(content: str, metadata: Optional[Dict[str, str]] = None) -> str:
    """Format markdown for LLM input.
    
    Combines system prompt and instruction into a system message format,
    with the content as user message.
    
    Returns:
        Formatted string for LLM
    """
    if metadata is None:
        metadata, _ = parse_frontmatter(content)
    
    system = metadata.get("system", DEFAULT_SYSTEM)
    instruction = metadata.get("instruction", DEFAULT_INSTRUCTION)
    output_format = metadata.get("output_format", DEFAULT_OUTPUT_FORMAT)
    
    
    # Build system prompt
    system_prompt = f"{system}\n\n{output_format}\n\n{instruction}"
    
    return system_prompt
