"""A product's components on its entity page (issue 0165 A, the display that stays).

The things (not versions) whose parent is a product's cluster are listed apart from its versions on the product's
entity page (`components_of`). The rule that made component entities from "<product> <name>" mentions (0165 A:
split, plan, make, preview, the span routing in identity.resolve_mention and the `timeline.components` switch) was
dropped in v10.18 (0203: measured 26 of 60 right, 43%, 32-56%); the rows it ever wrote stay.
"""
from __future__ import annotations

from typing import List, Optional

from insight_core.markx import identity as I


def product_like(book: I.Book, root: Optional[str]) -> bool:
    """A cluster a component can belong to: a product family or a product-typed thing, not an org or person."""
    if root is None or root not in book.ents:
        return False
    e = book.ents[root]
    if e.status == "not_entity" or e.level in I.VERSION_LEVELS:
        return False
    if book.org_like(root):
        return False
    fam, org = book.sides(book.cluster(root))
    if org:
        return False
    return bool(fam) or book.etype(root) in I.PRODUCT_TYPES


def components_of(book: I.Book, root: str) -> List[str]:
    """The component roots under a product's cluster: things (not versions) whose parent is in it, the product not
    an org (an org's things are its products, not its components)."""
    if not product_like(book, root):
        return []
    members = set(book.cluster(root))
    out = {book.root(x) for x in book.with_parent_in(root)   # v10.17 (0186): asked of the book, not walked
           if (e := book.ents[x]).level == "thing" and e.parent in members and e.status != "not_entity"
           and book.root(x) != root}
    return sorted(r for r in out if r in book.ents)


__all__ = ["components_of", "product_like"]
