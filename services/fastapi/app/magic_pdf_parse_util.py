"""MinerU 4.0 解析工具（fork 服务）。

模块名保留 3.x 的 ``magic_pdf_parse_util`` 以兼容既有导入；
内部实现已从 ``magic_pdf`` pipe API 迁移到 MinerU 4.0 的
``mineru.parser.parse`` + ``mineru.render.content_list``。

与 3.x 的行为差异：
- ``model_json_path``（复用已计算的模型数据跳过推理）在 4.0 公共 API 中
  没有等价能力，传入时记录警告并忽略；
- 3.x 解析后删除输出目录、仅把 content_list 与 markdown 写入 Redis，
  4.0 全程内存处理，无需输出目录（``output_dir`` 参数保留但不再使用）。
"""

import os
import tempfile

from loguru import logger

from . import redis_util


def pdf_parse(
        md5_value,
        pdf_bytes: bytes,
        parse_method: str = 'auto',
        model_json_path: str = None,
        output_dir: str = None
):
    """
    执行从 pdf 转换到 json、md 的过程，结果写入 Redis。
    :param parse_method: 解析方法，共 auto、ocr、txt 三种，默认 auto，如果效果不好，可以尝试 ocr
    :param model_json_path: 3.x 遗留参数（复用模型数据跳过推理），4.0 不支持，传入时忽略
    :param output_dir: 3.x 遗留参数，4.0 内存处理无需输出目录，保留以兼容签名
    """
    tmp_path = None
    try:
        file_info = redis_util.get_file_info(md5_value)
        if not file_info:
            return
        if file_info["state"] != "waiting":
            return
        if model_json_path:
            logger.warning(
                f"pdf_parse: model_json_path is not supported in MinerU 4.0, "
                f"ignoring it for {md5_value}"
            )
        redis_util.set_parse_parsing(md5_value)

        # 4.0 的 parse() 接受文件路径，先把请求字节落盘到临时文件
        suffix = os.path.splitext(md5_value)[1] or ".pdf"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
            tmp_file.write(pdf_bytes)
            tmp_path = tmp_file.name

        from mineru.parser import parse
        from mineru.render.content_list import render_content_list

        result = parse(tmp_path, tier="standard", ocr_mode=parse_method)
        content_list = render_content_list(result.middle_json)
        md_content = result.markdown()

        redis_util.set_parse_parsed(md5_value, content_list, md_content)

    except Exception as e:
        redis_util.set_parse_failed(md5_value)
        logger.exception(e)
    finally:
        if tmp_path and os.path.isfile(tmp_path):
            os.unlink(tmp_path)

