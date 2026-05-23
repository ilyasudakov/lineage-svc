from app.schemas import OpenLineageEvent
from app.translator import translate


def _event() -> OpenLineageEvent:
    return OpenLineageEvent(
        eventType="COMPLETE",
        eventTime="2026-05-23T00:00:00Z",
        run={"runId": "run-1"},
        job={"namespace": "ns", "name": "extract.fb_ads"},
        inputs=[{"namespace": "ns", "name": "fb_ads.api"}],
        outputs=[{"namespace": "ns", "name": "data_table.fb_ads"}],
    )


def test_translate_produces_three_edge_shapes():
    edges = translate(_event())
    types = {e.edge_type for e in edges}
    assert types == {"consumes", "produces", "derives_from"}
    assert len(edges) == 3


def test_translate_is_pure():
    e1 = translate(_event())
    e2 = translate(_event())
    assert [e.model_dump() for e in e1] == [e.model_dump() for e in e2]
