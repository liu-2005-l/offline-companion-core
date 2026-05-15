"""engine：出站许可与同意流核心逻辑（A2）。"""

from __future__ import annotations

from typing import Callable

from offline_companion.shared.errors import OutboundDenied
from offline_companion.shared.types import OutboundPlan, OutboundScope, PrivacyMode

ConfirmFn = Callable[[OutboundPlan], bool]


def default_cli_confirm(plan: OutboundPlan) -> bool:
    """摘要：终端环境下的默认交互式确认。"""
    print("\n--- Outbound confirmation (no silent upload) ---")
    print("Purpose:", plan.purpose)
    print("Scope:", plan.scope.value)
    print("Will send:")
    for x in plan.will_send:
        print("  -", x)
    print("Will NOT send:")
    for x in plan.will_not_send:
        print("  -", x)
    print("Payload excerpt:\n", plan.payload_excerpt[:2000])
    ans = input("Type YES to allow this single request: ").strip()
    return ans == "YES"


def ensure_outbound_allowed(
    mode: PrivacyMode,
    plan: OutboundPlan,
    *,
    confirm: ConfirmFn | None = None,
    global_double_confirm: bool = True,
    risk_ack_auto_route: bool = False,
) -> None:
    """摘要：在发起任何出站请求前执行策略闸门。

    参数：
        mode: 当前隐私模式。
        plan: 出站披露计划。
        confirm: 可选 UI 注入的确认回调。
        global_double_confirm: 是否对 GLOBAL 范围二次确认。
        risk_ack_auto_route: AUTO_ROUTE 模式下的风险确认开关。

    异常：
        OutboundDenied：策略或用户拒绝出站。
    """
    if mode is PrivacyMode.LOCAL_ONLY:
        raise OutboundDenied("Privacy mode is local_only: outbound requests are disabled.")

    if mode is PrivacyMode.AUTO_ROUTE_CLOUD:
        if not risk_ack_auto_route:
            raise OutboundDenied(
                "AUTO_ROUTE_CLOUD requires risk_ack_auto_route=True after explicit UI warning."
            )
    else:
        fn = confirm or default_cli_confirm
        if not fn(plan):
            raise OutboundDenied("User did not consent to outbound request.")

    if plan.scope is OutboundScope.GLOBAL and global_double_confirm:
        ans = input("GLOBAL scope: type GLOBAL OK to confirm (extra guard): ").strip()
        if ans != "GLOBAL OK":
            raise OutboundDenied("Global scope not confirmed.")
