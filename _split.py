import os

SRC = 'ui/app.py'
content = open(SRC, encoding='utf-8').read()

marker = 'HTML_TEMPLATE = r"""'
start = content.index(marker) + len(marker)
end_marker = '"""\n\n\ndef start_background_tasks'
end = content.index(end_marker, start)
template = content[start:end]  # starts with '\n'
assert template[0] == '\n', 'unexpected template start'
template = template[1:]

style_open = template.index('<style>')
style_close = template.index('</style>') + len('</style>')
script_open = template.index('<script>')
script_close = template.index('</script>') + len('</script>')

style_block = template[style_open:style_close]
script_block = template[script_open:script_close]

css = template[style_open + len('<style>'):style_close - len('</style>')].strip('\n')
js = template[script_open + len('<script>'):script_close - len('</script>')]

css_link = "<link rel=\"stylesheet\" href=\"{{ url_for('static', filename='css/style.css') }}\">"
init_script = (
    "<script>\n"
    "  window.__INIT__ = {\n"
    "    images: {{ images|tojson }},\n"
    "    mode: {{ mode|tojson }},\n"
    "    initial_img: {{ initial_img|tojson }},\n"
    "    initial_dpi: {{ initial_dpi|tojson }},\n"
    "    initial_scale: {{ initial_scale|tojson }}\n"
    "  };\n"
    "</script>\n"
    "<script src=\"{{ url_for('static', filename='js/app.js') }}\"></script>"
)

html = template.replace(style_block, css_link)
html = html.replace(script_block, init_script)

js_old = (
    'const images = {{ images|tojson }};\n'
    'const INIT_MODE = {{ mode|tojson }};\n'
    'const INIT_IMG = {{ initial_img|tojson }};\n'
    'const INIT_DPI = {{ initial_dpi|tojson }};\n'
    'const INIT_SCALE = {{ initial_scale|tojson }};'
)
js_new = 'const { images, mode: INIT_MODE, initial_img: INIT_IMG, initial_dpi: INIT_DPI, initial_scale: INIT_SCALE } = window.__INIT__;'
assert js_old in js, 'JS jinja block not found'
js = js.replace(js_old, js_new)
js = js.strip('\n') + '\n'

assert '{{' not in js, 'leftover jinja in js'
assert '{%' not in js, 'leftover jinja in js'

os.makedirs('ui/templates', exist_ok=True)
os.makedirs('ui/static/css', exist_ok=True)
os.makedirs('ui/static/js', exist_ok=True)

open('ui/templates/index.html', 'w', encoding='utf-8').write(html)
open('ui/static/css/style.css', 'w', encoding='utf-8').write(css)
open('ui/static/js/app.js', 'w', encoding='utf-8').write(js)

print('CSS chars:', len(css))
print('JS chars:', len(js))
print('HTML chars:', len(html))
print('OK')
