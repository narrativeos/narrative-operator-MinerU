# -*- coding: utf-8 -*-
"""版面量化评分工具命令行入口。

用法 (在仓库根目录执行):
    # 1. 单本书质检 (主要用法): 输出 <目录>/layout_quality.csv (与 middle.json/model.json 同目录)
    python -m scripts.layout_quality.cli output/<uuid>/demo3/hybrid_auto

    # 2. 多本书对比 (至少 2 本): 每本书各自输出 layout_quality.csv,
    #    TOPSIS 综合评分结果写入 --out (默认 ./layout_quality)
    python -m scripts.layout_quality.cli <目录1> <目录2> ...

    # 3. 外部逐页指标 CSV (19 列: 书名,页码,版面覆盖率,文本块数,重心x,重心y,页宽,C1~C12)
    python -m scripts.layout_quality.cli --csv 你的minerU逐页指标.csv

    # 4. 书级聚合指标 CSV (13 列: 样本名 + C1~C12)
    python -m scripts.layout_quality.cli --book-csv 你的书级指标.csv

    # 5. 内置模拟演示 (含自检)
    python -m scripts.layout_quality.cli --demo

输出:
    目录模式: <hybrid_auto>/layout_quality.csv (逐页指标明细, 每本书一个)
              + <hybrid_auto>/layout_quality_score.csv (全书综合评分, 每本书一个)
              + 多本书模式另输出 版面量化综合评分结果.csv 到 --out
    CSV/演示模式: 写入 --out (默认 ./layout_quality)
    全书排版一致性质检报告与全书综合评分: 打印到 stdout
"""
import argparse
import os
import sys

# 支持从仓库根目录以 -m 方式运行 (scripts 为命名空间包)
if __package__ in (None, ''):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from scripts.layout_quality import demo as _demo  # noqa: F401
    from scripts.layout_quality.aggregator import load_book_pages_from_csv
    from scripts.layout_quality.extractor import load_book_from_hybrid_dir
    from scripts.layout_quality.pipeline import (
        load_metrics_from_csv, run_book_level_pipeline, run_book_qa,
        run_evaluation,
    )
else:
    from . import demo as _demo
    from .aggregator import load_book_pages_from_csv
    from .extractor import load_book_from_hybrid_dir
    from .pipeline import (
        load_metrics_from_csv, run_book_level_pipeline, run_book_qa,
        run_evaluation,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='版面量化评估 AHP-熵权TOPSIS 综合评分工具 (逐页 -> 全书聚合版)')
    parser.add_argument('dirs', nargs='*',
                        help='MinerU hybrid_auto 输出目录 (每个目录 = 一本书; 1 本 = 仅质检, 至少 2 本 = TOPSIS 对比)')
    parser.add_argument('--csv', help='逐页指标 CSV (19 列)')
    parser.add_argument('--book-csv', help='书级指标 CSV (13 列)')
    parser.add_argument('--demo', action='store_true', help='运行内置模拟演示 (含自检)')
    parser.add_argument('--out', help='综合评分结果输出目录 (默认 ./layout_quality; '
                        '目录模式下逐页明细恒写入 <目录>/layout_quality.csv)')
    parser.add_argument('--alpha', type=float, default=0.5,
                        help='主观(AHP)权重占比, 0~1, 默认 0.5')
    parser.add_argument('--n-sigma', type=float, default=3.0,
                        help='异常页检测 σ 阈值, 默认 3.0')
    parser.add_argument('--name', help='书名 (仅单目录模式有效, 默认取父目录名)')
    args = parser.parse_args(argv)

    modes = sum([bool(args.csv), bool(args.book_csv), args.demo, bool(args.dirs)])
    if modes != 1:
        parser.error('请指定且仅指定一种数据源: 目录列表 / --csv / --book-csv / --demo')

    out_dir = args.out or 'layout_quality'

    if args.demo:
        result, w_final, qa_text = _demo.run_demo(alpha=args.alpha,
                                                  n_sigma=args.n_sigma, out_dir=out_dir)
        print()
        print('=' * 72)
        print('最终综合评级 (含全书聚合信息)')
        print('=' * 72)
        print(result.to_string(index=False))
        return result, w_final, qa_text

    if args.csv:
        books = load_book_pages_from_csv(args.csv)
        result, w_final, qa_text = run_book_level_pipeline(
            books, alpha=args.alpha, n_sigma=args.n_sigma, out_dir=out_dir)
        return result, w_final, qa_text

    if args.book_csv:
        X, names = load_metrics_from_csv(args.book_csv)
        result, w_final = run_evaluation(X, names, alpha=args.alpha)
        os.makedirs(out_dir, exist_ok=True)
        score_csv = os.path.join(out_dir, '版面量化综合评分结果.csv')
        result.to_csv(score_csv, index=False, encoding='utf-8-sig')
        print(f'综合评分结果已保存: {score_csv}')
        return result, w_final, None

    # 目录模式: 每个 hybrid_auto 目录 = 一本书, 逐页明细写入 <目录>/layout_quality.csv
    if args.name and len(args.dirs) != 1:
        parser.error('--name 仅在单目录模式有效')
    books, page_csv_paths = {}, {}
    for d in args.dirs:
        name = args.name if (args.name and len(args.dirs) == 1) else None
        agg = load_book_from_hybrid_dir(d, book_name=name)
        if agg.name in books:
            raise ValueError(f'书名重复: {agg.name} (可用 --name 指定)')
        books[agg.name] = agg
        page_csv_paths[agg.name] = os.path.join(os.path.abspath(d), 'layout_quality.csv')

    if len(books) == 1:
        name, agg = next(iter(books.items()))
        print(f'仅 1 本书 ({name}), 执行单本书质检 (不做 TOPSIS 排序, 需至少 2 本)')
        detail, qa_text = run_book_qa(agg, csv_path=page_csv_paths[name], n_sigma=args.n_sigma)
        return None, None, qa_text
    result, w_final, qa_text = run_book_level_pipeline(
        books, page_csv_paths=page_csv_paths, alpha=args.alpha, n_sigma=args.n_sigma, out_dir=out_dir)
    return result, w_final, qa_text


if __name__ == '__main__':
    main()
