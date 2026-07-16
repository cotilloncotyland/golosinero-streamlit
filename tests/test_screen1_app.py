from streamlit.testing.v1 import AppTest


def app_test():
    app = AppTest.from_file("app.py", default_timeout=90)
    for section in ("drive", "company", "app", "freshness"):
        app.secrets[section] = {}
    return app.run()


def generate_combo(app,profile="VARIADO"):
    app.segmented_control(key="profile_widget").set_value(profile).run()
    next(button for button in app.button if button.label == "GENERAR COMBO").click().run()


def test_screen1_generates_all_profiles_without_rerun_errors():
    app = app_test()

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


def test_bags_quantity_subtotal_and_navigation_to_extras():
    app=app_test()
    generate_combo(app)
    next(button for button in app.button if button.label == "Continuar a Bolsitas →").click().run()

    assert not app.exception
    assert app.session_state["step"] == 2
    plus=next(button for button in app.button if str(button.key).startswith("bags_selection_plus_"))
    sku=str(plus.key).removeprefix("bags_selection_plus_")
    plus.click().run()

    assert not app.exception
    assert app.session_state["bags_selection"][sku] == 1
    assert app.session_state["history"][-1]["totals"]["subtotal_bolsitas"] > 0
    minus=next(button for button in app.button if button.key==f"bags_selection_minus_{sku}")
    minus.click().run()
    assert app.session_state["bags_selection"].get(sku,0) == 0

    next(button for button in app.button if button.label == "Continuar a Extras →").click().run()
    assert not app.exception
    assert app.session_state["step"] == 3
