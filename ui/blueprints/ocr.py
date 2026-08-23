import os

from flask import Blueprint, Response, jsonify, request, send_file

from core.comic import IMG_EXTS, get_comic_dir, read_config

from ui.services.ocr_engine import (run_ocr, preload_ocr, unload_ocr, ocr_status,
                                    stream_auto_ocr, stream_auto_ocr_all)
from ui.services.originals import clear_originals, load_originals, save_original, save_originals
from ui.services.translate import translate
from ui.services.markdown_io import export_markdown, DEFAULT_SYSTEM, DEFAULT_INSTRUCTION, DEFAULT_OUTPUT_FORMAT

ocr_bp = Blueprint('ocr', __name__)


def _load_ocr_cfg():
    cfg = read_config()
    return cfg.get('ocr') or {}


@ocr_bp.route('/api/ocr', methods=['POST'])
def ocr_recognize():
    data = request.json or {}
    img = data.get('img')
    if not img:
        return jsonify({'error': 'No image specified'}), 400
    for k in ('x', 'y', 'w', 'h'):
        if k not in data:
            return jsonify({'error': f'Missing box field: {k}'}), 400

    ocr_cfg = _load_ocr_cfg()
    lang = ocr_cfg.get('lang') or 'japan'
    reading_order = ocr_cfg.get('reading_order') or 'auto'

    try:
        original, layout = run_ocr(img, data, lang=lang, reading_order=reading_order)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    try:
        translated = translate(original, ocr_cfg.get('translate') or {})
    except Exception as e:
        # OCR 成功但翻譯失敗：仍回傳原文，前端可寫回標號並提示使用者
        return jsonify({'status': 'ok', 'original': original, 'translated': '', 'translate_error': str(e), 'layout': layout})

    return jsonify({'status': 'ok', 'original': original, 'translated': translated, 'layout': layout})


@ocr_bp.route('/api/ocr/preload', methods=['POST'])
def ocr_preload():
    ocr_cfg = _load_ocr_cfg()
    lang = ocr_cfg.get('lang') or 'japan'
    try:
        state = preload_ocr(lang)
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500
    return jsonify({'status': 'ok', 'ocr': state})


@ocr_bp.route('/api/ocr/status', methods=['GET'])
def ocr_status_route():
    return jsonify({'status': 'ok', 'ocr': ocr_status()})


@ocr_bp.route('/api/ocr/unload', methods=['POST'])
def ocr_unload():
    return jsonify({'status': 'ok', 'ocr': unload_ocr()})


@ocr_bp.route('/api/ocr/auto', methods=['POST'])
def ocr_auto():
    """Streaming auto-OCR.

    Default (no `img`, or `all:true`) processes EVERY image in the comic folder
    and writes each page's markers back to the comic TXT + originals cache as it
    goes. Pass `img` to restrict to a single page. Emits NDJSON events."""
    data = request.json or {}
    ocr_cfg = _load_ocr_cfg()
    lang = ocr_cfg.get('lang') or 'japan'
    reading_order = ocr_cfg.get('reading_order') or 'auto'
    translate_cfg = ocr_cfg.get('translate') or {}
    debug_ocr = bool(read_config().get('debug_ocr', False))

    img = data.get('img')
    do_all = bool(data.get('all')) or not img

    if do_all:
        files = sorted(
            f for f in os.listdir(get_comic_dir())
            if os.path.isfile(os.path.join(get_comic_dir(), f))
            and os.path.splitext(f)[1].lower() in IMG_EXTS
        )
        if not files:
            return jsonify({'error': '資料夾中找不到圖片'}), 400

        def gen():
            yield from stream_auto_ocr_all(files, lang=lang, reading_order=reading_order,
                                          translate_cfg=translate_cfg, debug=debug_ocr)
    else:
        if not img:
            return jsonify({'error': 'No image specified'}), 400

        def gen():
            yield from stream_auto_ocr(img, lang=lang, reading_order=reading_order,
                                       translate_cfg=translate_cfg, debug=debug_ocr)

    return Response(gen(), mimetype='application/x-ndjson')


@ocr_bp.route('/api/originals', methods=['GET', 'POST'])
def originals():
    if request.method == 'GET':
        img = request.args.get('img')
        if not img:
            return jsonify({'error': 'No image specified'}), 400
        return jsonify({'originals': load_originals(img)})

    # POST
    data = request.json or {}
    img = data.get('img')
    if not img:
        return jsonify({'error': 'Missing params'}), 400
    if data.get('clear'):
        try:
            clear_originals(img)
            return jsonify({'status': 'ok', 'originals': {}})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    marker_id = data.get('id')
    original = data.get('original')
    if marker_id is None:
        return jsonify({'error': 'Missing params'}), 400
    try:
        originals = save_original(img, marker_id, original)
        return jsonify({'status': 'ok', 'originals': originals})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@ocr_bp.route('/api/markdown/defaults', methods=['GET'])
def markdown_defaults():
    """Return default prompt values for the export modal."""
    return jsonify({
        'system': DEFAULT_SYSTEM,
        'instruction': DEFAULT_INSTRUCTION,
        'output_format': DEFAULT_OUTPUT_FORMAT,
    })


