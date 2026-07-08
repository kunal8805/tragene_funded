import re

with open('c:/codes/tragene funded/admin_routes.py.bak', 'r', encoding='utf-8') as f:
    content = f.read()

# Find all occurrences of @admin_bp.route
pattern = re.compile(r'@admin_bp\.(?:route|errorhandler)\(.*?\)\n(?:@[^\n]+\n)*def ([a-zA-Z0-9_]+)\(', re.MULTILINE)
matches = pattern.findall(content)

with open('c:/codes/tragene funded/scratch/route_list.txt', 'w', encoding='utf-8') as out:
    for match in matches:
        out.write(match + '\n')
