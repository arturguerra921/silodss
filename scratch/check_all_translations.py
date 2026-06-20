import re
import json
import os

locales_dir = r"c:\Users\artur\Documents\GitHub\silodss\src\locales"
en_path = os.path.join(locales_dir, "en.json")
pt_path = os.path.join(locales_dir, "pt.json")

with open(en_path, "r", encoding="utf-8") as f:
    en = json.load(f)

with open(pt_path, "r", encoding="utf-8") as f:
    pt = json.load(f)

results_py = r"c:\Users\artur\Documents\GitHub\silodss\src\view\pages\results.py"
view_py = r"c:\Users\artur\Documents\GitHub\silodss\src\view\view.py"

translate_re = re.compile(r'translate\(\s*["\'](.*?)["\']\s*,\s*lang\s*\)')

keys_found = set()

# Read results.py
with open(results_py, "r", encoding="utf-8") as f:
    content = f.read()
    for match in translate_re.finditer(content):
        keys_found.add(match.group(1))

# Read view.py. We are only interested in the parts related to comparison (stochastic results).
# But let's check ALL translate calls in view.py and results.py to be absolutely complete!
with open(view_py, "r", encoding="utf-8") as f:
    content = f.read()
    for match in translate_re.finditer(content):
        keys_found.add(match.group(1))

# Let's print which ones are missing in en.json and pt.json
missing_en = []
missing_pt = []

for k in sorted(keys_found):
    if k not in en:
        missing_en.append(k)
    if k not in pt:
        missing_pt.append(k)

print(f"Total unique translate keys found: {len(keys_found)}")
print(f"Missing in en.json ({len(missing_en)}):")
for k in missing_en:
    print(f"  - {k.encode('ascii', errors='backslashreplace').decode('ascii')}")

print(f"\nMissing in pt.json ({len(missing_pt)}):")
for k in missing_pt:
    print(f"  - {k.encode('ascii', errors='backslashreplace').decode('ascii')}")