@ocr_bp.route('/api/markdown/export', methods=['POST'])
def markdown_export():
    """Export originals as markdown for translation.
    
    Request body:
        img: image name (optional, if not provided exports all pages)
        system: system prompt (optional)
        instruction: translation instruction (optional)
        output_format: output format instruction (optional)
    
    Returns:
        Markdown file download
    """
    data = request.json or {}
    img = data.get('img')
    
    system = data.get('system') or DEFAULT_SYSTEM
    instruction = data.get('instruction') or DEFAULT_INSTRUCTION
    output_format = data.get('output_format') or DEFAULT_OUTPUT_FORMAT
    
    if img:
        # Single page
        originals = load_originals(img)
        if not originals:
            return jsonify({'error': '此頁沒有原文數據'}), 400
        md_content = export_markdown(
            originals,
            system=system,
            instruction=instruction,
            output_format=output_format,
            page_name=img
        )
        return jsonify({'status': 'ok', 'markdown': md_content, 'filename': f'{img}.md'})
    else:
        # All pages
        from core.comic import get_comic_dir
        import json
        
        all_originals = {}
        for filename in sorted(os.listdir(get_comic_dir())):
            if os.path.isfile(os.path.join(get_comic_dir(), filename)):
                ext = os.path.splitext(filename)[1].lower()
                if ext in IMG_EXTS:
                    origs = load_originals(filename)
                    if origs:
                        all_originals[filename] = origs
        
        if not all_originals:
            return jsonify({'error': '沒有原文數據'}), 400
        
        # Generate markdown for all pages
        lines = []
        lines.append("---")
        lines.append(f"system: {system}")
        lines.append(f"instruction: {instruction}")
        lines.append(f"output_format: {output_format}")
        lines.append("export_all: true")
        lines.append("---")
        lines.append("")
        
        for page_name in sorted(all_originals.keys()):
            lines.append(f"# {page_name}")
            lines.append("")
            for marker_id in sorted(all_originals[page_name].keys()):
                text = all_originals[page_name][marker_id]
                lines.append(f"[{marker_id}]")
                lines.append(f"原文: {text}")
                lines.append("")
        
        md_content = "\n".join(lines)
        return jsonify({'status': 'ok', 'markdown': md_content, 'filename': 'all_pages.md'})


@ocr_bp.route('/api/markdown/import', methods=['POST'])
def markdown_import():
    """Import translations from markdown.
    
    Request body:
        img: image name
        markdown: markdown content with translations
    
    Returns:
        Updated dialogues
    """
    data = request.json or {}
    img = data.get('img')
    markdown_content = data.get('markdown')
    
    if not img:
        return jsonify({'error': 'No image specified'}), 400
    if not markdown_content:
        return jsonify({'error': 'No markdown content'}), 400
    
    # Parse translations and originals
    from ui.services.markdown_io import extract_items
    originals_map, translations = extract_items(markdown_content)
    if not translations and not originals_map:
        return jsonify({'error': '無法解析譯文，請確認格式正確'}), 400
    
    # Load existing dialogues
    from core.comic import get_txt_file, parse_all_comics, save_all_comics
    all_data = parse_all_comics(get_txt_file())
    dialogues = all_data.get(img, [])
    
    # Update dialogues with translations
    updated_count = 0
    for d in dialogues:
        marker_id = d.get('id')
        if marker_id in translations:
            d['text'] = translations[marker_id]
            updated_count += 1
    
    # Save originals
    if originals_map:
        save_originals(img, originals_map)
    
    if updated_count == 0 and not originals_map:
        return jsonify({'error': '沒有匹配的標號'}), 400
    
    # Save
    all_data[img] = dialogues
    save_all_comics(get_txt_file(), all_data)
    
    return jsonify({
        'status': 'ok',
        'updated': updated_count,
        'dialogues': dialogues
    })


@ocr_bp.route('/api/markdown/import_all', methods=['POST'])
def markdown_import_all():
    """Import translations from markdown for all pages.
    
    Request body:
        markdown: markdown content with translations (multi-page format)
    
    Returns:
        Summary of updates
    """
    data = request.json or {}
    markdown_content = data.get('markdown')
    
    if not markdown_content:
        return jsonify({'error': 'No markdown content'}), 400
    
    # Parse multi-page markdown
    import re
    
    # Remove frontmatter
    _, body = markdown_content.split("---", 2)[-1].rsplit("---", 1) if markdown_content.count("---") >= 2 else ("", markdown_content)
    
    # Split by page headers (with or without # prefix, any image extension)
    page_blocks = re.split(r'^#? *(\S+\.(?:png|jpg|jpeg|webp|bmp|gif|tif|tiff|avif))$', body, flags=re.MULTILINE)
    
    from core.comic import get_txt_file, parse_all_comics, save_all_comics
    from ui.services.markdown_io import extract_items
    all_data = parse_all_comics(get_txt_file())
    
    results = {}
    has_any = False
    
    # page_blocks[0] is before first header (empty), then alternating: page_name, content
    for i in range(1, len(page_blocks), 2):
        page_name = page_blocks[i].strip()
        content = page_blocks[i + 1] if i + 1 < len(page_blocks) else ""
        
        originals_map, translations = extract_items(content)
        if originals_map or translations:
            has_any = True
        
        dialogues = all_data.get(page_name, [])
        updated_count = 0
        for d in dialogues:
            marker_id = d.get('id')
            if marker_id in translations:
                d['text'] = translations[marker_id]
                updated_count += 1
        
        # Save originals for this page
        if originals_map:
            save_originals(page_name, originals_map)
        
        if updated_count > 0:
            all_data[page_name] = dialogues
            results[page_name] = updated_count
    
    if not has_any:
        return jsonify({'error': '沒有匹配的譯文'}), 400
    
    save_all_comics(get_txt_file(), all_data)
    
    return jsonify({
        'status': 'ok',
        'results': results,
        'total_pages': len(results),
        'total_updated': sum(results.values())
    })
