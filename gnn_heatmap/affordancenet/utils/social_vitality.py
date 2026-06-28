"""由 active_zone 行为空间热力综合计算区域社交活力指数（SVI）。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, List, Sequence

import numpy as np

# SVI = w_mean * 区域均值 + w_hot * 热点均值(top fraction)
DEFAULT_WEIGHTS = (0.60, 0.40)
DEFAULT_HOTSPOT_FRACTION = 0.2
DEFAULT_COVERAGE_THRESHOLD = 0.05

VITALITY_LEVELS: Sequence[tuple[float, str]] = (
    (0.80, "高"),
    (0.60, "较高"),
    (0.40, "中等"),
    (0.20, "较低"),
    (0.00, "低"),
)


@dataclass
class SocialVitalityMetrics:
    """区域整体社交活力（0~1，与热力强度同量纲）。"""

    index: float
    level_cn: str
    mean_intensity: float
    hotspot_mean: float
    hotspot_fraction: float
    coverage: float
    coverage_threshold: float
    max_intensity: float
    voxel_count: int
    heated_voxel_count: int
    formula: str
    formula_general: str
    formula_computed: str

    def to_dict(self) -> dict:
        return asdict(self)


def formula_general_text(
    weights: tuple[float, float] = DEFAULT_WEIGHTS,
    hotspot_fraction: float = DEFAULT_HOTSPOT_FRACTION,
) -> str:
    """通用公式（不含数值）。"""
    w0, w1 = weights
    pct = int(hotspot_fraction * 100)
    return (
        f"SVI = {w0:.2f}·Ī + {w1:.2f}·H̄<br>"
        f"Ī = (1/N) Σ Iᵢ &nbsp;&nbsp;（active_zone 内全部 N 个体素强度算术平均）<br>"
        f"H̄ = mean(Top{pct}% Iᵢ) &nbsp;&nbsp;（强度最高 {pct}% 体素均值）<br>"
        f"Iᵢ ∈ [0,1] 为 active_zone 内第 i 个行为空间体素预测强度，N 为体素总数"
    )


def formula_computed_text(
    *,
    index: float,
    mean_intensity: float,
    hotspot_mean: float,
    hotspot_fraction: float,
    coverage: float,
    coverage_threshold: float,
    voxel_count: int,
) -> str:
    """代入本次预测数值后的公式。"""
    w0, w1 = DEFAULT_WEIGHTS
    pct = int(hotspot_fraction * 100)
    return (
        f"SVI = {w0:.2f}×{mean_intensity:.4f} + "
        f"{w1:.2f}×{hotspot_mean:.4f} = {index:.4f}<br>"
        f"Ī={mean_intensity:.4f}, H̄(Top{pct}%)={hotspot_mean:.4f}, "
        f"N={voxel_count}, 覆盖(>{coverage_threshold})={coverage * 100:.1f}%"
    )


def vitality_plotly_annotation(metrics: SocialVitalityMetrics, region_label: str) -> dict:
    """Plotly 布局 annotation：公式 + 结果。"""
    return dict(
        text=(
            f"<b>社交活力指数 SVI = {metrics.index:.3f}</b>（{region_label} · {metrics.level_cn}）<br>"
            f"{formula_general_text()}<br>"
            f"""<b>本次计算：</b>{formula_computed_text(
                index=metrics.index,
                mean_intensity=metrics.mean_intensity,
                hotspot_mean=metrics.hotspot_mean,
                hotspot_fraction=metrics.hotspot_fraction,
                coverage=metrics.coverage,
                coverage_threshold=metrics.coverage_threshold,
                voxel_count=metrics.voxel_count,
            )}"""
        ),
        xref="paper",
        yref="paper",
        x=1.0,
        y=1.0,
        xanchor="right",
        yanchor="top",
        showarrow=False,
        bgcolor="rgba(255,255,255,0.93)",
        bordercolor="#90A4AE",
        borderwidth=1,
        font=dict(size=11, color="#263238"),
        align="left",
        width=420,
    )


def _vitality_level(index: float) -> str:
    for threshold, label in VITALITY_LEVELS:
        if index >= threshold:
            return label
    return "低"


def compute_social_vitality(
    intensities: Iterable[float],
    *,
    hotspot_fraction: float = DEFAULT_HOTSPOT_FRACTION,
    coverage_threshold: float = DEFAULT_COVERAGE_THRESHOLD,
    weights: tuple[float, float] = DEFAULT_WEIGHTS,
) -> SocialVitalityMetrics:
    """
    综合社交活力指数 SVI。

    对 active_zone 内全部行为空间体素强度 {I_i}，i=1…N：

    - Ī (mean_intensity) = (1/N) Σ I_i
    - H̄ (hotspot_mean) = mean(Top 20% 的 I_i)
    - SVI = 0.60·Ī + 0.40·H̄，裁剪至 [0,1]
    """
    arr = np.asarray(list(intensities), dtype=np.float64)
    n = len(arr)
    if n == 0:
        empty = SocialVitalityMetrics(
            index=0.0,
            level_cn="低",
            mean_intensity=0.0,
            hotspot_mean=0.0,
            hotspot_fraction=hotspot_fraction,
            coverage=0.0,
            coverage_threshold=coverage_threshold,
            max_intensity=0.0,
            voxel_count=0,
            heated_voxel_count=0,
            formula=_formula_text(weights, hotspot_fraction, coverage_threshold),
            formula_general=formula_general_text(weights, hotspot_fraction),
            formula_computed=formula_computed_text(
                index=0.0,
                mean_intensity=0.0,
                hotspot_mean=0.0,
                hotspot_fraction=hotspot_fraction,
                coverage=0.0,
                coverage_threshold=coverage_threshold,
                voxel_count=0,
            ),
        )
        return empty

    mean_i = float(np.mean(arr))
    max_i = float(np.max(arr))
    heated = int(np.sum(arr > coverage_threshold))
    coverage = heated / n

    k = max(1, int(n * hotspot_fraction))
    top_vals = np.partition(arr, n - k)[-k:]
    hotspot_mean = float(np.mean(top_vals))

    w_mean, w_hot = weights
    svi = w_mean * mean_i + w_hot * hotspot_mean
    svi = float(np.clip(svi, 0.0, 1.0))

    metrics = SocialVitalityMetrics(
        index=svi,
        level_cn=_vitality_level(svi),
        mean_intensity=mean_i,
        hotspot_mean=hotspot_mean,
        hotspot_fraction=hotspot_fraction,
        coverage=coverage,
        coverage_threshold=coverage_threshold,
        max_intensity=max_i,
        voxel_count=n,
        heated_voxel_count=heated,
        formula=_formula_text(weights, hotspot_fraction, coverage_threshold),
        formula_general=formula_general_text(weights, hotspot_fraction),
        formula_computed=formula_computed_text(
            index=svi,
            mean_intensity=mean_i,
            hotspot_mean=hotspot_mean,
            hotspot_fraction=hotspot_fraction,
            coverage=coverage,
            coverage_threshold=coverage_threshold,
            voxel_count=n,
        ),
    )
    return metrics


def _formula_text(
    weights: tuple[float, float],
    hotspot_fraction: float,
    coverage_threshold: float,
) -> str:
    w0, w1 = weights
    pct = int(hotspot_fraction * 100)
    return (
        f"SVI = {w0:.2f}×区域均值 + {w1:.2f}×热点Top{pct}%均值 "
        f"(覆盖率统计阈值>{coverage_threshold})"
    )


def intensities_from_active_space(space_voxels, active_bounds, in_bounds_fn) -> List[float]:
    """从 pred space 列表提取 active_zone 内全部强度（含 0）。"""
    if not active_bounds:
        return [sv.social_intensity for sv in space_voxels]
    return [
        sv.social_intensity
        for sv in space_voxels
        if in_bounds_fn(sv, active_bounds)
    ]
