#!/usr/bin/env python3
"""原地更新 MinerU 输出的 page_type 字段（用增强后的 classify_all_pages）。

同步更新 middle.json + content_list.json + content_list_v2.json + markdown，
使页面类型标注一致。（page_type 由 middle.json 派生并传播到 content_list
与 markdown，故需一并更新。）

用法（需非沙箱执行，写 ~/.TraceView）:
    python3 scripts/reclassify_page_type.py <hybrid_auto_dir>

例如:
    python3 scripts/reclassify_page_type.py \
        ~/.TraceView/出版学基础正文/mineru/<book>/hybrid_auto
"""
import json
import os
import re
import shutil
import sys
from collections import Counter

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mineru.backend.pipeline.page_type_classifier import classify_all_pages


def _find_file(directory, suffix):
    """在目录顶层查找以 suffix 结尾的文件（兼容 MIME 编码文件名前缀）。"""
    for name in sorted(os.listdir(directory)):
        if name.endswith(suffix) and os.path.isfile(os.path.join(directory, name)):
            return os.path.join(directory, name)
    return None


def _backup(path):
    bak = path + ".page_type_bak"
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
        print(f"[ok] backed up to {bak}")
    else:
        print(f"[warn] backup already exists, skipping: {bak}")


def _update_content_list_v2(clv2_path, pi):
    """根据重分类后的 middle.json 页面类型，同步更新 content_list_v2.json。"""
    with open(clv2_path) as f:
        clv2 = json.load(f)
    if len(clv2) != len(pi):
        print(f"[warn] content_list_v2 页数({len(clv2)}) != middle.json 页数({len(pi)})，跳过")
        return
    changed = 0
    for i, page in enumerate(clv2):
        new_type = pi[i].get("page_type")
        new_secondary = pi[i].get("page_type_secondary")
        if page.get("page_type") != new_type:
            changed += 1
        page["page_type"] = new_type
        if new_secondary:
            page["page_type_secondary"] = new_secondary
        elif "page_type_secondary" in page:
            del page["page_type_secondary"]
        for block in page.get("contents", []):
            block["page_type"] = new_type
            if new_secondary:
                block["page_type_secondary"] = new_secondary
            elif "page_type_secondary" in block:
                del block["page_type_secondary"]
    with open(clv2_path, "w") as f:
        json.dump(clv2, f, ensure_ascii=False)
    print(f"[ok] updated content_list_v2: {clv2_path} ({changed} 页级变化)")


def _update_content_list(cl_path, pi):
    """根据重分类后的 middle.json 页面类型，同步更新 content_list.json（v1，block 级列表）。

    v1 中每个 block 带 page_idx（0-based）与 page_type，按 page_idx 对齐更新。
    """
    with open(cl_path) as f:
        cl = json.load(f)
    if not isinstance(cl, list):
        print(f"[warn] content_list 格式非 block 列表，跳过: {cl_path}")
        return
    changed = 0
    for block in cl:
        if not isinstance(block, dict) or "page_idx" not in block:
            continue
        idx = block["page_idx"]
        if not isinstance(idx, int) or not (0 <= idx < len(pi)):
            continue
        new_type = pi[idx].get("page_type")
        new_secondary = pi[idx].get("page_type_secondary")
        if block.get("page_type") != new_type:
            changed += 1
        block["page_type"] = new_type
        if new_secondary:
            block["page_type_secondary"] = new_secondary
        elif "page_type_secondary" in block:
            del block["page_type_secondary"]
    with open(cl_path, "w") as f:
        json.dump(cl, f, ensure_ascii=False)
    print(f"[ok] updated content_list: {cl_path} ({changed} block 变化)")


def _update_markdown(md_path, pi):
    """根据重分类后的 middle.json 页面类型，同步更新 markdown 的 page_type 注释。

    空白页（无 preproc_blocks）在 markdown 中不生成 page_type 注释，
    注释数可能小于页数；此时按非空白页（按页序）对齐替换。
    """
    with open(md_path) as f:
        md = f.read()
    comments = re.findall(r"<!--\s*page_type:[^>]*-->", md)
    non_blank = [p for p in pi if p.get("preproc_blocks")]
    if len(comments) == len(pi):
        target = pi
    elif len(comments) == len(non_blank):
        target = non_blank
    else:
        print(f"[warn] markdown page_type 注释数({len(comments)}) != middle.json 页数({len(pi)})"
              f" 或非空白页数({len(non_blank)})，跳过")
        return
    new_comments = []
    for p in target:
        t = p.get("page_type")
        s = p.get("page_type_secondary")
        if s:
            new_comments.append(f"<!-- page_type: {t}; page_type_secondary: {s} -->")
        else:
            new_comments.append(f"<!-- page_type: {t} -->")
    it = iter(new_comments)
    md_new = re.sub(r"<!--\s*page_type:[^>]*-->", lambda _m: next(it), md)
    with open(md_path, "w") as f:
        f.write(md_new)
    print(f"[ok] updated markdown: {md_path} ({len(new_comments)} 注释)")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("[error] 请提供 hybrid_auto 目录路径")
        sys.exit(1)
    target = os.path.expanduser(sys.argv[1])
    if not os.path.isdir(target):
        print(f"[error] 目录不存在: {target}")
        sys.exit(1)

    middle = _find_file(target, "_middle.json")
    clv2 = _find_file(target, "_content_list_v2.json")
    # v1 content_list（排除 v2 文件）
    cl = None
    for name in sorted(os.listdir(target)):
        if name.endswith("_content_list.json") and os.path.isfile(os.path.join(target, name)):
            cl = os.path.join(target, name)
            break
    md = _find_file(target, ".md")
    if not middle:
        print(f"[error] 未找到 *_middle.json: {target}")
        sys.exit(1)

    _backup(middle)
    if clv2:
        _backup(clv2)
    if cl:
        _backup(cl)
    if md:
        _backup(md)

    with open(middle) as f:
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

    # 写回 middle.json
    with open(middle, "w") as f:
        json.dump(m, f, ensure_ascii=False)
    print(f"\n[ok] updated middle.json: {middle}")

    if clv2:
        _update_content_list_v2(clv2, pi)
    else:
        print("[warn] 未找到 *_content_list_v2.json，跳过")
    if cl:
        _update_content_list(cl, pi)
    else:
        print("[warn] 未找到 *_content_list.json，跳过")
    if md:
        _update_markdown(md, pi)
    else:
        print("[warn] 未找到 .md，跳过")

    print("\n[done]")


if __name__ == "__main__":
    sys.exit(main())
