# -*- coding: utf-8 -*-
"""版面量化评估 AHP-熵权TOPSIS 综合评分工具 (逐页 -> 全书聚合版)。

针对 MinerU 解析引擎输出的版面量化指标, 采用"自下而上提取, 自上而下评估"的双层架构:
  [逐页层]  每页独立计算 12 指标局部特征向量 (Page-level)
  [全书层]  噪声页剔除 -> 均值/方差聚合 -> 全书版面指纹 -> TOPSIS 综合评级 (Book-level)
            同时进行跨页 (Spread) 对称性分析与 3σ 异常页检测,
            输出《全书排版一致性质检报告》

模块划分:
  indicators  指标体系定义 (4 准则层 x 12 指标)
  ahp         AHP 主观赋权 (特征向量法 + 一致性检验)
  entropy     熵权法客观赋权
  topsis      TOPSIS 逼近理想解综合排序
  aggregator  逐页 -> 全书聚合器 (去噪/聚合/跨页对称/3σ/质检报告)
  extractor   从 MinerU 输出 (model.json + middle.json) 提取逐页 12 指标
  pipeline    组合赋权与 TOPSIS 评估主流程
  demo        内置模拟演示与自检
  cli         命令行入口
"""
