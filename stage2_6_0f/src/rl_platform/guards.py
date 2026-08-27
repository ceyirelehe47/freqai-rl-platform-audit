"""conv_width 硬性守卫(阶段 2.5.1 工作包 B)。

阶段 2.5 只在 conv_width = 1 下验证过路线 C:
- AlignedLongFlatEnv 的观察构造(特征窗口 ravel + 末维仓位)按窗口整块拼接;
- SequentialPositionPredictor 的逐行推理假设"一行观察 = 一次决策";
- live 增量调用只传入最新 CONV_WIDTH 行,没有跨调用特征缓冲去重逻辑。

提高 conv_width 前必须实现跨调用特征缓冲和 live 去重,否则:
- 观察窗口在窗口边界处重复/缺失历史行;
- live heartbeat 会反复重放窗口尾部。

因此在配置渲染、RouteCModel 构造、顺序推理入口与实验启动前四处
统一调用本守卫。配置为其他值时抛出清晰异常,不得静默降级为 1。
"""

from __future__ import annotations

SUPPORTED_CONV_WIDTH = 1

CONV_WIDTH_MESSAGE = (
    "Route C 当前仅验证 conv_width=1。"
    "提高窗口长度前必须实现跨调用特征缓冲和 live 去重。"
)


class RouteCConvWidthError(RuntimeError):
    """conv_width 超出已验证范围的硬性错误(不得被捕获后降级)。"""


def assert_conv_width(conv_width: int | float | None, source: str = "") -> int:
    """断言 conv_width 为已验证值,返回规范化后的 int。

    :param conv_width: 待检查的窗口宽度(来自配置或推理器参数)。
    :param source: 检查点描述(用于错误信息定位四处断言中的哪一处)。
    """
    if isinstance(conv_width, float) and not float(conv_width).is_integer():
        # 1.5 这类非整数值不得被 int() 截断静默接受(不得静默降级)
        raise RouteCConvWidthError(
            f"conv_width 必须是整数,收到 {conv_width!r}({source})。{CONV_WIDTH_MESSAGE}"
        )
    try:
        cw = int(conv_width)
    except (TypeError, ValueError) as e:
        raise RouteCConvWidthError(
            f"conv_width 必须是整数,收到 {conv_width!r}({source})。{CONV_WIDTH_MESSAGE}"
        ) from e
    if cw != SUPPORTED_CONV_WIDTH:
        raise RouteCConvWidthError(
            f"conv_width={cw}({source})。{CONV_WIDTH_MESSAGE}"
        )
    return cw
