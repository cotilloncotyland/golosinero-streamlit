from streamlit.testing.v1 import AppTest


def test_screen1_generates_all_profiles_without_rerun_errors():
    app = AppTest.from_file("app.py", default_timeout=90)
    for section in ("drive", "company", "app", "freshness"):
        app.secrets[section] = {}
    app.run()

    assert not app.exception
    guests = app.number_input(key="kids_widget")
    assert guests.label == "Cantidad de invitados"
    assert guests.value == 20
    assert not guests.disabled

    profiles = app.segmented_control(key="profile_widget")
    assert profiles.options == ["ECONÓMICO", "VARIADO", "PREMIUM"]
    assert profiles.value == "VARIADO"

    for label, expected in (
        ("ECONÓMICO", "economico"),
        ("VARIADO", "variado"),
        ("PREMIUM", "premium"),
    ):
        app.segmented_control(key="profile_widget").set_value(label).run()
        generate = next(button for button in app.button if button.label == "GENERAR COMBO")
        assert not generate.disabled
        generate.click().run()

        assert not app.exception
        assert app.session_state["kids"] == 20
        assert app.session_state["kids_widget"] == 20
        assert app.session_state["combo_profile"] == expected
        assert app.session_state["combo_config"]["items"]
        assert app.session_state["history"][-1]["totals"]["total_pedido"] > 0
        assert any(heading.value == "Tu combo está listo" for heading in app.subheader)
