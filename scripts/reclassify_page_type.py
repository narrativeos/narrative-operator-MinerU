#!/usr/bin/env python3
"""原地更新 middle.json 的 page_type 字段（用增强后的 classify_all_pages）。

用法（需非沙箱执行，写 ~/.TraceView）:
    python3 scripts/reclassify_page_type.py
"""
import json
import os
import shutil
import sys
from collections import Counter

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mineru.backend.pipeline.page_type_classifier import classify_all_pages

TARGET = os.path.expanduser(
    "~/.TraceView/978-7-111-74324-8_1-1_2/mineru/978-7-111-74324-8_1-1_2/hybrid_auto"
)
MIDDLE = os.path.join(TARGET, "978-7-111-74324-8_1-1_2_middle.json")
BAK = MIDDLE + ".page_type_bak"

GT_TOC = set(range(12, 23))


def main():
    if not os.path.exists(MIDDLE):
        print(f"[error] middle.json not found: {MIDDLE}")
        sys.exit(1)

    # 备份
    if not os.path.exists(BAK):
        shutil.copy2(MIDDLE, BAK)
        print(f"[ok] backed up to {BAK}")
    else:
        print(f"[warn] backup already exists, skipping: {BAK}")

    with open(MIDDLE) as f:
        m = json.load(f)
    pi = m["pdf_info"]

    # 记录旧值
    old_types = [p.get("page_type") for p in pi]
    before = Counter(old_types)
    print(f"\n[before] pages: {len(pi)}  distribution: {dict(sorted(before.items()))}")

    classify_all_pages(pi)

    new_types = [p.get("page_type") for p in pi]
    after = Counter(new_types)
    print(f"[after]  pages: {len(pi)}  distribution: {dict(sorted(after.items()))}")

    # 变化明细
    changed = [(i + 1, o, n) for i, (o, n) in enumerate(zip(old_types, new_types)) if o != n]
    print(f"\n[changed] {len(changed)} pages")
    for pg, old, new in changed:
        print(f"  p{pg}: {old} -> {new}")

    # GT TOC check
    toc_pages = {i+1 for i, p in enumerate(pi) if p.get("page_type") == "toc"}
    tp = toc_pages & GT_TOC
    print(f"\n[toc recall] {len(tp)}/{len(GT_TOC)} pages: {sorted(tp)}")
    fp = toc_pages - GT_TOC
    if fp:
        print(f"[toc false+] {sorted(fp)}")

    # 写回
    with open(MIDDLE, "w") as f:
        json.dump(m, f, ensure_ascii=False)
    print(f"\n[ok] updated: {MIDDLE}")


if __name__ == "__main__":
    sys.exit(main())
