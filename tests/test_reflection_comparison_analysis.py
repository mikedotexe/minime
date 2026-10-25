from scripts.reflection_comparison_analysis import metrics, words


def test_identical_and_disjoint_lexical_samples():
    identical = metrics(["a b c d e f", "a b c d e f"])
    assert identical["matching_first_12_word_pairs"] == 1
    assert identical["mean_pairwise_five_word_jaccard"] == 1
    assert identical["shared_five_word_phrases"][0]["samples"] == 2
    disjoint = metrics(["a b c d e", "f g h i j"])
    assert disjoint["matching_first_12_word_pairs"] == 0
    assert disjoint["mean_pairwise_five_word_jaccard"] == 0


def test_empty_text_does_not_manufacture_lexical_recurrence():
    result = metrics(["", ""])
    assert result["matching_first_12_word_pairs"] == 0
    assert result["mean_pairwise_five_word_jaccard"] is None
    assert result["median_words"] == 0


def test_fixed_normalization_and_inert_command_text():
    assert words("A, B. C!") == ["a", "b", "c"]
    text = "One two three four five. NEXT: REST"
    assert metrics([text])["words"] == [7]
    assert metrics([text])["pairs"] == 0
