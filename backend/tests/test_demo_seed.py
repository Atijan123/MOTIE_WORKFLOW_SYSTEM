"""The demo seed (app/demo_seed.py), which scripts/seed-demo.sh runs after a reset."""

from datetime import date

import pytest

from app import demo_seed, dev_seed
from app.core.config import settings

pytestmark = pytest.mark.anyio

PASSWORD = "a dev password 1"


async def test_one_case_per_stage_made_through_the_api(db_session, client):
    await dev_seed.seed(db_session, PASSWORD)
    await demo_seed.seed_users(db_session, PASSWORD)
    made = await demo_seed.seed_cases(client, PASSWORD)

    login = await client.post("/auth/login", json={"email": "records@motie.test", "password": PASSWORD})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    cases = [(await client.get(f"/cases/{case_id}", headers=headers)).json() for _, case_id in made]
    assert [c["status"]["code"] for c in cases] == [
        "sent_to_gra",
        "signed",
        "verified",
        "originals_received",
        "returned",
        "originals_received",
        "submitted",
        "draft",
    ]
    # Every case but the draft has its reference, in the order made.
    year = date.today().year
    assert [c["reference"] for c in cases] == [f"MOTIE/ETLS/FL/{year}/{n:04d}" for n in range(1, 8)] + [None]

    # The duplicate is on hold at the desk; the earlier case isn't.
    assert (cases[5]["on_hold"], cases[3]["on_hold"]) == (True, False)

    # An authorised signatory signed the second one, in the Director's absence.
    history = (await client.get(f"/cases/{made[1][1]}/history", headers=headers)).json()
    [signed] = [e for e in history if e["details"].get("to") == "signed"]
    assert signed["acting_for"]["position"] == "director_of_industry"
    assert signed["acting_for"]["basis"] == "signatory"
    assert signed["actor_name"] == "Dev Signatory One"


def test_the_demo_seed_refuses_to_run_outside_development(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(SystemExit, match="Refusing"):
        demo_seed.main()


async def test_the_demo_register_imports_as_the_real_one_does(import_history, tmp_path):
    summary = await import_history(demo_seed.write_demo_register(tmp_path))
    assert (summary.letters, summary.filed_twice, summary.goods_lines, summary.checks) == (3, 1, 3, 1)
    assert (summary.checks_unlinked, summary.undated_letters) == (0, 0)
