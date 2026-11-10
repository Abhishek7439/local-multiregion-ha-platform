import re
import zlib

pdf_path = "/home/cloud_automator/setu-starter/report/SETU_SWFW_5S_02_Project_Report.pdf"
with open(pdf_path, "rb") as f:
    data = f.read()

# Parse ToUnicode CMaps
cmap_mapping = {}
streams = re.findall(rb"stream[\r\n]+(.*?)[\r\n]+endstream", data, re.DOTALL)
for s in streams:
    try:
        dec = zlib.decompress(s).decode("latin1", errors="ignore")
        if "beginbfrange" in dec or "beginbfchar" in dec:
            # Parse bfchar: <0033> <0050>
            for m in re.finditer(r"<([0-9a-fA-F]{4})>\s*<([0-9a-fA-F]{4})>", dec):
                src = int(m.group(1), 16)
                dst = chr(int(m.group(2), 16))
                cmap_mapping[src] = dst
            # Parse bfrange: <0001> <0005> <0041>
            for m in re.finditer(r"<([0-9a-fA-F]{4})>\s*<([0-9a-fA-F]{4})>\s*<([0-9a-fA-F]{4})>", dec):
                s_code = int(m.group(1), 16)
                e_code = int(m.group(2), 16)
                d_base = int(m.group(3), 16)
                for code in range(s_code, e_code + 1):
                    cmap_mapping[code] = chr(d_base + (code - s_code))
    except Exception:
        pass

print(f"Total CMap entries parsed: {len(cmap_mapping)}")

# Now decode all hex glyphs
all_decoded_chars = []
for s in streams:
    try:
        dec = zlib.decompress(s).decode("latin1", errors="ignore")
        if "BT" in dec and "ET" in dec:
            hex_tokens = re.findall(r"<([0-9a-fA-F]+)>", dec)
            for token in hex_tokens:
                # 4-char chunks
                for i in range(0, len(token), 4):
                    code = int(token[i:i+4], 16)
                    char = cmap_mapping.get(code, "")
                    all_decoded_chars.append(char)
            all_decoded_chars.append(" ")
    except Exception:
        pass

decoded_full_text = "".join(all_decoded_chars)
print(f"Decoded text character count: {len(decoded_full_text)}")

keywords = [
    "Abhishek Kothe",
    "SWFW_5S_02",
    "YCCE",
    "HAProxy",
    "Toxiproxy",
    "3448 ms",
    "149",
    "docs/04-test-evidence/",
    "E1",
    "E2",
    "E3",
    "E4",
    "E5"
]

for kw in keywords:
    found = kw.lower() in decoded_full_text.lower()
    print(f"Contains '{kw}': {found}")

# Verify page count
pages = re.findall(rb"/Type\s*/Page\b", data)
print(f"Total Page Count: {len(pages)}")

# Verify placeholders in HTML source
with open("/home/cloud_automator/setu-starter/report/report.html", "r") as f:
    html = f.read()
placeholders = re.findall(r"(TODO|placeholder|\[SETU_|FIXME)", html, re.IGNORECASE)
print(f"Placeholders in report.html: {len(placeholders)}")
