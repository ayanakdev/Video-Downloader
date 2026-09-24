"""Display sizes and produce portable download filenames."""
import re


def format_size(size):
    if size < 1_000_000:
        return f"{size / 1_000:,.1f} KB"
    return f"{size / 1_000_000:,.2f} MB"


def download_filename(title, kind):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "", title).strip().rstrip(". ")
    # Accept a pasted filename without doubling its extension.
    name = re.sub(r"\.(mp3|mp4)$", "", name, flags=re.IGNORECASE).rstrip(". ")
    name = name[:120].rstrip(". ") or "GetVideo"
    if re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", name, re.IGNORECASE):
        name = "GetVideo-" + name
    return f"{name}.{kind.lower()}"
