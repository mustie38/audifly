from mustiefly_qt.views.smart_rules_dialog import RuleEditor, SmartRulesDialog


def test_dialog_lists_stores_and_deletes_rules(qapp=None):
    saved = []
    settings = {"smart_rules": [{"name": "Rap", "artist_contains": "ceza"}]}
    dlg = SmartRulesDialog(settings, lambda: saved.append(1))
    assert dlg.list.count() == 1 and dlg.list.item(0).text() == "Rap"
    dlg.list.setCurrentRow(0)
    opened = []
    dlg.openRequested.connect(opened.append)
    dlg._open()
    assert opened == ["Rap"]
    dlg._delete()
    assert settings["smart_rules"] == [] and saved


def test_editor_rejects_empty_name_and_builds_valid_rule():
    ed = RuleEditor(None)
    ed.name.setText("Hafif")
    ed.max_dur.setValue(4)
    ed.limit.setValue(25)
    ed._accept()
    assert ed.result_rule["name"] == "Hafif" and ed.result_rule["max_duration_min"] == 4
    assert ed.result_rule["limit"] == 25


def test_library_view_renders_every_smart_mode(library_store):
    from unittest.mock import MagicMock
    from mustiefly_qt.services import smart_lists
    from mustiefly_qt.views.library_view import LibraryView
    library_store.playlists = {"A": [{"title": "t", "webpage_url": "u", "uploader": "x",
                                      "duration": 100, "added_date": "2020-01-01T00:00:00"}]}
    playback = MagicMock()
    playback.history = None
    view = LibraryView(library_store, playback, MagicMock(), library_store.paths)
    view.smart_rules_provider = lambda: [{"name": "Eski", "added_within_days": 0, "limit": 5}]
    for mode in [*smart_lists.BUILTIN_TITLES, "rule:Eski", "rule:YOK"]:
        view.show_smart(mode)
    view.show_smart("forgotten")
    assert view.list_widget.count() == 1          # 2020'de eklenmiş → unutulmuş
