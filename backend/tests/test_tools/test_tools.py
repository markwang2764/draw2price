from app.orchestration.tools import EquipmentMatcher, JSONResponseParser, StreamEventEmitter


def test_stream_event_emitter_format():
    emitter = StreamEventEmitter()
    assert emitter.format_event("start", {"message": "hi"}) == 'data: {"type": "start", "message": "hi"}\n\n'


def test_equipment_matcher_prefers_type_then_available():
    matcher = EquipmentMatcher([
        {"name": "A", "type": "CNC_LATHE", "status": "maintenance"},
        {"name": "B", "type": "CNC_MILL", "status": "available"},
    ])
    assert matcher.match("CNC_MILL")["name"] == "B"


def test_json_parser_importable():
    parser = JSONResponseParser()
    assert parser.parse('{"a":1}')["a"] == 1
