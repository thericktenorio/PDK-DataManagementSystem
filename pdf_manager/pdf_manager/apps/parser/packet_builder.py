"""Build main, signature, and payment-voucher page orders from registry roles."""
from __future__ import annotations

from pdf_manager.apps.parser.drake_registry import DrakeRegistry, load_drake_registry
from pdf_manager.apps.parser.types import TaggedPage


def _role_for_page(tp: TaggedPage) -> str:
    if not tp.tags:
        return "form_other"
    return tp.tags[0].label


def build_packet_orders(
    tagged_pages: list[TaggedPage],
    base_order: list[int],
    registry: DrakeRegistry | None = None,
) -> tuple[list[int], list[int], list[int]]:
    """
    Returns (main_order, signature_indices, voucher_indices).
    Main packet: covers first, then remaining included pages in base_order.
    """
    reg = registry or load_drake_registry()
    tags_by_idx = {tp.page.index: tp for tp in tagged_pages}

    signature_indices: list[int] = []
    voucher_indices: list[int] = []
    exclude: set[int] = set()

    for tp in tagged_pages:
        role = _role_for_page(tp)
        idx = tp.page.index
        packet = reg.packet_for_role(role)
        if packet == "signature":
            signature_indices.append(idx)
        elif packet == "payment_voucher":
            voucher_indices.append(idx)
        elif packet == "exclude":
            exclude.add(idx)

    signature_set = set(signature_indices)
    voucher_set = set(voucher_indices)

    filtered = [
        i
        for i in base_order
        if i not in exclude and i not in signature_set and i not in voucher_set
    ]

    cover_indices = [
        i for i in filtered if _role_for_page(tags_by_idx[i]) == "cover"
    ]
    non_cover = [i for i in filtered if i not in set(cover_indices)]

    section_order = reg.main_section_order
    if section_order:
        base_rank = {idx: pos for pos, idx in enumerate(base_order)}

        def _sort_key(page_idx: int) -> tuple[int, int]:
            role = _role_for_page(tags_by_idx[page_idx])
            return (reg.main_role_rank(role), base_rank.get(page_idx, page_idx))

        non_cover.sort(key=_sort_key)
    else:
        non_cover.sort(key=lambda i: base_order.index(i) if i in base_order else i)

    main_order = cover_indices + non_cover

    return main_order, sorted(signature_indices), sorted(voucher_indices)
