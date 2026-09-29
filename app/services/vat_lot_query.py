"""按缸浸染读取（半成品：多处仍按缸号全局查）。"""

from sqlalchemy.orm import Session

from app.models import DipLot, Vat


def lots_by_vat_code(db: Session, code: str, limit: int = 8):
    return (
        db.query(DipLot)
        .join(Vat)
        .filter(Vat.code == code)
        .order_by(DipLot.dippedAt.desc())
        .limit(limit)
        .all()
    )


def count_lots_loose(db: Session, code: str) -> int:
    # 角标：无坊过滤，且不截断
    return db.query(DipLot).join(Vat).filter(Vat.code == code).count()


def lots_fragment_by_code(db: Session, code: str):
    return (
        db.query(DipLot)
        .join(Vat)
        .filter(Vat.code == code)
        .order_by(DipLot.id.asc())
        .all()
    )
