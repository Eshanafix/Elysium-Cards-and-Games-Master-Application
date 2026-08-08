from elysium import ui_settings


def test_get_display_scale_defaults_when_no_file(monkeypatch, tmp_path):
    monkeypatch.setattr(ui_settings, "_settings_path", lambda: tmp_path / "ui_settings.json")
    assert ui_settings.get_display_scale() == ui_settings.DEFAULT_SCALE


def test_set_then_get_display_scale_round_trips(monkeypatch, tmp_path):
    path = tmp_path / "nested" / "ui_settings.json"
    monkeypatch.setattr(ui_settings, "_settings_path", lambda: path)

    ui_settings.set_display_scale(2.0)

    assert path.exists()
    assert ui_settings.get_display_scale() == 2.0


def test_set_display_scale_clamps_to_bounds(monkeypatch, tmp_path):
    path = tmp_path / "ui_settings.json"
    monkeypatch.setattr(ui_settings, "_settings_path", lambda: path)

    ui_settings.set_display_scale(10.0)
    assert ui_settings.get_display_scale() == ui_settings.MAX_SCALE

    ui_settings.set_display_scale(0.1)
    assert ui_settings.get_display_scale() == ui_settings.MIN_SCALE


def test_get_display_scale_defaults_on_corrupt_file(monkeypatch, tmp_path):
    path = tmp_path / "ui_settings.json"
    path.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(ui_settings, "_settings_path", lambda: path)

    assert ui_settings.get_display_scale() == ui_settings.DEFAULT_SCALE
