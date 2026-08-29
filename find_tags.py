import re
with open('index.html', encoding='utf-8') as f:
    text = f.read()

print('IMAGES:', re.findall(r'<img[^>]+src=['"].*?['"]', text))
print('SCRIPTS:', re.findall(r'<script[^>]+src=['"].*?['"]', text))
print('STYLES:', re.findall(r'<link[^>]+href=['"].*?['"]', text))

