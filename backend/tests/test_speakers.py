from app.speakers import (Turn, Word, assign_speakers, build_utterances, join_words, merge_timed_chunks,
                          speaker_overview, words_from_whisper)
from app.textutil import split_text


def w(start, text, dur=0.4):
    return Word(start, start + dur, text)


def test_words_from_whisper_offsets_and_filters_special_tokens():
    payload = {"segments": [
        {"start": 0.0, "end": 2.0, "text": " Hallo Welt", "words": [
            {"word": "[_BEG_]", "start": 0.0, "end": 0.0},
            {"word": " Hallo", "start": 0.1, "end": 0.5},
            {"word": " Welt", "start": 0.6, "end": 1.0},
        ]},
        {"start": 2.0, "end": 3.0, "text": " Ohne Wörter"},  # Segment ohne Wortzeitstempel
    ]}
    words = words_from_whisper(payload, offset=100.0)
    assert [x.text for x in words] == [" Hallo", " Welt", " Ohne Wörter"]
    assert words[0].start == 100.1 and words[2].end == 103.0


def test_merge_timed_chunks_cuts_overlap_in_the_middle():
    # Chunk 1: 0–300 s, Chunk 2: 290–590 s → Schnitt bei 295 s
    c1 = [w(t, f" a{t}") for t in (100, 293, 294.5, 296, 299.5)]
    c2 = [w(t, f" b{t}") for t in (290.2, 294.5, 296, 400)]
    merged = merge_timed_chunks([(0, 300, c1), (290, 300, c2)])
    assert [x.text for x in merged] == [" a100", " a293", " a294.5", " b296", " b400"]


def test_assign_speakers_by_overlap_and_gaps():
    turns = [Turn(0, 5, 3), Turn(5.2, 9, 1), Turn(20, 25, 3)]
    words = [w(1, " a"), w(4.8, " b"), w(6, " c"), w(10, " d"), w(15, " e"), w(21, " f")]
    # "b" überlappt stärker mit Sprecher 3; "d" liegt 1 s hinter Sprecher 1 → nächster;
    # "e" ist weit weg von allem → übernimmt den vorherigen Sprecher
    assert assign_speakers(words, turns) == [3, 3, 1, 1, 1, 3]


def test_build_utterances_numbers_speakers_by_first_appearance():
    words = [w(0, " Wir"), w(0.5, " gehen"), w(1, " rein."), w(2, " Ihr"), w(2.5, " seht"), w(3, " Orks."),
             w(4, " Angriff!")]
    utts = build_utterances(words, [7, 7, 7, 2, 2, 2, 7])
    assert [(u.speaker, u.text) for u in utts] == [("1", "Wir gehen rein."), ("2", "Ihr seht Orks."),
                                                     ("1", "Angriff!")]


def test_build_utterances_splits_long_pauses():
    utts = build_utterances([w(0, " eins"), w(30, " zwei")], [0, 0])
    assert len(utts) == 2


def test_join_words_handles_both_token_styles():
    assert join_words([w(0, " Fest"), w(1, "platten"), w(2, " frei.")]) == "Festplatten frei."
    assert join_words([w(0, "ohne"), w(1, "Leerzeichen")]) == "ohne Leerzeichen"


def test_speaker_overview_prefers_medium_length_samples():
    words = [w(0, " kurz", 1), w(10, " mittel", 8), w(30, " lang", 25)]
    utts = build_utterances(words, [0, 0, 0])
    info = speaker_overview(utts)
    assert info[0]["id"] == "1" and info[0]["utterances"] == 3
    assert info[0]["samples"][1]["text"] == "mittel"
    assert all(s["end"] - s["start"] <= 12 for s in info[0]["samples"])


def test_split_text_keeps_speaker_lines_together():
    lines = [f"Sprecher {i % 3}: " + "bla " * 20 for i in range(40)]
    parts = split_text("\n".join(lines), 500)
    assert len(parts) > 1
    assert all(line.startswith("Sprecher") for p in parts for line in p.splitlines())


