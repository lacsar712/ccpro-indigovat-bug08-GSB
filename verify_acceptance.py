"""按缸浸染读取改造的端到端验收（不依赖 pytest / Postgres，用 SQLite 跑真实路由）。

覆盖四条验收：
1. 跨坊同号缸 V-01 不串笔；
2. 角标声称条数 == 展开区列出行数 == 库内该缸笔数（差 0）；
3. 近笔 / 角标 / 按缸列表片段三处同一排序截断；
4. 片段读取失败或登记失败后，还原台仍可打开、展开区不空白。
"""

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from decimal import Decimal

_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_DB.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB.name}"
os.environ["SESSION_SECRET"] = "accept-secret"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import DipLot, Vat, Workshop  # noqa: E402


def fail(msg):
    raise AssertionError(msg)


def embedded_vats(html: str):
    m = re.search(r"vats: (\[.*?\]),\n\s*filterWs:", html, re.S)
    if not m:
        fail("页面中未找到内嵌 vats 数据")
    return json.loads(m.group(1))


def fragment_ids(html: str):
    return [int(x) for x in re.findall(r'data-lot-id="(\d+)"', html)]


def db_ordered_ids(vat_id: int):
    db = SessionLocal()
    try:
        rows = (
            db.query(DipLot)
            .filter(DipLot.vat_id == vat_id)
            .order_by(DipLot.dippedAt.desc(), DipLot.id.desc())
            .all()
        )
        return [r.id for r in rows]
    finally:
        db.close()


