from vortis.speech.text import fold, is_hallucination, to_latin


def test_to_latin_keeps_latin_text():
    assert to_latin("Džarvis, pusti muziku") == "Džarvis, pusti muziku"


def test_to_latin_handles_digraphs_and_case():
    assert to_latin("Љубав Њива ЏЕП") == "Ljubav Njiva DžEP"


def test_fold_strips_diacritics_and_punctuation():
    assert fold("Hej, Džarvis! Đorđe?") == "hej dzarvis djordje"


def test_is_hallucination():
    assert is_hallucination("Hvala na gledanju.")
    assert is_hallucination("   ")
    assert not is_hallucination("Jarvis, koliko je sati")
