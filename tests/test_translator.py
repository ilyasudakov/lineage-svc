from app.schemas import OpenLineageEvent
from app.translator import translate


def _extract_event() -> OpenLineageEvent:
    return OpenLineageEvent(
        eventType="COMPLETE",
        eventTime="2026-05-23T00:00:00Z",
        run={"runId": "run-1"},
        job={"namespace": "1_2_abc", "name": "extract.facebook_ads.campaigns"},
        inputs=[{"namespace": "1_2_abc", "name": "facebook_ads.api.campaigns"}],
        outputs=[{"namespace": "1_2_abc", "name": "data_table__facebook_ads__campaigns__sql__42"}],
    )


def _load_event() -> OpenLineageEvent:
    return OpenLineageEvent(
        eventType="COMPLETE",
        eventTime="2026-05-23T00:00:00Z",
        run={"runId": "run-2"},
        job={"namespace": "1_2_abc", "name": "load.clickhouse.facebook_ads"},
        inputs=[{"namespace": "1_2_abc", "name": "data_table__facebook_ads__campaigns__sql__42"}],
        outputs=[{"namespace": "1_2_abc", "name": "clickhouse.fb_ads_campaigns"}],
    )


def _transform_event_with_facet() -> OpenLineageEvent:
    return OpenLineageEvent(
        eventType="COMPLETE",
        eventTime="2026-05-23T00:00:00Z",
        run={"runId": "run-3"},
        job={
            "namespace": "1_2_abc",
            "name": "recipe.fb_normalize",
            "facets": {
                "transformMetadata": {
                    "source_tables": [
                        {
                            "namespace": "1_2_abc",
                            "name": "data_table__facebook_ads__campaigns__sql__42",
                        },
                        {
                            "namespace": "1_2_abc",
                            "name": "data_table__google_ads__campaigns__sql__7",
                        },
                    ]
                }
            },
        },
        inputs=[],
        outputs=[{"namespace": "1_2_abc", "name": "data_table__normalized__campaigns__sql__99"}],
    )


def test_extract_event_produces_all_three_edge_types():
    edges = translate(_extract_event())
    types = {e.edge_type for e in edges}
    assert types == {"consumes", "produces", "derives_from"}
    assert len(edges) == 3


def test_load_event_links_source_to_destination():
    edges = translate(_load_event())
    derives = [e for e in edges if e.edge_type == "derives_from"]
    assert len(derives) == 1
    assert derives[0].src_urn.endswith("data_table__facebook_ads__campaigns__sql__42")
    assert derives[0].dst_urn.endswith("clickhouse.fb_ads_campaigns")


def test_transform_event_falls_back_to_facet_source_tables():
    edges = translate(_transform_event_with_facet())
    consumes = [e for e in edges if e.edge_type == "consumes"]
    assert len(consumes) == 2
    derives = [e for e in edges if e.edge_type == "derives_from"]
    assert len(derives) == 2


def test_translation_is_idempotent():
    """Translating the same event N times yields identical edge sets."""
    one = [e.model_dump() for e in translate(_extract_event())]
    two = [e.model_dump() for e in translate(_extract_event())]
    three = [e.model_dump() for e in translate(_extract_event())]
    assert one == two == three


def test_duplicate_inputs_collapsed_within_event():
    """Two inputs with the same URN must not produce duplicate edges."""
    event = OpenLineageEvent(
        eventType="COMPLETE",
        eventTime="2026-05-23T00:00:00Z",
        run={"runId": "run-x"},
        job={"namespace": "ns", "name": "j"},
        inputs=[
            {"namespace": "ns", "name": "same"},
            {"namespace": "ns", "name": "same"},
        ],
        outputs=[{"namespace": "ns", "name": "out"}],
    )
    edges = translate(event)
    keys = [(e.src_urn, e.dst_urn, e.edge_type) for e in edges]
    assert len(keys) == len(set(keys))


def test_namespace_propagated_from_job():
    edges = translate(_extract_event())
    assert all(e.namespace == "1_2_abc" for e in edges)


def test_run_id_set_on_every_edge():
    edges = translate(_extract_event())
    assert all(e.run_id == "run-1" for e in edges)
