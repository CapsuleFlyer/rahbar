import glob, subprocess

for f in sorted(glob.glob("corpus/raw/*.pdf")):
    out = subprocess.run(["pdftotext", "-q", f, "-"], capture_output=True).stdout
    text = out.decode("utf-8", errors="ignore").lower()
    print(f"{f}: mind flayer={text.count('mind flayer')}  warlord={text.count('warlord')}  chars={len(text)}")