"""按缸浸染读取模块（唯一取数口径）。

近笔组装、条数角标、按缸列表片段三处一律改走本模块：

- 取数与计数都跟染缸主键（``DipLot.vat_id`` / ``Vat.id``），
  绝不按缸号 ``Vat.code`` 全局查——缸号只在坊内唯一，跨坊同号会串笔；
- 三处共用同一过滤、同一排序（``dippedAt DESC, id DESC``，主键兜底，
  同一时刻多笔不会因刷新而换位）与同一截断（``vat_dips`` 一个入口），
  近笔展开区与「列表片段」是同一份结果；
- 角标条数直接取列出行数，而该结果不截断该缸任何笔，
  故「声称条数 == 列出行数 == 库内该缸笔数」恒成立。
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import DipLot


def lot_dips(db: Session, vat_id: int, limit: int | None = None) -> list[DipLot]:
    """该缸浸染笔，三处共用的唯一取数口。

    按染缸主键过滤；近笔组装与按缸列表片段都调用本函数、传同一 ``limit``，
    因此排序与截断必然一致。``limit=None`` 列出该缸全部笔（与角标计数对齐）。
    """
    query = (
        db.query(DipLot)
        .filter(DipLot.vat_id == vat_id)
        .order_by(DipLot.dippedAt.desc(), DipLot.id.desc())
    )
    if limit is not None:
        query = query.limit(max(limit, 0))
    return query.all()


@dataclass
class DipSnapshot:
    """某一缸浸染的一致性快照：计数与列出同源。"""

    total: int
    lots: list[DipLot]

    @property
    def claimed(self) -> int:
        # 角标声称条数 = 真实列出行数 = 库内该缸笔数
        return len(self.lots)


def dip_snapshot(db: Session, vat_id: int, limit: int | None = None) -> DipSnapshot:
    """近笔组装 + 条数角标共用的一次读取；与片段同一查询口径。"""
    lots = lot_dips(db, vat_id, limit)
    return DipSnapshot(total=len(lots), lots=lots)
