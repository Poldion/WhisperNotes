"""Englische Oberfläche: Einstellungen und Zusammenfassungen vollständig übersetzt."""

from app.i18n import EN, tr
from app.prompts import DE
from app.prompts import EN as EN_PROMPTS
from app.runtime_settings import GROUPS, RuntimeSettings


def test_every_settings_text_has_an_english_translation():
    texts = set()
    for group in GROUPS:
        texts |= {group.label, group.description}
        for f in group.fields:
            texts |= {f.label, f.help, f.applies, *(label for _, label in f.options)}
    texts |= {"wie im Dashboard (Standardmodell bzw. gerade geladenes)", "automatisch (gerade geladenes)", "keins"}
    missing = sorted(t for t in texts if t and t not in EN)
    assert missing == []


def test_placeholders_survive_translation():
    for de, en in EN.items():
        assert sorted(part.split("}")[0] for part in de.split("{")[1:]) == \
               sorted(part.split("}")[0] for part in en.split("{")[1:]), de
    assert tr("en", "{n} Sprecher erkannt – bitte zuordnen", n=3) == "3 speakers detected – please assign them"
    assert tr("de", "{n} Sprecher erkannt – bitte zuordnen", n=3) == "3 Sprecher erkannt – bitte zuordnen"


def test_english_settings_page_and_templates(settings):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    runtime = RuntimeSettings(settings)
    runtime.update({"language": "en"})
    groups = {g["id"]: g for g in runtime.describe()["groups"]}
    assert groups["general"]["label"] == "General"
    templates = {f["key"]: f for f in groups["templates"]["fields"]}
    assert templates["template_dnd_recap"]["placeholder"] == EN_PROMPTS.dnd_recap
    assert "## Previously" in EN_PROMPTS.dnd_recap and "## Was bisher geschah" in DE.dnd_recap
    for name in ("summary", "dnd_recap", "dnd_player", "dnd_lore"):
        assert "Deutsch" not in getattr(EN_PROMPTS, name)


def test_custom_template_replaces_task_but_keeps_rules(settings):
    from app.ollama import profile_prompts

    settings.language = "en"
    _, task = profile_prompts(settings, "dnd")
    assert task.startswith(EN_PROMPTS.dnd_recap) and task.endswith(EN_PROMPTS.dnd_rules)
    settings.template_dnd_recap = "## Previously\nOne paragraph, pirate voice."
    _, task = profile_prompts(settings, "dnd")
    assert task.startswith("## Previously\nOne paragraph") and task.endswith(EN_PROMPTS.dnd_rules)
    settings.language, settings.template_dnd_recap = "de", ""
    map_system, task = profile_prompts(settings, "standard")
    assert map_system.endswith(DE.common_rules) and task.startswith(DE.summary)