def main():
    with TestClient(app) as client:
        # 登录拿会话
        r = client.post("/login", data={"username": "admin", "password": "123456"}, follow_redirects=False)
        assert r.status_code in (302, 303), r.status_code

        db = SessionLocal()
        w1 = db.query(Workshop).filter_by(name="蓝靛湾一号坊").one()
        w2 = db.query(Workshop).filter_by(name="清水江二号坊").one()
        v_w1 = db.query(Vat).filter_by(workshop_id=w1.id, code="V-01").one()
        v_other = db.query(Vat).filter_by(workshop_id=w2.id, code="V-01").one()
        v12 = db.query(Vat).filter_by(code="V-12").one()

        # 额外制造「同一时刻多笔」，验证 id 兜底排序在三处一致、刷新不跳
        latest12 = max(l.dippedAt for l in v12.lots)
        tie = latest12.replace(microsecond=0)
        from datetime import timedelta as _td

        tie = tie + _td(hours=1)
        db.add_all(
            [
                DipLot(vat_id=v12.id, dippedAt=tie, clothMeters=Decimal("11.00"), redoxMv=None),
                DipLot(vat_id=v12.id, dippedAt=tie, clothMeters=Decimal("12.00"), redoxMv=None),
                DipLot(vat_id=v12.id, dippedAt=tie, clothMeters=Decimal("13.00"), redoxMv=None),
            ]
        )
        db.commit()

        def db_count(vat_id):
            return db.query(DipLot).filter(DipLot.vat_id == vat_id).count()

        # ---------- 取两次主页：模拟刷新，条数/顺序不得跳 ----------
        html_a = client.get("/?vat=%d" % v_w1.id).text
        html_b = client.get("/?vat=%d" % v_w1.id).text
        vats_a = {v["id"]: v for v in embedded_vats(html_a)}
        vats_b = {v["id"]: v for v in embedded_vats(html_b)}
        assert vats_a == vats_b, "刷新后缸位数据发生跳变"

        # ---------- 验收1：跨坊同号不串 ----------
        for vat in (v_w1, v_other):
            payload = vats_a[vat.id]
            listed_ids = [row["id"] for row in payload["recentLots"]]
            expected = set(db_ordered_ids(vat.id))
            assert set(listed_ids) == expected, (
                f"缸 {vat.code}(坊{vat.workshop_id}) 串入他坊笔: "
                f"{set(listed_ids) ^ expected}"
            )
            # 两个同号缸列出的笔不得有任何交集
        ids_w1 = {row["id"] for row in vats_a[v_w1.id]["recentLots"]}
        ids_w2 = {row["id"] for row in vats_a[v_other.id]["recentLots"]}
        assert not (ids_w1 & ids_w2), "跨坊同号 V-01 浸染笔串到一起"
        assert vats_a[v_w1.id]["workshopName"] == "蓝靛湾一号坊"
        assert vats_a[v_other.id]["workshopName"] == "清水江二号坊"

        # ---------- 验收2：声称条数 == 列出行数 == 库内笔数（差 0） ----------
        for vat_id, payload in vats_a.items():
            n_claim = payload["recentLotClaimed"]
            n_list = len(payload["recentLots"])
            n_db = db_count(vat_id)
            assert n_claim == n_list == n_db, (
                f"缸{vat_id} 条数不一致: 角标={n_claim} 列出={n_list} 库内={n_db}"
            )

        # ---------- 验收3：三处同一排序截断 ----------
        for vat in (v_w1, v_other, v12):
            expected_order = db_ordered_ids(vat.id)
            # 读路径A：主页内嵌近笔
            recent_order = [row["id"] for row in vats_a[vat.id]["recentLots"]]
            # 读路径C：按缸列表片段（局部刷新）
            fr = client.get(f"/bay/vats/{vat.id}/lots-fragment", headers={"X-Partial": "1"})
            assert fr.status_code == 200
            frag_order = fragment_ids(fr.text)
            assert recent_order == expected_order, f"缸{vat.id} 近笔排序不符"
            assert frag_order == expected_order, f"缸{vat.id} 片段排序不符"
            assert recent_order == frag_order, f"缸{vat.id} 近笔与片段排序/截断互殴"
            # 角标头 == 行 == 库内
            assert int(fr.headers["X-Lot-Total"]) == len(frag_order) == db_count(vat.id)
        # 同刻三笔按 id desc：片段末三位（最新在最前）应是新 id 倒序
        fr12 = fragment_ids(
            client.get(f"/bay/vats/{v12.id}/lots-fragment", headers={"X-Partial": "1"}).text
        )
        assert fr12[:3] == sorted(fr12[:3], reverse=True), "同一时刻笔未按主键兜底排序"

        # 浏览器直访片段（不带 X-Partial）：落回还原台，不再产出互殴的整页
        direct = client.get(f"/bay/vats/{v_w1.id}/lots-fragment", follow_redirects=False)
        assert direct.status_code == 303 and direct.headers["location"] == f"/?vat={v_w1.id}"

        # ---------- 验收4：失败后还原台可开、不空白 ----------
        # 4a. 未登录的局部刷新 → 401 空体（不回灌整页）
        anon = TestClient(app)
        r401 = anon.get(f"/bay/vats/{v_w1.id}/lots-fragment", headers={"X-Partial": "1"})
        assert r401.status_code == 401 and r401.text == ""
        # 4b. 不存在的缸局部刷新 → 404 空体
        r404 = client.get("/bay/vats/999999/lots-fragment", headers={"X-Partial": "1"})
        assert r404.status_code == 404 and r404.text == ""
        # 4c. 失败之后还原台照常打开，选中缸仍有近笔，展开区不空白
        after = client.get(f"/?vat={v_w1.id}")
        assert after.status_code == 200
        pv = {v["id"]: v for v in embedded_vats(after.text)}
        assert len(pv[v_w1.id]["recentLots"]) == db_count(v_w1.id) == 5
        assert "近几笔浸染" in after.text
        # 4d. 登记非法浸染（米数非法）→ 400 但还原台仍完整渲染、保留该缸笔与错误提示
        bad = client.post(
            f"/bay/vats/{v_w1.id}/lots",
            data={"dippedAt": "2026-09-29T10:00", "clothMeters": "not-a-number", "redoxMv": ""},
        )
        assert bad.status_code == 400
        assert "error-box" in bad.text
        bv = {v["id"]: v for v in embedded_vats(bad.text)}
        assert len(bv[v_w1.id]["recentLots"]) == 5, "登记失败回灌后展开区近笔丢失/空白"

        db.close()

    print("ACCEPTANCE PASS: 跨坊不串 / 条数差0 / 三处同序截断 / 失败可还原")


if __name__ == "__main__":
    main()
