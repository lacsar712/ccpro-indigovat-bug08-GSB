"""按缸浸染读取模块。

近笔组装、条数角标、按缸列表片段三处读路径全部收口于此：

- 取数与计数一律跟染缸主键（``dip_lots.vat_id`` → ``vats.id``），
  绝不按缸号 ``Vat.code`` 全局查，避免跨工坊同缸号串笔；
- 三处共用同一筛选、同一排序（``dippedAt DESC, id DESC``）、同一截断，
  角标条数恒等于列出的行数，也恒等于库内该缸的笔数。
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.models import DipLot

# 三处读路径共用的截断口径。None 表示不截断：列出该缸全部浸染笔，
# 这样角标、列出行、库内该缸笔数三者始终相等（差 0）。
LOT_LIMIT: Optional[int] = None


def _lot_query(db: Session, vat_id: int):
    return (
        db.query(DipLot)
        .filter(DipLot.vat_id == vat_id)
        .order_by(DipLot.dippedAt.desc(), DipLot.id.desc())
    )


def recent_lots(db: Session, vat_id: int, limit: Optional[int] = LOT_LIMIT) -> list[DipLot]:
    """近笔浸染（新 → 旧）。按染缸主键取，跟角标/片段同一排序与截断。"""
    query = _lot_query(db, vat_id)
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def count_lots(db: Session, vat_id: int) -> int:
    """库内该缸的浸染笔数（角标口径），按染缸主键计数，不做截断。"""
    return db.query(DipLot).filter(DipLot.vat_id == vat_id).count()


def vat_lot_view(
    db: Session, vat_id: int, limit: Optional[int] = LOT_LIMIT
) -> tuple[list[DipLot], int]:
    """一次取齐「近笔列表 + 条数角标」。

    返回 (近笔行, 该缸库内总笔数)。列表按与计数相同的主键过滤产出，
    默认不截断，故 ``len(rows) == total``。
    """
    rows = recent_lots(db, vat_id, limit)
    if limit is None:
        return rows, len(rows)
    return rows, count_lots(db, vat_id)


def fragment_lots(db: Session, vat_id: int, limit: Optional[int] = LOT_LIMIT) -> list[DipLot]:
    """按缸列表片段：与近笔完全同一条查询路径（同主键、同排序、同截断）。"""
    return recent_lots(db, vat_id, limit)