def test_smooth_speakers_absorbs_short_blips_inside_continuous_speech():
    from app.speakers import smooth_speakers

    # A redet durchgehend, dazwischen ein 0,4-s-Wort "B" ohne Pausen → Zuordnungsfehler
    words = [w(0.0, " eins"), w(0.4, " zwei"), w(0.8, " drei"), w(1.2, " vier"), w(1.6, " fünf")]
    assert smooth_speakers(words, [0, 0, 1, 0, 0]) == [0, 0, 0, 0, 0]


def test_smooth_speakers_keeps_real_interjections_and_long_runs():
    from app.speakers import smooth_speakers

    # Einwurf mit Pause davor bleibt erhalten
    words = [w(0.0, " und"), w(0.4, " dann"), w(1.5, " Ja!"), w(2.0, " weiter"), w(2.4, " so")]
    assert smooth_speakers(words, [0, 0, 1, 0, 0]) == [0, 0, 1, 0, 0]
    # Längerer Einschub (> 1 s) bleibt ebenfalls
    words = [w(t * 0.4, f" w{t}") for t in range(10)]
    speakers = [0, 0, 1, 1, 1, 1, 0, 0, 0, 0]
    assert smooth_speakers(words, speakers) == speakers
    # Abschaltbar
    assert smooth_speakers(words[:5], [0, 0, 1, 0, 0], max_seconds=0) == [0, 0, 1, 0, 0]


def test_strip_leading_title():
    from app.jobs import strip_leading_title

    assert strip_leading_title("# Session Recap: X\n\n## Was bisher geschah\nText") == "## Was bisher geschah\nText"
    assert strip_leading_title("## Zusammenfassung\nText") == "## Zusammenfassung\nText"


def test_join_words_glues_continuation_tokens_even_in_short_groups():
    # " Ho" + "ffentlich": nur der Wortanfang trägt ein Leerzeichen – vorher wurde daraus "Ho ffentlich"
    assert join_words([w(0, " Ho"), w(0.2, "ffentlich")]) == "Hoffentlich"
    assert join_words([w(0, " Ste"), w(0.1, "ck"), w(0.2, "d"), w(0.3, "ose")]) == "Steckdose"


def test_merge_speaker_tracks_keeps_sentences_whole_when_people_overlap():
    from app.speakers import merge_speaker_tracks

    # Packman und Tottooro reden gleichzeitig; Tottooros Wort "Gruseliger" besteht aus 4 Tokens,
    # die zeitlich zwischen Packmans Wörtern liegen.
    packman = [w(3.0, " Mein"), w(3.5, " Kind"), w(4.0, " ist"), w(4.5, " aufgewacht.")]
    tottooro = [w(3.2, " Gr"), w(3.7, "us"), w(4.2, "el"), w(4.7, "iger")]
    pold = [w(20.0, " Also"), w(20.4, " am"), w(20.8, " zehnten.")]
    utts, labels = merge_speaker_tracks([packman, tottooro, pold])
    assert [(u.speaker, u.text) for u in utts] == [
        ("1", "Mein Kind ist aufgewacht."),
        ("2", "Gruseliger"),
        ("3", "Also am zehnten."),
    ]
    assert labels == {0: "1", 1: "2", 2: "3"}


def test_merge_speaker_tracks_splits_on_pauses_and_numbers_by_first_appearance():
    from app.speakers import merge_speaker_tracks

    late = [w(10.0, " später")]
    early = [w(1.0, " eins"), w(1.5, " zwei"), w(8.0, " neu")]  # Pause > 2 s → zwei Beiträge
    utts, labels = merge_speaker_tracks([late, early])
    assert [(u.speaker, u.text) for u in utts] == [("1", "eins zwei"), ("1", "neu"), ("2", "später")]
    assert labels == {1: "1", 0: "2"}


def test_sentences_are_split_but_not_at_ordinals_and_abbreviations():
    tokens = [" Am", " 16", ".", " Oktober", " spielen", " wir", ".", " Kommst", " du", "?",
              " Das", " ist", " z", ".", " B", ".", " gut", "!", " Ich", "..."]
    words = [w(i * 0.3, t) for i, t in enumerate(tokens)]
    utts = build_utterances(words, [0] * len(words))
    assert [u.text for u in utts] == ["Am 16. Oktober spielen wir.", "Kommst du?", "Das ist z. B. gut!", "Ich..."]
    # abschaltbar
    assert len(build_utterances(words, [0] * len(words), split_sentences=False)) == 1


