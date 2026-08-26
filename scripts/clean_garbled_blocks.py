#!/usr/bin/env python3
r"""清理 MinerU 输出中的"纯符号乱码" block。

某些 PDF 的装饰性符号（页边花体、分隔符等）会被 OCR 误识别为
`! " # $ %` 之类的纯符号串，并被布局模型标成 title，最终在 markdown 中
呈现为 `## ! " # $ %`（横向）或竖排的 `# !` / `"` / `#` / `\$` / `%`（纵向）。

本脚本按"纯符号"特征识别这些乱码 block，并同步更新
middle.json + content_list_v2.json + markdown（按统一 block_id 跨文件定位）。

用法（需非沙箱执行，写 ~/.TraceView）:
    python3 scripts/clean_garbled_blocks.py <hybrid_auto_dir>
"""
import json
import os
import re
import shutil
import sys


def _find_file(directory, suffix):
    """在目录顶层查找以 suffix 结尾的文件（兼容 MIME 编码文件名前缀）。"""
    for name in sorted(os.listdir(directory)):
        if name.endswith(suffix) and os.path.isfile(os.path.join(directory, name)):
            return os.path.join(directory, name)
    return None


def _backup(path):
    bak = path + ".garbled_bak"
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
        print(f"[ok] backed up to {bak}")
    else:
        print(f"[warn] backup already exists, skipping: {bak}")


def _block_text(block):
    return "".join(
        str(span.get("content", ""))
        for line in block.get("lines", [])
        for span in line.get("spans", [])
    )


def _is_garbled(text):
    """纯符号乱码：无中文、无字母数字、去空白后长度 >= 3。

    真正的文本 block 必含中文/字母/数字，故该规则不会误删正常内容。
    """
    s = text.strip()
    if len(s) < 3:
        return False
    if any("\u4e00" <= c <= "\u9fff" for c in s):
        return False
    if any(c.isalnum() for c in s):
        return False
    return True


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
    md = _find_file(target, ".md")
    if not middle:
        print(f"[error] 未找到 *_middle.json: {target}")
        sys.exit(1)

    _backup(middle)
    if clv2:
        _backup(clv2)
    if md:
        _backup(md)

    # 1. 从 middle.json 识别并删除乱码 block，收集 block_id
    with open(middle) as f:
        m = json.load(f)
    pi = m["pdf_info"]
    garbled_ids = set()
    removed_middle = 0
    for idx, p in enumerate(pi):
        kept = []
        for b in p.get("preproc_blocks", []):
            txt = _block_text(b)
            if _is_garbled(txt):
                bid = b.get("block_id")
                if bid:
                    garbled_ids.add(bid)
                removed_middle += 1
                print(f"  [middle] p{idx} [{b.get('type')}] {repr(txt.strip()[:24])} id={bid}")
            else:
                kept.append(b)
        p["preproc_blocks"] = kept
    with open(middle, "w") as f:
        json.dump(m, f, ensure_ascii=False)
    print(f"[ok] middle.json: 删除 {removed_middle} 个乱码 block")

    # 2. 从 content_list_v2.json 按 block_id 删除对应 block
    if clv2:
        with open(clv2) as f:
            clv2_data = json.load(f)
        removed_clv2 = 0
        for page in clv2_data:
            contents = page.get("contents", [])
            kept = [c for c in contents if c.get("block_id") not in garbled_ids]
            removed_clv2 += len(contents) - len(kept)
            page["contents"] = kept
        with open(clv2, "w") as f:
            json.dump(clv2_data, f, ensure_ascii=False)
        print(f"[ok] content_list_v2.json: 删除 {removed_clv2} 个乱码 block")

    # 3. 清理 markdown 乱码行（横向 1 行 / 纵向 5 行连续）
    if md:
        with open(md) as f:
            md_text = f.read()
        h_pattern = re.compile(r'^##\s*!\s*"\s*#\s*\\?\$\s*%\s*$', re.MULTILINE)
        v_pattern = re.compile(
            r'^#\s*!\s*$\n^"\s*$\n^#\s*$\n^\\?\$\s*$\n^%\s*$\n?', re.MULTILINE
        )
        md_new, n_h = h_pattern.subn("", md_text)
        md_new, n_v = v_pattern.subn("", md_new)
        with open(md, "w") as f:
            f.write(md_new)
        print(f"[ok] markdown: 删除 {n_h} 处横向 + {n_v} 处纵向乱码")

    print("\n[done] 共删除乱码 block:", removed_middle)


if __name__ == "__main__":
    sys.exit(main())