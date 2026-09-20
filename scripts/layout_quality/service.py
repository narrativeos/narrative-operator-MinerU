"""版面质量 API 服务层：纯计算入口（不写文件、不打印 stdout）。

供 V1 解析 API（mineru/parser/api_server.py 的 layout_quality 输出格式）与其他程序化调用方使用。
CLI（cli.py）继续使用 pipeline.run_book_qa（带 CSV 落盘与报告打印），
两者的计算逻辑统一收敛在 analyze_book()，避免重复实现。
"""
from __future__ import annotations

from .ahp import ahp_subjective_weights
from .extractor import load_book_from_hybrid_dir, load_book_from_parse_result
from .indicators import IND_NAMES
from .scoring import book_quality_score, grade_of

__all__ = [
    "DEFAULT_N_SIGMA",
    "DEFAULT_COVERAGE_MIN",
    "DEFAULT_MIN_TEXT_BLOCKS",
    "analyze_book",
    "analyze_hybrid_dir",
    "analyze_parse_result",
]

# QA 默认参数（pipeline / cli 从这里复用，保持单一来源）
DEFAULT_N_SIGMA = 3.0
# 去噪保留判据: 版面覆盖率 >= DEFAULT_COVERAGE_MIN 或 文本块数 >= DEFAULT_MIN_TEXT_BLOCKS,
# 满足其一即保留 (整页表格/图片靠覆盖率保留, 空白页/版权页两者都不达标被剔除)。
DEFAULT_COVERAGE_MIN = 0.10
DEFAULT_MIN_TEXT_BLOCKS = 3


def analyze_book(
    agg,
    n_sigma: float = DEFAULT_N_SIGMA,
    coverage_min: float = DEFAULT_COVERAGE_MIN,
    min_text_blocks: int = DEFAULT_MIN_TEXT_BLOCKS,
    w_sub=None,
) -> dict:
    """对整本书执行版面质量分析，返回 JSON 可序列化的 dict（无副作用）。

    流程与 CLI 一致：噪声页过滤 → 聚合 → 分布形态 → 离群检测 → 绝对评分。

    Returns:
        {
          'book': 书名,
          'total_pages': 总页数,
          'valid_pages': 有效页数,
          'dropped_pages': 被剔除噪声页的页码列表,
          'score': {'value', 'percent', 'grade', 'stability_index',
                    'spread_symmetry', 'outlier_count', 'sub_scores'},
          'fingerprint': {指标名: {'mean', 'std'}},
          'outliers': [离群页记录],
          'pages': [逐页明细记录],
          'qa_report': QA 报告全文,
        }
    """
    raw_pages = list(agg.pages)
    dropped_nos = set(agg.filter_noise_pages(coverage_min, min_text_blocks))
    agg.aggregate()
    agg.spread_analysis()
    agg.detect_outliers(n_sigma)

    if w_sub is None:
        w_sub = ahp_subjective_weights(verbose=False)
    score, sub_scores = book_quality_score(agg, w_sub)

    return {
        'book': agg.name,
        'total_pages': len(raw_pages),
        'valid_pages': len(agg.pages),
        'dropped_pages': sorted(dropped_nos),
        'score': {
            'value': round(float(score), 4),
            'percent': round(float(score) * 100, 2),
            'grade': grade_of(score),
            'stability_index': round(float(agg.stability_index), 4),
            'spread_symmetry': (
                None if agg.spread_symmetry is None else round(float(agg.spread_symmetry), 4)
            ),
            'outlier_count': len(agg.outliers),
            'sub_scores': {
                nm: round(float(v), 4) for nm, v in zip(IND_NAMES, sub_scores)
            },
        },
        'fingerprint': {
            nm: {'mean': round(float(m), 4), 'std': round(float(s), 4)}
            for nm, m, s in zip(IND_NAMES, agg.fingerprint, agg.stability)
        },
        'outliers': agg.outliers.to_dict(orient='records'),
        'pages': [
            {
                '页码': p['page_no'],
                # 0-based 源页号，与 MiddleJson 的 page_idx 直接对齐（页码 = page_idx + 1）。
                'page_idx': p['page_no'] - 1,
                '是否有效': '否' if p['page_no'] in dropped_nos else '是',
                '版面覆盖率': (
                    None if p['coverage'] is None else round(float(p['coverage']), 4)
                ),
                '文本块数': p['text_blocks'],
                **{nm: round(float(v), 4) for nm, v in zip(IND_NAMES, p['metrics'])},
            }
            for p in raw_pages
        ],
        'qa_report': agg.qa_report_text(n_sigma),
    }


def analyze_hybrid_dir(
    hybrid_dir,
    n_sigma: float = DEFAULT_N_SIGMA,
    coverage_min: float = DEFAULT_COVERAGE_MIN,
    min_text_blocks: int = DEFAULT_MIN_TEXT_BLOCKS,
    w_sub=None,
) -> dict:
    """加载 MinerU hybrid_auto 输出目录并执行整书版面质量分析。

    Args:
        hybrid_dir: 含 ``*_model.json`` 与 ``*_middle.json`` 的目录。

    Raises:
        FileNotFoundError: model/middle json 缺失或无法配对。
    """
    agg = load_book_from_hybrid_dir(hybrid_dir)
    return analyze_book(agg, n_sigma, coverage_min, min_text_blocks, w_sub)


def analyze_parse_result(
    result,
    book_name: str | None = None,
    n_sigma: float = DEFAULT_N_SIGMA,
    coverage_min: float = DEFAULT_COVERAGE_MIN,
    min_text_blocks: int = DEFAULT_MIN_TEXT_BLOCKS,
    w_sub=None,
) -> dict:
    """对内存中的 4.0 ParseResult 执行整书版面质量分析 (无需落盘)。

    供 V1 API (mineru/parser/api_server.py) 在解析完成后直接评分。
    页尺寸取自 model_output 的 docvortex_layout 扩展, 缺失时兜底 A4。

    Args:
        result: ``mineru.parser.base.ParseResult`` 实例。
        book_name: 书名 (默认 'parse_result')。

    Raises:
        ValueError: 去噪后无有效正文页 (与 analyze_book 一致)。
    """
    agg = load_book_from_parse_result(result, book_name=book_name)
    return analyze_book(agg, n_sigma, coverage_min, min_text_blocks, w_sub)