def test_sentence_split_orders_overlapping_speakers_by_sentence():
    from app.speakers import merge_speaker_tracks

    # "Und … dann los." hat eine Denkpause von 3,1 s – der Satz bleibt trotzdem ganz (erst ab 6 s wird getrennt)
    a = [w(0.0, " Ich"), w(0.3, " komme."), w(0.6, " Und"), w(4.0, " dann"), w(4.3, " los.")]
    b = [w(1.0, " Okay."), w(1.4, " Gut.")]
    utts, _ = merge_speaker_tracks([a, b])
    assert [(u.speaker, u.text) for u in utts] == [
        ("1", "Ich komme."), ("1", "Und dann los."), ("2", "Okay."), ("2", "Gut."),
    ]


def test_continuation_tokens_never_split_from_their_word():
    from app.speakers import merge_speaker_tracks

    # Aus dem echten Test: "Grusel" bei 3 s, "iger" (ungenauer Zeitstempel) erst bei 9 s;
    # "ist" + einzelner Punkt mit 8 s Abstand
    # Satzzeichen-Token mit führendem Leerzeichen (" .") ist kein neues Wort und hängt am vorherigen
    tottooro = [w(3.0, " Grusel"), w(9.0, "iger"), w(20.0, " Scheiß"), w(20.4, ".")]
    packman = [w(100.0, " ist"), w(108.0, " ."), w(108.5, "..")]
    utts, _ = merge_speaker_tracks([tottooro, packman])
    assert [u.text for u in utts] == ["Gruseliger", "Scheiß.", "ist..."]


def test_group_for_display_merges_consecutive_sentences_of_same_person():
    from app.speakers import Utterance, group_for_display

    utts = [Utterance(0, 1, "1", "Hallo."), Utterance(1.2, 2, "1", "Wie geht's?"),
            Utterance(2.1, 3, "2", "Gut."), Utterance(3.1, 4, "1", "Schön."), Utterance(9, 10, "1", "Später.")]
    assert [(u.speaker, u.text) for u in group_for_display(utts)] == [
        ("1", "Hallo. Wie geht's?"), ("2", "Gut."), ("1", "Schön."), ("1", "Später."),
    ]


def _payload(tokens):
    return {"segments": [{"start": 0.0, "end": 9.0, "text": "",
                          "words": [{"word": t, "start": i * 0.3, "end": i * 0.3 + 0.3} for i, t in enumerate(tokens)]}]}


def test_words_from_whisper_merges_tokens_to_whole_words():
    words = words_from_whisper(_payload([" N", "iemand", " ist", " da", "."]), offset=0.0)
    assert [x.text for x in words] == [" Niemand", " ist", " da."]
    assert words[0].start == 0.0 and words[0].end == 0.6
    # Sprecherwechsel zwischen "N" und "iemand" kann es so nicht mehr geben
    assert assign_speakers(words, [Turn(0.0, 0.32, 1), Turn(0.32, 9.0, 2)])[0] in (1, 2)


def test_words_from_whisper_drops_noise_markers():
    words = words_from_whisper(_payload([" Ja", ".", " *", "l", "acht", "*", " Gut", " *lacht laut*",
                                         " [", "Musik", "]", " so", " *", " nicht"]), offset=0.0)
    assert [x.text for x in words] == [" Ja.", " Gut", " so", " *", " nicht"]


def test_collapse_repeats_removes_hallucination_loops():
    from app.textutil import collapse_repeats, collapse_text_repeats
    loop = "Ich habe hier noch ein bisschen gekoppelt. " * 12
    assert collapse_text_repeats("Also. " + loop + "Weiter geht's.") == \
        "Also. Ich habe hier noch ein bisschen gekoppelt. Weiter geht's."
    # Echte kurze Wiederholungen bleiben
    assert collapse_text_repeats("ja ja ja genau") == "ja ja ja genau"
    assert collapse_text_repeats("Das war gut. Das war gut. Weiter.") == "Das war gut. Das war gut. Weiter."
    words = [w(i, t) for i, t in enumerate([" Ja,", " ich", " habe", " noch", " mal", " bei", " dir."] * 6)]
    assert [x.text for x in collapse_repeats(words, key=lambda x: x.text)] == \
        [" Ja,", " ich", " habe", " noch", " mal", " bei", " dir."]


def _sentence(texts_speakers, start=0.0, step=0.3):
    words, speakers = [], []
    for text, speaker in texts_speakers:
        words.append(Word(start, start + step - 0.05, text))
        speakers.append(speaker)
        start += step
    return words, speakers


def test_consolidate_sentences_gives_sentence_to_the_speaker_who_finishes_it():
    from app.speakers import consolidate_sentences

    # "Oder können deine Tränke das nicht?" (Spielerin) · "Lieber zauber | ich ihm den Mund zu." (DM)
    words, speakers = _sentence([(" Oder", 1), (" können", 1), (" deine", 1), (" Tränke", 1), (" das", 1),
                                 (" nicht?", 1), (" Lieber", 1), (" zauber", 1), (" ich", 2), (" ihm", 2),
                                 (" den", 2), (" Mund", 2), (" zu.", 2)])
    assert consolidate_sentences(words, speakers) == [1] * 6 + [2] * 7
    # Einschub mitten im Satz: "Ich lerne | meine Magie aus | Magiebüchern."
    words, speakers = _sentence([(" Ich", 1), (" lerne", 1), (" meine", 2), (" Magie", 2), (" aus", 2),
                                 (" Magiebüchern.", 1)])
    assert consolidate_sentences(words, speakers) == [1] * 6


def test_consolidate_sentences_keeps_real_changes():
    from app.speakers import consolidate_sentences

    # Langer erster Teil (deutlich mehr Redezeit) → Mehrheit statt Satzende
    words, speakers = _sentence([(f" w{i}", 1) for i in range(12)] + [(" ja.", 2)])
    assert consolidate_sentences(words, speakers) == [1] * 13
    # Pause > 1 s trennt: zwei Teile, jeder behält seinen Sprecher
    first, s1 = _sentence([(" Also", 1), (" ich", 1)])
    second, s2 = _sentence([(" habe", 2), (" Hunger.", 2)], start=3.0)
    assert consolidate_sentences(first + second, s1 + s2) == [1, 1, 2, 2]
    # Satzende trennt ebenfalls
    words, speakers = _sentence([(" Nein.", 1), (" Okay.", 2)])
    assert consolidate_sentences(words, speakers) == [1, 2]


def test_drop_hallucinations_only_when_alone_in_a_pause():
    from app.speakers import drop_hallucinations

    talk = [w(10.0, " Ja."), w(14.0, " Vielen"), w(14.4, " Dank."), w(20.0, " Weiter.")]
    assert [x.text for x in drop_hallucinations(talk)] == [" Ja.", " Weiter."]
    # mitten im Gespräch (Nachbar < 1,5 s) bleibt es stehen
    chat = [w(10.0, " Hier,"), w(10.5, " bitte."), w(11.2, " Vielen"), w(11.6, " Dank."), w(12.3, " Gern.")]
    assert len(drop_hallucinations(chat)) == 5
    # Untertitel-Floskeln, Segmente als Einheit
    seg = [Word(30.0, 33.0, " Untertitel im Auftrag des ZDF, 2020"), Word(60.0, 62.0, " Wir würfeln Initiative.")]
    assert [x.text for x in drop_hallucinations(seg)] == [" Wir würfeln Initiative."]
    # Mehrspur: in der eigenen Spur allein, aber jemand anderes spricht gerade → echt
    mine = [w(14.0, " Vielen"), w(14.4, " Dank.")]
    other = [w(13.5, " Hier"), w(13.9, " ist"), w(14.3, " dein"), w(14.7, " Gold.")]
    assert len(drop_hallucinations(mine, context=mine + other)) == 2
    assert drop_hallucinations(mine, context=mine) == []


def test_segments_from_whisper():
    from app.speakers import segments_from_whisper

    payload = {"segments": [{"start": 1.0, "end": 2.0, "text": " Hallo."}, {"start": 3, "end": 4, "text": "  "}]}
    assert segments_from_whisper(payload, 10.0) == [Word(11.0, 12.0, " Hallo.")]
